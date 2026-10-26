"""Gate entities and explicit preview-source dispatch."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.camera import async_get_image
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.intelpark import camera
from custom_components.intelpark.api import AccountPlace, Gate
from custom_components.intelpark.const import CONF_HASH, CONF_PHONE, DOMAIN


def _gate(gid="1460", name="№1", live_url="https://v/1460-abc", live_cam="0",
          snapshot_image="https://s/img"):
    return Gate(gid, name, 743, "Дом", live_url, live_cam, snapshot_image)


async def _setup(hass, gates, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_PHONE: "7900", CONF_HASH: "H"}, unique_id="7900",
        options=options or {},
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
    await _setup(hass, [_gate()])
    assert hass.states.async_entity_ids("camera") == ["camera.shlagbaum_1_kamera"]


async def test_gate_camera_not_created_without_live_url(hass):
    await _setup(hass, [_gate(live_url="")])
    assert hass.states.async_entity_ids("camera") == []


@pytest.mark.parametrize("options", [{}, {"gate_preview_source": "stream"}, {"gate_preview_source": "snapshot"}])
async def test_live_availability_and_attributes_unchanged(hass, options):
    entry = await _setup(hass, [_gate()], options)
    coordinator = entry.runtime_data
    ent = camera.IntelparkGateCamera(coordinator, coordinator.data.gates[0])
    assert await ent.stream_source() == "https://v/1460-abc/mono.m3u8"
    assert ent.available
    assert ent.extra_state_attributes == {"live_cam": "0"}
    coordinator.data.gates.clear()
    assert not ent.available
    assert await ent.stream_source() is None
    assert ent.extra_state_attributes == {}
    assert await ent.async_camera_image() is None


@pytest.mark.parametrize("options, uses_stream", [({}, True), ({"gate_preview_source": "stream"}, True), ({"gate_preview_source": "snapshot"}, False)])
@pytest.mark.parametrize("snapshot_url", ["https://s/img", ""])
async def test_core_dispatch_uses_selected_source_without_snapshot_fallback(hass, options, uses_stream, snapshot_url):
    await _setup(hass, [_gate(snapshot_image=snapshot_url)], options)
    with (
        patch.object(
            camera.IntelparkGateCamera, "async_camera_image", new_callable=AsyncMock, return_value=b"snapshot"
        ) as snapshot,
        patch("homeassistant.components.camera.async_get_stream_image", new_callable=AsyncMock, return_value=b"frame") as stream,
    ):
        result = await async_get_image(hass, "camera.shlagbaum_1_kamera")
    assert result.content == (b"frame" if uses_stream else b"snapshot")
    assert stream.await_count == int(uses_stream)
    assert snapshot.await_count == int(not uses_stream)


async def test_direct_stream_image_uses_actual_helper_and_existing_stream(hass):
    entry = await _setup(hass, [_gate()])
    ent = camera.IntelparkGateCamera(entry.runtime_data, entry.runtime_data.data.gates[0])
    ent.hass = hass
    ent.stream = MagicMock()
    ent.stream.async_get_image = AsyncMock(return_value=b"existing stream frame")
    with (
        patch.object(entry.runtime_data.client, "async_fetch_snapshot") as fetch,
        patch.object(ent, "async_create_stream", new_callable=AsyncMock) as create,
    ):
        assert await ent.async_camera_image(width=640, height=360) == b"existing stream frame"
    ent.stream.async_get_image.assert_awaited_once_with(width=640, height=360, wait_for_next_keyframe=False)
    create.assert_not_awaited()
    fetch.assert_not_awaited()


@pytest.mark.parametrize("error", [None, HomeAssistantError("stream failed"), TimeoutError()])
async def test_direct_stream_helper_failures_preserved(hass, error):
    entry = await _setup(hass, [_gate()])
    ent = camera.IntelparkGateCamera(entry.runtime_data, entry.runtime_data.data.gates[0])
    with (
        patch.object(camera, "async_get_stream_image", return_value=None, side_effect=error) as stream,
        patch.object(entry.runtime_data.client, "async_fetch_snapshot") as fetch,
    ):
        if error is None:
            assert await ent.async_camera_image() is None
        else:
            with pytest.raises(type(error)):
                await ent.async_camera_image()
    stream.assert_awaited_once()
    fetch.assert_not_awaited()
