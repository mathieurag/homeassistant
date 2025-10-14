import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from .const import DOMAIN, CONF_SCAN_INTERVAL, CONF_MTU, CONF_IP, CONF_USERNAME, CONF_PASSWORD

_LOGGER = logging.getLogger(__name__)

# Explicitly Register the Config Flow Handler
@config_entries.HANDLERS.register(DOMAIN)
class TPLinkConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for TP-Link Monitor."""

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input:
            try:
                from .tplink_monitor import fetch_port_statistics
                result = await self.hass.async_add_executor_job(
                    fetch_port_statistics, user_input[CONF_IP], user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
                )
                if result is None:
                    errors["base"] = "auth_failed"  # Uses `en.json`
                else:
                    return self.async_create_entry(title="TP-Link Switch", data=user_input)
            except Exception:
                _LOGGER.exception("Unexpected error during validation")
                errors["base"] = "cannot_connect"  # Uses `en.json`

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_IP): str,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_SCAN_INTERVAL, default=15): int,
                vol.Optional(CONF_MTU, default=1500): int,
            }),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry):
        """Return the options flow handler."""
        return TPLinkOptionsFlowHandler(entry)


class TPLinkOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for TP-Link Monitor."""

    def __init__(self, entry):
        """Initialize options flow."""
        self.entry = entry

    async def async_step_init(self, user_input=None):
        """Manage options."""
        if user_input:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_SCAN_INTERVAL, default=self.entry.options.get(CONF_SCAN_INTERVAL, 15)): int,
                vol.Optional(CONF_MTU, default=self.entry.options.get(CONF_MTU, 1500)): int,
            }),
        )
