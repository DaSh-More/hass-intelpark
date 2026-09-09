from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.intelpark.api import AccountPlace, Camera, Gate
from custom_components.intelpark.const import CONF_HASH, CONF_PHONE, DOMAIN


async def test_setup_and_unload(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_PHONE: "7900", CONF_HASH: "H"}, unique_id="7900"
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.intelpark.coordinator.IntelparkApiClient.async_get_objects",
        AsyncMock(return_value=[AccountPlace(7, "Дом", "1")]),
    ), patch(
        "custom_components.intelpark.coordinator.IntelparkApiClient.async_get_gates",
        AsyncMock(return_value=[Gate("1", "Ш", 7, "Дом", "")]),
    ), patch(
        "custom_components.intelpark.coordinator.IntelparkApiClient.async_get_cameras",
        AsyncMock(return_value=[Camera("c1", "Двор", "Дом", "s", "http://v/c1", "T", 0)]),
    ), patch(
        "custom_components.intelpark.coordinator.IntelparkApiClient.async_get_passes",
        AsyncMock(return_value=[]),
    ), patch(
        "custom_components.intelpark.coordinator.IntelparkApiClient.async_get_notifications",
        AsyncMock(return_value=[]),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
