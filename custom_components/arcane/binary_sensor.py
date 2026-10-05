"""Binary sensors for Arcane: environment connectivity and container updates."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ArcaneConfigEntry, ArcaneCoordinator
from .entity import ArcaneContainerEntity, ArcaneEnvironmentEntity, add_new_entities

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: ArcaneConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    add_new_entities(
        coordinator,
        entry,
        async_add_entities,
        for_environment=lambda env_id: [ArcaneEnvironmentOnline(coordinator, env_id)],
        for_container=lambda env_id, name: [ArcaneUpdateAvailable(coordinator, env_id, name)],
    )


class ArcaneEnvironmentOnline(ArcaneEnvironmentEntity, BinarySensorEntity):
    """Whether Arcane can reach this environment's Docker host."""

    _attr_translation_key = "online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ArcaneCoordinator, env_id: str) -> None:
        super().__init__(coordinator, env_id, "online")

    @property
    def is_on(self) -> bool | None:
        env = self.environment
        return env.online if env else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        env = self.environment
        if env is None:
            return None
        return {"arcane_status": env.status, "error": env.error}


class ArcaneUpdateAvailable(ArcaneContainerEntity, BinarySensorEntity):
    """On when Arcane has found a newer image for this container."""

    _attr_translation_key = "update_available"
    _attr_device_class = BinarySensorDeviceClass.UPDATE

    def __init__(self, coordinator: ArcaneCoordinator, env_id: str, name: str) -> None:
        super().__init__(coordinator, env_id, name, "update_available")

    @property
    def is_on(self) -> bool | None:
        container = self.container
        return container.has_update if container else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        container = self.container
        if container is None:
            return None
        return {
            "image": container.image,
            "current_version": container.current_version,
            "latest_version": container.latest_version,
            "check_error": container.update_error,
        }
