"""Config flow for the UM Smart USB Hub."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
import voluptuous as vol

from .api import HubInfo, UsbHubClient, UsbHubConnectionError, UsbHubError
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_HOST,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .coordinator import UsbHubConfigEntry


class UsbHubConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the UM Smart USB Hub."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the flow."""
        self._host: str | None = None
        self._hub: HubInfo | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: UsbHubConfigEntry) -> UsbHubOptionsFlow:
        """Return the options flow."""
        return UsbHubOptionsFlow()

    async def _async_probe(self, host: str) -> HubInfo:
        client = UsbHubClient(async_get_clientsession(self.hass), host)
        return await client.get_hub()

    async def _async_validate(self, host: str) -> tuple[HubInfo | None, str | None]:
        """Probe the host; return the hub info or an error key."""
        try:
            hub = await self._async_probe(host)
        except UsbHubConnectionError:
            return None, "cannot_connect"
        except UsbHubError:
            return None, "not_a_hub"
        except Exception:
            LOGGER.exception("Unexpected error probing %s", host)
            return None, "unknown"
        if not hub.hostname:
            return None, "not_a_hub"
        return hub, None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set up a hub by host name or IP address."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            hub, error = await self._async_validate(host)
            if hub is not None:
                await self.async_set_unique_id(hub.hostname)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self.async_create_entry(title=hub.name, data={CONF_HOST: host})
            errors["base"] = error or "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_HOST): str}),
                user_input or {CONF_HOST: DEFAULT_HOST},
            ),
            errors=errors,
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle a hub found via its `_http._tcp` mDNS advertisement."""
        if discovery_info.ip_address.version != 4:
            return self.async_abort(reason="not_ipv4_address")
        host = discovery_info.host
        hub, error = await self._async_validate(host)
        if hub is None:
            return self.async_abort(reason=error or "unknown")
        await self.async_set_unique_id(hub.hostname)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        self._host = host
        self._hub = hub
        self.context["title_placeholders"] = {"name": hub.name}
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm adding a discovered hub."""
        assert self._hub is not None
        assert self._host is not None
        if user_input is not None:
            return self.async_create_entry(
                title=self._hub.name, data={CONF_HOST: self._host}
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={"name": self._hub.name, "host": self._host},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the address of an existing hub."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            hub, error = await self._async_validate(host)
            if hub is not None:
                await self.async_set_unique_id(hub.hostname)
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_HOST: host}
                )
            errors["base"] = error or "unknown"

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_HOST): str}),
                user_input or {CONF_HOST: entry.data[CONF_HOST]},
            ),
            errors=errors,
        )


class UsbHubOptionsFlow(OptionsFlowWithReload):
    """Options: polling interval."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])}
            )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_SCAN_INTERVAL): NumberSelector(
                            NumberSelectorConfig(
                                min=MIN_SCAN_INTERVAL,
                                max=MAX_SCAN_INTERVAL,
                                step=1,
                                mode=NumberSelectorMode.BOX,
                                unit_of_measurement="s",
                            )
                        )
                    }
                ),
                {
                    CONF_SCAN_INTERVAL: self.config_entry.options.get(
                        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                    )
                },
            ),
        )
