"""Шлагбаумы Intelpark как ворота (cover) — действие «Открыть»."""
from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import Gate, IntelparkError
from .const import DOMAIN
from .coordinator import IntelparkConfigEntry, IntelparkCoordinator
from .entity import IntelparkEntity, gate_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IntelparkConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        IntelparkGateCover(coordinator, gate) for gate in coordinator.data.gates
    )


class IntelparkGateCover(IntelparkEntity, CoverEntity):
    """Шлагбаум как ворота: поддерживает только открытие."""

    _attr_device_class = CoverDeviceClass.GATE
    _attr_supported_features = CoverEntityFeature.OPEN
    _attr_icon = "mdi:boom-gate"

    # Основная сущность устройства-въезда: имя берётся от устройства «Шлагбаум N».
    _attr_name = None

    def __init__(self, coordinator: IntelparkCoordinator, gate: Gate) -> None:
        super().__init__(coordinator, gate.object_name)
        self._gid = gate.gid
        self._gate_id_int = gate.gate_id_int
        self._attr_unique_id = f"{DOMAIN}_gate_{gate.gid}"
        self._attr_device_info = gate_device_info(
            coordinator.config_entry.entry_id, gate
        )
        if gate.live_url:
            self._attr_extra_state_attributes = {"live_url": gate.live_url}

    @property
    def _gate(self) -> Gate | None:
        return next(
            (g for g in self.coordinator.data.gates if g.gid == self._gid), None
        )

    @property
    def available(self) -> bool:
        return super().available and self._gate is not None

    @property
    def is_closed(self) -> bool:
        # API не даёт обратной связи о положении шлагбаума; считаем его «закрытым»,
        # чтобы действие «Открыть» всегда было доступно (открытие — разовый импульс).
        return True

    async def async_open_cover(self, **kwargs: Any) -> None:
        try:
            await self.coordinator.client.async_open_gate(self._gate_id_int)
        except IntelparkError as err:
            raise HomeAssistantError(
                f"Не удалось открыть «{self._attr_name}»: {err}"
            ) from err
