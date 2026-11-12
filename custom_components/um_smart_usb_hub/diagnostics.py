"""Diagnostics for the UM Smart USB Hub."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .coordinator import UsbHubConfigEntry

TO_REDACT = {
    CONF_HOST,
    "ssid",
    "ip",
    "iso",
    "hostname",
    "city",
    "gateway",
    "subnet",
    "password",
    "mac",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: UsbHubConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = entry.runtime_data.data
    return {
        "entry": async_redact_data(
            {"data": dict(entry.data), "options": dict(entry.options)}, TO_REDACT
        ),
        "hub": async_redact_data(data.hub.raw, TO_REDACT),
        "ports": [asdict(p) for p in data.ports],
        "settings": async_redact_data(data.settings, TO_REDACT),
        "schedules": [[e.to_web() for e in port] for port in data.schedules],
    }
