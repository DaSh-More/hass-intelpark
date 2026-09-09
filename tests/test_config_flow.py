from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType

from custom_components.intelpark.const import CONF_HASH, CONF_PHONE, DOMAIN


async def test_full_flow_ok(hass):
    with patch(
        "custom_components.intelpark.config_flow.IntelparkApiClient.async_send_code",
        return_value=None,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PHONE: "+7 916 123-45-67"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "code"

    with patch(
        "custom_components.intelpark.config_flow.IntelparkApiClient.async_get_hash",
        return_value=("79161234567", "HASH"),
    ), patch(
        "custom_components.intelpark.config_flow.IntelparkApiClient.async_check_auth",
        return_value=None,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"code": "1234"}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_PHONE: "79161234567", CONF_HASH: "HASH"}


async def test_bad_code_shows_error(hass):
    from custom_components.intelpark.api import IntelparkError

    with patch(
        "custom_components.intelpark.config_flow.IntelparkApiClient.async_send_code",
        return_value=None,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PHONE: "79161234567"}
        )

    with patch(
        "custom_components.intelpark.config_flow.IntelparkApiClient.async_get_hash",
        side_effect=IntelparkError("Неверный код"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"code": "0000"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_code"}


async def test_reauth_updates_hash(hass):
    from homeassistant.config_entries import SOURCE_REAUTH
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="79161234567",
        data={CONF_PHONE: "79161234567", CONF_HASH: "OLD"},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.intelpark.config_flow.IntelparkApiClient.async_send_code",
        return_value=None,
    ):
        result = await entry.start_reauth_flow(hass)
        assert result["step_id"] == "user"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PHONE: "79161234567"}
        )

    with patch(
        "custom_components.intelpark.config_flow.IntelparkApiClient.async_get_hash",
        return_value=("79161234567", "NEW"),
    ), patch(
        "custom_components.intelpark.config_flow.IntelparkApiClient.async_check_auth",
        return_value=None,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"code": "1234"}
        )

    assert result["type"].name == "ABORT"
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_HASH] == "NEW"


async def test_invalid_phone(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PHONE: "abc"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_phone"}


async def test_cannot_connect_on_send(hass):
    from custom_components.intelpark.api import IntelparkConnectionError

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with patch(
        "custom_components.intelpark.config_flow.IntelparkApiClient.async_send_code",
        side_effect=IntelparkConnectionError("net"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PHONE: "79161234567"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_already_configured(hass):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="79161234567",
        data={CONF_PHONE: "79161234567", CONF_HASH: "OLD"},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.intelpark.config_flow.IntelparkApiClient.async_send_code",
        return_value=None,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PHONE: "79161234567"}
        )

    with patch(
        "custom_components.intelpark.config_flow.IntelparkApiClient.async_get_hash",
        return_value=("79161234567", "H"),
    ), patch(
        "custom_components.intelpark.config_flow.IntelparkApiClient.async_check_auth",
        return_value=None,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"code": "1234"}
        )

    assert result["type"].name == "ABORT"
    assert result["reason"] == "already_configured"


async def test_reauth_wrong_account_aborts(hass):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="79161234567",
        data={CONF_PHONE: "79161234567", CONF_HASH: "OLD"},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.intelpark.config_flow.IntelparkApiClient.async_send_code",
        return_value=None,
    ):
        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PHONE: "79161234567"}
        )

    with patch(
        "custom_components.intelpark.config_flow.IntelparkApiClient.async_get_hash",
        return_value=("79990000000", "NEW"),
    ), patch(
        "custom_components.intelpark.config_flow.IntelparkApiClient.async_check_auth",
        return_value=None,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"code": "1234"}
        )

    assert result["type"].name == "ABORT"
    assert result["reason"] == "unique_id_mismatch"
    assert entry.data[CONF_HASH] == "OLD"
