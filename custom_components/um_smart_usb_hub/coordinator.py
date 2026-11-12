"""Data update coordinator for the UM Smart USB Hub."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    PORT_COUNT,
    HubInfo,
    PortState,
    ScheduleEntry,
    Schedules,
    UsbHubClient,
    UsbHubError,
)
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
    SLOW_REFRESH_INTERVAL,
)

type UsbHubConfigEntry = ConfigEntry[UsbHubCoordinator]


@dataclass(slots=True)
class UsbHubData:
    """Everything the entities read from."""

    hub: HubInfo
    ports: list[PortState]
    settings: dict[str, dict[str, Any]] = field(default_factory=dict)
    schedules: Schedules = field(default_factory=list)

    def port(self, n: int) -> PortState:
        """Return port n (1-based)."""
        return self.ports[n - 1]


class UsbHubCoordinator(DataUpdateCoordinator[UsbHubData]):
    """Polls /api/hub + /api/ports; settings and schedules on a slower cadence."""

    config_entry: UsbHubConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: UsbHubConfigEntry, client: UsbHubClient
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = client
        # Serialises read-modify-write updates of whole-hub arrays
        # (power_mode, names, schedules).
        self.write_lock = asyncio.Lock()
        self._slow_refreshed: float | None = None
        # Registry id of the hub device; set during setup, before the platforms
        # load, so port devices can link to it.
        self.hub_device_id: str | None = None

    @property
    def hostname(self) -> str:
        """Stable identifier of the hub (also the config entry unique id)."""
        return self.config_entry.unique_id or self.config_entry.entry_id

    async def _async_update_data(self) -> UsbHubData:
        try:
            hub, ports = await asyncio.gather(
                self.client.get_hub(), self.client.get_ports()
            )
            settings = self.data.settings if self.data else {}
            schedules = self.data.schedules if self.data else []
            now = dt_util.utcnow().timestamp()
            if (
                self._slow_refreshed is None
                or now - self._slow_refreshed >= SLOW_REFRESH_INTERVAL.total_seconds()
            ):
                settings, schedules = await asyncio.gather(
                    self.client.get_settings(), self.client.get_schedules()
                )
                self._slow_refreshed = now
        except UsbHubError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        if len(ports) != PORT_COUNT:
            raise UpdateFailed(f"Expected {PORT_COUNT} ports, got {len(ports)}")
        return UsbHubData(hub=hub, ports=ports, settings=settings, schedules=schedules)

    async def _call(self, func: Callable[[], Awaitable[Any]]) -> Any:
        """Run a write against the hub, translating errors."""
        try:
            return await func()
        except UsbHubError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={"error": str(err)},
            ) from err

    def _push_ports(self, ports: list[PortState]) -> None:
        """Apply port states read back by a write response."""
        if self.data is None or len(ports) != PORT_COUNT:
            return
        # The /api/port response (status form) lacks the next-event details
        # in REST form; keep power_mode from the previous data.
        merged = [
            replace(new, power_mode=old.power_mode)
            for new, old in zip(ports, self.data.ports, strict=True)
        ]
        self.async_set_updated_data(replace(self.data, ports=merged))

    # Port actions

    async def async_set_port(self, n: int, on: bool) -> None:
        """Switch one port."""
        ports = await self._call(lambda: self.client.set_port(n, on))
        self._push_ports(ports)

    async def async_set_all_ports(self, on: bool) -> None:
        """Switch all ports."""
        ports = await self._call(lambda: self.client.set_all_ports(on))
        self._push_ports(ports)

    async def async_power_cycle(self, n: int, off_time: float) -> None:
        """Switch a port off, wait, and switch it back on."""
        await self.async_set_port(n, False)
        await asyncio.sleep(off_time)
        await self.async_set_port(n, True)

    async def async_identify(self, n: int) -> None:
        """Flash a port's LED."""
        await self._call(lambda: self.client.identify(n))

    async def async_detect_location(self) -> None:
        """Ask the hub to geolocate itself, then re-read settings."""
        await self._call(self.client.detect_location)
        await asyncio.sleep(3)
        await self.async_refresh_settings()

    # Settings

    async def async_refresh_settings(self) -> None:
        """Re-read settings from the hub and push them to entities."""
        settings = await self._call(self.client.get_settings)
        if self.data is not None:
            self.async_set_updated_data(replace(self.data, settings=settings))

    async def async_set_setting(self, group: str, key: str, value: Any) -> None:
        """Write a single setting and verify it by reading back."""
        async with self.write_lock:
            await self._call(lambda: self.client.post_settings({group: {key: value}}))
            await self.async_refresh_settings()
        self._verify_setting(group, key, value)

    async def async_set_port_setting(self, key: str, n: int, value: Any) -> None:
        """Change one port's element of a six-element `ports` setting array."""
        async with self.write_lock:
            settings = await self._call(self.client.get_settings)
            current = list(settings.get("ports", {}).get(key, []))
            if len(current) != PORT_COUNT:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="unexpected_settings",
                )
            current[n - 1] = value
            await self._call(
                lambda: self.client.post_settings({"ports": {key: current}})
            )
            await self.async_refresh_settings()
        await self.async_request_refresh()
        stored = self.data.settings.get("ports", {}).get(key, [])
        if len(stored) == PORT_COUNT and stored[n - 1] != value:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="setting_not_applied",
                translation_placeholders={"setting": f"ports.{key}[{n}]"},
            )

    def _verify_setting(self, group: str, key: str, value: Any) -> None:
        stored = self.data.settings.get(group, {}).get(key)
        if stored != value:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="setting_not_applied",
                translation_placeholders={"setting": f"{group}.{key}"},
            )

    # Schedules

    async def async_get_schedule(self, n: int) -> list[ScheduleEntry]:
        """Read port n's schedule entries from the hub."""
        schedules = await self._call(self.client.get_schedules)
        return schedules[n - 1]

    async def async_update_schedule(
        self,
        n: int,
        update: Callable[[list[ScheduleEntry]], list[ScheduleEntry]],
    ) -> list[ScheduleEntry]:
        """Read all schedules, replace port n's via `update`, write back.

        Returns the saved entries for port n. Raises if the hub silently
        rejected the write (it answers 200 with the unchanged set).
        """
        async with self.write_lock:
            schedules = await self._call(self.client.get_schedules)
            wanted = update(list(schedules[n - 1]))
            schedules[n - 1] = wanted
            saved = await self._call(lambda: self.client.post_schedules(schedules))
        port_saved = saved[n - 1]
        if len(port_saved) != len(wanted) or not all(
            a.same_rule(b) for a, b in zip(port_saved, wanted, strict=True)
        ):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="schedule_rejected",
                translation_placeholders={"port": str(n)},
            )
        invalid = [i for i, e in enumerate(port_saved) if e.invalid]
        if invalid:
            LOGGER.warning(
                "Port %s schedule saved, but the hub marked entries %s as invalid"
                " (clashing or contradictory) and will not act on them",
                n,
                invalid,
            )
        if self.data is not None:
            self.async_set_updated_data(replace(self.data, schedules=saved))
        await self.async_request_refresh()
        return port_saved
