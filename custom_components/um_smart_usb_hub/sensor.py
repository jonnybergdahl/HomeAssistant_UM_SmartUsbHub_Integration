"""Sensors for the UM Smart USB Hub."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfInformation,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .api import PORT_COUNT, PORT_STATES, HubInfo, PortState
from .const import RESET_REASONS
from .coordinator import UsbHubConfigEntry, UsbHubCoordinator
from .entity import UsbHubEntity, UsbHubPortEntity

PARALLEL_UPDATES = 0

# A computed timestamp is only moved when it drifts more than this, so the
# state doesn't change on every poll.
TIMESTAMP_TOLERANCE = timedelta(seconds=30)


@dataclass(frozen=True, kw_only=True)
class HubSensorDescription(SensorEntityDescription):
    """Describes a hub sensor."""

    value_fn: Callable[[HubInfo], StateType]
    available_fn: Callable[[HubInfo], bool] = lambda _: True


@dataclass(frozen=True, kw_only=True)
class PortSensorDescription(SensorEntityDescription):
    """Describes a per-port sensor."""

    value_fn: Callable[[PortState], StateType]
    needs_monitor: bool = False


HUB_SENSORS: tuple[HubSensorDescription, ...] = (
    HubSensorDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda h: h.temp_c,
        available_fn=lambda h: h.sensors_valid and h.devices.get("aht20", True),
    ),
    HubSensorDescription(
        key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda h: h.humidity,
        available_fn=lambda h: h.sensors_valid and h.devices.get("aht20", True),
    ),
    HubSensorDescription(
        key="total_current",
        translation_key="total_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.MILLIAMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda h: h.total_ma,
    ),
    HubSensorDescription(
        key="total_power",
        translation_key="total_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.MILLIWATT,
        suggested_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda h: h.total_mw,
    ),
    HubSensorDescription(
        key="ports_powered",
        translation_key="ports_powered",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda h: h.ports_powered,
    ),
    HubSensorDescription(
        key="ports_occupied",
        translation_key="ports_occupied",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda h: h.ports_occupied,
    ),
    HubSensorDescription(
        key="ports_faulted",
        translation_key="ports_faulted",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda h: h.ports_faulted,
    ),
    HubSensorDescription(
        key="reset_reason",
        translation_key="reset_reason",
        device_class=SensorDeviceClass.ENUM,
        options=[r.lower() for r in RESET_REASONS],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda h: (
            h.reset_reason.lower() if h.reset_reason in RESET_REASONS else "unknown"
        ),
    ),
    HubSensorDescription(
        key="wifi_signal",
        translation_key="wifi_signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda h: h.rssi,
        available_fn=lambda h: h.connected,
    ),
    HubSensorDescription(
        key="ip_address",
        translation_key="ip_address",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda h: h.ip or None,
    ),
    HubSensorDescription(
        key="ssid",
        translation_key="ssid",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda h: h.ssid or None,
    ),
    HubSensorDescription(
        key="heap_free",
        translation_key="heap_free",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.KIBIBYTES,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda h: h.heap_free,
    ),
)

PORT_SENSORS: tuple[PortSensorDescription, ...] = (
    PortSensorDescription(
        key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda p: p.volts,
        needs_monitor=True,
    ),
    PortSensorDescription(
        key="current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.MILLIAMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda p: p.ma,
        needs_monitor=True,
    ),
    PortSensorDescription(
        key="power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.MILLIWATT,
        suggested_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda p: p.mw,
        needs_monitor=True,
    ),
    PortSensorDescription(
        key="led_state",
        translation_key="led_state",
        device_class=SensorDeviceClass.ENUM,
        options=list(PORT_STATES),
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p: p.state if p.state in PORT_STATES else None,
    ),
    PortSensorDescription(
        key="schedule_rules",
        translation_key="schedule_rules",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda p: p.schedule_count,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UsbHubConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        HubSensor(coordinator, description) for description in HUB_SENSORS
    ]
    entities.append(LastRestartSensor(coordinator))
    for n in range(1, PORT_COUNT + 1):
        entities.extend(PortSensor(coordinator, n, d) for d in PORT_SENSORS)
        entities.append(NextScheduleSensor(coordinator, n))
    async_add_entities(entities)


class HubSensor(UsbHubEntity, SensorEntity):
    """A sensor reading from /api/hub."""

    entity_description: HubSensorDescription

    def __init__(
        self, coordinator: UsbHubCoordinator, description: HubSensorDescription
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Unavailable when the hub reports the reading as not valid."""
        return super().available and self.entity_description.available_fn(
            self.coordinator.data.hub
        )

    @property
    def native_value(self) -> StateType:
        """Return the reading."""
        return self.entity_description.value_fn(self.coordinator.data.hub)


class LastRestartSensor(UsbHubEntity, SensorEntity):
    """When the hub last booted, derived from its uptime."""

    _attr_translation_key = "last_restart"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: UsbHubCoordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, "last_restart")
        self._value: datetime | None = None
        self._update_value()

    def _update_value(self) -> None:
        booted = dt_util.utcnow() - timedelta(
            seconds=self.coordinator.data.hub.uptime_s
        )
        if self._value is None or abs(booted - self._value) > TIMESTAMP_TOLERANCE:
            self._value = booted.replace(microsecond=0)

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_value()
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> datetime | None:
        """Return the boot time."""
        return self._value


class PortSensor(UsbHubPortEntity, SensorEntity):
    """A per-port reading."""

    entity_description: PortSensorDescription

    def __init__(
        self,
        coordinator: UsbHubCoordinator,
        n: int,
        description: PortSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, n, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Unavailable when the port's INA3221 monitor is missing."""
        if self.entity_description.needs_monitor and not self.port.monitor:
            return False
        return super().available

    @property
    def native_value(self) -> StateType:
        """Return the reading."""
        return self.entity_description.value_fn(self.port)


class NextScheduleSensor(UsbHubPortEntity, SensorEntity):
    """When the port's on-hub schedule next switches it."""

    _attr_translation_key = "next_schedule"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: UsbHubCoordinator, n: int) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, n, "next_schedule")
        self._value: datetime | None = None
        self._update_value()

    def _update_value(self) -> None:
        nxt = self.port.next_event
        if nxt is None:
            self._value = None
            return
        # Schedule events fire on whole minutes; round to the nearest one.
        target = dt_util.utcnow() + timedelta(seconds=nxt.in_s + 30)
        when = target.replace(second=0, microsecond=0)
        if self._value is None or abs(when - self._value) > TIMESTAMP_TOLERANCE:
            self._value = when

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_value()
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> datetime | None:
        """Return the time of the next scheduled switch."""
        return self._value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Details of the next event."""
        nxt = self.port.next_event
        if nxt is None:
            return None
        return {"action": "on" if nxt.on else "off", "entry": nxt.entry, "at": nxt.at}
