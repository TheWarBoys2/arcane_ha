"""Start, stop, restart and redeploy buttons for each container."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import ACTION_REDEPLOY, ACTION_RESTART, ACTION_START, ACTION_STOP
from .coordinator import ArcaneConfigEntry, ArcaneCoordinator
from .entity import ArcaneContainerEntity, add_new_entities

# Actions run one at a time per platform, so a burst of presses can't pile up on Arcane.
PARALLEL_UPDATES = 1

BUTTONS = (
    ButtonEntityDescription(key=ACTION_START, translation_key=ACTION_START),
    ButtonEntityDescription(key=ACTION_STOP, translation_key=ACTION_STOP),
    ButtonEntityDescription(key=ACTION_RESTART, translation_key=ACTION_RESTART, device_class=ButtonDeviceClass.RESTART),
    ButtonEntityDescription(key=ACTION_REDEPLOY, translation_key=ACTION_REDEPLOY),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ArcaneConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    add_new_entities(
        coordinator,
        entry,
        async_add_entities,
        for_container=lambda env_id, name: [ArcaneButton(coordinator, env_id, name, d) for d in BUTTONS],
    )


class ArcaneButton(ArcaneContainerEntity, ButtonEntity):
    def __init__(
        self, coordinator: ArcaneCoordinator, env_id: str, name: str, description: ButtonEntityDescription
    ) -> None:
        super().__init__(coordinator, env_id, name, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        container = self.container
        if self.entity_description.key == ACTION_REDEPLOY and container and container.redeploy_disabled:
            return False  # Arcane won't redeploy itself
        return super().available

    async def async_press(self) -> None:
        await self.async_run_action(self.entity_description.key)
