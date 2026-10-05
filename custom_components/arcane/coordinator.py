"""Polls Arcane for environments and their containers."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ArcaneAuthError, ArcaneClient, ArcaneError
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

_HEALTH = re.compile(r"\((healthy|unhealthy|health: starting)\)")

type ArcaneConfigEntry = ConfigEntry[ArcaneCoordinator]


@dataclass
class Container:
    """One container, keyed by name because a redeploy gives it a new ID."""

    name: str
    id: str
    state: str
    status: str
    image: str
    health: str | None
    project: str | None
    cpu_percent: float | None
    memory_usage: int | None
    memory_limit: int | None
    has_update: bool
    current_version: str | None
    latest_version: str | None
    update_error: str | None
    redeploy_disabled: bool

    @classmethod
    def from_summary(cls, summary: dict[str, Any]) -> Container | None:
        names = [str(n).lstrip("/") for n in summary.get("names") or [] if n]
        if not names or not summary.get("id"):
            return None
        status = str(summary.get("status") or "")
        health = _HEALTH.search(status)
        labels = summary.get("labels") if isinstance(summary.get("labels"), dict) else {}
        sample = summary.get("resourceSample") if isinstance(summary.get("resourceSample"), dict) else None
        update = summary.get("updateInfo") if isinstance(summary.get("updateInfo"), dict) else {}
        return cls(
            name=names[0],
            id=str(summary["id"]),
            state=str(summary.get("state") or "unknown").lower(),
            status=status,
            image=str(summary.get("image") or ""),
            health=health.group(1).replace("health: ", "") if health else None,
            project=labels.get("com.docker.compose.project"),
            cpu_percent=round(float(sample["cpuPercent"]), 2)
            if sample and sample.get("cpuPercent") is not None
            else None,
            memory_usage=int(sample["memoryUsageBytes"])
            if sample and sample.get("memoryUsageBytes") is not None
            else None,
            memory_limit=int(sample["memoryLimitBytes"]) if sample and sample.get("memoryLimitBytes") else None,
            has_update=bool(update.get("hasUpdate")) and not update.get("error"),
            current_version=update.get("currentVersion") or None,
            latest_version=update.get("latestVersion") or None,
            update_error=update.get("error") or None,
            redeploy_disabled=bool(summary.get("redeployDisabled")),
        )


@dataclass
class Environment:
    """One Arcane environment (a Docker host) and its containers."""

    id: str
    name: str
    status: str
    containers: dict[str, Container] = field(default_factory=dict)
    error: str | None = None

    @property
    def online(self) -> bool:
        return self.error is None and self.status.lower() not in ("offline", "error")

    @property
    def running(self) -> int:
        return sum(1 for c in self.containers.values() if c.state == "running")

    @property
    def stopped(self) -> int:
        return sum(1 for c in self.containers.values() if c.state != "running")

    @property
    def updates(self) -> int:
        return sum(1 for c in self.containers.values() if c.has_update)


class ArcaneCoordinator(DataUpdateCoordinator[dict[str, Environment]]):
    """Fetches every environment and its containers each poll."""

    config_entry: ArcaneConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ArcaneConfigEntry, client: ArcaneClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        )
        self.client = client
        self.client_url: str = entry.data[CONF_URL]

    async def _async_update_data(self) -> dict[str, Environment]:
        try:
            envs = await self.client.list_environments()
        except ArcaneAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ArcaneError as err:
            raise UpdateFailed(str(err)) from err

        result: dict[str, Environment] = {}
        for raw in envs:
            env = Environment(
                id=str(raw["id"]),
                name=str(raw.get("name") or raw["id"]),
                status=str(raw.get("status") or ""),
            )
            result[env.id] = env
            if raw.get("enabled") is False:
                env.error = "disabled in Arcane"
                continue
            try:
                summaries, _ = await self.client.list_containers(env.id)
            except ArcaneAuthError as err:
                # A key without access to one environment shouldn't break the rest.
                env.error = str(err)
                continue
            except ArcaneError as err:
                env.error = str(err)
                _LOGGER.debug("Arcane environment %s is unavailable: %s", env.name, err)
                continue
            for summary in summaries:
                container = Container.from_summary(summary)
                if container and container.name not in env.containers:
                    env.containers[container.name] = container
        return result

    def container(self, env_id: str, name: str) -> Container | None:
        env = self.data.get(env_id) if self.data else None
        return env.containers.get(name) if env else None
