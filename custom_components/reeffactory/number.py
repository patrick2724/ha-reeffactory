"""Number platform for Reef Factory devices (alarm thresholds)."""

from __future__ import annotations

import logging
import struct

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, UnitOfTemperature, CONCENTRATION_PARTS_PER_MILLION
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
    DOMAIN,
)
from .rf_websocket import RfWebSocketClient, read_uint32

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    client: RfWebSocketClient = data[DATA_CLIENT]
    device_type = entry.data[CONF_DEVICE_TYPE]
    host = entry.data[CONF_HOST]
    name = entry.data[CONF_NAME]

    device_info = DeviceInfo(
        identifiers={(DOMAIN, f"{device_type}_{host}")},
        name=name,
        manufacturer="Reef Factory",
        model=DEVICE_TYPES[device_type],
        configuration_url=f"http://{host}",
    )

    entities: list[RfNumberEntity] = []

    if device_type == DEVICE_TYPE_SALINITY_GUARDIAN:
        low = RfNumberEntity(
            client, device_info, f"sg_{host}_alarm_low",
            "Alarm Salinity Low", "ppt", 0, 50, 0.1,
            "sgSet", "alarmLow", scale=100,
        )
        high = RfNumberEntity(
            client, device_info, f"sg_{host}_alarm_high",
            "Alarm Salinity High", "ppt", 0, 50, 0.1,
            "sgSet", "alarmHigh", scale=100,
        )

        def handle_sg(data: bytes) -> None:
            try:
                off = 0
                name_len = data[off]; off += 1
                sub = data[off:off+name_len].decode(); off += name_len
                dlen = struct.unpack_from(">I", data, off)[0]; off += 4
                p = data[off:off+dlen]
                if sub == "settings":
                    pos = 4 * 5
                    _, pos = read_uint32(p, pos)   # salinity
                    _, pos = read_uint32(p, pos)   # temp
                    low_raw, pos = read_uint32(p, pos)
                    high_raw, pos = read_uint32(p, pos)
                    low._set_value(low_raw / 100)
                    high._set_value(high_raw / 100)
            except Exception as exc:
                _LOGGER.error("Error parsing sg numbers: %s", exc)

        client.register_callback('sgRefresh', handle_sg)
        entities = [low, high]

    elif device_type == DEVICE_TYPE_THERMO_VIEW:
        low = RfNumberEntity(
            client, device_info, f"tv_{host}_alarm_low",
            "Alarm Temp Low", UnitOfTemperature.CELSIUS, 0, 40, 0.1,
            "tvSet", "alarmLow", scale=100,
        )
        high = RfNumberEntity(
            client, device_info, f"tv_{host}_alarm_high",
            "Alarm Temp High", UnitOfTemperature.CELSIUS, 0, 40, 0.1,
            "tvSet", "alarmHigh", scale=100,
        )

        def handle_tv(data: bytes) -> None:
            try:
                off = 0
                name_len = data[off]; off += 1
                sub = data[off:off+name_len].decode(); off += name_len
                dlen = struct.unpack_from(">I", data, off)[0]; off += 4
                p = data[off:off+dlen]
                if sub == 'settings':
                    if all(b == 0xFF for b in p[:4]):
                        return
                    pos = 0
                    _, pos = read_uint32(p, pos)
                    low_raw, pos = read_uint32(p, pos)
                    high_raw, pos = read_uint32(p, pos)
                    low._set_value(low_raw / 100)
                    high._set_value(high_raw / 100)
            except Exception as exc:
                _LOGGER.error("Error parsing tv numbers: %s", exc)

        client.register_callback('tvRefresh', handle_tv)
        entities = [low, high]

    elif device_type == DEVICE_TYPE_TDS_METER:
        alarm = RfNumberEntity(
            client, device_info, f"tm_{host}_alarm",
            "Alarm TDS", CONCENTRATION_PARTS_PER_MILLION, 0, 500, 1,
            "tmSet", "alarm", scale=1,
        )

        def handle_tm(data: bytes) -> None:
            try:
                off = 0
                name_len = data[off]; off += 1
                sub = data[off:off+name_len].decode(); off += name_len
                dlen = struct.unpack_from(">I", data, off)[0]; off += 4
                p = data[off:off+dlen]
                if sub == 'settings':
                    pos = 0
                    _, pos = read_uint32(p, pos)
                    alarm_raw, pos = read_uint32(p, pos)
                    alarm._set_value(float(alarm_raw))
            except Exception as exc:
                _LOGGER.error("Error parsing tm numbers: %s", exc)

        client.register_callback('tmRefresh', handle_tm)
        entities = [alarm]

    elif device_type == DEVICE_TYPE_PH_METER:
        low = RfNumberEntity(
            client, device_info, f"ph_{host}_alarm_low",
            "Alarm pH Low", None, 0, 14, 0.01,
            "phSet", "alarmLow", scale=100,
        )
        high = RfNumberEntity(
            client, device_info, f"ph_{host}_alarm_high",
            "Alarm pH High", None, 0, 14, 0.01,
            "phSet", "alarmHigh", scale=100,
        )

        def handle_ph(data: bytes) -> None:
            try:
                off = 0
                name_len = data[off]; off += 1
                sub = data[off:off+name_len].decode(); off += name_len
                dlen = struct.unpack_from(">I", data, off)[0]; off += 4
                p = data[off:off+dlen]
                if sub == 'settings':
                    pos = 12
                    low_raw, pos = read_uint32(p, pos)
                    high_raw, pos = read_uint32(p, pos)
                    low._set_value(low_raw / 100)
                    high._set_value(high_raw / 100)
            except Exception as exc:
                _LOGGER.error("Error parsing ph numbers: %s", exc)

        client.register_callback('pmRefresh', handle_ph)
        entities = [low, high]

    if entities:
        async_add_entities(entities)


class RfNumberEntity(NumberEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX

    def __init__(self, client, device_info, unique_id, name, unit, min_val, max_val, step, set_cmd, set_key, scale=100):
        self._attr_unique_id = unique_id
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_native_min_value = min_val
        self._attr_native_max_value = max_val
        self._attr_native_step = step
        self._attr_native_value = None
        self._attr_available = False
        self._attr_device_info = device_info
        self._client = client
        self._set_cmd = set_cmd
        self._set_key = set_key
        self._scale = scale

    def _set_value(self, val: float) -> None:
        self._attr_native_value = val
        self._attr_available = True
        self.schedule_update_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        raw = int(value * self._scale)
        key_bytes = self._set_key.encode()
        payload = bytes([len(key_bytes)]) + key_bytes + struct.pack(">I", 4) + struct.pack(">I", raw)
        await self._client.send_command(self._set_cmd, payload)
        self._attr_native_value = value
        self.schedule_update_ha_state()
