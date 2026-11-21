"""Buttons for the UM Smart USB Hub."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import PORT_COUNT
from .const import DEFAULT_POWER_CYCLE_OFF_TIME
from .coordinator import UsbHubConfigEntry, UsbHubCoordinator
from .entity import UsbHubEntity, UsbHubPortEntity, async_add_feature_entities

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class HubButtonDescription(ButtonEntityDescription):
    """Describes a hub button."""

    press_fn: Callable[[UsbHubCoordinator], Awaitable[None]]


@dataclass(frozen=True, kw_only=True)
class PortButtonDescription(ButtonEntityDescription):
    """Describes a per-port button."""

    press_fn: Callable[[UsbHubCoordinator, int], Awaitable[None]]


HUB_BUTTONS: tuple[HubButtonDescription, ...] = (
    HubButtonDescription(
        key="all_ports_on",
        translation_key="all_ports_on",
        press_fn=lambda c: c.async_set_all_ports(True),
    ),
    HubButtonDescription(
        key="all_ports_off",
        translation_key="all_ports_off",
        press_fn=lambda c: c.async_set_all_ports(False),
    ),
    HubButtonDescription(
        key="detect_location",
        translation_key="detect_location",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        press_fn=lambda c: c.async_detect_location(),
    ),
)

REBOOT_BUTTON = HubButtonDescription(
    key="reboot",
    device_class=ButtonDeviceClass.RESTART,
    entity_category=EntityCategory.CONFIG,
    press_fn=lambda c: c.async_reboot(),
)

PORT_BUTTONS: tuple[PortButtonDescription, ...] = (
    PortButtonDescription(
        key="identify",
        device_class=ButtonDeviceClass.IDENTIFY,
        entity_category=EntityCategory.DIAGNOSTIC,
        press_fn=lambda c, n: c.async_identify(n),
    ),
    PortButtonDescription(
        key="power_cycle",
        translation_key="power_cycle",
        press_fn=lambda c, n: c.async_power_cycle(n, DEFAULT_POWER_CYCLE_OFF_TIME),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UsbHubConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up buttons."""
    coordinator = entry.runtime_data
    entities: list[ButtonEntity] = [HubButton(coordinator, d) for d in HUB_BUTTONS]
    for n in range(1, PORT_COUNT + 1):
        entities.extend(PortButton(coordinator, n, d) for d in PORT_BUTTONS)
    async_add_entities(entities)
    # The reboot endpoint came with firmware 2.3.0, as did s3_usb_connected;
    # probing the endpoint itself would reboot the hub.
    async_add_feature_entities(
        entry,
        async_add_entities,
        [
            (
                "reboot",
                lambda data: data.hub.s3_usb_connected is not None,
                lambda: HubButton(coordinator, REBOOT_BUTTON),
            )
        ],
    )


class HubButton(UsbHubEntity, ButtonEntity):
    """A hub-level button."""

    entity_description: HubButtonDescription

    def __init__(
        self, coordinator: UsbHubCoordinator, description: HubButtonDescription
    ) -> None:
        """Initialise the button."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        """Press the button."""
        await self.entity_description.press_fn(self.coordinator)


class PortButton(UsbHubPortEntity, ButtonEntity):
    """A per-port button."""

    entity_description: PortButtonDescription

    def __init__(
        self,
        coordinator: UsbHubCoordinator,
        n: int,
        description: PortButtonDescription,
    ) -> None:
        """Initialise the button."""
        super().__init__(coordinator, n, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        """Press the button."""
        await self.entity_description.press_fn(self.coordinator, self.port_number)
