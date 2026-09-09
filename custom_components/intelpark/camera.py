"""Камеры Intelpark (HLS-поток + снимок)."""
from __future__ import annotations

import logging
import time

from homeassistant.components.camera import Camera as HACamera, CameraEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import Camera, Gate, IntelparkError
from .const import DOMAIN, TOKEN_REFRESH_MARGIN
from .coordinator import IntelparkConfigEntry, IntelparkCoordinator
from .entity import gate_device_info, object_device_info, strip_number_sign

_LOGGER = logging.getLogger(__name__)


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

    @property
    def _gate(self) -> Gate | None:
        return next(
            (g for g in self.coordinator.data.gates if g.gid == self._gid), None
        )

    @property
    def use_stream_for_stills(self) -> bool:
        return True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

    async def stream_source(self) -> str | None:
        gate = self._gate
        return gate.live_stream_url() if gate and gate.live_url else None

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        gate = self._gate
        if gate is None or not gate.snapshot_image:
            return None
        try:
            return await self.coordinator.client.async_fetch_snapshot(
                gate.snapshot_image
            )
        except IntelparkError as err:
            _LOGGER.warning(
                "Не удалось получить снимок ворот %s: %s", self._gid, err
            )
            return None

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
