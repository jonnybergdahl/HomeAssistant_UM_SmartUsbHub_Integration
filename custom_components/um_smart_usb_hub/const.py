"""Constants for the UM Smart USB Hub integration."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Final

DOMAIN: Final = "um_smart_usb_hub"
LOGGER = logging.getLogger(__package__)

MANUFACTURER: Final = "Unexpected Maker"
MODEL: Final = "Smart USB Hub 6"

DEFAULT_HOST: Final = "usb-hub.local"
CONF_SCAN_INTERVAL: Final = "scan_interval"
DEFAULT_SCAN_INTERVAL: Final = 5
MIN_SCAN_INTERVAL: Final = 2
MAX_SCAN_INTERVAL: Final = 60

# Settings and schedules change rarely; refresh them on this cadence and
# right after every write.
SLOW_REFRESH_INTERVAL: Final = timedelta(minutes=5)

DEFAULT_POWER_CYCLE_OFF_TIME: Final = 5

AVERAGING_OPTIONS: Final = ("0", "2", "4", "8", "16")

RESET_REASONS: Final = (
    "POWERON",
    "SW",
    "USB",
    "PANIC",
    "TASK_WDT",
    "INT_WDT",
    "WDT",
    "BROWNOUT",
    "PWR_GLITCH",
    "EXT",
    "DEEPSLEEP",
    "JTAG",
    "EFUSE",
    "CPU_LOCKUP",
    "SDIO",
    "UNKNOWN",
)
