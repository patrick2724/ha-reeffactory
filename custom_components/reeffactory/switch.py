"""Switch platform for Reef Factory devices (sound alarm toggle)."""

from __future__ import annotations

import logging
import struct

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_DEVICE_TYPE,
    DATA_CLIENT,
    DEVICE_TYPES,
    DEVICE_TYPE_SALINITY_GUARDIAN,
    DEVICE_TYPE_THERMO_VIEW,
    DEVICE_TYPE_TDS_METER,
    DEVICE_TYPE_PH_METER,
    WS_REFRESH_CB,
    WS_SOUND_CMD,
    DOMAIN,
)
from .rf_websocket import RfWebSocketClient, read_uint8, read_uint32

_LOGGER = logging.getLogger(__name__)

_SOUND_BYTE_OFFSET = {
    DEVICE_TYPE_SALINITY_GUARDIAN: 16,
    DEVICE_TYPE_THERMO_VIEW:       12,
    DEVICE_TYPE_TDS_METER:          8,
    DEVICE_TYPE_PH_METER:          12,
}

_SOUND_IS_FLAGS = {DEVICE_TYPE_TDS_METER: True}


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    client = data[DATA_CLIENT]
    device_type = entry.data[CONF_DEVICE_TYPE]
    host = entry.data[CONF_HOST]
    name = entry.data[CONF_NAME]
    if device_type not in WS_SOUND_CMD:
        return
    device_info = DeviceInfo(
        identifiers={(DOMAIN, f"{device_type}_{host}")},
        name=name, manufacturer="Reef Factory",
        model=DEVICE_TYPES[device_type], configuration_url=f"http://{host}",
    )
    entity = RfSoundSwitch(
        client, device_info, device_type, host,
        WS_REFRESH_CB[device_type], WS_SOUND_CMD[device_type],
        _SOUND_BYTE_OFFSET[device_type], _SOUND_IS_FLAGS.get(device_type, False)
    )
    async_add_entities([entity])


class RfSoundSwitch(SwitchEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = "Alarm Sound"

    def __init__(self, client, device_info, device_type, host, cb_name, sound_cmd, byte_off, is_flags):
        self._attr_unique_id = f"{device_type}_{host}_sound"
        self._attr_device_info = device_info
        self._attr_available = False
        self._attr_is_on = False
        self._client = client
        self._cb_name = cb_name
        self._sound_cmd = sound_cmd
        self._byte_off = byte_off
        self._is_flags = is_flags

    async def async_added_to_hass(self):
        self._client.register_callback(self._cb_name, self._handle_refresh)
        self._client.register_disconnect_callback(self._set_unavailable)

    def _set_unavailable(self):
        self._attr_available = False; self.schedule_update_ha_state()

    def _handle_refresh(self, data):
        try:
            off = 0; nl = data[off]; off += 1
            sub = data[off:off+nl].decode(); off += nl
            dl = struct.unpack_from(">I", data, off)[0]; off += 4
            p = data[off:off+dl]
            if sub == "settings" and len(p) > self._byte_off:
                sb = p[self._byte_off]
                self._attr_is_on = (sb & 0xF0) != 0 if self._is_flags else sb != 0
                self._attr_available = True; self.schedule_update_ha_state()
        except Exception as e: _LOGGER.error("Sound switch error: %s", e)

    async def async_turn_on(self, **kw): await self._client.send_command(self._sound_cmd, b"on")
    async def async_turn_off(self, **kw): await self._client.send_command(self._sound_cmd, b"off")
