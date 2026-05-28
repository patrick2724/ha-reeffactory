"""Binary sensor platform for Reef Factory devices."""

from __future__ import annotations

import logging
import struct

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_DEVICE_TYPE,
    DATA_CLIENT,
    DEVICE_TYPES,
    DEVICE_TYPE_KH_KEEPER,
    DEVICE_TYPE_SALINITY_GUARDIAN,
    DEVICE_TYPE_THERMO_VIEW,
    DEVICE_TYPE_TDS_METER,
    DEVICE_TYPE_PH_METER,
    DOMAIN,
)
from .rf_websocket import RfWebSocketClient, read_uint8, read_uint32

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

    entities: list[RfBinarySensorEntity] = []

    if device_type == DEVICE_TYPE_KH_KEEPER:
        entities = _setup_kh_keeper(client, device_info, host)
    elif device_type == DEVICE_TYPE_SALINITY_GUARDIAN:
        entities = _setup_salinity_guardian(client, device_info, host)
    elif device_type == DEVICE_TYPE_THERMO_VIEW:
        entities = _setup_thermo_view(client, device_info, host)
    elif device_type == DEVICE_TYPE_TDS_METER:
        entities = _setup_tds_meter(client, device_info, host)
    elif device_type == DEVICE_TYPE_PH_METER:
        entities = _setup_ph_meter(client, device_info, host)

    if entities:
        async_add_entities(entities)


class RfBinarySensorEntity(BinarySensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, client, device_info, unique_id_suffix, name, device_class=None):
        host = list(device_info["identifiers"])[0][1]
        self._attr_unique_id = f"{host}_{unique_id_suffix}"
        self._attr_name = name
        self._attr_device_class = device_class
        self._attr_device_info = device_info
        self._attr_available = False
        self._attr_is_on = False
        self._client = client

    def _set_state(self, is_on: bool) -> None:
        self._attr_is_on = is_on
        self._attr_available = True
        self.schedule_update_ha_state()

    def set_unavailable(self) -> None:
        self._attr_available = False
        self.schedule_update_ha_state()

    async def async_added_to_hass(self) -> None:
        self._client.register_disconnect_callback(self.set_unavailable)


def _setup_kh_keeper(client, device_info, host):
    measuring = RfBinarySensorEntity(
        client, device_info, "kh_measuring", "Measuring", BinarySensorDeviceClass.RUNNING
    )
    alert = RfBinarySensorEntity(
        client, device_info, "kh_alert", "KH Alert", BinarySensorDeviceClass.PROBLEM
    )

    def handle(data: bytes) -> None:
        try:
            off = 0
            name_len = data[off]; off += 1
            sub_name = data[off:off+name_len].decode("utf-8", errors="replace"); off += name_len
            data_len = struct.unpack_from(">I", data, off)[0]; off += 4
            payload = data[off:off+data_len]
            if sub_name == "settings":
                # alert is at payload[8] after two uint32s
                if len(payload) > 8:
                    p = 0
                    _, p = read_uint32(payload, p)  # kh
                    _, p = read_uint32(payload, p)  # ph
                    alert_val, _ = read_uint8(payload, p)
                    alert._set_state(alert_val != 0)
        except Exception as exc:
            _LOGGER.error("Error parsing kh binary sensor: %s", exc)

    client.register_callback("khRefresh", handle)
    return [measuring, alert]


def _setup_salinity_guardian(client, device_info, host):
    alarm_low = RfBinarySensorEntity(
        client, device_info, "sg_alarm_low", "Salinity Alarm Low", BinarySensorDeviceClass.PROBLEM
    )
    alarm_high = RfBinarySensorEntity(
        client, device_info, "sg_alarm_high", "Salinity Alarm High", BinarySensorDeviceClass.PROBLEM
    )

    def handle(data: bytes) -> None:
        try:
            off = 0
            name_len = data[off]; off += 1
            sub_name = data[off:off+name_len].decode("utf-8", errors="replace"); off += name_len
            data_len = struct.unpack_from(">I", data, off)[0]; off += 4
            payload = data[off:off+data_len]
            if sub_name == "settings":
                p = 4 * 5  # skip config
                sal_raw, p = read_uint32(payload, p)
                _, p = read_uint32(payload, p)   # temp
                alarm_low_val, p = read_uint32(payload, p)
                alarm_high_val, p = read_uint32(payload, p)
                sal = sal_raw / 100
                alarm_low._set_state(sal < alarm_low_val / 100)
                alarm_high._set_state(sal > alarm_high_val / 100)
        except Exception as exc:
            _LOGGER.error("Error parsing sg binary sensor: %s", exc)

    client.register_callback("sgRefresh", handle)
    return [alarm_low, alarm_high]


def _setup_thermo_view(client, device_info, host):
    alarm_low = RfBinarySensorEntity(
        client, device_info, "tv_alarm_low", "Temp Alarm Low", BinarySensorDeviceClass.COLD
    )
    alarm_high = RfBinarySensorEntity(
        client, device_info, "tv_alarm_high", "Temp Alarm High", BinarySensorDeviceClass.HEAT
    )

    def handle(data: bytes) -> None:
        try:
            off = 0
            name_len = data[off]; off += 1
            sub_name = data[off:off+name_len].decode("utf-8", errors="replace"); off += name_len
            data_len = struct.unpack_from(">I", data, off)[0]; off += 4
            payload = data[off:off+data_len]
            if sub_name == "settings":
                if all(b == 0xFF for b in payload[:4]):
                    return
                p = 0
                temp_raw, p = read_uint32(payload, p)
                alarm1_raw, p = read_uint32(payload, p)
                alarm2_raw, p = read_uint32(payload, p)
                temp = temp_raw / 100
                alarm_low._set_state(temp < alarm1_raw / 100)
                alarm_high._set_state(temp > alarm2_raw / 100)
        except Exception as exc:
            _LOGGER.error("Error parsing tv binary sensor: %s", exc)

    client.register_callback("tvRefresh", handle)
    return [alarm_low, alarm_high]


def _setup_tds_meter(client, device_info, host):
    """TDS Meter alarm — triggers when TDS exceeds the alarm threshold."""
    alarm = RfBinarySensorEntity(
        client, device_info, "tm_alarm", "TDS Alarm", BinarySensorDeviceClass.PROBLEM
    )

    def handle(data: bytes) -> None:
        try:
            off = 0
            name_len = data[off]; off += 1
            sub_name = data[off:off+name_len].decode("utf-8", errors="replace"); off += name_len
            data_len = struct.unpack_from(">I", data, off)[0]; off += 4
            payload = data[off:off+data_len]
            if sub_name == "settings":
                p = 0
                if all(b == 0xFF for b in payload[p:p+4]):
                    return
                tds_raw, p = read_uint32(payload, p)     # TDS ppm
                alarm_raw, p = read_uint32(payload, p)   # alarm threshold ppm
                alarm._set_state(tds_raw >= alarm_raw)
            elif sub_name == "alert":
                if len(payload) > 0:
                    alarm._set_state(payload[0] != 0)
        except Exception as exc:
            _LOGGER.error("Error parsing tmRefresh binary sensor: %s", exc)

    client.register_callback("tmRefresh", handle)
    return [alarm]


def _setup_ph_meter(client, device_info, host):
    alarm_low = RfBinarySensorEntity(
        client, device_info, "ph_alarm_low", "pH Alarm Low", BinarySensorDeviceClass.PROBLEM
    )
    alarm_high = RfBinarySensorEntity(
        client, device_info, "ph_alarm_high", "pH Alarm High", BinarySensorDeviceClass.PROBLEM
    )

    def handle(data: bytes) -> None:
        try:
            off = 0
            name_len = data[off]; off += 1
            sub_name = data[off:off+name_len].decode("utf-8", errors="replace"); off += name_len
            data_len = struct.unpack_from(">I", data, off)[0]; off += 4
            payload = data[off:off+data_len]
            if sub_name == "settings":
                p = 0
                ph_raw, p = read_uint32(payload, p)    # pH x100
                alarm_low_val, p = read_uint32(payload, p)   # alarmPh1 x100
                alarm_high_val, p = read_uint32(payload, p)  # alarmPh2 x100
                ph = ph_raw / 100
                alarm_low._set_state(ph < alarm_low_val / 100)
                alarm_high._set_state(ph > alarm_high_val / 100)
            elif sub_name == "alert":
                # alert byte: 0=ok, 1=high
                if len(payload) > 0:
                    alarm_high._set_state(payload[0] != 0)
        except Exception as exc:
            _LOGGER.error("Error parsing pmRefresh binary sensor: %s", exc)

    client.register_callback("pmRefresh", handle)  # RFPM01 uses "pm" prefix
    return [alarm_low, alarm_high]
