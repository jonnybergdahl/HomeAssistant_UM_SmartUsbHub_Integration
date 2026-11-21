"""Tests for the features that need hub firmware 2.3.0 or newer."""

from __future__ import annotations

from typing import Any

from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from .conftest import BASE, load

S3_SWITCH = "switch.smart_usb_hub_esp32_s3_usb"
S3_ON_BOOT = "switch.smart_usb_hub_disconnect_esp32_s3_usb_on_boot"
REBOOT = "button.smart_usb_hub_restart"
SINGLE = "select.smart_usb_hub_user_button_single_press"
DOUBLE = "select.smart_usb_hub_user_button_double_press"
LONG = "select.smart_usb_hub_user_button_long_press"


def _settings_with(button: dict[str, str]) -> dict[str, Any]:
    data = load("settings_schema")
    for group in data["groups"]:
        if group["name"] == "button":
            group["values"] = button
    return data


async def test_new_entities(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    assert hass.states.get(S3_SWITCH).state == STATE_ON
    assert hass.states.get(S3_ON_BOOT).state == STATE_OFF
    assert hass.states.get(REBOOT) is not None
    assert hass.states.get(SINGLE).state == "toggle_ports"
    assert hass.states.get(DOUBLE).state == "none"
    assert hass.states.get(LONG).state == "none"


NEW_ENTITIES = (S3_SWITCH, S3_ON_BOOT, REBOOT, SINGLE, DOUBLE, LONG)


def _mock_firmware(mock: AiohttpClientMocker, *, new: bool) -> None:
    """Answer the read endpoints as firmware 2.3.0 (new) or 2.2.0."""
    hub = load("hub")
    settings = load("settings_schema")
    if not new:
        hub["fw"] = "2.2.0"
        del hub["s3_usb_connected"]
        del hub["network"]["mac"]
        settings["groups"] = [
            g for g in settings["groups"] if g["name"] not in ("s3_usb", "button")
        ]
    mock.clear_requests()
    mock.get(f"{BASE}/hub", json=hub)
    mock.get(f"{BASE}/ports", json=load("ports"))
    mock.get(f"{BASE}/settings/schema", json=settings)
    mock.get(f"{BASE}/schedules", json=load("schedules"))


async def test_old_firmware_has_no_new_entities(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    _mock_firmware(aioclient_mock, new=False)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    for entity_id in NEW_ENTITIES:
        assert hass.states.get(entity_id) is None, entity_id
    # Everything else still works.
    assert hass.states.get("switch.smart_usb_hub_port_1").state == STATE_ON


async def test_upgrade_adds_entities_without_reload(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A firmware upgrade while running adds the new entities on the next poll."""
    _mock_firmware(aioclient_mock, new=False)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = config_entry.runtime_data
    port_1 = hass.states.get("switch.smart_usb_hub_port_1")

    _mock_firmware(aioclient_mock, new=True)
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    # Settings were re-read on the same poll because the firmware changed,
    # so the settings-based entities are there too, not 5 minutes later.
    assert hass.states.get(S3_SWITCH).state == STATE_ON
    assert hass.states.get(S3_ON_BOOT).state == STATE_OFF
    assert hass.states.get(REBOOT) is not None
    assert hass.states.get(SINGLE).state == "toggle_ports"
    # No reload: the same coordinator, and existing entities never changed state.
    assert config_entry.runtime_data is coordinator
    assert hass.states.get("switch.smart_usb_hub_port_1").last_changed == (
        port_1.last_changed
    )

    # Later polls don't add them again.
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    # 6 power modes + 3 user button selects (averaging is disabled by default).
    assert len(hass.states.async_entity_ids("select")) == 6 + 3


async def test_downgrade_makes_entities_unavailable(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_hub: AiohttpClientMocker,
) -> None:
    """Entities stay after a downgrade, so automations keep their references."""
    _mock_firmware(mock_hub, new=False)
    await setup_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()

    for entity_id in NEW_ENTITIES:
        if entity_id == REBOOT:
            # A button has no feature state to lose; it stays as it was.
            continue
        assert hass.states.get(entity_id).state == "unavailable", entity_id


async def test_disconnect_s3_usb(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_hub: AiohttpClientMocker,
) -> None:
    hub = load("hub")
    hub["s3_usb_connected"] = False
    mock_hub.post(f"{BASE}/hub/usbs3", json=hub)
    await hass.services.async_call(
        "switch", "turn_off", {ATTR_ENTITY_ID: S3_SWITCH}, blocking=True
    )
    assert dict(mock_hub.mock_calls[-1][1].query) == {"on": "0"}
    # State comes from the hub's response, not an assumption.
    assert hass.states.get(S3_SWITCH).state == STATE_OFF


async def test_reboot(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_hub: AiohttpClientMocker,
) -> None:
    mock_hub.post(f"{BASE}/hub/reboot", json={"ok": True})
    await hass.services.async_call(
        "button", "press", {ATTR_ENTITY_ID: REBOOT}, blocking=True
    )
    assert mock_hub.mock_calls[-1][0] == "POST"
    assert str(mock_hub.mock_calls[-1][1]).endswith("/api/hub/reboot")


def _schema_sequence(first: dict, then: dict):
    calls = {"n": 0}

    async def respond(method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        calls["n"] += 1
        return AiohttpClientMockResponse(
            method, url, json=first if calls["n"] == 1 else then
        )

    return respond


async def test_button_action_moves_from_other_press(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_hub: AiohttpClientMocker,
) -> None:
    """Choosing an action another press has moves it there, in one write."""
    before = _settings_with(
        {"press": "toggle_ports", "double_press": "none", "long_press": "none"}
    )
    after = _settings_with(
        {"press": "none", "double_press": "toggle_ports", "long_press": "none"}
    )
    mock_hub.clear_requests()
    mock_hub.get(f"{BASE}/hub", json=load("hub"))
    mock_hub.get(f"{BASE}/ports", json=load("ports"))
    mock_hub.get(f"{BASE}/schedules", json=load("schedules"))
    mock_hub.get(f"{BASE}/settings/schema", side_effect=_schema_sequence(before, after))
    mock_hub.post(f"{BASE}/settings", json={"ok": True})

    await hass.services.async_call(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: DOUBLE, "option": "toggle_ports"},
        blocking=True,
    )
    posts = [c for c in mock_hub.mock_calls if c[0] == "POST"]
    assert posts[-1][2] == {"button": {"double_press": "toggle_ports", "press": "none"}}
    assert hass.states.get(DOUBLE).state == "toggle_ports"
    assert hass.states.get(SINGLE).state == "none"


async def test_button_action_not_applied(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_hub: AiohttpClientMocker,
) -> None:
    """A write the hub didn't apply is reported, not silently accepted."""
    unchanged = load("settings_schema")
    mock_hub.clear_requests()
    mock_hub.get(f"{BASE}/hub", json=load("hub"))
    mock_hub.get(f"{BASE}/ports", json=load("ports"))
    mock_hub.get(f"{BASE}/schedules", json=load("schedules"))
    mock_hub.get(f"{BASE}/settings/schema", json=unchanged)
    mock_hub.post(f"{BASE}/settings", json={"ok": True})
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "select",
            "select_option",
            {ATTR_ENTITY_ID: LONG, "option": "all_off"},
            blocking=True,
        )
