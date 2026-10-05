"""Sensors for Arcane environments and containers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import ACTIONS, CONTAINER_STATES
from .coordinator import ArcaneConfigEntry, ArcaneCoordinator, Container, Environment
from .entity import ArcaneContainerEntity, ArcaneEnvironmentEntity, add_new_entities

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class EnvironmentSensorDescription(SensorEntityDescription):
    value_fn: Callable[[Environment], int]


@dataclass(frozen=True, kw_only=True)
class ContainerSensorDescription(SensorEntityDescription):
    value_fn: Callable[[Container], Any]


ENVIRONMENT_SENSORS = (
    EnvironmentSensorDescription(
        key="running",
        translation_key="running",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda env: env.running,
    ),
    EnvironmentSensorDescription(
        key="stopped",
        translation_key="stopped",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda env: env.stopped,
    ),
    EnvironmentSensorDescription(
        key="total",
        translation_key="total",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda env: len(env.containers),
    ),
    EnvironmentSensorDescription(
        key="updates",
        translation_key="updates",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda env: env.updates,
    ),
)

CONTAINER_SENSORS = (
    ContainerSensorDescription(
        key="cpu",
        translation_key="cpu",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda c: c.cpu_percent if c.state == "running" else 0,
    ),
    ContainerSensorDescription(
        key="memory",
        translation_key="memory",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.MEBIBYTES,
        suggested_display_precision=0,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.memory_usage if c.state == "running" else 0,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ArcaneConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data

    add_new_entities(
        coordinator,
        entry,
        async_add_entities,
        for_environment=lambda env_id: [ArcaneEnvironmentSensor(coordinator, env_id, d) for d in ENVIRONMENT_SENSORS],
        for_container=lambda env_id, name: [
            ArcaneContainerStateSensor(coordinator, env_id, name),
            *(ArcaneContainerSensor(coordinator, env_id, name, d) for d in CONTAINER_SENSORS),
        ],
    )

    # arcane.start / stop / restart / redeploy, aimed at a container's State sensor.
    # The Lovelace card uses these, and they read well in automations.
    platform = entity_platform.async_get_current_platform()
    for action in ACTIONS:
        platform.async_register_entity_service(action, None, f"async_service_{action}")


class ArcaneEnvironmentSensor(ArcaneEnvironmentEntity, SensorEntity):
    entity_description: EnvironmentSensorDescription

    def __init__(self, coordinator: ArcaneCoordinator, env_id: str, description: EnvironmentSensorDescription) -> None:
        super().__init__(coordinator, env_id, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        env = self.environment
        return super().available and env is not None and env.online

    @property
    def native_value(self) -> int | None:
        env = self.environment
        return self.entity_description.value_fn(env) if env else None


class ArcaneContainerSensor(ArcaneContainerEntity, SensorEntity):
    entity_description: ContainerSensorDescription

    def __init__(
        self, coordinator: ArcaneCoordinator, env_id: str, name: str, description: ContainerSensorDescription
    ) -> None:
        super().__init__(coordinator, env_id, name, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        container = self.container
        return self.entity_description.value_fn(container) if container else None


class ArcaneContainerStateSensor(ArcaneContainerEntity, SensorEntity):
    """The container's Docker state. Its attributes feed the Arcane card."""

    _attr_translation_key = "state"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [*CONTAINER_STATES, "unknown"]
    # Live stats change every poll; keep them out of the recorder.
    _unrecorded_attributes = frozenset(
        {"cpu_percent", "memory_usage", "memory_limit", "status", "container_id", "latest_version", "current_version"}
    )

    def __init__(self, coordinator: ArcaneCoordinator, env_id: str, name: str) -> None:
        super().__init__(coordinator, env_id, name, "state")

    @property
    def native_value(self) -> str | None:
        container = self.container
        if container is None:
            return None
        return container.state if container.state in CONTAINER_STATES else "unknown"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        container = self.container
        if container is None:
            return None
        env = self.coordinator.data[self.env_id]
        return {
            "arcane_container": container.name,
            "arcane_environment": env.id,
            "arcane_environment_name": env.name,
            "container_id": container.id,
            "image": container.image,
            "status": container.status,
            "health": container.health,
            "project": container.project,
            "cpu_percent": container.cpu_percent,
            "memory_usage": container.memory_usage,
            "memory_limit": container.memory_limit,
            "update_available": container.has_update,
            "current_version": container.current_version,
            "latest_version": container.latest_version,
            "redeploy_disabled": container.redeploy_disabled,
        }
