"""Text entities for the UM Smart USB Hub."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import PORT_COUNT
from .coordinator import UsbHubConfigEntry, UsbHubCoordinator
from .entity import UsbHubPortEntity

PARALLEL_UPDATES = 1

PORT_NAME_MAX_LENGTH = 24


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UsbHubConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up text entities."""
    coordinator = entry.runtime_data
    async_add_entities(PortNameText(coordinator, n) for n in range(1, PORT_COUNT + 1))


class PortNameText(UsbHubPortEntity, TextEntity):
    """The port's name as stored on the hub (shown on its web page)."""

    _attr_translation_key = "port_name"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min = 0
    _attr_native_max = PORT_NAME_MAX_LENGTH

    def __init__(self, coordinator: UsbHubCoordinator, n: int) -> None:
        """Initialise the text entity."""
        super().__init__(coordinator, n, "name")

    @property
    def native_value(self) -> str:
        """Return the port name (empty when unnamed)."""
        return self.port.name

    async def async_set_value(self, value: str) -> None:
        """Rename the port on the hub."""
        await self.coordinator.async_set_port_setting(
            "names", self.port_number, value.strip()[:PORT_NAME_MAX_LENGTH]
        )
