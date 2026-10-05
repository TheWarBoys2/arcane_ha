"""Base entities: one device per environment, one per container."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import ArcaneError, normalize_url
from .const import DOMAIN
from .coordinator import ArcaneConfigEntry, ArcaneCoordinator, Container, Environment


def env_identifier(coordinator: ArcaneCoordinator, env_id: str) -> tuple[str, str]:
    return (DOMAIN, f"{coordinator.config_entry.entry_id}_{env_id}")


def container_identifier(coordinator: ArcaneCoordinator, env_id: str, name: str) -> tuple[str, str]:
    return (DOMAIN, f"{coordinator.config_entry.entry_id}_{env_id}_{name}")


class ArcaneEnvironmentEntity(CoordinatorEntity[ArcaneCoordinator]):
    """An entity on an environment's device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ArcaneCoordinator, env_id: str, key: str) -> None:
        super().__init__(coordinator)
        self.env_id = env_id
        env = coordinator.data[env_id]
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{env_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={env_identifier(coordinator, env_id)},
            name=env.name,
            manufacturer="Arcane",
            model="Docker environment",
            configuration_url=f"{normalize_url(coordinator.client_url)}/environments/{env_id}",
        )

    @property
    def environment(self) -> Environment | None:
        return self.coordinator.data.get(self.env_id) if self.coordinator.data else None

    async def _not_a_container(self) -> None:
        raise ServiceValidationError(f"{self.entity_id} is an environment sensor; target a container's entity")

    async_service_start = async_service_stop = _not_a_container
    async_service_restart = async_service_redeploy = _not_a_container


class ArcaneContainerEntity(CoordinatorEntity[ArcaneCoordinator]):
    """An entity on a container's device, linked to its environment."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ArcaneCoordinator, env_id: str, name: str, key: str) -> None:
        super().__init__(coordinator)
        self.env_id = env_id
        self.container_name = name
        container = coordinator.data[env_id].containers[name]
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{env_id}_{name}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={container_identifier(coordinator, env_id, name)},
            name=name,
            manufacturer="Arcane",
            model=container.image or "Container",
            via_device=env_identifier(coordinator, env_id),
            configuration_url=f"{normalize_url(coordinator.client_url)}/containers",
        )

    @property
    def container(self) -> Container | None:
        return self.coordinator.container(self.env_id, self.container_name)

    @property
    def available(self) -> bool:
        env = self.coordinator.data.get(self.env_id) if self.coordinator.data else None
        return super().available and env is not None and env.online and self.container is not None

    async def async_run_action(self, action: str) -> None:
        """Start, stop, restart or redeploy this container, then refresh."""
        container = self.container
        if container is None:
            raise HomeAssistantError(f"{self.container_name} is not in Arcane any more")
        try:
            await self.coordinator.client.container_action(self.env_id, container.id, action)
        except ArcaneError as err:
            raise HomeAssistantError(f"Arcane could not {action} {self.container_name}: {err}") from err
        await self.coordinator.async_request_refresh()

    # Targets of the arcane.start / stop / restart / redeploy services.
    async def async_service_start(self) -> None:
        await self.async_run_action("start")

    async def async_service_stop(self) -> None:
        await self.async_run_action("stop")

    async def async_service_restart(self) -> None:
        await self.async_run_action("restart")

    async def async_service_redeploy(self) -> None:
        await self.async_run_action("redeploy")


def add_new_entities(
    coordinator: ArcaneCoordinator,
    entry: ArcaneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    for_environment: Callable[[str], Iterable[Entity]] | None = None,
    for_container: Callable[[str, str], Iterable[Entity]] | None = None,
) -> None:
    """Add entities for environments and containers now, and for new ones as they appear."""
    seen: set[tuple[str, ...]] = set()

    @callback
    def _check() -> None:
        new: list[Entity] = []
        for env_id, env in (coordinator.data or {}).items():
            if for_environment and (env_id,) not in seen:
                seen.add((env_id,))
                new.extend(for_environment(env_id))
            if for_container:
                for name in env.containers:
                    if (env_id, name) not in seen:
                        seen.add((env_id, name))
                        new.extend(for_container(env_id, name))
        if new:
            async_add_entities(new)

    _check()
    entry.async_on_unload(coordinator.async_add_listener(_check))
