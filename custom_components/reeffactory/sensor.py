"""Sensor platform for Reef Factory devices."""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    UnitOfTemperature,
    CONCENTRATION_PARTS_PER_MILLION,
    PERCENTAGE,
)
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
    DEVICE_TYPE_SMART_ROLLER,
    DOMAIN,
    WS_REFRESH_CB,
)
from .rf_websocket import RfWebSocketClient, read_uint8, read_uint16, read_uint32

_LOGGER = logging.getLogger(__name__)

# Unit constants not yet in HA
UNIT_DKH = "dKH"
UNIT_PPT = "ppt"
UNIT_MS_CM = "mS/cm"
UNIT_PPM = "ppm"
UNIT_ROLLER_PERCENT = "%"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors for a Reef Factory device."""
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

    entities: list[RfSensorEntity] = []

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
    elif device_type == DEVICE_TYPE_SMART_ROLLER:
        entities = _setup_smart_roller(client, device_info, host)

    if entities:
        async_add_entities(entities)


# ---------------------------------------------------------------------------
# Base entity
# ---------------------------------------------------------------------------

class RfSensorEntity(SensorEntity):
    """Base class for Reef Factory sensor entities."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        client: RfWebSocketClient,
        device_info: DeviceInfo,
        unique_id_suffix: str,
        name: str,
        unit: str | None,
        device_class: SensorDeviceClass | None,
        state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT,
    ) -> None:
        host = list(device_info["identifiers"])[0][1]
        self._attr_unique_id = f"{host}_{unique_id_suffix}"
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_device_info = device_info
        self._attr_available = False
        self._client = client

    def _set_value(self, value: Any) -> None:
        self._attr_native_value = value
        self._attr_available = True
        self.schedule_update_ha_state()

    def set_unavailable(self) -> None:
        self._attr_available = False
        self.schedule_update_ha_state()

    async def async_added_to_hass(self) -> None:
        self._client.register_disconnect_callback(self.set_unavailable)


# ---------------------------------------------------------------------------
# KH Keeper Plus
# ---------------------------------------------------------------------------

def _setup_kh_keeper(
    client: RfWebSocketClient, device_info: DeviceInfo, host: str
) -> list[RfSensorEntity]:
    """
    khRefresh binary layout (from JS reverse engineering):
    Frame type "khRefresh" with sub-type as first field.

    Sub-type "pH":    [ph_x100: uint32] -> pH = value/100
    Sub-type "settings": [kh_x100: uint32][ph_x100: uint32][alert: uint8]...
                         history array: [count: uint8] then N records of:
                         [kh: uint32][ph: uint32][year: uint16][month: uint8]
                         [day: uint8][hour: uint8][min: uint8][alert: uint8][status: uint8]
    """
    kh_sensor = RfSensorEntity(
        client, device_info, "kh_value", "KH Value", UNIT_DKH, None,
    )
    ph_sensor = RfSensorEntity(
        client, device_info, "ph_value", "pH Value", None, SensorDeviceClass.PH,
    )
    kh_diff_sensor = RfSensorEntity(
        client, device_info, "kh_difference", "KH Difference", UNIT_DKH, None,
    )

    def handle_kh_refresh(data: bytes) -> None:
        """Parse khRefresh binary frame."""
        try:
            # First byte: name length of sub-command
            off = 0
            name_len = data[off]; off += 1
            sub_name = data[off:off+name_len].decode("utf-8", errors="replace"); off += name_len
            # Next 4 bytes: data length
            data_len = struct.unpack_from(">I", data, off)[0]; off += 4
            payload = data[off:off+data_len]

            if sub_name == "pH":
                # Single pH reading pushed during measurement
                ph_raw, _ = read_uint32(payload, 0)
                ph_sensor._set_value(round(ph_raw / 100, 2))

            elif sub_name == "settings":
                p = 0
                # Parse settings block - contains last measurement + history
                # Interval (uint32)
                _, p = read_uint32(payload, p)
                # Reagent volume (uint32)
                _, p = read_uint32(payload, p)
                # Waste volume (uint32)
                _, p = read_uint32(payload, p)
                # Reagent capacity (uint32)
                _, p = read_uint32(payload, p)
                # Various settings bytes
                _, p = read_uint8(payload, p)  # return water
                _, p = read_uint8(payload, p)  # mixer speed
                _, p = read_uint8(payload, p)  # light
                adj_raw, p = read_uint32(payload, p)  # adjustment x10
                _, p = read_uint32(payload, p)  # remeasure threshold
                # Measurement interval slots (8 slots)
                for _ in range(8):
                    _, p = read_uint16(payload, p)
                # History count
                count, p = read_uint8(payload, p)
                if count > 0 and p + 14 <= len(payload):
                    kh_raw, p = read_uint32(payload, p)
                    ph_raw, p = read_uint32(payload, p)
                    # skip timestamp (6 bytes) + alert (1) + status (1)
                    p += 8
                    kh_val = round(kh_raw / 100, 2)
                    ph_val = round(ph_raw / 100, 2)
                    kh_sensor._set_value(kh_val)
                    ph_sensor._set_value(ph_val)
                    # compute diff from previous if more records
                    if count > 1 and p + 14 <= len(payload):
                        kh2_raw, _ = read_uint32(payload, p)
                        diff = round(kh_val - kh2_raw / 100, 2)
                        kh_diff_sensor._set_value(diff)

        except Exception as exc:
            _LOGGER.error("Error parsing khRefresh: %s", exc)

    client.register_callback("khRefresh", handle_kh_refresh)

    return [kh_sensor, ph_sensor, kh_diff_sensor]


# ---------------------------------------------------------------------------
# Salinity Guardian
# ---------------------------------------------------------------------------

def _setup_salinity_guardian(
    client: RfWebSocketClient, device_info: DeviceInfo, host: str
) -> list[RfSensorEntity]:
    """
    sgRefresh binary layout (from JS reverse engineering):
    Sub-type "settings":
      settings block:
        Various config uint32/uint8 values
        salinity: uint32 (in units depending on mode, e.g. ppt x100)
        temperature: uint32 (Celsius x100)
        alarmLow: uint32
        alarmHigh: uint32
        unit: uint8 (0=ppt, 1=kg/m3, 2=mS/cm)
        soundOn: uint8
        probeCalib: int32
        tempCalib: int32
    """
    sal_sensor = RfSensorEntity(
        client, device_info, "salinity", "Salinity", UNIT_PPT, None,
    )
    temp_sensor = RfSensorEntity(
        client, device_info, "temperature", "Temperature",
        UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE,
    )

    def handle_sg_refresh(data: bytes) -> None:
        try:
            off = 0
            name_len = data[off]; off += 1
            sub_name = data[off:off+name_len].decode("utf-8", errors="replace"); off += name_len
            data_len = struct.unpack_from(">I", data, off)[0]; off += 4
            payload = data[off:off+data_len]

            if sub_name == "settings":
                p = 0
                # Skip config header (interval uint32 + 4 alarm uint32s)
                p += 4 * 5
                # salinity raw (x100)
                sal_raw, p = read_uint32(payload, p)
                # temperature raw (x100)
                temp_raw, p = read_uint32(payload, p)
                sal_sensor._set_value(round(sal_raw / 100, 1))
                temp_sensor._set_value(round(temp_raw / 100, 1))

        except Exception as exc:
            _LOGGER.error("Error parsing sgRefresh: %s", exc)

    client.register_callback("sgRefresh", handle_sg_refresh)
    return [sal_sensor, temp_sensor]


# ---------------------------------------------------------------------------
# Thermo View
# ---------------------------------------------------------------------------

def _setup_thermo_view(
    client: RfWebSocketClient, device_info: DeviceInfo, host: str
) -> list[RfSensorEntity]:
    """
    tvRefresh binary layout (from JS reverse engineering):
    Sub-type "settings":
      temperature: uint32 (Celsius x100)
      alarmTemp1: uint32 (low threshold x100)
      alarmTemp2: uint32 (high threshold x100)
      unit: uint8 (0=C, 1=F)
      soundOn: uint8
    Special case: if bytes are all 0xFF -> sensor error (display "---")
    """
    temp_sensor = RfSensorEntity(
        client, device_info, "temperature", "Temperature",
        UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE,
    )

    def handle_tv_refresh(data: bytes) -> None:
        try:
            off = 0
            name_len = data[off]; off += 1
            sub_name = data[off:off+name_len].decode("utf-8", errors="replace"); off += name_len
            data_len = struct.unpack_from(">I", data, off)[0]; off += 4
            payload = data[off:off+data_len]

            if sub_name == "settings":
                p = 0
                # Check for sensor error (all 0xFF)
                if all(b == 0xFF for b in payload[p:p+4]):
                    temp_sensor._attr_available = False
                    temp_sensor.schedule_update_ha_state()
                    return
                temp_raw, p = read_uint32(payload, p)
                temp_sensor._set_value(round(temp_raw / 100, 1))

        except Exception as exc:
            _LOGGER.error("Error parsing tvRefresh: %s", exc)

    client.register_callback("tvRefresh", handle_tv_refresh)
    return [temp_sensor]


# ---------------------------------------------------------------------------
# TDS Meter
# ---------------------------------------------------------------------------

def _setup_tds_meter(
    client: RfWebSocketClient, device_info: DeviceInfo, host: str
) -> list[RfSensorEntity]:
    """
    tmRefresh binary layout (verified from JS reverse engineering of RFTM01):
    Sub-type "settings":
      Byte layout (from handler function v()):
        - 4 bytes: TDS value (uint32, direct ppm, no scaling)
        - 4 bytes: alarm threshold (uint32 ppm)
        - 1 byte:  sound flags (bit 0-3 = off, bit 4-15 = on)
      Special: if first 4 bytes all 0xFF → sensor error

    WS commands:
      tmConnect / join   → subscribe
      tmSet / calibration → calibrate
      tmSet / adjust     → set calibration offset
      tmSound / on|off   → sound toggle
    """
    tds_sensor = RfSensorEntity(
        client, device_info, "tds_value", "TDS", CONCENTRATION_PARTS_PER_MILLION, None,
    )

    def handle_tds_refresh(data: bytes) -> None:
        try:
            off = 0
            name_len = data[off]; off += 1
            sub_name = data[off:off+name_len].decode("utf-8", errors="replace"); off += name_len
            data_len = struct.unpack_from(">I", data, off)[0]; off += 4
            payload = data[off:off+data_len]

            if sub_name == "settings":
                p = 0
                # Check for sensor error (all 0xFF)
                if all(b == 0xFF for b in payload[p:p+4]):
                    tds_sensor._attr_available = False
                    tds_sensor.schedule_update_ha_state()
                    return
                tds_raw, p = read_uint32(payload, p)
                tds_sensor._set_value(tds_raw)  # direct ppm, no scaling

        except Exception as exc:
            _LOGGER.error("Error parsing tmRefresh: %s", exc)

    client.register_callback("tmRefresh", handle_tds_refresh)
    return [tds_sensor]


# ---------------------------------------------------------------------------
# pH Meter
# ---------------------------------------------------------------------------

def _setup_ph_meter(
    client: RfWebSocketClient, device_info: DeviceInfo, host: str
) -> list[RfSensorEntity]:
    """
    pmRefresh binary layout (verified from JS reverse engineering of RFPM01):
    Sub-type "settings":
      p = 0
        pH value:     uint32 / 100  → e.g. 815 → 8.15
        alarmPh1:     uint32 / 100  → low alarm
        alarmPh2:     uint32 / 100  → high alarm
        sound flags:  uint8
      Sub-type "alert":
        i[0]: alert status byte

    WS commands (from JS .send() calls):
      pmConnect / join           → subscribe
      pmSet / calibrationStart   → start calibration
      pmSet / calibrationLow     → confirm pH 4 calibration
      pmSet / calibrationHigh    → confirm pH 7 calibration
      pmSound / on|off           → sound toggle
      pmSet / adjust             → set pH adjustment offset
    """
    ph_sensor = RfSensorEntity(
        client, device_info, "ph_value", "pH", None, SensorDeviceClass.PH,
    )
    adj_sensor = RfSensorEntity(
        client, device_info, "ph_adjustment", "pH Adjustment", None, None,
        state_class=None,
    )

    def handle_pm_refresh(data: bytes) -> None:
        try:
            off = 0
            name_len = data[off]; off += 1
            sub_name = data[off:off+name_len].decode("utf-8", errors="replace"); off += name_len
            data_len = struct.unpack_from(">I", data, off)[0]; off += 4
            payload = data[off:off+data_len]

            if sub_name == "settings":
                p = 0
                ph_raw, p = read_uint32(payload, p)    # pH x100
                _, p = read_uint32(payload, p)          # alarmPh1 (handled in binary_sensor)
                _, p = read_uint32(payload, p)          # alarmPh2
                # adjustment offset (signed int32)
                if p + 4 <= len(payload):
                    adj_raw = struct.unpack_from(">i", payload, p)[0]; p += 4
                    adj_sensor._set_value(round(adj_raw / 100, 2))
                ph_sensor._set_value(round(ph_raw / 100, 2))

        except Exception as exc:
            _LOGGER.error("Error parsing pmRefresh: %s", exc)

    client.register_callback("pmRefresh", handle_pm_refresh)
    return [ph_sensor, adj_sensor]


# ---------------------------------------------------------------------------
# Smart Roller
# ---------------------------------------------------------------------------

def _setup_smart_roller(
    client: RfWebSocketClient, device_info: DeviceInfo, host: str
) -> list[RfSensorEntity]:
    """
    srRefresh - Smart Roller fleece filter.
    Based on ha-reef-factory-smartroller repo protocol.
    """
    waste_sensor = RfSensorEntity(
        client, device_info, "waste_level", "Waste Level", UNIT_ROLLER_PERCENT, None,
    )

    def handle_sr_refresh(data: bytes) -> None:
        try:
            off = 0
            name_len = data[off]; off += 1
            sub_name = data[off:off+name_len].decode("utf-8", errors="replace"); off += name_len
            data_len = struct.unpack_from(">I", data, off)[0]; off += 4
            payload = data[off:off+data_len]

            if sub_name == "settings":
                p = 0
                waste_raw, p = read_uint32(payload, p)
                waste_sensor._set_value(waste_raw)

        except Exception as exc:
            _LOGGER.error("Error parsing srRefresh: %s", exc)

    client.register_callback("srRefresh", handle_sr_refresh)
    return [waste_sensor]
