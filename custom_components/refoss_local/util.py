"""Refoss helpers functions."""

from __future__ import annotations

from .refosslib.discovery import Discovery

from homeassistant.core import HomeAssistant
from homeassistant.helpers import singleton


@singleton.singleton("refoss_local_discovery_server")
async def refoss_local_discovery_server(hass: HomeAssistant) -> Discovery:
    """Get refoss_local Discovery server."""
    discovery_server = Discovery()
    await discovery_server.initialize()
    return discovery_server
