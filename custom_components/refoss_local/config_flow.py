from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from .const import DOMAIN, _LOGGER, DISCOVERY_TIMEOUT
from .util import refoss_local_discovery_server


class ConfigFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Refoss Local."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        refoss_discovery = await refoss_local_discovery_server(self.hass)
        devices = await refoss_discovery.broadcast_msg(wait_for=DISCOVERY_TIMEOUT)

        if not devices:
            errors["base"] = "no_devices"
        else:
            return self.async_create_entry(
                title="Refoss Local",
                data={"devices": [d.dev_id for d in devices]},
            )

        return self.async_show_form(step_id="user", errors=errors)
