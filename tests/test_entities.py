"""Tests for entity setup, state and writes."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.um_smart_usb_hub.const import DOMAIN
from custom_components.um_smart_usb_hub.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import BASE, load


async def test_setup_and_unload(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    assert setup_integration.state is ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    assert setup_integration.state is ConfigEntryState.NOT_LOADED


async def test_setup_retry_on_error(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    aioclient_mock.get(f"{BASE}/hub", exc=TimeoutError)
    aioclient_mock.get(f"{BASE}/ports", exc=TimeoutError)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_devices(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    devices = {
        ident: device
        for device in dr.async_entries_for_config_entry(
            device_registry, setup_integration.entry_id
        )
        for domain, ident in device.identifiers
        if domain == DOMAIN
    }
    assert len(devices) == 7
    hub = devices["usb-hub"]
    assert hub.sw_version == "2.3.0"
    assert hub.manufacturer == "Unexpected Maker"
    for n in range(1, 7):
        port = devices[f"usb-hub_port{n}"]
        assert port.via_device_id == hub.id
        assert port.name == f"Smart USB Hub Port {n}"


async def test_states(hass: HomeAssistant, setup_integration: MockConfigEntry) -> None:
    assert hass.states.get("switch.smart_usb_hub_port_1").state == STATE_ON
    assert hass.states.get("switch.smart_usb_hub_port_2").state == STATE_OFF
    assert (
        hass.states.get("binary_sensor.smart_usb_hub_port_1_device_connected").state
        == STATE_ON
    )
    assert (
        hass.states.get("binary_sensor.smart_usb_hub_port_1_over_current").state
        == STATE_OFF
    )
    assert float(hass.states.get("sensor.smart_usb_hub_port_1_current").state) == 77.6
    assert float(hass.states.get("sensor.smart_usb_hub_port_1_voltage").state) == 4.64
    # mW reported, shown in W
    assert float(hass.states.get("sensor.smart_usb_hub_port_1_power").state) == 0.3601
    assert hass.states.get("sensor.smart_usb_hub_port_1_led_state").state == "green"
    assert float(hass.states.get("sensor.smart_usb_hub_temperature").state) == 32.1
    assert hass.states.get("sensor.smart_usb_hub_reset_reason").state == "usb"
    assert hass.states.get("binary_sensor.smart_usb_hub_main_5v").state == STATE_ON
    assert (
        hass.states.get("binary_sensor.smart_usb_hub_hardware_problem").state
        == STATE_OFF
    )
    assert hass.states.get("select.smart_usb_hub_port_1_power_mode").state == "connect"
    assert hass.states.get("select.smart_usb_hub_port_2_power_mode").state == "manual"
    assert hass.states.get("switch.smart_usb_hub_leds").state == STATE_ON
    assert float(hass.states.get("number.smart_usb_hub_led_brightness").state) == 50
    assert hass.states.get("text.smart_usb_hub_port_1_name").state == ""


async def test_disabled_by_default(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    for entity_id in (
        "sensor.smart_usb_hub_wifi_signal",
        "switch.smart_usb_hub_esphome_api",
        "select.smart_usb_hub_measurement_averaging",
        "number.smart_usb_hub_utc_offset",
    ):
        entry = entity_registry.async_get(entity_id)
        assert entry is not None, entity_id
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_monitor_missing_makes_readings_unavailable(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    ports = load("ports")
    ports["ports"][0]["monitor"] = False
    aioclient_mock.get(f"{BASE}/hub", json=load("hub"))
    aioclient_mock.get(f"{BASE}/ports", json=ports)
    aioclient_mock.get(f"{BASE}/settings/schema", json=load("settings_schema"))
    aioclient_mock.get(f"{BASE}/schedules", json=load("schedules"))
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.smart_usb_hub_port_1_current").state == "unavailable"
    assert hass.states.get("sensor.smart_usb_hub_port_2_current").state != "unavailable"


async def test_turn_on_port(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_hub: AiohttpClientMocker,
) -> None:
    status = load("status")
    status["ports"][1]["enabled"] = True
    status["ports"][1]["state"] = "pulse"
    mock_hub.post(f"{BASE}/port", json=status)
    await hass.services.async_call(
        "switch",
        "turn_on",
        {ATTR_ENTITY_ID: "switch.smart_usb_hub_port_2"},
        blocking=True,
    )
    call = mock_hub.mock_calls[-1]
    assert call[0] == "POST"
    assert dict(call[1].query) == {"n": "2", "on": "1"}
    assert hass.states.get("switch.smart_usb_hub_port_2").state == STATE_ON


async def test_all_ports_off(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_hub: AiohttpClientMocker,
) -> None:
    ports = load("ports")
    for p in ports["ports"]:
        p["enabled"] = False
    mock_hub.post(f"{BASE}/hub/ports", json=ports)
    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: "button.smart_usb_hub_all_ports_off"},
        blocking=True,
    )
    assert dict(mock_hub.mock_calls[-1][1].query) == {"on": "0"}
    assert hass.states.get("switch.smart_usb_hub_port_1").state == STATE_OFF


async def test_identify(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_hub: AiohttpClientMocker,
) -> None:
    mock_hub.post(f"{BASE}/identify", json={"ok": True})
    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: "button.smart_usb_hub_port_3_identify"},
        blocking=True,
    )
    assert dict(mock_hub.mock_calls[-1][1].query) == {"n": "3"}


async def test_set_power_mode(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_hub: AiohttpClientMocker,
) -> None:
    mock_hub.post(f"{BASE}/settings", json={"ok": True})
    # The hub accepts the write; reads after it return the new value.
    updated = load("settings_schema")
    for group in updated["groups"]:
        if group["name"] == "ports":
            group["values"]["power_mode"][1] = "boot"
    original = load("settings_schema")
    calls = {"n": 0}

    async def schema_response(method, url, data):
        calls["n"] += 1
        # First read is the read-modify-write snapshot, later reads verify.
        return AiohttpClientMockResponse(
            method, url, json=original if calls["n"] == 1 else updated
        )

    mock_hub.clear_requests()
    mock_hub.get(f"{BASE}/hub", json=load("hub"))
    mock_hub.get(f"{BASE}/ports", json=load("ports"))
    mock_hub.get(f"{BASE}/schedules", json=load("schedules"))
    mock_hub.get(f"{BASE}/settings/schema", side_effect=schema_response)
    mock_hub.post(f"{BASE}/settings", json={"ok": True})

    await hass.services.async_call(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: "select.smart_usb_hub_port_2_power_mode", "option": "boot"},
        blocking=True,
    )
    posts = [c for c in mock_hub.mock_calls if c[0] == "POST"]
    assert posts[-1][2] == {
        "ports": {
            "power_mode": ["connect", "boot", "connect", "manual", "manual", "manual"]
        }
    }
    assert hass.states.get("select.smart_usb_hub_port_2_power_mode").state == "boot"


async def test_diagnostics_redacts(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    diag = await async_get_config_entry_diagnostics(hass, setup_integration)
    assert diag["hub"]["network"]["ssid"] == "**REDACTED**"
    assert diag["entry"]["data"]["host"] == "**REDACTED**"
    assert "wifi" not in diag["settings"]


async def test_mac_links_device(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
) -> None:
    hub = load("hub")
    hub["mac"] = "98A316C8D324"
    aioclient_mock.get(f"{BASE}/hub", json=hub)
    aioclient_mock.get(f"{BASE}/ports", json=load("ports"))
    aioclient_mock.get(f"{BASE}/settings/schema", json=load("settings_schema"))
    aioclient_mock.get(f"{BASE}/schedules", json=load("schedules"))
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    devices = [
        d
        for d in dr.async_entries_for_config_entry(
            device_registry, config_entry.entry_id
        )
        if (DOMAIN, "usb-hub") in d.identifiers
    ]
    assert devices[0].connections == {(dr.CONNECTION_NETWORK_MAC, "98:a3:16:c8:d3:24")}
