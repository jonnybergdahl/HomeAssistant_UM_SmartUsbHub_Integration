"""Tests for the config flow."""

from __future__ import annotations

from ipaddress import ip_address
import json
from pathlib import Path

from homeassistant.config_entries import SOURCE_USER, SOURCE_ZEROCONF
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.um_smart_usb_hub.const import CONF_SCAN_INTERVAL, DOMAIN

from .conftest import BASE, HOST, load

ZEROCONF = ZeroconfServiceInfo(
    ip_address=ip_address(HOST),
    ip_addresses=[ip_address(HOST)],
    hostname="usb-hub.local.",
    name="usb-hub._http._tcp.local.",
    port=80,
    type="_http._tcp.local.",
    properties={},
)


async def test_user_flow(hass: HomeAssistant, mock_hub: AiohttpClientMocker) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Smart USB Hub"
    assert result["data"] == {CONF_HOST: HOST}
    assert result["result"].unique_id == "usb-hub"


async def test_user_flow_cannot_connect(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE}/hub", exc=TimeoutError)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/hub", json=load("hub"))
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_not_a_hub(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE}/hub", json={"hello": "world"})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )
    assert result["errors"] == {"base": "not_a_hub"}


async def test_user_flow_already_configured(
    hass: HomeAssistant, mock_hub: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_zeroconf_flow(
    hass: HomeAssistant, mock_hub: AiohttpClientMocker
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=ZEROCONF
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: HOST}


async def test_zeroconf_updates_host(
    hass: HomeAssistant, mock_hub: AiohttpClientMocker
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="usb-hub", data={CONF_HOST: "10.0.0.9"}
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=ZEROCONF
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == HOST


async def test_reconfigure(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    result = await setup_integration.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"


async def test_options(hass: HomeAssistant, setup_integration: MockConfigEntry) -> None:
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 10}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert setup_integration.options == {CONF_SCAN_INTERVAL: 10}


async def test_zeroconf_renamed_hub_by_txt_records(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A renamed hub is found through its vendor/model TXT records."""
    hub = load("hub")
    hub["network"]["hostname"] = "lab-hub"
    aioclient_mock.get(f"{BASE}/hub", json=hub)
    info = ZeroconfServiceInfo(
        ip_address=ip_address(HOST),
        ip_addresses=[ip_address(HOST)],
        hostname="lab-hub.local.",
        name="lab-hub._http._tcp.local.",
        port=80,
        type="_http._tcp.local.",
        properties={"vendor": "unexpectedmaker", "model": "smart-usb-hub"},
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=info
    )
    assert result["step_id"] == "zeroconf_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "lab-hub"


def test_manifest_matches_txt_records() -> None:
    """The manifest discovers hubs by TXT records, whatever their name."""
    manifest = json.loads(
        (
            Path(__file__).parents[1]
            / "custom_components/um_smart_usb_hub/manifest.json"
        ).read_text()
    )
    assert {
        "type": "_http._tcp.local.",
        "properties": {"vendor": "unexpectedmaker", "model": "smart-usb-hub"},
    } in manifest["zeroconf"]
