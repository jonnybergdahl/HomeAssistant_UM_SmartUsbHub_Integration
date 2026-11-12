"""Tests for the integration's actions."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceNotSupported
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.um_smart_usb_hub.const import DOMAIN

from .conftest import BASE, load

PORT6 = "switch.smart_usb_hub_port_6"


def _echo_schedules(mock: AiohttpClientMocker) -> None:
    """Make POST /api/schedules return what was sent (as a hub that accepted it)."""

    async def echo(method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        ports = [[{**e, "invalid": False} for e in port] for port in data["ports"]]
        return AiohttpClientMockResponse(method, url, json={"ports": ports})

    mock.post(f"{BASE}/schedules", side_effect=echo)


def _posted_schedules(mock: AiohttpClientMocker) -> dict[str, Any]:
    return next(c[2] for c in reversed(mock.mock_calls) if c[0] == "POST")


async def test_get_schedule(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    response = await hass.services.async_call(
        DOMAIN,
        "get_schedule",
        {ATTR_ENTITY_ID: PORT6},
        blocking=True,
        return_response=True,
    )
    result = response[PORT6]
    assert result["port"] == 6
    assert [e["mode"] for e in result["entries"]] == ["on_until", "off"]
    assert result["entries"][0]["days"] == ["mon", "tue", "wed", "thu", "fri"]
    assert result["entries"][1]["invalid"] is True


async def test_set_schedule_keeps_other_ports(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_hub: AiohttpClientMocker,
) -> None:
    _echo_schedules(mock_hub)
    response = await hass.services.async_call(
        DOMAIN,
        "set_schedule",
        {
            ATTR_ENTITY_ID: PORT6,
            "entries": [
                {
                    "days": ["sat", "sun"],
                    "time": "09:00:00",
                    "mode": "on_for",
                    "duration": 90,
                }
            ],
        },
        blocking=True,
        return_response=True,
    )
    sent = _posted_schedules(mock_hub)["ports"]
    assert len(sent) == 6
    # Port 5's existing rule is sent back untouched.
    assert sent[4] == [
        {
            "days": 127,
            "time": "08:00",
            "on": True,
            "mode": 1,
            "dur": 540,
            "until": "17:00",
            "every": 30,
            "allday": True,
            "once": False,
            "enabled": True,
        }
    ]
    assert sent[5] == [
        {
            "days": 65,
            "time": "09:00",
            "on": True,
            "mode": 1,
            "dur": 90,
            "until": "17:00",
            "every": 30,
            "allday": True,
            "once": False,
            "enabled": True,
        }
    ]
    assert response[PORT6]["entries"][0]["mode"] == "on_for"


async def test_add_schedule_entry(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_hub: AiohttpClientMocker,
) -> None:
    _echo_schedules(mock_hub)
    await hass.services.async_call(
        DOMAIN,
        "add_schedule_entry",
        {ATTR_ENTITY_ID: PORT6, "days": ["mon"], "time": "06:00", "mode": "off"},
        blocking=True,
    )
    sent = _posted_schedules(mock_hub)["ports"][5]
    assert len(sent) == 3
    assert sent[-1]["on"] is False
    assert sent[-1]["days"] == 2


async def test_clear_schedule(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_hub: AiohttpClientMocker,
) -> None:
    _echo_schedules(mock_hub)
    await hass.services.async_call(
        DOMAIN, "clear_schedule", {ATTR_ENTITY_ID: PORT6}, blocking=True
    )
    assert _posted_schedules(mock_hub)["ports"][5] == []


async def test_set_schedule_silent_reject(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_hub: AiohttpClientMocker,
) -> None:
    # A hub that rejects the body answers 200 with the unchanged set.
    mock_hub.post(f"{BASE}/schedules", json=load("schedules_example"))
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "clear_schedule", {ATTR_ENTITY_ID: PORT6}, blocking=True
        )


async def test_set_schedule_validation(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    with pytest.raises(Exception, match="every"):
        await hass.services.async_call(
            DOMAIN,
            "set_schedule",
            {
                ATTR_ENTITY_ID: PORT6,
                "entries": [
                    {"days": ["mon"], "time": "09:00", "mode": "on_every", "every": 5}
                ],
            },
            blocking=True,
        )


async def test_power_cycle(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_hub: AiohttpClientMocker,
) -> None:
    mock_hub.post(f"{BASE}/port", json=load("status"))
    with patch("custom_components.um_smart_usb_hub.coordinator.asyncio.sleep") as sleep:
        await hass.services.async_call(
            DOMAIN,
            "power_cycle",
            {ATTR_ENTITY_ID: "switch.smart_usb_hub_port_3", "off_time": 2},
            blocking=True,
        )
    sleep.assert_awaited_once_with(2)
    posts = [dict(c[1].query) for c in mock_hub.mock_calls if c[0] == "POST"]
    assert posts == [{"n": "3", "on": "0"}, {"n": "3", "on": "1"}]


async def test_action_rejects_non_port_switch(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    with pytest.raises(ServiceNotSupported):
        await hass.services.async_call(
            DOMAIN,
            "power_cycle",
            {ATTR_ENTITY_ID: "switch.smart_usb_hub_leds"},
            blocking=True,
        )
