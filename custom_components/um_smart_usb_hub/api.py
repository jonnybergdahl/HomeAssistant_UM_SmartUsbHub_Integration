"""Async client for the UM Smart USB Hub REST API.

This module has no Home Assistant imports so it can be extracted into a
standalone library later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import aiohttp

PORT_COUNT = 6
DEFAULT_TIMEOUT = 10

# Schedule modes, REST (string) form. Index matches the web UI integer `mode`
# for the "on" variants; "off" is on=False/mode=0.
SCHEDULE_MODES = ("off", "on", "on_for", "on_until", "on_every")
_MODE_TO_INT: dict[str, tuple[bool, int]] = {
    "off": (False, 0),
    "on": (True, 0),
    "on_for": (True, 1),
    "on_until": (True, 2),
    "on_every": (True, 3),
}
_INT_TO_MODE: dict[int, str] = {0: "on", 1: "on_for", 2: "on_until", 3: "on_every"}

# Weekday bitmask: bit0 = Sunday ... bit6 = Saturday.
WEEKDAYS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")

POWER_MODES = ("manual", "boot", "connect")
# User button (firmware 2.3.0+): settings group "button", one key per kind of
# press, each holding one action. An action other than "none" can be set on
# only one kind of press.
BUTTON_PRESSES = ("press", "double_press", "long_press")
BUTTON_ACTIONS = (
    "none",
    "toggle_ports",
    "all_on",
    "all_off",
    "cycle_ports",
    "toggle_leds",
    "toggle_s3_usb",
)

PORT_STATES = ("off", "blue", "green", "pulse", "pink", "pinkpulse", "fault")


class UsbHubError(Exception):
    """Base error for the hub client."""


class UsbHubConnectionError(UsbHubError):
    """The hub could not be reached."""


class UsbHubResponseError(UsbHubError):
    """The hub returned an error or an unexpected payload."""


def days_to_list(mask: int) -> list[str]:
    """Convert a weekday bitmask to a list of day names."""
    return [day for bit, day in enumerate(WEEKDAYS) if mask & (1 << bit)]


def list_to_days(days: list[str] | int) -> int:
    """Convert a list of day names (or a ready bitmask) to a weekday bitmask."""
    if isinstance(days, int):
        return days & 0x7F
    mask = 0
    for day in days:
        mask |= 1 << WEEKDAYS.index(day.lower()[:3])
    return mask


@dataclass(slots=True)
class NextEvent:
    """The next upcoming schedule event of a port."""

    in_s: int
    on: bool
    at: str
    entry: int

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> NextEvent | None:
        """Parse REST (`in_s`/`entry`) or status (`in`/`i`) form."""
        if not data:
            return None
        return cls(
            in_s=int(data.get("in_s", data.get("in", 0))),
            on=bool(data.get("on", False)),
            at=str(data.get("at", "")),
            entry=int(data.get("entry", data.get("i", 0))),
        )


@dataclass(slots=True)
class PortState:
    """Live state of one port."""

    n: int
    enabled: bool
    occupied: bool
    fault: bool
    state: str
    name: str
    monitor: bool
    volts: float
    ma: float
    mw: float
    schedule_count: int = 0
    next_event: NextEvent | None = None
    power_mode: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PortState:
        """Parse a port from `/api/ports` or the short `/api/status` form."""
        schedule = data.get("schedule")
        if isinstance(schedule, dict):
            count = int(schedule.get("count", 0))
            next_event = NextEvent.from_dict(schedule.get("next"))
        else:
            count = int(data.get("sched", 0))
            next_event = NextEvent.from_dict(data.get("next"))
        return cls(
            n=int(data["n"]),
            enabled=bool(data.get("enabled", False)),
            occupied=bool(data.get("occupied", False)),
            fault=bool(data.get("fault", False)),
            state=str(data.get("state", "off")),
            name=str(data.get("name", "")),
            monitor=bool(data.get("monitor", data.get("mon", False))),
            volts=float(data.get("volts", data.get("v", 0.0))),
            ma=float(data.get("ma", 0.0)),
            mw=float(data.get("mw", 0.0)),
            schedule_count=count,
            next_event=next_event,
            power_mode=data.get("power_mode"),
        )


@dataclass(slots=True)
class HubInfo:
    """Whole-hub snapshot from `/api/hub`."""

    name: str
    fw: str
    uptime_s: int
    reset_reason: str
    main_5v: bool
    upstream_5v: bool
    total_ma: float
    total_mw: float
    sensors_valid: bool
    temp_c: float
    humidity: float
    clock_synced: bool
    clock_iso: str
    utc_offset: int
    connected: bool
    ip: str
    ssid: str
    rssi: int
    hostname: str
    devices: dict[str, bool]
    heap_free: int
    heap_max_block: int
    ports_powered: int
    ports_occupied: int
    ports_faulted: int
    mac: str | None = None
    # None on firmware before 2.3.0, which can't switch the ESP32-S3's USB.
    s3_usb_connected: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HubInfo:
        """Parse `/api/hub`."""
        if "fw" not in data or "ports_summary" not in data:
            raise UsbHubResponseError("Response does not look like a Smart USB Hub")
        power = data.get("power", {})
        sensors = data.get("sensors", {})
        clock = data.get("clock", {})
        network = data.get("network", {})
        memory = data.get("memory", {})
        summary = data.get("ports_summary", {})
        mac = data.get("mac") or network.get("mac")
        return cls(
            name=str(data.get("name", "Smart USB Hub")),
            fw=str(data.get("fw", "")),
            uptime_s=int(data.get("uptime_s", 0)),
            reset_reason=str(data.get("reset_reason", "UNKNOWN")),
            main_5v=bool(power.get("main_5v", False)),
            upstream_5v=bool(power.get("upstream_5v", False)),
            total_ma=float(power.get("total_ma", 0.0)),
            total_mw=float(power.get("total_mw", 0.0)),
            sensors_valid=bool(sensors.get("valid", False)),
            temp_c=float(sensors.get("temp_c", 0.0)),
            humidity=float(sensors.get("humidity", 0.0)),
            clock_synced=bool(clock.get("synced", False)),
            clock_iso=str(clock.get("iso", "")),
            utc_offset=int(clock.get("utc_offset", 0)),
            connected=bool(network.get("connected", False)),
            ip=str(network.get("ip", "")),
            ssid=str(network.get("ssid", "")),
            rssi=int(network.get("rssi", 0)),
            hostname=str(network.get("hostname", "")),
            devices={k: bool(v) for k, v in data.get("devices", {}).items()},
            heap_free=int(memory.get("heap_free", 0)),
            heap_max_block=int(memory.get("heap_max_block", 0)),
            ports_powered=int(summary.get("powered", 0)),
            ports_occupied=int(summary.get("occupied", 0)),
            ports_faulted=int(summary.get("faulted", 0)),
            mac=str(mac).lower() if mac else None,
            s3_usb_connected=(
                bool(data["s3_usb_connected"]) if "s3_usb_connected" in data else None
            ),
            raw=data,
        )


@dataclass(slots=True)
class ScheduleEntry:
    """One schedule rule, in friendly (REST string mode) form."""

    days: int = 0
    time: str = "00:00"
    mode: str = "off"
    dur: int = 60
    until: str = "17:00"
    every: int = 30
    allday: bool = True
    once: bool = False
    enabled: bool = True
    invalid: bool = False

    @classmethod
    def from_web(cls, data: dict[str, Any]) -> ScheduleEntry:
        """Parse the web-UI integer form (`on` + integer `mode`)."""
        if not data.get("on", False):
            mode = "off"
        else:
            mode = _INT_TO_MODE.get(int(data.get("mode", 0)), "on")
        return cls(
            days=int(data.get("days", 0)),
            time=str(data.get("time", "00:00")),
            mode=mode,
            dur=int(data.get("dur", 60)),
            until=str(data.get("until", "17:00")),
            every=int(data.get("every", 30)),
            allday=bool(data.get("allday", True)),
            once=bool(data.get("once", False)),
            enabled=bool(data.get("enabled", True)),
            invalid=bool(data.get("invalid", False)),
        )

    def to_web(self) -> dict[str, Any]:
        """Serialise to the web-UI integer form accepted by POST /api/schedules."""
        on, mode = _MODE_TO_INT[self.mode]
        return {
            "days": self.days,
            "time": self.time,
            "on": on,
            "mode": mode,
            "dur": self.dur,
            "until": self.until,
            "every": self.every,
            "allday": self.allday,
            "once": self.once,
            "enabled": self.enabled,
        }

    def as_dict(self) -> dict[str, Any]:
        """Friendly representation for service responses."""
        return {
            "days": days_to_list(self.days),
            "days_mask": self.days,
            "time": self.time,
            "mode": self.mode,
            "duration": self.dur,
            "until": self.until,
            "every": self.every,
            "all_day": self.allday,
            "once": self.once,
            "enabled": self.enabled,
            "invalid": self.invalid,
        }

    def same_rule(self, other: ScheduleEntry) -> bool:
        """Compare stored fields, ignoring the device-computed `invalid` flag."""
        return self.to_web() == other.to_web()


Schedules = list[list[ScheduleEntry]]


def parse_schedules(data: dict[str, Any]) -> Schedules:
    """Parse `/api/schedules` (web-UI form) into six lists of entries."""
    ports = data.get("ports")
    if not isinstance(ports, list) or len(ports) != PORT_COUNT:
        raise UsbHubResponseError("Unexpected schedules payload")
    return [[ScheduleEntry.from_web(e) for e in port] for port in ports]


def parse_settings(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Flatten `/api/settings/schema` to {group: values}.

    The `wifi` group is dropped entirely: it carries the WiFi password in
    clear text and nothing in the integration needs it.
    """
    groups = data.get("groups")
    if not isinstance(groups, list):
        raise UsbHubResponseError("Unexpected settings payload")
    return {
        g["name"]: dict(g.get("values", {}))
        for g in groups
        if isinstance(g, dict) and "name" in g and g["name"] != "wifi"
    }


class UsbHubClient:
    """Minimal async client for the hub's REST API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialise the client."""
        self._session = session
        self.host = host
        self._base = f"http://{host}/api"
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> dict[str, Any]:
        try:
            async with self._session.request(
                method,
                f"{self._base}{path}",
                params=params,
                json=json,
                timeout=self._timeout,
            ) as resp:
                if resp.status >= 400:
                    try:
                        body = await resp.json(content_type=None)
                        detail = body.get("detail") or body.get("error")
                    except (aiohttp.ContentTypeError, ValueError, AttributeError):
                        detail = resp.reason
                    raise UsbHubResponseError(
                        f"{method} {path} failed: HTTP {resp.status} ({detail})"
                    )
                data = await resp.json(content_type=None)
        except (TimeoutError, aiohttp.ClientError) as err:
            raise UsbHubConnectionError(
                f"Error talking to hub at {self.host}: {err}"
            ) from err
        except ValueError as err:
            raise UsbHubResponseError(f"Invalid JSON from {path}") from err
        if not isinstance(data, dict):
            raise UsbHubResponseError(f"Unexpected payload from {path}")
        return data

    # Reads

    async def get_hub(self) -> HubInfo:
        """GET /api/hub."""
        return HubInfo.from_dict(await self._request("GET", "/hub"))

    async def get_ports(self) -> list[PortState]:
        """GET /api/ports."""
        return _parse_ports(await self._request("GET", "/ports"))

    async def get_port(self, n: int) -> PortState:
        """GET /api/ports/{n} (includes power_mode)."""
        return PortState.from_dict(await self._request("GET", f"/ports/{n}"))

    async def get_schedules(self) -> Schedules:
        """GET /api/schedules (web-UI integer form)."""
        return parse_schedules(await self._request("GET", "/schedules"))

    async def get_settings(self) -> dict[str, dict[str, Any]]:
        """GET /api/settings/schema, flattened and without the wifi group."""
        return parse_settings(await self._request("GET", "/settings/schema"))

    # Writes

    async def set_port(self, n: int, on: bool) -> list[PortState]:
        """POST /api/port; returns all ports as read back by the hub."""
        data = await self._request(
            "POST", "/port", params={"n": n, "on": 1 if on else 0}
        )
        return _parse_ports(data)

    async def set_all_ports(self, on: bool) -> list[PortState]:
        """POST /api/hub/ports; returns all ports as read back by the hub."""
        data = await self._request("POST", "/hub/ports", params={"on": 1 if on else 0})
        return _parse_ports(data)

    async def set_s3_usb(self, connected: bool) -> HubInfo:
        """POST /api/hub/usbs3 (firmware 2.3.0+); returns the hub as read back."""
        data = await self._request(
            "POST", "/hub/usbs3", params={"on": 1 if connected else 0}
        )
        return HubInfo.from_dict(data)

    async def reboot(self) -> None:
        """POST /api/hub/reboot (firmware 2.3.0+). The hub restarts ~0.5 s later."""
        await self._request("POST", "/hub/reboot")

    async def identify(self, n: int) -> None:
        """POST /api/identify: flash a port's LED."""
        await self._request("POST", "/identify", params={"n": n})

    async def post_settings(self, settings: dict[str, dict[str, Any]]) -> None:
        """POST /api/settings with a partial update.

        The hub always replies {"ok": true}; callers must re-read settings to
        confirm what landed.
        """
        await self._request("POST", "/settings", json=settings)

    async def post_schedules(self, schedules: Schedules) -> Schedules:
        """POST /api/schedules (whole-hub replace); returns the saved set."""
        if len(schedules) != PORT_COUNT:
            raise ValueError("Exactly six port schedules are required")
        body = {"ports": [[e.to_web() for e in port] for port in schedules]}
        return parse_schedules(await self._request("POST", "/schedules", json=body))

    async def detect_location(self) -> None:
        """POST /api/location/detect (queued on the hub)."""
        await self._request("POST", "/location/detect")


def _parse_ports(data: dict[str, Any]) -> list[PortState]:
    ports = data.get("ports")
    if not isinstance(ports, list):
        raise UsbHubResponseError("Unexpected ports payload")
    return [PortState.from_dict(p) for p in ports]
