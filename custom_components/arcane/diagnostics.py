"""Diagnostics for Arcane, with the URL and API key redacted."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY, CONF_URL
from homeassistant.core import HomeAssistant

from .coordinator import ArcaneConfigEntry

TO_REDACT = {CONF_API_KEY, CONF_URL}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ArcaneConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "environments": {env_id: asdict(env) for env_id, env in (coordinator.data or {}).items()},
    }
