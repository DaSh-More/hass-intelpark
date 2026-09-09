from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.intelpark.api import (
    AccountPlace,
    Camera,
    Gate,
    IntelparkAuthError,
    IntelparkConnectionError,
    IntelparkError,
)
from custom_components.intelpark.const import CONF_HASH, CONF_PHONE, DOMAIN, EVENT_NOTIFICATION
from custom_components.intelpark.coordinator import IntelparkCoordinator, IntelparkData


def _entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_PHONE: "7900", CONF_HASH: "H"}, unique_id="7900"
    )
    entry.add_to_hass(hass)
    return entry


def _cam():
    return Camera("c1", "Двор", "Дом", "http://s", "http://v/c1", "T", 0)


async def test_update_ok(hass):
    entry = _entry(hass)
    coord = IntelparkCoordinator(hass, entry)
    coord.client.async_get_objects = AsyncMock(return_value=[AccountPlace(7, "Дом", "1")])
    coord.client.async_get_gates = AsyncMock(return_value=[Gate("1", "Ш", 7, "Дом", "")])
    coord.client.async_get_cameras = AsyncMock(return_value=[_cam()])
    coord.client.async_get_passes = AsyncMock(return_value=[])
    coord.client.async_get_notifications = AsyncMock(return_value=[])

    data = await coord._async_update_data()
    assert data.cameras["c1"].name == "Двор"
    assert data.gates[0].gid == "1"
    assert data.objects[0].name == "Дом"
    assert data.passes == []
    assert data.notifications == []


async def test_update_auth_error(hass):
    entry = _entry(hass)
    coord = IntelparkCoordinator(hass, entry)
    coord.client.async_get_objects = AsyncMock(side_effect=IntelparkAuthError("bad"))
    with pytest.raises(ConfigEntryAuthFailed):
        await coord._async_update_data()


async def test_update_conn_error(hass):
    entry = _entry(hass)
    coord = IntelparkCoordinator(hass, entry)
    coord.client.async_get_objects = AsyncMock(side_effect=IntelparkConnectionError("net"))
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()


async def test_notification_event_fired(hass):
    entry = _entry(hass)
    coord = IntelparkCoordinator(hass, entry)
    coord.client.async_get_objects = AsyncMock(return_value=[])
    coord.client.async_get_gates = AsyncMock(return_value=[])
    coord.client.async_get_cameras = AsyncMock(return_value=[])
    coord.client.async_get_passes = AsyncMock(return_value=[])
    # реальный ключ id уведомления — notificationId
    coord.client.async_get_notifications = AsyncMock(
        return_value=[{"notificationId": "n1", "notification": "Гость"}]
    )
    events = []
    hass.bus.async_listen(EVENT_NOTIFICATION, lambda e: events.append(e))

    # первый апдейт инициализирует базу id, событий нет
    await coord._async_update_data()
    await hass.async_block_till_done()
    assert events == []

    # второй апдейт с новым id -> событие
    coord.client.async_get_notifications = AsyncMock(
        return_value=[
            {"notificationId": "n2", "notification": "Новый"},
            {"notificationId": "n1", "notification": "Гость"},
        ]
    )
    await coord._async_update_data()
    await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data["notificationId"] == "n2"


async def test_refresh_camera_success(hass):
    entry = _entry(hass)
    coord = IntelparkCoordinator(hass, entry)
    coord.data = IntelparkData(cameras={"c1": _cam()})
    coord.client.async_get_camera = AsyncMock(
        return_value=Camera("c1", "Двор", "Дом", "http://s", "http://v/c1", "NEW", 999)
    )

    with patch.object(coord, "async_update_listeners") as mock_notify:
        result = await coord.async_refresh_camera("c1")

    assert result.stream_token == "NEW"
    assert coord.data.cameras["c1"].stream_token == "NEW"
    mock_notify.assert_called_once()


async def test_refresh_camera_error_returns_none(hass):
    entry = _entry(hass)
    coord = IntelparkCoordinator(hass, entry)
    coord.data = IntelparkData(cameras={"c1": _cam()})
    coord.client.async_get_camera = AsyncMock(side_effect=IntelparkError("boom"))

    result = await coord.async_refresh_camera("c1")

    assert result is None
    assert coord.data.cameras["c1"].stream_token == "T"
