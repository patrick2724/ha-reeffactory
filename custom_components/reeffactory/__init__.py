"""Reef Factory integration."""

from __future__ import annotations
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from .const import CONF_DEVICE_TYPE, DATA_CLIENT, DATA_ENTITIES, DOMAIN, WS_CONNECT_MSG
from .rf_websocket import RfWebSocketClient

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH, Platform.BUTTON, Platform.NUMBER]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    host = entry.data["host"]
    device_type = entry.data[CONF_DEVICE_TYPE]
    connect_msg = WS_CONNECT_MSG[device_type]
    client = RfWebSocketClient(host=host, connect_msg=connect_msg)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {DATA_CLIENT: client, DATA_ENTITIES: []}
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await client.start()
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data[DATA_CLIENT].stop()
    return unload_ok
