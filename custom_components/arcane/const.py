"""Constants for the Arcane integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "arcane"

CONF_SCAN_INTERVAL: Final = "scan_interval"
DEFAULT_SCAN_INTERVAL: Final = 30  # seconds
MIN_SCAN_INTERVAL: Final = 10
DEFAULT_TIMEOUT: Final = 20  # a resource-sorted list waits on docker stats

PAGE_SIZE: Final = 100
MAX_PAGES: Final = 50

# Docker container states, as Arcane reports them in a container summary.
CONTAINER_STATES: Final = [
    "running",
    "paused",
    "restarting",
    "created",
    "exited",
    "removing",
    "dead",
]

ACTION_START: Final = "start"
ACTION_STOP: Final = "stop"
ACTION_RESTART: Final = "restart"
ACTION_REDEPLOY: Final = "redeploy"
ACTIONS: Final = [ACTION_START, ACTION_STOP, ACTION_RESTART, ACTION_REDEPLOY]

# Where the bundled Lovelace card is served from.
CARD_FILENAME: Final = "arcane-card.js"
CARD_URL_BASE: Final = "/arcane_static"

REFRESH_AFTER_ACTION: Final = timedelta(seconds=2)
