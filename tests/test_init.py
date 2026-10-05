"""Setup, entities, actions and the bundled card."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr

from .conftest import API, ENVIRONMENTS


async def _setup(hass: HomeAssistant, entry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_entities(hass: HomeAssistant, arcane, entry) -> None:
    await _setup(hass, entry)

    state = hass.states.get("sensor.web_state")
    assert state.state == "running"
    assert state.attributes["arcane_container"] == "web"
    assert state.attributes["arcane_environment"] == "0"
    assert state.attributes["arcane_environment_name"] == "Main"
    assert state.attributes["health"] == "healthy"
    assert state.attributes["project"] == "web"
    assert state.attributes["update_available"] is True
    assert state.attributes["cpu_percent"] == 1.23

    assert hass.states.get("sensor.web_cpu").state == "1.23"
    assert float(hass.states.get("sensor.web_memory").state) == 50.0  # MiB
    assert hass.states.get("binary_sensor.web_update_available").state == "on"
    assert hass.states.get("sensor.db_state").state == "exited"
    assert hass.states.get("sensor.db_cpu").state == "0"
    assert hass.states.get("binary_sensor.db_update_available").state == "off"

    assert hass.states.get("sensor.main_running_containers").state == "2"
    assert hass.states.get("sensor.main_stopped_containers").state == "1"
    assert hass.states.get("sensor.main_updates_available").state == "1"
    assert hass.states.get("binary_sensor.main_online").state == "on"

    # Arcane can't redeploy itself, so that button is unavailable.
    assert hass.states.get("button.arcane_redeploy").state == "unavailable"
    assert hass.states.get("button.arcane_restart").state != "unavailable"

    # The offline environment is a device, but reports offline.
    assert hass.states.get("binary_sensor.remote_online").state == "off"
    assert hass.states.get("sensor.remote_running_containers").state == "unavailable"

    devices = dr.async_get(hass)
    vw = devices.async_get_device(identifiers={("arcane", f"{entry.entry_id}_0_web")})
    main = devices.async_get_device(identifiers={("arcane", f"{entry.entry_id}_0")})
    assert vw.via_device_id == main.id
    assert main.name == "Main"


async def test_button_press(hass: HomeAssistant, arcane, entry) -> None:
    await _setup(hass, entry)
    arcane.mock_calls.clear()
    await hass.services.async_call("button", "press", {"entity_id": "button.web_restart"}, blocking=True)
    posts = [str(c[1]) for c in arcane.mock_calls if c[0] == "POST"]
    assert posts == [f"{API}/environments/0/containers/aaa111/restart"]


async def test_entity_services(hass: HomeAssistant, arcane, entry) -> None:
    await _setup(hass, entry)
    arcane.mock_calls.clear()
    await hass.services.async_call("arcane", "start", {"entity_id": "sensor.db_state"}, blocking=True)
    await hass.services.async_call("arcane", "redeploy", {"entity_id": "sensor.web_cpu"}, blocking=True)
    posts = [str(c[1]) for c in arcane.mock_calls if c[0] == "POST"]
    assert posts == [
        f"{API}/environments/0/containers/bbb222/start",
        f"{API}/environments/0/containers/aaa111/redeploy",
    ]
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "arcane", "restart", {"entity_id": "sensor.main_running_containers"}, blocking=True
        )


async def test_action_error(hass: HomeAssistant, arcane, entry) -> None:
    await _setup(hass, entry)
    arcane.clear_requests()
    arcane.post(
        f"{API}/environments/0/containers/aaa111/stop", status=500, json={"detail": "Failed to stop container: boom"}
    )
    with pytest.raises(HomeAssistantError, match="boom"):
        await hass.services.async_call("button", "press", {"entity_id": "button.web_stop"}, blocking=True)


async def test_new_container_and_redeploy_id_change(hass: HomeAssistant, arcane, entry, containers) -> None:
    await _setup(hass, entry)
    containers["data"][0]["id"] = "aaa999"  # a redeploy recreates the container
    containers["data"].append(
        {"id": "ddd444", "names": ["/cache"], "image": "redis:7", "state": "running", "status": "Up 1 minute"}
    )
    arcane.clear_requests()
    arcane.get(f"{API}/environments", json=ENVIRONMENTS)
    arcane.get(f"{API}/environments/0/containers", json=containers)
    arcane.get(f"{API}/environments/abc/containers", status=502)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.cache_state").state == "running"
    assert hass.states.get("sensor.web_state").attributes["container_id"] == "aaa999"


async def test_auth_failure_starts_reauth(hass: HomeAssistant, aioclient_mock, entry) -> None:
    aioclient_mock.get(f"{API}/environments", status=401, json={"detail": "invalid API key"})
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flows)


async def test_card_is_served(hass: HomeAssistant, arcane, entry, hass_client) -> None:
    await _setup(hass, entry)
    client = await hass_client()
    resp = await client.get("/arcane_static/arcane-card.js")
    assert resp.status == 200
    assert 'customElements.define("arcane-card"' in await resp.text()

    from homeassistant.components.frontend import DATA_EXTRA_JS_URL_ES5, DATA_EXTRA_MODULE_URL  # noqa: F401

    assert any(url.startswith("/arcane_static/arcane-card.js") for url in hass.data[DATA_EXTRA_JS_URL_ES5].urls) or any(
        url.startswith("/arcane_static/arcane-card.js") for url in hass.data[DATA_EXTRA_MODULE_URL].urls
    )
