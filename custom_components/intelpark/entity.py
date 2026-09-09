"""Общие помощники сущностей Intelpark."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Gate
from .const import DOMAIN, MANUFACTURER
from .coordinator import IntelparkCoordinator


def strip_number_sign(name: str) -> str:
    """Убрать символ «№» из имени сущности.

    Символ «№» ломает проброс в Яндекс/УДЯ (yaha), поэтому «№1» → «1».
    """
    return name.replace("№", "").strip()


def gate_device_info(entry_id: str, gate: Gate) -> DeviceInfo:
    """Устройство «въезд» — общее для кнопки открытия и камеры одного шлагбаума."""
    name = strip_number_sign(gate.name) or gate.gid
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry_id}:gate:{gate.gid}")},
        name=f"Шлагбаум {name}",
        manufacturer=MANUFACTURER,
        model="Шлагбаум",
    )


def object_device_info(entry_id: str, object_name: str) -> DeviceInfo:
    """DeviceInfo для объекта (двора), группирующего камеры/ворота/сенсоры."""
    name = object_name or "Дворецкий"
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry_id}:{name}")},
        name=name,
        manufacturer=MANUFACTURER,
    )


class IntelparkEntity(CoordinatorEntity[IntelparkCoordinator]):
    """Базовая сущность на координаторе."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: IntelparkCoordinator, object_name: str) -> None:
        super().__init__(coordinator)
        self._attr_device_info = object_device_info(
            coordinator.config_entry.entry_id, object_name
        )
