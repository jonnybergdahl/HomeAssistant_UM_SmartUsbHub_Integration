"""Selects for the UM Smart USB Hub."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import BUTTON_ACTIONS, BUTTON_PRESSES, PORT_COUNT, POWER_MODES
from .const import AVERAGING_OPTIONS
from .coordinator import UsbHubConfigEntry, UsbHubCoordinator
from .entity import UsbHubEntity, UsbHubPortEntity, async_add_feature_entities

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UsbHubConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up selects."""
    coordinator = entry.runtime_data
    entities: list[SelectEntity] = [AveragingSelect(coordinator)]
    entities.extend(PowerModeSelect(coordinator, n) for n in range(1, PORT_COUNT + 1))
    async_add_entities(entities)
    # User button actions: firmware 2.3.0+ has a "button" settings group.
    async_add_feature_entities(
        entry,
        async_add_entities,
        [
            (
                f"button_{press}",
                lambda data: "button" in data.settings,
                # Bind press now; the factory runs later.
                lambda press=press: ButtonActionSelect(coordinator, press),
            )
            for press in BUTTON_PRESSES
        ],
    )


class ButtonActionSelect(UsbHubEntity, SelectEntity):
    """What a single, double or long press on the hub's user button does.

    An action can be set on only one kind of press; choosing one that another
    press already has moves it here and sets the other press to "none".
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(BUTTON_ACTIONS)

    def __init__(self, coordinator: UsbHubCoordinator, press: str) -> None:
        """Initialise the select."""
        super().__init__(coordinator, f"button_{press}")
        self._press = press
        self._attr_translation_key = f"button_{press}"

    @property
    def available(self) -> bool:
        """Available while the hub reports the setting."""
        return super().available and self._press in self.coordinator.data.settings.get(
            "button", {}
        )

    @property
    def current_option(self) -> str | None:
        """Return the action for this kind of press."""
        value = self.coordinator.data.settings.get("button", {}).get(self._press)
        return value if value in BUTTON_ACTIONS else None

    async def async_select_option(self, option: str) -> None:
        """Change the action for this kind of press."""
        await self.coordinator.async_set_button_action(self._press, option)


class PowerModeSelect(UsbHubPortEntity, SelectEntity):
    """A port's power mode: manual, on at boot, or on while a device is plugged in."""

    _attr_translation_key = "power_mode"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(POWER_MODES)

    def __init__(self, coordinator: UsbHubCoordinator, n: int) -> None:
        """Initialise the select."""
        super().__init__(coordinator, n, "power_mode")

    def _modes(self) -> list[str]:
        return self.coordinator.data.settings.get("ports", {}).get("power_mode", [])

    @property
    def available(self) -> bool:
        """Available once settings have been read."""
        return super().available and len(self._modes()) == PORT_COUNT

    @property
    def current_option(self) -> str | None:
        """Return the port's power mode."""
        modes = self._modes()
        if len(modes) != PORT_COUNT:
            return None
        mode = modes[self.port_number - 1]
        return mode if mode in POWER_MODES else "manual"

    async def async_select_option(self, option: str) -> None:
        """Change the port's power mode."""
        await self.coordinator.async_set_port_setting(
            "power_mode", self.port_number, option
        )


class AveragingSelect(UsbHubEntity, SelectEntity):
    """How many INA samples the hub averages per reading."""

    _attr_translation_key = "averaging"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_options = list(AVERAGING_OPTIONS)

    def __init__(self, coordinator: UsbHubCoordinator) -> None:
        """Initialise the select."""
        super().__init__(coordinator, "averaging")

    @property
    def available(self) -> bool:
        """Available once settings have been read."""
        return super().available and "averaging" in self.coordinator.data.settings.get(
            "profiler", {}
        )

    @property
    def current_option(self) -> str | None:
        """Return the averaging setting."""
        value = self.coordinator.data.settings.get("profiler", {}).get("averaging")
        return str(value) if str(value) in AVERAGING_OPTIONS else None

    async def async_select_option(self, option: str) -> None:
        """Change the averaging setting."""
        await self.coordinator.async_set_setting("profiler", "averaging", int(option))
