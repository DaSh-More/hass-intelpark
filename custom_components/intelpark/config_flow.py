"""Config flow интеграции Intelpark."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig

from .api import (
    IntelparkApiClient,
    IntelparkAuthError,
    IntelparkConnectionError,
    IntelparkError,
    normalize_phone,
)
from .const import (
    CONF_GATE_PREVIEW_SOURCE,
    CONF_HASH,
    CONF_PHONE,
    DEFAULT_GATE_PREVIEW_SOURCE,
    DOMAIN,
    GATE_PREVIEW_SOURCES,
)


class IntelparkConfigFlow(ConfigFlow, domain=DOMAIN):
    """Двухшаговая SMS-авторизация."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> IntelparkOptionsFlow:
        return IntelparkOptionsFlow()

    def __init__(self) -> None:
        self._phone: str = ""
        self._reauth_entry = None

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        self._reauth_entry = self._get_reauth_entry()
        self._phone = entry_data.get(CONF_PHONE, "")
        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                phone = normalize_phone(user_input[CONF_PHONE])
            except ValueError:
                errors["base"] = "invalid_phone"
            else:
                client = IntelparkApiClient(async_get_clientsession(self.hass))
                try:
                    await client.async_send_code(phone)
                except IntelparkConnectionError:
                    errors["base"] = "cannot_connect"
                except IntelparkError:
                    errors["base"] = "send_code_failed"
                else:
                    self._phone = phone
                    return await self.async_step_code()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_PHONE, default=self._phone): str}
            ),
            errors=errors,
        )

    async def async_step_code(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            client = IntelparkApiClient(async_get_clientsession(self.hass))
            try:
                phone, hash_ = await client.async_get_hash(
                    self._phone, user_input["code"]
                )
                verify = IntelparkApiClient(
                    async_get_clientsession(self.hass), phone=phone, hash_=hash_
                )
                await verify.async_check_auth()
            except IntelparkConnectionError:
                errors["base"] = "cannot_connect"
            # IntelparkAuthError и IntelparkError обрабатываются раздельно
            # намеренно (хотя AuthError — подкласс Error): сейчас оба ведут
            # к invalid_code, но это разные причины и в будущем могут разойтись.
            except IntelparkAuthError:
                errors["base"] = "invalid_code"
            except IntelparkError:
                errors["base"] = "invalid_code"
            else:
                if self._reauth_entry is not None:
                    await self.async_set_unique_id(phone)
                    self._abort_if_unique_id_mismatch()
                    return self.async_update_reload_and_abort(
                        self._reauth_entry,
                        data={CONF_PHONE: phone, CONF_HASH: hash_},
                    )
                await self.async_set_unique_id(phone)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=phone,
                    data={CONF_PHONE: phone, CONF_HASH: hash_},
                )

        return self.async_show_form(
            step_id="code",
            data_schema=vol.Schema({vol.Required("code"): str}),
            errors=errors,
        )


class IntelparkOptionsFlow(OptionsFlow):
    """Choose the still-image source without changing SMS credentials."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get(CONF_GATE_PREVIEW_SOURCE) not in GATE_PREVIEW_SOURCES:
                errors[CONF_GATE_PREVIEW_SOURCE] = "invalid_preview_source"
            else:
                return self.async_create_entry(
                    title="",
                    data={
                        **self.config_entry.options,
                        CONF_GATE_PREVIEW_SOURCE: user_input[CONF_GATE_PREVIEW_SOURCE],
                    },
                )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_GATE_PREVIEW_SOURCE,
                    default=self.config_entry.options.get(
                        CONF_GATE_PREVIEW_SOURCE, DEFAULT_GATE_PREVIEW_SOURCE
                    ),
                ): SelectSelector(SelectSelectorConfig(
                    options=list(GATE_PREVIEW_SOURCES),
                    translation_key=CONF_GATE_PREVIEW_SOURCE,
                )),
            }),
            errors=errors,
        )
