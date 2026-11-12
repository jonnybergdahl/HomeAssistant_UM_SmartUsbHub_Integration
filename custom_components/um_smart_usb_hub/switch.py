"""Switches for the UM Smart USB Hub."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import PORT_COUNT
from .coordinator import UsbHubConfigEntry, UsbHubCoordinator
from .entity import UsbHubEntity, UsbHubPortEntity

# Writes are serialised by the hub; a running power cycle must not block
# other ports.
PARALLEL_UPDATES = 0

# (description, settings group, settings key)
SETTING_SWITCHES: tuple[tuple[SwitchEntityDescription, str, str], ...] = (
    (
        SwitchEntityDescription(
            key="leds",
            translation_key="leds",
            entity_category=EntityCategory.CONFIG,
        ),
        "leds",
        "enabled",
    ),
    (
        SwitchEntityDescription(
            key="esphome_api",
            translation_key="esphome_api",
            entity_category=EntityCategory.CONFIG,
            entity_registry_enabled_default=False,
        ),
        "esphome",
        "enabled",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UsbHubConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switches."""
    coordinator = entry.runtime_data
    entities: list[SwitchEntity] = [
        PortPowerSwitch(coordinator, n) for n in range(1, PORT_COUNT + 1)
    ]
    entities.extend(
        SettingSwitch(coordinator, description, group, key)
        for description, group, key in SETTING_SWITCHES
    )
    async_add_entities(entities)


class PortPowerSwitch(UsbHubPortEntity, SwitchEntity):
    """Switches a port's 5V on or off.

    This is the port device's main entity, so it takes the device's name.
    The integration's per-port actions target these entities (device class
    outlet).
    """

    _attr_name = None
    _attr_device_class = SwitchDeviceClass.OUTLET
    _attr_translation_key = "port_power"

    def __init__(self, coordinator: UsbHubCoordinator, n: int) -> None:
        """Initialise the switch."""
        super().__init__(coordinator, n, "power")

    @property
    def is_on(self) -> bool:
        """Whether the firmware has enabled the port."""
        return self.port.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Switch the port on."""
        await self.coordinator.async_set_port(self.port_number, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Switch the port off."""
        await self.coordinator.async_set_port(self.port_number, False)


class SettingSwitch(UsbHubEntity, SwitchEntity):
    """A boolean hub setting."""

    def __init__(
        self,
        coordinator: UsbHubCoordinator,
        description: SwitchEntityDescription,
        group: str,
        key: str,
    ) -> None:
        """Initialise the switch."""
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._group = group
        self._key = key

    @property
    def available(self) -> bool:
        """Available once the setting has been read."""
        return super().available and self._key in self.coordinator.data.settings.get(
            self._group, {}
        )

    @property
    def is_on(self) -> bool | None:
        """Return the setting."""
        value = self.coordinator.data.settings.get(self._group, {}).get(self._key)
        return None if value is None else bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the setting."""
        await self.coordinator.async_set_setting(self._group, self._key, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the setting."""
        await self.coordinator.async_set_setting(self._group, self._key, False)
