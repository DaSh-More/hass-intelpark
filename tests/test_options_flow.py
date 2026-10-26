"""Entry-scoped preview options, validation and supported reload lifecycle."""
from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.intelpark.const import DOMAIN

from .test_camera_gate import _gate, _setup

KEY = "gate_preview_source"


@pytest.mark.parametrize("options, default", [({}, "stream"), ({KEY: "snapshot"}, "snapshot"), ({KEY: "stream"}, "stream")])
async def test_form_has_one_translated_selector_with_saved_default(hass, options, default):
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=options)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    schema = result["data_schema"]
    assert schema({}) == {KEY: default}
    selector = next(iter(schema.schema.values()))
    assert selector.config["options"] == ["stream", "snapshot"]
    assert selector.config["translation_key"] == KEY
    assert len(schema.schema) == 1


@pytest.mark.parametrize("source", ["stream", "snapshot"])
async def test_save_preserves_unrelated_options_and_auth(hass, source):
    entry = MockConfigEntry(domain=DOMAIN, data={"phone": "7900", "hash": "H"}, options={"future_option": 42})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {KEY: source})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {KEY: source, "future_option": 42}
    assert dict(entry.data) == {"phone": "7900", "hash": "H"}


@pytest.mark.parametrize("value", ["invalid", "", None, 1, ["snapshot"]])
async def test_invalid_selection_rejected(hass, value):
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={KEY: "stream"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    # Form schema and direct flow submission both enforce the allowlist.
    with pytest.raises(vol.Invalid):
        result["data_schema"]({KEY: value})
    from homeassistant.data_entry_flow import InvalidData

    from custom_components.intelpark.config_flow import IntelparkOptionsFlow
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(result["flow_id"], {KEY: value})
    flow = IntelparkOptionsFlow()
    flow.hass = hass
    flow.handler = entry.entry_id
    result = await flow.async_step_init({KEY: value})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {KEY: "invalid_preview_source"}
    assert dict(entry.options) == {KEY: "stream"}


async def test_saving_options_reloads_only_entry_and_listener_removed_on_unload(hass):
    entry = await _setup(hass, [_gate()])
    with patch.object(hass.config_entries, "async_reload", new_callable=AsyncMock) as reload:
        result = await hass.config_entries.options.async_init(entry.entry_id)
        await hass.config_entries.options.async_configure(result["flow_id"], {KEY: "snapshot"})
        await hass.async_block_till_done()
        reload.assert_awaited_once_with(entry.entry_id)
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        hass.config_entries.async_update_entry(entry, options={KEY: "stream"})
        await hass.async_block_till_done()
        reload.assert_awaited_once()


async def test_actual_reload_switches_mode_without_migrating_unset_options(hass):
    from homeassistant.helpers import entity_component

    from custom_components.intelpark.camera import IntelparkGateCamera
    entry = await _setup(hass, [_gate()])
    original = entry.runtime_data
    assert dict(entry.options) == {}
    assert IntelparkGateCamera(original, original.data.gates[0]).use_stream_for_stills
    with patch.multiple(
        "custom_components.intelpark.coordinator.IntelparkApiClient",
        async_get_objects=AsyncMock(return_value=list(original.data.objects)),
        async_get_gates=AsyncMock(return_value=[_gate()]),
        async_get_cameras=AsyncMock(return_value=[]),
        async_get_passes=AsyncMock(return_value=[]),
        async_get_notifications=AsyncMock(return_value=[]),
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        await hass.config_entries.options.async_configure(result["flow_id"], {KEY: "snapshot"})
        await hass.async_block_till_done()
    assert entry.runtime_data is not original
    component = hass.data[entity_component.DATA_INSTANCES]["camera"]
    assert not next(iter(component.entities)).use_stream_for_stills


async def test_actual_options_reload_drains_pending_snapshot_and_resets_cache(hass):
    import asyncio

    from homeassistant.helpers import entity_component

    from custom_components.intelpark.api import AccountPlace
    entry = await _setup(hass, [_gate()], {KEY: "snapshot"})
    component = hass.data[entity_component.DATA_INSTANCES]["camera"]
    old = next(iter(component.entities))
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def pending(url):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with patch.object(entry.runtime_data.client, "async_fetch_snapshot", side_effect=pending):
        waiter = asyncio.create_task(old.async_camera_image())
        await started.wait()
        with patch.multiple(
            "custom_components.intelpark.coordinator.IntelparkApiClient",
            async_get_objects=AsyncMock(return_value=[AccountPlace(743, "Дом", "1")]),
            async_get_gates=AsyncMock(return_value=[_gate()]),
            async_get_cameras=AsyncMock(return_value=[]),
            async_get_passes=AsyncMock(return_value=[]),
            async_get_notifications=AsyncMock(return_value=[]),
        ):
            result = await hass.config_entries.options.async_init(entry.entry_id)
            await hass.config_entries.options.async_configure(result["flow_id"], {KEY: "stream"})
            await hass.async_block_till_done()
        with pytest.raises(asyncio.CancelledError):
            await waiter
    assert cancelled.is_set()
    assert not old._image_tasks
    assert not old._image_inflight
    current = next(iter(component.entities))
    assert current is not old
    assert current.use_stream_for_stills
    assert current._last_snapshot is None


def test_translations_match_selector_values_and_russian_label():
    import json
    from pathlib import Path
    root = Path(__file__).parents[1] / "custom_components" / DOMAIN
    for filename in ("strings.json", "translations/ru.json", "translations/en.json"):
        data = json.loads((root / filename).read_text())
        assert set(data["selector"][KEY]["options"]) == {"stream", "snapshot"}
        labels = data["options"]["step"]["init"]["data"]
        assert set(labels) == {KEY}
        if filename != "translations/en.json":
            assert labels[KEY] == "Источник изображения"
            assert data["options"]["step"]["init"]["title"] == "Выбор источника превью камеры"
