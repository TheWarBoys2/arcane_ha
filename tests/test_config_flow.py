"""Config and options flow."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY, CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.arcane.const import CONF_SCAN_INTERVAL, DOMAIN

from .conftest import API, ENVIRONMENTS, URL


async def test_user_flow(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{API}/environments", json=ENVIRONMENTS)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: URL + "/api/", CONF_API_KEY: "arc_test", CONF_VERIFY_SSL: True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_URL] == URL
    assert aioclient_mock.mock_calls[0][3]["X-API-Key"] == "arc_test"


async def test_user_flow_bad_key(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{API}/environments", status=401, json={"detail": "Unauthorized"})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: URL, CONF_API_KEY: "nope", CONF_VERIFY_SSL: True}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_unreachable(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{API}/environments", exc=TimeoutError())
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: "arcane.example:3552", CONF_API_KEY: "arc_test", CONF_VERIFY_SSL: True}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_options_flow(hass: HomeAssistant, arcane, entry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_SCAN_INTERVAL: 60})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_SCAN_INTERVAL] == 60
    assert entry.runtime_data.update_interval.total_seconds() == 60
