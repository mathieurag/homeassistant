"""Corddinator for Bbox."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from bboxpy import AuthorizationError, Bbox
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_REFRESH_RATE, CONF_USE_TLS, DEFAULT_REFRESH_RATE, DOMAIN

_LOGGER = logging.getLogger(__name__)


class BboxDataUpdateCoordinator(DataUpdateCoordinator):
    """Define an object to fetch data."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry,
    ) -> None:
        """Class to manage fetching data API."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_REFRESH_RATE, DEFAULT_REFRESH_RATE)
            ),
        )
        self.entry = entry

    async def _async_setup(self) -> None:
        """Start Bbox connection."""
        try:
            self.bbox = Bbox(
                password=self.entry.data[CONF_PASSWORD],
                hostname=self.entry.data[CONF_HOST],
                session=async_create_clientsession(self.hass),
                use_tls=self.entry.data.get(CONF_USE_TLS, False),
                verify_ssl=self.entry.data.get(CONF_VERIFY_SSL, False),
            )
        except AuthorizationError as error:
            raise ConfigEntryAuthFailed(
                f"Password expired for {self.entry.data[CONF_HOST]}"
            ) from error

    async def update_configuration(
        self, hass: HomeAssistant, entry: ConfigEntry
    ) -> None:
        """Update configuration."""
        self.update_interval = timedelta(seconds=entry.options[CONF_REFRESH_RATE])
        _LOGGER.debug("Coordinator refresh interval updated (%s)", self.update_interval)

        await self.async_refresh()

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Fetch data."""
        try:
            bbox_info = self.check_list(await self.bbox.device.async_get_bbox_info())
            devices = await self.bbox.lan.async_get_connected_devices()
            wan_ip_stats = self.check_list(await self.bbox.wan.async_get_wan_ip_stats())
            parentalcontrol = self.check_list(
                await self.bbox.parentalcontrol.async_get_parental_control_service_state()
            )
            wps = self.check_list(await self.bbox.wifi.async_get_wps())
            wifi = self.check_list(await self.bbox.wifi.async_get_wireless())
            wan_ip = self.check_list(await self.bbox.wan.async_get_wan_ip())
        except Exception as error:
            _LOGGER.error(error)
            raise UpdateFailed from error

        return {
            "info": bbox_info,
            "devices": self.merge_objects(devices),
            "wan_ip_stats": wan_ip_stats,
            "parentalcontrol": parentalcontrol,
            "wps": wps,
            "wifi": wifi,
            "wan_ip": wan_ip,
        }

    @staticmethod
    def merge_objects(objs: Any) -> dict[str, Any]:
        """Merge objects return by the Bbox API."""
        assert isinstance(objs, list)

        def merge(a: dict, b: dict, path=[]):
            for key in b:
                if key in a:
                    if isinstance(a[key], dict) and isinstance(b[key], dict):
                        merge(a[key], b[key], path + [str(key)])
                    elif isinstance(a[key], list) and isinstance(b[key], list):
                        a[key].extend(b[key])
                    elif a[key] != b[key]:
                        raise ValueError(
                            f"Conflict merging the key {'.'.join(path + [str(key)])} of the "
                            "objects return by the Bbox API: "
                            f"'{a[key]}' ({type(a[key])}) != '{b[key]}' ({type(b[key])})"
                        )
                else:
                    a[key] = b[key]
            return a

        result = objs[0]
        assert isinstance(
            result, dict
        ), f"The first element of the list is not a dict (but {type(result)}): {result}"
        for idx, obj in enumerate(objs[1:]):
            assert isinstance(
                obj, dict
            ), f"The {idx+2} element of the list is not a dict (but {type(obj)}): {obj}"
            result = merge(result, obj)
        return result

    @staticmethod
    def check_list(obj: Any) -> dict[str, Any]:
        """Return element if one only."""
        if not isinstance(obj, list):
            raise UpdateFailed(f"The call is not a list ({type(obj)}): {obj}")
        if len(obj) != 1:
            raise UpdateFailed(
                f"The call contains more than one element ({len(obj)}): {obj}"
            )
        return obj[0]
