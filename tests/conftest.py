"""Fixtures for UM Smart USB Hub tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.um_smart_usb_hub.const import DOMAIN

HOST = "192.168.1.100"
BASE = f"http://{HOST}/api"
FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict[str, Any]:
    """Load a JSON fixture."""
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations in every test."""


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A config entry for the hub."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Smart USB Hub",
        unique_id="usb-hub",
        data={CONF_HOST: HOST},
    )


@pytest.fixture
def mock_hub(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Answer the hub's read endpoints from fixtures."""
    aioclient_mock.get(f"{BASE}/hub", json=load("hub"))
    aioclient_mock.get(f"{BASE}/ports", json=load("ports"))
    aioclient_mock.get(f"{BASE}/settings/schema", json=load("settings_schema"))
    aioclient_mock.get(f"{BASE}/schedules", json=load("schedules_example"))
    return aioclient_mock


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_hub: AiohttpClientMocker
) -> MockConfigEntry:
    """Set up the integration with the mocked hub."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
