"""Base entities for the UM Smart USB Hub."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.core import callback
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import PortState
from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import UsbHubConfigEntry, UsbHubCoordinator, UsbHubData

# (key, supported by the hub's firmware?, entity factory)
type Feature = tuple[str, Callable[[UsbHubData], bool], Callable[[], Entity]]


@callback
def async_add_feature_entities(
    entry: UsbHubConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    features: Iterable[Feature],
) -> None:
    """Add entities for firmware features, now or once the hub reports them.

    Checked at setup and after every coordinator update, so a hub that gets
    a firmware upgrade while Home Assistant runs gains the new entities
    without a reload. An entity is added once; if a later downgrade drops the
    feature, it stays and goes unavailable.
    """
    coordinator = entry.runtime_data
    pending = list(features)

    @callback
    def _add_supported() -> None:
        data = coordinator.data
        if data is None or not pending:
            return
        ready = [feature for feature in pending if feature[1](data)]
        if not ready:
            return
        for feature in ready:
            pending.remove(feature)
        async_add_entities([factory() for _key, _supported, factory in ready])

    _add_supported()
    if pending:
        entry.async_on_unload(coordinator.async_add_listener(_add_supported))


def hub_device_info(coordinator: UsbHubCoordinator) -> DeviceInfo:
    """Device info for the hub itself."""
    hub = coordinator.data.hub
    info = DeviceInfo(
        identifiers={(DOMAIN, coordinator.hostname)},
        name=hub.name,
        manufacturer=MANUFACTURER,
        model=MODEL,
        sw_version=hub.fw,
        configuration_url=f"http://{coordinator.client.host}",
    )
    if hub.mac:
        # Same normalisation as ESPHome, so both integrations share one device.
        info["connections"] = {(CONNECTION_NETWORK_MAC, format_mac(hub.mac))}
    return info


def port_device_name(hub_name: str, port: PortState) -> str:
    """Name of a port's sub-device, following the name set on the hub."""
    base = f"{hub_name} Port {port.n}"
    return f"{base} ({port.name})" if port.name else base


def port_device_info(coordinator: UsbHubCoordinator, n: int) -> DeviceInfo:
    """Device info for one port's sub-device."""
    info = DeviceInfo(
        identifiers={(DOMAIN, f"{coordinator.hostname}_port{n}")},
        name=port_device_name(coordinator.data.hub.name, coordinator.data.port(n)),
        manufacturer=MANUFACTURER,
        model=f"{MODEL} port",
    )
    if coordinator.hub_device_id is not None:
        info["via_device_id"] = coordinator.hub_device_id
    return info


class UsbHubEntity(CoordinatorEntity[UsbHubCoordinator]):
    """An entity on the hub device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: UsbHubCoordinator, key: str) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.hostname}_{key}"
        self._attr_device_info = hub_device_info(coordinator)


class UsbHubPortEntity(CoordinatorEntity[UsbHubCoordinator]):
    """An entity on one port's sub-device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: UsbHubCoordinator, n: int, key: str) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self.port_number = n
        self._attr_unique_id = f"{coordinator.hostname}_port{n}_{key}"
        self._attr_device_info = port_device_info(coordinator, n)

    @property
    def port(self) -> PortState:
        """Current state of this entity's port."""
        return self.coordinator.data.port(self.port_number)
