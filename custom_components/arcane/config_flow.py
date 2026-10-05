"""Config flow for Arcane: an Arcane URL plus an API key."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_API_KEY, CONF_URL, CONF_VERIFY_SSL
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import ArcaneAuthError, ArcaneClient, ArcaneConnectionError, ArcaneError, normalize_url
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, MIN_SCAN_INTERVAL
from .coordinator import ArcaneConfigEntry

_LOGGER = logging.getLogger(__name__)

API_KEY_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


async def _validate(hass, url: str, api_key: str, verify_ssl: bool) -> str | None:
    """Try the credentials. Returns an error key, or None if they work."""
    client = ArcaneClient(async_get_clientsession(hass, verify_ssl=verify_ssl), url, api_key, verify_ssl=verify_ssl)
    try:
        envs = await client.list_environments()
    except ArcaneAuthError:
        return "invalid_auth"
    except ArcaneConnectionError:
        return "cannot_connect"
    except ArcaneError:
        _LOGGER.exception("Unexpected answer from Arcane")
        return "unknown"
    return None if envs else "no_environments"


class ArcaneConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = normalize_url(user_input[CONF_URL])
            if not url.startswith(("http://", "https://")):
                url = "http://" + url
            await self.async_set_unique_id(url.lower())
            self._abort_if_unique_id_configured()
            error = await _validate(self.hass, url, user_input[CONF_API_KEY], user_input[CONF_VERIFY_SSL])
            if error is None:
                return self.async_create_entry(
                    title="Arcane",
                    data={**user_input, CONF_URL: url},
                )
            errors["base"] = error

        schema = vol.Schema(
            {
                vol.Required(CONF_URL, default=(user_input or {}).get(CONF_URL, "http://")): str,
                vol.Required(CONF_API_KEY): API_KEY_SELECTOR,
                vol.Required(CONF_VERIFY_SSL, default=(user_input or {}).get(CONF_VERIFY_SSL, True)): bool,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await _validate(
                self.hass, entry.data[CONF_URL], user_input[CONF_API_KEY], entry.data.get(CONF_VERIFY_SSL, True)
            )
            if error is None:
                return self.async_update_reload_and_abort(entry, data_updates={CONF_API_KEY: user_input[CONF_API_KEY]})
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): API_KEY_SELECTOR}),
            description_placeholders={"url": entry.data[CONF_URL]},
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: ArcaneConfigEntry) -> OptionsFlow:
        return ArcaneOptionsFlow()


class ArcaneOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])})
        current = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=3600,
                            step=1,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
        )
