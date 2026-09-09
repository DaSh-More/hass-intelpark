import time
from unittest.mock import AsyncMock, patch

from homeassistant.components.camera import CameraEntityFeature
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.intelpark.api import AccountPlace, Camera
from custom_components.intelpark.const import CONF_HASH, CONF_PHONE, DOMAIN


def _cam(token="T", valid_till=0):
    return Camera("c1", "Двор", "Дом", "http://v/c1/s.jpg", "http://v/c1", token, valid_till)


async def _setup(hass, cam):
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_PHONE: "7900", CONF_HASH: "H"}, unique_id="7900"
    )
    entry.add_to_hass(hass)
    with patch.multiple(
        "custom_components.intelpark.coordinator.IntelparkApiClient",
        async_get_objects=AsyncMock(return_value=[AccountPlace(7, "Дом", "1")]),
        async_get_gates=AsyncMock(return_value=[]),
        async_get_cameras=AsyncMock(return_value=[cam]),
        async_get_passes=AsyncMock(return_value=[]),
        async_get_notifications=AsyncMock(return_value=[]),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_camera_created(hass):
    await _setup(hass, _cam())
    assert hass.states.get("camera.dom_dvor") is not None


async def test_stream_source_valid_token(hass):
    entry = await _setup(hass, _cam(token="T", valid_till=int(time.time()) + 3600))
    coordinator = entry.runtime_data
    from custom_components.intelpark.camera import IntelparkCamera

    ent = IntelparkCamera(coordinator, coordinator.data.cameras["c1"])
    url = await ent.stream_source()
    assert url == "http://v/c1/index.m3u8?token=T"


async def test_stream_source_refreshes_expired_token(hass):
    entry = await _setup(hass, _cam(token="OLD", valid_till=int(time.time()) - 10))
    coordinator = entry.runtime_data
    from custom_components.intelpark.camera import IntelparkCamera

    ent = IntelparkCamera(coordinator, coordinator.data.cameras["c1"])
    with patch.object(
        coordinator, "async_refresh_camera",
        AsyncMock(return_value=_cam(token="NEW", valid_till=int(time.time()) + 3600)),
    ) as mock_refresh:
        url = await ent.stream_source()
    mock_refresh.assert_awaited_once_with("c1")
    assert url == "http://v/c1/index.m3u8?token=NEW"


async def test_camera_image(hass):
    entry = await _setup(hass, _cam())
    coordinator = entry.runtime_data
    from custom_components.intelpark.camera import IntelparkCamera

    ent = IntelparkCamera(coordinator, coordinator.data.cameras["c1"])
    with patch(
        "custom_components.intelpark.coordinator.IntelparkApiClient.async_fetch_snapshot",
        AsyncMock(return_value=b"JPEGBYTES"),
    ) as mock_fetch:
        img = await ent.async_camera_image()
    assert img == b"JPEGBYTES"
    mock_fetch.assert_awaited_once_with("http://v/c1/s.jpg")


async def test_stream_source_refresh_fails_falls_back(hass):
    entry = await _setup(hass, _cam(token="OLD", valid_till=int(time.time()) - 10))
    coordinator = entry.runtime_data
    from custom_components.intelpark.camera import IntelparkCamera

    ent = IntelparkCamera(coordinator, coordinator.data.cameras["c1"])
    with patch.object(
        coordinator, "async_refresh_camera", AsyncMock(return_value=None)
    ) as mock_refresh:
        url = await ent.stream_source()
    mock_refresh.assert_awaited_once_with("c1")
    assert url == "http://v/c1/index.m3u8?token=OLD"


async def test_available_true_and_false(hass):
    entry = await _setup(hass, _cam())
    coordinator = entry.runtime_data
    from custom_components.intelpark.camera import IntelparkCamera

    ent = IntelparkCamera(coordinator, coordinator.data.cameras["c1"])
    assert ent.available is True

    coordinator.data.cameras.pop("c1")
    assert ent.available is False

    coordinator.data.cameras["c1"] = _cam()
    coordinator.last_update_success = False
    assert ent.available is False


async def test_stream_source_no_camera(hass):
    entry = await _setup(hass, _cam())
    coordinator = entry.runtime_data
    from custom_components.intelpark.camera import IntelparkCamera

    ent = IntelparkCamera(coordinator, coordinator.data.cameras["c1"])
    coordinator.data.cameras.clear()
    assert await ent.stream_source() is None


async def test_camera_image_no_snapshot(hass):
    cam = Camera("c1", "Двор", "Дом", "", "http://v/c1", "T", 0)
    entry = await _setup(hass, cam)
    coordinator = entry.runtime_data
    from custom_components.intelpark.camera import IntelparkCamera

    ent = IntelparkCamera(coordinator, coordinator.data.cameras["c1"])
    assert await ent.async_camera_image() is None


async def test_entity_attributes(hass):
    entry = await _setup(hass, _cam())
    coordinator = entry.runtime_data
    from custom_components.intelpark.camera import IntelparkCamera

    ent = IntelparkCamera(coordinator, coordinator.data.cameras["c1"])
    assert ent.unique_id == "intelpark_camera_c1"
    assert CameraEntityFeature.STREAM in ent.supported_features
    assert ent.device_info["name"] == "Дом"
