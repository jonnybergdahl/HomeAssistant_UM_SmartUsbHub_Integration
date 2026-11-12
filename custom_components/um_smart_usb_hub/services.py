"""Actions for the UM Smart USB Hub.

All actions target port power switches (or port devices), and are handled
by the PortPowerSwitch entity of the targeted port.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN, SwitchDeviceClass
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.helpers import config_validation as cv, service
import voluptuous as vol

from .api import SCHEDULE_MODES, WEEKDAYS, ScheduleEntry, list_to_days
from .const import DEFAULT_POWER_CYCLE_OFF_TIME, DOMAIN

if TYPE_CHECKING:
    from .switch import PortPowerSwitch

SERVICE_POWER_CYCLE = "power_cycle"
SERVICE_GET_SCHEDULE = "get_schedule"
SERVICE_SET_SCHEDULE = "set_schedule"
SERVICE_ADD_SCHEDULE_ENTRY = "add_schedule_entry"
SERVICE_CLEAR_SCHEDULE = "clear_schedule"

ATTR_OFF_TIME = "off_time"
ATTR_ENTRIES = "entries"


def _hhmm(value: Any) -> str:
    """Accept "HH:MM" or "HH:MM:SS" and normalise to "HH:MM"."""
    time = cv.time(value)
    return f"{time.hour:02d}:{time.minute:02d}"


def _days(value: Any) -> int:
    if isinstance(value, int):
        if not 0 <= value <= 127:
            raise vol.Invalid("days bitmask must be 0-127")
        return value
    if isinstance(value, str):
        value = [v.strip() for v in value.split(",") if v.strip()]
    days = vol.Schema([vol.All(cv.string, vol.Lower, vol.In(WEEKDAYS))])(value)
    return list_to_days(days)


ENTRY_SCHEMA = vol.Schema(
    {
        vol.Required("days"): _days,
        vol.Required("time"): _hhmm,
        vol.Required("mode"): vol.In(SCHEDULE_MODES),
        vol.Optional("duration", default=60): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=1439)
        ),
        vol.Optional("until", default="17:00"): _hhmm,
        vol.Optional("every", default=30): vol.All(
            vol.Coerce(int), vol.Range(min=30, max=1440)
        ),
        vol.Optional("all_day", default=True): cv.boolean,
        vol.Optional("once", default=False): cv.boolean,
        vol.Optional("enabled", default=True): cv.boolean,
    }
)


def entry_from_input(data: dict[str, Any]) -> ScheduleEntry:
    """Build a schedule entry from validated action data."""
    return ScheduleEntry(
        days=data["days"],
        time=data["time"],
        mode=data["mode"],
        dur=data["duration"],
        until=data["until"],
        every=data["every"],
        allday=data["all_day"],
        once=data["once"],
        enabled=data["enabled"],
    )


async def _power_cycle(entity: PortPowerSwitch, call: ServiceCall) -> None:
    await entity.coordinator.async_power_cycle(
        entity.port_number, call.data[ATTR_OFF_TIME]
    )


def _schedule_response(entity: PortPowerSwitch, entries: list[ScheduleEntry]):
    port = entity.port
    nxt = port.next_event
    return {
        "port": entity.port_number,
        "name": port.name,
        "count": port.schedule_count,
        "next": (
            {
                "in_s": nxt.in_s,
                "action": "on" if nxt.on else "off",
                "at": nxt.at,
                "entry": nxt.entry,
            }
            if nxt
            else None
        ),
        "entries": [e.as_dict() for e in entries],
    }


async def _get_schedule(entity: PortPowerSwitch, call: ServiceCall):
    entries = await entity.coordinator.async_get_schedule(entity.port_number)
    return _schedule_response(entity, entries)


async def _set_schedule(entity: PortPowerSwitch, call: ServiceCall):
    wanted = [entry_from_input(e) for e in call.data[ATTR_ENTRIES]]
    saved = await entity.coordinator.async_update_schedule(
        entity.port_number, lambda _current: wanted
    )
    return _schedule_response(entity, saved)


async def _add_schedule_entry(entity: PortPowerSwitch, call: ServiceCall):
    new = entry_from_input(call.data)
    saved = await entity.coordinator.async_update_schedule(
        entity.port_number, lambda current: [*current, new]
    )
    return _schedule_response(entity, saved)


async def _clear_schedule(entity: PortPowerSwitch, call: ServiceCall) -> None:
    await entity.coordinator.async_update_schedule(
        entity.port_number, lambda _current: []
    )


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions."""

    def register(name, func, schema, response=SupportsResponse.NONE) -> None:
        service.async_register_platform_entity_service(
            hass,
            DOMAIN,
            name,
            entity_domain=SWITCH_DOMAIN,
            entity_device_classes=(SwitchDeviceClass.OUTLET,),
            func=func,
            schema=schema,
            supports_response=response,
        )

    register(
        SERVICE_POWER_CYCLE,
        _power_cycle,
        {
            vol.Optional(ATTR_OFF_TIME, default=DEFAULT_POWER_CYCLE_OFF_TIME): vol.All(
                vol.Coerce(float), vol.Range(min=0.5, max=300)
            )
        },
    )
    register(SERVICE_GET_SCHEDULE, _get_schedule, None, SupportsResponse.ONLY)
    register(
        SERVICE_SET_SCHEDULE,
        _set_schedule,
        {vol.Required(ATTR_ENTRIES): vol.All(cv.ensure_list, [ENTRY_SCHEMA])},
        SupportsResponse.OPTIONAL,
    )
    register(
        SERVICE_ADD_SCHEDULE_ENTRY,
        _add_schedule_entry,
        ENTRY_SCHEMA.schema,
        SupportsResponse.OPTIONAL,
    )
    register(SERVICE_CLEAR_SCHEDULE, _clear_schedule, None)
