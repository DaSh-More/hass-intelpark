"""Координатор опроса Intelpark."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    AccountPlace,
    Camera,
    Gate,
    IntelparkApiClient,
    IntelparkAuthError,
    IntelparkError,
)
from .const import (
    CONF_HASH,
    CONF_PHONE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_NOTIFICATION,
)

_LOGGER = logging.getLogger(__name__)

type IntelparkConfigEntry = ConfigEntry[IntelparkCoordinator]


@dataclass
class IntelparkData:
    objects: list[AccountPlace] = field(default_factory=list)
    gates: list[Gate] = field(default_factory=list)
    cameras: dict[str, Camera] = field(default_factory=dict)
    passes: list[dict] = field(default_factory=list)
    notifications: list[dict] = field(default_factory=list)


class IntelparkCoordinator(DataUpdateCoordinator[IntelparkData]):
    """Опрашивает API и раздаёт данные сущностям."""

    config_entry: IntelparkConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
            config_entry=entry,
        )
        self.client = IntelparkApiClient(
            async_get_clientsession(hass),
            phone=entry.data[CONF_PHONE],
            hash_=entry.data[CONF_HASH],
        )
        self._seen_notifications: set[str] | None = None

    async def _async_update_data(self) -> IntelparkData:
        # Последовательные await намеренно: fail-fast — ошибка авторизации
        # на первом же вызове прерывает опрос остальных и уходит в reauth.
        try:
            objects = await self.client.async_get_objects()
            gates = await self.client.async_get_gates()
            cameras = await self.client.async_get_cameras()
            passes = await self.client.async_get_passes()
            notifications = await self.client.async_get_notifications()
        except IntelparkAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except IntelparkError as err:
            raise UpdateFailed(str(err)) from err

        self._fire_new_notifications(notifications)

        return IntelparkData(
            objects=objects,
            gates=gates,
            cameras={c.cam_id: c for c in cameras},
            passes=passes,
            notifications=notifications,
        )

    def _fire_new_notifications(self, notifications: list[dict]) -> None:
        by_id: dict[str, dict] = {}
        for n in notifications:
            if isinstance(n, dict):
                # реальный ответ notifications использует ключ "notificationId";
                # "id" оставлен запасным вариантом.
                nid = n.get("notificationId")
                if nid is None:
                    nid = n.get("id")
                if nid is not None:
                    by_id.setdefault(str(nid), n)
        ids = set(by_id)
        if self._seen_notifications is None:
            self._seen_notifications = ids
            return
        new_ids = ids - self._seen_notifications
        self._seen_notifications |= ids
        if len(self._seen_notifications) > 5000:
            # ограничиваем рост множества (редкая ветка): оставляем текущие id.
            self._seen_notifications = set(ids)
        for nid in new_ids:
            self.hass.bus.async_fire(EVENT_NOTIFICATION, by_id[nid])

    async def async_refresh_camera(self, cam_id: str) -> Camera | None:
        """Точечно обновить одну камеру (свежий streamToken)."""
        try:
            cam = await self.client.async_get_camera(cam_id)
        except IntelparkError as err:
            _LOGGER.warning("Не удалось обновить камеру %s: %s", cam_id, err)
            return None
        if self.data is not None:
            self.data.cameras[cam_id] = cam
            self.async_update_listeners()
        return cam
