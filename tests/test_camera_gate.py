"""Камеры шлагбаумов (`get_gates`): live-поток без токена."""
from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.intelpark.api import AccountPlace, Gate, IntelparkError
from custom_components.intelpark.const import CONF_HASH, CONF_PHONE, DOMAIN


def _gate(gid="1460", name="№1", live_url="https://v/1460-abc", live_cam="0",
          snapshot_image="https://s/img"):
    return Gate(gid, name, 743, "Дом", live_url, live_cam, snapshot_image)


async def _setup(hass, gates):
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_PHONE: "7900", CONF_HASH: "H"}, unique_id="7900"
    )
    entry.add_to_hass(hass)
    with patch.multiple(
        "custom_components.intelpark.coordinator.IntelparkApiClient",
        async_get_objects=AsyncMock(return_value=[AccountPlace(743, "Дом", "1")]),
        async_get_gates=AsyncMock(return_value=gates),
        async_get_cameras=AsyncMock(return_value=[]),
        async_get_passes=AsyncMock(return_value=[]),
        async_get_notifications=AsyncMock(return_value=[]),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_gate_camera_created_when_live_url_present(hass):
    entry = await _setup(hass, [_gate()])
    ids = hass.states.async_entity_ids("camera")
    assert ids == ["camera.shlagbaum_1_kamera"]
    assert hass.states.get("camera.shlagbaum_1_kamera") is not None


async def test_gate_camera_not_created_without_live_url(hass):
    await _setup(hass, [_gate(live_url="")])
    assert hass.states.async_entity_ids("camera") == []


async def test_stream_source_no_token(hass):
    entry = await _setup(hass, [_gate()])
    coordinator = entry.runtime_data
    from custom_components.intelpark.camera import IntelparkGateCamera

    ent = IntelparkGateCamera(coordinator, coordinator.data.gates[0])
    assert await ent.stream_source() == "https://v/1460-abc/mono.m3u8"


async def test_gate_camera_unavailable_when_gate_gone(hass):
    entry = await _setup(hass, [_gate()])
    coordinator = entry.runtime_data
    from custom_components.intelpark.camera import IntelparkGateCamera

    ent = IntelparkGateCamera(coordinator, coordinator.data.gates[0])
    assert ent.available is True

    coordinator.data.gates.clear()
    assert ent.available is False
    assert await ent.stream_source() is None


async def test_camera_image_fallback_none_on_error(hass):
    entry = await _setup(hass, [_gate()])
    coordinator = entry.runtime_data
    from custom_components.intelpark.camera import IntelparkGateCamera

    ent = IntelparkGateCamera(coordinator, coordinator.data.gates[0])
    with patch(
        "custom_components.intelpark.coordinator.IntelparkApiClient.async_fetch_snapshot",
        AsyncMock(side_effect=IntelparkError("HTTP 502")),
    ) as mock_fetch:
        img = await ent.async_camera_image()
    assert img is None
    mock_fetch.assert_awaited_once_with("https://s/img")


async def test_camera_image_no_snapshot_image(hass):
    entry = await _setup(hass, [_gate(snapshot_image="")])
    coordinator = entry.runtime_data
    from custom_components.intelpark.camera import IntelparkGateCamera

    ent = IntelparkGateCamera(coordinator, coordinator.data.gates[0])
    assert await ent.async_camera_image() is None


async def test_use_stream_for_stills(hass):
    entry = await _setup(hass, [_gate()])
    coordinator = entry.runtime_data
    from custom_components.intelpark.camera import IntelparkGateCamera

    ent = IntelparkGateCamera(coordinator, coordinator.data.gates[0])
    assert ent.use_stream_for_stills is True


async def test_extra_state_attributes(hass):
    entry = await _setup(hass, [_gate()])
    coordinator = entry.runtime_data
    from custom_components.intelpark.camera import IntelparkGateCamera

    ent = IntelparkGateCamera(coordinator, coordinator.data.gates[0])
    assert ent.extra_state_attributes == {"live_cam": "0"}

    coordinator.data.gates.clear()
    assert ent.extra_state_attributes == {}
