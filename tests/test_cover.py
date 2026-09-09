from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.intelpark.api import AccountPlace, Gate, IntelparkError
from custom_components.intelpark.const import CONF_HASH, CONF_PHONE, DOMAIN

ENTITY = "cover.shlagbaum_1"


async def _setup(hass, open_side_effect=None):
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_PHONE: "7900", CONF_HASH: "H"}, unique_id="7900"
    )
    entry.add_to_hass(hass)
    patchers = {
        "async_get_objects": [AccountPlace(7, "Дом", "1")],
        "async_get_gates": [Gate("42", "№1", 7, "Дом", "")],
        "async_get_cameras": [],
        "async_get_passes": [],
        "async_get_notifications": [],
    }
    with patch.multiple(
        "custom_components.intelpark.coordinator.IntelparkApiClient",
        **{k: AsyncMock(return_value=v) for k, v in patchers.items()},
        async_open_gate=AsyncMock(side_effect=open_side_effect),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_cover_created(hass):
    await _setup(hass)
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == "closed"


async def test_open_calls_open_gate(hass):
    await _setup(hass)
    with patch(
        "custom_components.intelpark.coordinator.IntelparkApiClient.async_open_gate",
        AsyncMock(return_value=None),
    ) as mock_open:
        await hass.services.async_call(
            "cover", "open_cover", {"entity_id": ENTITY}, blocking=True
        )
    mock_open.assert_awaited_once_with(42)


async def test_open_error_raises(hass):
    await _setup(hass)
    with patch(
        "custom_components.intelpark.coordinator.IntelparkApiClient.async_open_gate",
        AsyncMock(side_effect=IntelparkError("нет доступа")),
    ):
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(
                "cover", "open_cover", {"entity_id": ENTITY}, blocking=True
            )


async def test_cover_unavailable_when_gate_gone(hass):
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    from custom_components.intelpark.cover import IntelparkGateCover

    ent = IntelparkGateCover(coordinator, coordinator.data.gates[0])
    assert ent.available is True
    coordinator.data.gates.clear()
    assert ent.available is False
