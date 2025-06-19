"""Refoss devices platform loader."""

from __future__ import annotations

import voluptuous as vol
from datetime import timedelta
from typing import Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from .bridge import DiscoveryService
from .util import refoss_discovery_server
from .const import COORDINATORS, _LOGGER, DATA_DISCOVERY_SERVICE, DISCOVERY_SCAN_INTERVAL, DOMAIN


PLATFORMS: Final = [
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Refoss from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    discover = await refoss_discovery_server(hass)
    refoss_discovery = DiscoveryService(hass, entry, discover)
    hass.data[DOMAIN][DATA_DISCOVERY_SERVICE] = refoss_discovery

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _async_scan_update(_=None):
        await refoss_discovery.discovery.broadcast_msg()

    await _async_scan_update()

    entry.async_on_unload(
        async_track_time_interval(
            hass, _async_scan_update, timedelta(seconds=DISCOVERY_SCAN_INTERVAL)
        )
    )

    return True


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up services for the Refoss integration."""

    async def handle_manual_refresh(call):
        device_id = call.data.get("device_id")
        coordinators = hass.data.get(DOMAIN, {}).get(COORDINATORS, {})

        if device_id:
            coordinator = coordinators.get(device_id)
            if coordinator:
                _LOGGER.debug("Rafraîchissement manuel ciblé pour %s", device_id)
                await coordinator.async_request_refresh()
            else:
                _LOGGER.warning("Aucun coordinator trouvé pour %s", device_id)
        else:
            _LOGGER.debug("Rafraîchissement manuel global")
            for did, coordinator in coordinators.items():
                _LOGGER.debug("→ Rafraîchissement %s", did)
                await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        "manual_refresh",
        handle_manual_refresh,
        schema=vol.Schema({vol.Optional("device_id"): str}),
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if hass.data[DOMAIN].get(DATA_DISCOVERY_SERVICE) is not None:
        refoss_discovery: DiscoveryService = hass.data[DOMAIN][DATA_DISCOVERY_SERVICE]
        refoss_discovery.discovery.clean_up()
        hass.data[DOMAIN].pop(DATA_DISCOVERY_SERVICE)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(COORDINATORS)

    return unload_ok
