"""Sensor platform for Reef Factory devices."""
from __future__ import annotations
import logging, struct
from typing import Any
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, UnitOfTemperature, CONCENTRATION_PARTS_PER_MILLION
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import CONF_DEVICE_TYPE, DATA_CLIENT, DEVICE_TYPES, DEVICE_TYPE_KH_KEEPER, DEVICE_TYPE_SALINITY_GUARDIAN, DEVICE_TYPE_THERMO_VIEW, DEVICE_TYPE_TDS_METER, DEVICE_TYPE_PH_METER, DEVICE_TYPE_SMART_ROLLER, DOMAIN, WS_REFRESH_CB
from .rf_websocket import RfWebSocketClient, read_uint8, read_uint16, read_uint32
_LOGGER = logging.getLogger(__name__)
UNIT_DKH = "dKH"
UNIT_PPT = "ppt"
UNIT_ROLLER_PERCENT = "%"

async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]; client = data[DATA_CLIENT]
    dt = entry.data[CONF_DEVICE_TYPE]; host = entry.data[CONF_HOST]; name = entry.data[CONF_NAME]
    di = DeviceInfo(identifiers={(DOMAIN, f"{dt}_{host}")}, name=name, manufacturer="Reef Factory", model=DEVICE_TYPES[dt], configuration_url=f"http://{host}")
    fn = {DEVICE_TYPE_KH_KEEPER: _setup_kh_keeper, DEVICE_TYPE_SALINITY_GUARDIAN: _setup_salinity_guardian, DEVICE_TYPE_THERMO_VIEW: _setup_thermo_view, DEVICE_TYPE_TDS_METER: _setup_tds_meter, DEVICE_TYPE_PH_METER: _setup_ph_meter, DEVICE_TYPE_SMART_ROLLER: _setup_smart_roller}
    if dt in fn: async_add_entities(fn[dt](client, di, host))

class RfSensorEntity(SensorEntity):
    _attr_should_poll = False; _attr_has_entity_name = True
    def __init__(self, c, di, uid, name, unit, dcls, scls=SensorStateClass.MEASUREMENT):
        host = list(di["identifiers"])[0][1]
        self._attr_unique_id = f"{host}_{uid}"; self._attr_name = name
        self._attr_native_unit_of_measurement = unit; self._attr_device_class = dcls
        self._attr_state_class = scls; self._attr_device_info = di
        self._attr_available = False; self._client = c
    def _set_value(self, v): self._attr_native_value = v; self._attr_available = True; self.schedule_update_ha_state()
    def set_unavailable(self): self._attr_available = False; self.schedule_update_ha_state()
    async def async_added_to_hass(self): self._client.register_disconnect_callback(self.set_unavailable)

def _setup_kh_keeper(c, di, host):
    kh = RfSensorEntity(c, di, "kh_value", "KH Value", UNIT_DKH, None)
    ph = RfSensorEntity(c, di, "ph_value", "pH Value", None, SensorDeviceClass.PH)
    diff = RfSensorEntity(c, di, "kh_diff", "KH Difference", UNIT_DKH, None)
    def handle(data):
        try:
            off = 0; nl = data[off]; off += 1; sub = data[off:off+nl].decode(); off += nl
            dl = struct.unpack_from(">I", data, off)[0]; off += 4; p = data[off:off+dl]
            if sub == "pH":
                r, _ = read_uint32(p, 0); ph._set_value(round(r/100, 2))
            elif sub == "settings":
                pos = 0
                for _ in range(4): _, pos = read_uint32(p, pos)
                for _ in range(3): _, pos = read_uint8(p, pos)
                _, pos = read_uint32(p, pos); _, pos = read_uint32(p, pos)
                for _ in range(8): _, pos = read_uint16(p, pos)
                cnt, pos = read_uint8(p, pos)
                if cnt > 0 and pos + 14 <= len(p):
                    kr, pos = read_uint32(p, pos); pr, pos = read_uint32(p, pos); pos += 8
                    kv = round(kr/100, 2); pv = round(pr/100, 2); kh._set_value(kv); ph._set_value(pv)
                    if cnt > 1 and pos + 4 <= len(p): k2, _ = read_uint32(p, pos); diff._set_value(round(kv - k2/100, 2))
        except Exception as e: _LOGGER.error("khRefresh: %s", e)
    c.register_callback("khRefresh", handle); return [kh, ph, diff]

def _setup_salinity_guardian(c, di, host):
    sal = RfSensorEntity(c, di, "salinity", "Salinity", UNIT_PPT, None)
    temp = RfSensorEntity(c, di, "temperature", "Temperature", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE)
    def handle(d):
        try:
            off=0; nl=d[off]; off+=1; sub=d[off:off+nl].decode(); off+=nl; dl=struct.unpack_from(">I",d,off)[0]; off+=4; p=d[off:off+dl]
            if sub=="settings": pos=4*5; sr,pos=read_uint32(p,pos); tr,pos=read_uint32(p,pos); sal._set_value(round(sr/100,1)); temp._set_value(round(tr/100,1))
        except Exception as e: _LOGGER.error("sgRefresh: %s", e)
    c.register_callback("sgRefresh", handle); return [sal, temp]

def _setup_thermo_view(c, di, host):
    t = RfSensorEntity(c, di, "temperature", "Temperature", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE)
    def handle(d):
        try:
            off=0; nl=d[off]; off+=1; sub=d[off:off+nl].decode(); off+=nl; dl=struct.unpack_from(">I",d,off)[0]; off+=4; p=d[off:off+dl]
            if sub=="settings":
                if all(b==0xFF for b in p[:4]): t._attr_available=False; t.schedule_update_ha_state(); return
                r,_=read_uint32(p,0); t._set_value(round(r/100,1))
        except Exception as e: _LOGGER.error("tvRefresh: %s", e)
    c.register_callback("tvRefresh", handle); return [t]

def _setup_tds_meter(c, di, host):
    t = RfSensorEntity(c, di, "tds_value", "TDS", CONCENTRATION_PARTS_PER_MILLION, None)
    def handle(d):
        try:
            off=0; nl=d[off]; off+=1; sub=d[off:off+nl].decode(); off+=nl; dl=struct.unpack_from(">I",d,off)[0]; off+=4; p=d[off:off+dl]
            if sub=="settings":
                if all(b==0xFF for b in p[:4]): t._attr_available=False; t.schedule_update_ha_state(); return
                r,_=read_uint32(p,0); t._set_value(r)
        except Exception as e: _LOGGER.error("tmRefresh: %s", e)
    c.register_callback("tmRefresh", handle); return [t]

def _setup_ph_meter(c, di, host):
    ph = RfSensorEntity(c, di, "ph_value", "pH", None, SensorDeviceClass.PH)
    adj = RfSensorEntity(c, di, "ph_adj", "pH Adjustment", None, None, scls=None)
    def handle(d):
        try:
            off=0; nl=d[off]; off+=1; sub=d[off:off+nl].decode(); off+=nl; dl=struct.unpack_from(">I",d,off)[0]; off+=4; p=d[off:off+dl]
            if sub=="settings":
                pos=0; phr,pos=read_uint32(p,pos); _,pos=read_uint32(p,pos); _,pos=read_uint32(p,pos)
                if pos+4<=len(p): ar=struct.unpack_from(">i",p,pos)[0]; adj._set_value(round(ar/100,2))
                ph._set_value(round(phr/100,2))
        except Exception as e: _LOGGER.error("pmRefresh: %s", e)
    c.register_callback("pmRefresh", handle); return [ph, adj]

def _setup_smart_roller(c, di, host):
    w = RfSensorEntity(c, di, "waste_level", "Waste Level", UNIT_ROLLER_PERCENT, None)
    def handle(d):
        try:
            off=0; nl=d[off]; off+=1; sub=d[off:off+nl].decode(); off+=nl; dl=struct.unpack_from(">I",d,off)[0]; off+=4; p=d[off:off+dl]
            if sub=="settings": r,_=read_uint32(p,0); w._set_value(r)
        except Exception as e: _LOGGER.error("srRefresh: %s", e)
    c.register_callback("srRefresh", handle); return [w]
