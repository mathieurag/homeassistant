"""Refoss integration."""

from __future__ import annotations

from .refosslib.device import DeviceInfo
from .refosslib.device_manager import async_build_base_device
from .refosslib.discovery import Discovery, Listener

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import _LOGGER, COORDINATORS, DISPATCH_DEVICE_DISCOVERED, DOMAIN
from .coordinator import RefossDataUpdateCoordinator


class DiscoveryService(Listener):
    """Discovery event handler for refoss_local devices."""

    def __init__(
        self, hass: HomeAssistant, config_entry: ConfigEntry, discovery: Discovery
    ) -> None:
        """Init discovery service."""
        self.hass = hass
        self.config_entry = config_entry

        self.discovery = discovery
        self.discovery.add_listener(self)

        hass.data[DOMAIN].setdefault(COORDINATORS, [])

    async def device_found(self, device_info: DeviceInfo) -> None:
        """Handle new device found on the network."""

        device = await async_build_base_device(device_info)
        if device is None:
            return

        coordo = RefossDataUpdateCoordinator(self.hass, self.config_entry, device)
        self.hass.data[DOMAIN][COORDINATORS].append(coordo)
        await coordo.async_refresh()

        _LOGGER.debug(
            "Discover new device: %s, ip: %s",
            device_info.dev_name,
            device_info.inner_ip,
        )
        async_dispatcher_send(self.hass, DISPATCH_DEVICE_DISCOVERED, coordo)

    async def device_update(self, device_info: DeviceInfo) -> None:
        """Handle updates in device information, update if ip has changed."""
        for coordinator in self.hass.data[DOMAIN][COORDINATORS]:
            if coordinator.device.device_info.mac == device_info.mac:
                _LOGGER.debug(
                    "Update device %s ip to %s",
                    device_info.dev_name,
                    device_info.inner_ip,
                )
                coordinator.device.device_info.inner_ip = device_info.inner_ip
                await coordinator.async_refresh()
