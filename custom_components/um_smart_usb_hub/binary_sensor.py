"""Binary sensors for the UM Smart USB Hub."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import PORT_COUNT, HubInfo, PortState
from .coordinator import UsbHubConfigEntry, UsbHubCoordinator
from .entity import UsbHubEntity, UsbHubPortEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class HubBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a hub binary sensor."""

    value_fn: Callable[[HubInfo], bool]
    attrs_fn: Callable[[HubInfo], dict[str, Any] | None] = lambda _: None


@dataclass(frozen=True, kw_only=True)
class PortBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a per-port binary sensor."""

    value_fn: Callable[[PortState], bool]


HUB_BINARY_SENSORS: tuple[HubBinarySensorDescription, ...] = (
    HubBinarySensorDescription(
        key="main_5v",
        translation_key="main_5v",
        device_class=BinarySensorDeviceClass.POWER,
        value_fn=lambda h: h.main_5v,
    ),
    HubBinarySensorDescription(
        key="upstream_5v",
        translation_key="upstream_5v",
        device_class=BinarySensorDeviceClass.POWER,
        value_fn=lambda h: h.upstream_5v,
    ),
    HubBinarySensorDescription(
        key="port_fault",
        translation_key="port_fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda h: h.ports_faulted > 0,
    ),
    HubBinarySensorDescription(
        key="clock_synced",
        translation_key="clock_synced",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda h: h.clock_synced,
    ),
    HubBinarySensorDescription(
        key="hardware_problem",
        translation_key="hardware_problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda h: not all(h.devices.values()),
        attrs_fn=lambda h: {
            "missing": [name for name, ok in h.devices.items() if not ok]
        },
    ),
)

PORT_BINARY_SENSORS: tuple[PortBinarySensorDescription, ...] = (
    PortBinarySensorDescription(
        key="connected",
        translation_key="connected",
        device_class=BinarySensorDeviceClass.PLUG,
        value_fn=lambda p: p.occupied,
    ),
    PortBinarySensorDescription(
        key="overcurrent",
        translation_key="overcurrent",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda p: p.fault,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UsbHubConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        HubBinarySensor(coordinator, d) for d in HUB_BINARY_SENSORS
    ]
    for n in range(1, PORT_COUNT + 1):
        entities.extend(
            PortBinarySensor(coordinator, n, d) for d in PORT_BINARY_SENSORS
        )
    async_add_entities(entities)


class HubBinarySensor(UsbHubEntity, BinarySensorEntity):
    """A hub-level binary sensor."""

    entity_description: HubBinarySensorDescription

    def __init__(
        self, coordinator: UsbHubCoordinator, description: HubBinarySensorDescription
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        """Return the state."""
        return self.entity_description.value_fn(self.coordinator.data.hub)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Extra details."""
        return self.entity_description.attrs_fn(self.coordinator.data.hub)


class PortBinarySensor(UsbHubPortEntity, BinarySensorEntity):
    """A per-port binary sensor."""

    entity_description: PortBinarySensorDescription

    def __init__(
        self,
        coordinator: UsbHubCoordinator,
        n: int,
        description: PortBinarySensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, n, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        """Return the state."""
        return self.entity_description.value_fn(self.port)
