"""Tests for the API client's parsing and conversion helpers."""

from __future__ import annotations

import pytest

from custom_components.um_smart_usb_hub.api import (
    HubInfo,
    PortState,
    ScheduleEntry,
    UsbHubResponseError,
    days_to_list,
    list_to_days,
    parse_schedules,
    parse_settings,
)

from .conftest import load


def test_parse_hub() -> None:
    hub = HubInfo.from_dict(load("hub"))
    assert hub.fw == "2.2.0"
    assert hub.hostname == "usb-hub"
    assert hub.main_5v is True
    assert hub.ports_powered == 2
    assert hub.mac is None
    assert hub.devices == {
        "expander": True,
        "ina_1": True,
        "ina_2": True,
        "aht20": True,
    }


def test_parse_hub_with_mac() -> None:
    data = load("hub")
    data["mac"] = "98:A3:16:C8:D3:24"
    assert HubInfo.from_dict(data).mac == "98:a3:16:c8:d3:24"


def test_parse_not_a_hub() -> None:
    with pytest.raises(UsbHubResponseError):
        HubInfo.from_dict({"name": "something else"})


def test_parse_ports_rest_and_status_forms() -> None:
    rest = [PortState.from_dict(p) for p in load("ports")["ports"]]
    status = [PortState.from_dict(p) for p in load("status")["ports"]]
    assert len(rest) == len(status) == 6
    assert rest[0].enabled
    assert rest[0].occupied
    assert rest[0].state == "green"
    assert status[0].monitor is True
    assert status[0].volts > 4


def test_parse_port_detail_power_mode() -> None:
    assert PortState.from_dict(load("ports_1")).power_mode == "connect"


def test_next_event_both_forms() -> None:
    rest = PortState.from_dict(
        {
            "n": 6,
            "schedule": {
                "count": 2,
                "next": {"in_s": 82, "on": False, "at": "Sun 16:35", "entry": 0},
            },
        }
    )
    status = PortState.from_dict(
        {"n": 6, "sched": 2, "next": {"in": 82, "on": False, "at": "Sun 16:35", "i": 0}}
    )
    assert rest.next_event == status.next_event
    assert rest.schedule_count == status.schedule_count == 2


def test_settings_drop_wifi() -> None:
    settings = parse_settings(load("settings_schema"))
    assert "wifi" not in settings
    assert settings["ports"]["power_mode"][0] == "connect"
    assert settings["leds"]["brightness"] == 50


@pytest.mark.parametrize(
    ("mode", "on", "num"),
    [
        ("off", False, 0),
        ("on", True, 0),
        ("on_for", True, 1),
        ("on_until", True, 2),
        ("on_every", True, 3),
    ],
)
def test_schedule_mode_round_trip(mode: str, on: bool, num: int) -> None:
    web = ScheduleEntry(mode=mode).to_web()
    assert (web["on"], web["mode"]) == (on, num)
    assert ScheduleEntry.from_web(web).mode == mode


def test_parse_schedules() -> None:
    schedules = parse_schedules(load("schedules_example"))
    assert [len(p) for p in schedules] == [0, 0, 0, 0, 1, 2]
    assert schedules[5][0].mode == "on_until"
    assert schedules[5][1].mode == "off"
    assert schedules[5][1].invalid is True
    with pytest.raises(UsbHubResponseError):
        parse_schedules({"ports": [[], []]})


def test_days() -> None:
    assert days_to_list(62) == ["mon", "tue", "wed", "thu", "fri"]
    assert list_to_days(["sun", "sat"]) == 65
    assert list_to_days(["Monday"]) == 2
    assert list_to_days(127) == 127
