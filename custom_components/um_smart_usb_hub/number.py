"""Numbers for the UM Smart USB Hub."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import UsbHubConfigEntry, UsbHubCoordinator
from .entity import UsbHubEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class SettingNumberDescription(NumberEntityDescription):
    """Describes an integer hub setting."""

    group: str
    setting: str


NUMBERS: tuple[SettingNumberDescription, ...] = (
    SettingNumberDescription(
        key="led_brightness",
        translation_key="led_brightness",
        entity_category=EntityCategory.CONFIG,
        native_min_value=0,
        native_max_value=255,
        native_step=5,
        mode=NumberMode.SLIDER,
        group="leds",
        setting="brightness",
    ),
    SettingNumberDescription(
        key="utc_offset",
        translation_key="utc_offset",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        native_min_value=-12,
        native_max_value=14,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.HOURS,
        mode=NumberMode.BOX,
        group="location",
        setting="utc_offset",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UsbHubConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up numbers."""
    coordinator = entry.runtime_data
    async_add_entities(SettingNumber(coordinator, d) for d in NUMBERS)


class SettingNumber(UsbHubEntity, NumberEntity):
    """An integer hub setting."""

    entity_description: SettingNumberDescription

    def __init__(
        self, coordinator: UsbHubCoordinator, description: SettingNumberDescription
    ) -> None:
        """Initialise the number."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    def _group(self) -> dict:
        return self.coordinator.data.settings.get(self.entity_description.group, {})

    @property
    def available(self) -> bool:
        """Available once settings have been read."""
        return super().available and self.entity_description.setting in self._group()

    @property
    def native_value(self) -> float | None:
        """Return the setting."""
        value = self._group().get(self.entity_description.setting)
        return None if value is None else float(value)

    async def async_set_native_value(self, value: float) -> None:
        """Change the setting."""
        await self.coordinator.async_set_setting(
            self.entity_description.group,
            self.entity_description.setting,
            int(value),
        )
