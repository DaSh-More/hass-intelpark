"""Камеры Intelpark (HLS-поток + снимок)."""
from __future__ import annotations

import asyncio
import logging
import time

from homeassistant.components.camera import Camera as HACamera
from homeassistant.components.camera import CameraEntityFeature
from homeassistant.components.camera.helper import async_get_stream_image
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import Camera, Gate, IntelparkError
from .const import (
    CONF_GATE_PREVIEW_SOURCE,
    DOMAIN,
    PREVIEW_SOURCE_SNAPSHOT,
    TOKEN_REFRESH_MARGIN,
)
from .coordinator import IntelparkConfigEntry, IntelparkCoordinator
from .entity import gate_device_info, object_device_info, strip_number_sign

_LOGGER = logging.getLogger(__name__)

# Bound card-driven snapshot attempts within HA's image request timeout.
GATE_SNAPSHOT_TIMEOUT = 3
GATE_SNAPSHOT_COOLDOWN = 60
GATE_SNAPSHOT_ATTEMPTS = 2
GATE_SNAPSHOT_FAILED_CYCLES = 3
GATE_SNAPSHOT_STALE_WARNING = 300
GATE_SNAPSHOT_REQUEST_GAP = 120


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IntelparkConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[HACamera] = [
        IntelparkCamera(coordinator, cam) for cam in coordinator.data.cameras.values()
    ]
    entities += [
        IntelparkGateCamera(coordinator, gate)
        for gate in coordinator.data.gates
        if gate.live_url
    ]
    async_add_entities(entities)


class IntelparkCamera(HACamera):
    """Одна камера двора."""

    _attr_has_entity_name = True
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(self, coordinator: IntelparkCoordinator, camera: Camera) -> None:
        super().__init__()
        self.coordinator = coordinator
        self._cam_id = camera.cam_id
        self._attr_unique_id = f"{DOMAIN}_camera_{camera.cam_id}"
        self._attr_name = strip_number_sign(camera.name) or camera.cam_id
        self._attr_device_info = object_device_info(
            coordinator.config_entry.entry_id, camera.object_name
        )

    @property
    def _camera(self) -> Camera | None:
        return self.coordinator.data.cameras.get(self._cam_id)

    async def _ensure_fresh(self) -> Camera | None:
        cam = self._camera
        if cam is None:
            return None
        if cam.stream_token_valid_till and cam.stream_token_valid_till <= (
            time.time() + TOKEN_REFRESH_MARGIN
        ):
            refreshed = await self.coordinator.async_refresh_camera(self._cam_id)
            if refreshed is not None:
                return refreshed
        return cam

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

    async def stream_source(self) -> str | None:
        cam = await self._ensure_fresh()
        return cam.stream_url() if cam else None

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        cam = self._camera
        if cam is None or not cam.snapshot:
            return None
        try:
            return await self.coordinator.client.async_fetch_snapshot(cam.snapshot)
        except IntelparkError as err:
            _LOGGER.warning(
                "Не удалось получить снимок камеры %s: %s", self._cam_id, err
            )
            return None

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.last_update_success
            and self._camera is not None
        )


class IntelparkGateCamera(HACamera):
    """Камера шлагбаума (`get_gates`): live-поток без токена."""

    _attr_has_entity_name = True
    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_icon = "mdi:cctv"

    def __init__(self, coordinator: IntelparkCoordinator, gate: Gate) -> None:
        super().__init__()
        self.coordinator = coordinator
        self._gid = gate.gid
        self._attr_unique_id = f"{DOMAIN}_gatecam_{gate.gid}"
        self._attr_name = "Камера"
        self._attr_device_info = gate_device_info(
            coordinator.config_entry.entry_id, gate
        )
        # Capture the option for this entity lifetime; updates reload the entry.
        self._snapshot_previews = (
            coordinator.config_entry.options.get(CONF_GATE_PREVIEW_SOURCE)
            == PREVIEW_SOURCE_SNAPSHOT
        )
        self._last_snapshot: bytes | None = None
        self._last_snapshot_at: float | None = None
        self._snapshot_outage_since: float | None = None
        self._snapshot_last_request: float | None = None
        self._snapshot_warned = False
        self._snapshot_lock = asyncio.Lock()
        self._snapshot_failures = 0
        self._snapshot_open_until = 0.0
        self._image_inflight: dict[tuple[int | None, int | None], list] = {}
        self._image_tasks: set[asyncio.Task] = set()
        self._image_removing = False

    @property
    def _gate(self) -> Gate | None:
        return next(
            (g for g in self.coordinator.data.gates if g.gid == self._gid), None
        )

    @property
    def use_stream_for_stills(self) -> bool:
        # Snapshot mode never falls back to stream, even without snapshotURL.
        return not self._snapshot_previews

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

    async def stream_source(self) -> str | None:
        gate = self._gate
        return gate.live_stream_url() if gate and gate.live_url else None

    async def async_will_remove_from_hass(self) -> None:
        """Stop shared image work before the entity is unloaded."""
        self._image_removing = True
        tasks = tuple(self._image_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._image_inflight.clear()
        await super().async_will_remove_from_hass()

    def _image_done(self, key, entry, task) -> None:
        # Identity checks protect newer work using the same canonical key.
        if self._image_inflight.get(key) is entry:
            del self._image_inflight[key]
        self._image_tasks.discard(task)
        if not task.cancelled():
            task.exception()  # Retrieve even when every waiter has left.

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Coalesce active requests; keep the last-good image separately in RAM."""
        if self._image_removing or self._gate is None:
            return None
        # Server snapshots ignore dimensions; stream helpers must preserve them.
        key = (None, None) if self._snapshot_previews else (width, height)
        entry = self._image_inflight.get(key)
        if entry is None or entry[0].done():
            task = asyncio.create_task(self._async_camera_image(width, height))
            entry = [task, 0]
            self._image_inflight[key] = entry
            self._image_tasks.add(task)
            task.add_done_callback(
                lambda done: self._image_done(key, entry, done)
            )
        task = entry[0]
        entry[1] += 1
        try:
            # A cancelled consumer must not cancel the other consumers' work.
            return await asyncio.shield(task)
        finally:
            entry[1] -= 1
            if entry[1] == 0:
                if self._image_inflight.get(key) is entry:
                    del self._image_inflight[key]
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    async def _async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        if not self._snapshot_previews:
            return await async_get_stream_image(
                self, width=width, height=height, wait_for_next_keyframe=False
            )
        # Across dimensions the server supplies the same native-size image.
        # Serialize fetch/cache updates so old tasks cannot overwrite new data.
        async with self._snapshot_lock:
            gate = self._gate
            if self._image_removing or gate is None:
                return None
            now = time.monotonic()
            # No warning merely because a card was closed. A long request gap
            # starts a new observation window, even for an existing outage.
            if (
                self._snapshot_last_request is not None
                and now - self._snapshot_last_request > GATE_SNAPSHOT_REQUEST_GAP
            ):
                self._snapshot_outage_since = None
                # Retain warned until recovery: at most one warning per outage.
            self._snapshot_last_request = now
            if now < self._snapshot_open_until:
                self._snapshot_failed("cooldown", now)
                return self._last_snapshot
            reason = "missing_url"
            image = None
            if gate.snapshot_image:
                # One shared card cycle: at most two bounded attempts, no sleep.
                for _ in range(GATE_SNAPSHOT_ATTEMPTS):
                    reason = "empty"
                    try:
                        async with asyncio.timeout(GATE_SNAPSHOT_TIMEOUT):
                            image = await self.coordinator.client.async_fetch_snapshot(
                                gate.snapshot_image
                            )
                    except (IntelparkError, TimeoutError) as err:
                        reason = (
                            "timeout" if isinstance(err, TimeoutError) else "intelpark_error"
                        )
                    if image:
                        break
            if self._image_removing or self._gate is None:
                return None
            now = time.monotonic()
            if image:
                self._snapshot_failures = 0
                self._snapshot_open_until = 0.0
                self._last_snapshot = image
                # Successful fetch time, not a claim about camera capture time.
                self._last_snapshot_at = now
                if self._snapshot_warned:
                    _LOGGER.info("Gate snapshot gate=%s recovered", self.entity_id)
                self._snapshot_outage_since = None
                self._snapshot_warned = False
                return image
            self._snapshot_failures = min(
                self._snapshot_failures + 1, GATE_SNAPSHOT_FAILED_CYCLES
            )
            if self._snapshot_failures >= GATE_SNAPSHOT_FAILED_CYCLES:
                self._snapshot_open_until = now + GATE_SNAPSHOT_COOLDOWN
            self._snapshot_failed(reason, now)
            return self._last_snapshot

    def _snapshot_failed(self, reason: str, now: float) -> None:
        """One sanitized debug, one sustained-outage warning, then recovery."""
        if self._snapshot_outage_since is None:
            self._snapshot_outage_since = now
            _LOGGER.debug(
                "Gate snapshot gate=%s snapshot_failure=%s", self.entity_id, reason
            )
        # No timer and no age-only alarm after idle. Both the observed failure
        # period and last-fetched data age must reach the five-minute threshold.
        stale_since = self._last_snapshot_at
        if (
            not self._snapshot_warned
            and now - self._snapshot_outage_since >= GATE_SNAPSHOT_STALE_WARNING
            and (
                stale_since is None
                or now - stale_since >= GATE_SNAPSHOT_STALE_WARNING
            )
        ):
            self._snapshot_warned = True
            _LOGGER.warning(
                "Gate snapshot gate=%s unavailable_for_s=%s cached=%s",
                self.entity_id,
                GATE_SNAPSHOT_STALE_WARNING,
                self._last_snapshot is not None,
            )

    @property
    def extra_state_attributes(self) -> dict:
        gate = self._gate
        if gate is None:
            return {}
        return {"live_cam": gate.live_cam}

    @property
    def available(self) -> bool:
        gate = self._gate
        return super().available and gate is not None and bool(gate.live_url)
