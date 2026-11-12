"""The UM Smart USB Hub integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import PORT_COUNT, UsbHubClient
from .const import DOMAIN
from .coordinator import UsbHubConfigEntry, UsbHubCoordinator
from .entity import hub_device_info, port_device_name
from .services import async_setup_services

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's actions."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: UsbHubConfigEntry) -> bool:
    """Set up a hub from a config entry."""
    client = UsbHubClient(async_get_clientsession(hass), entry.data[CONF_HOST])
    coordinator = UsbHubCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # Register the hub device first so port devices can point at it.
    device_registry = dr.async_get(hass)
    hub_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, **hub_device_info(coordinator)
    )
    coordinator.hub_device_id = hub_device.id

    entry.async_on_unload(
        coordinator.async_add_listener(_device_sync_listener(hass, coordinator))
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _device_sync_listener(hass: HomeAssistant, coordinator: UsbHubCoordinator):
    """Keep device names and firmware version in step with the hub."""
    last: dict[str, str | None] = {}

    @callback
    def _sync() -> None:
        if coordinator.data is None:
            return
        registry = dr.async_get(hass)
        hub = coordinator.data.hub
        wanted: dict[str, tuple[str, str | None]] = {
            coordinator.hostname: (hub.name, hub.fw),
        }
        for n in range(1, PORT_COUNT + 1):
            wanted[f"{coordinator.hostname}_port{n}"] = (
                port_device_name(hub.name, coordinator.data.port(n)),
                None,
            )
        if all(last.get(i) == f"{n}|{f}" for i, (n, f) in wanted.items()):
            return
        devices = {
            ident: device
            for device in dr.async_entries_for_config_entry(
                registry, coordinator.config_entry.entry_id
            )
            for domain, ident in device.identifiers
            if domain == DOMAIN
        }
        for ident, (name, fw) in wanted.items():
            last[ident] = f"{name}|{fw}"
            if (device := devices.get(ident)) is None:
                continue
            changes: dict[str, str] = {}
            if device.name != name:
                changes["name"] = name
            if fw is not None and device.sw_version != fw:
                changes["sw_version"] = fw
            if changes:
                registry.async_update_device(device.id, **changes)

    return _sync


async def async_unload_entry(hass: HomeAssistant, entry: UsbHubConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
