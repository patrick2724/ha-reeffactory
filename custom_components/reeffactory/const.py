"""Constants for the Reef Factory integration."""

DOMAIN = "reeffactory"

# Device types
DEVICE_TYPE_KH_KEEPER        = "kh_keeper"
DEVICE_TYPE_SALINITY_GUARDIAN= "salinity_guardian"
DEVICE_TYPE_THERMO_VIEW      = "thermo_view"
DEVICE_TYPE_TDS_METER        = "tds_meter"
DEVICE_TYPE_PH_METER         = "ph_meter"
DEVICE_TYPE_SMART_ROLLER     = "smart_roller"

DEVICE_TYPES = {
    DEVICE_TYPE_KH_KEEPER:         "KH Keeper Plus",
    DEVICE_TYPE_SALINITY_GUARDIAN:  "Salinity Guardian",
    DEVICE_TYPE_THERMO_VIEW:        "Thermo View",
    DEVICE_TYPE_TDS_METER:          "TDS Meter",
    DEVICE_TYPE_PH_METER:           "pH Meter",
    DEVICE_TYPE_SMART_ROLLER:       "Smart Roller",
}

WS_SUBPROTOCOL = "arduino"

WS_CONNECT_MSG = {
    DEVICE_TYPE_KH_KEEPER:         "khConnect",
    DEVICE_TYPE_SALINITY_GUARDIAN:  "sgConnect",
    DEVICE_TYPE_THERMO_VIEW:        "tvConnect",
    DEVICE_TYPE_TDS_METER:          "tmConnect",
    DEVICE_TYPE_PH_METER:           "pmConnect",
    DEVICE_TYPE_SMART_ROLLER:       "srConnect",
}

WS_REFRESH_CB = {
    DEVICE_TYPE_KH_KEEPER:         "khRefresh",
    DEVICE_TYPE_SALINITY_GUARDIAN:  "sgRefresh",
    DEVICE_TYPE_THERMO_VIEW:        "tvRefresh",
    DEVICE_TYPE_TDS_METER:          "tmRefresh",
    DEVICE_TYPE_PH_METER:           "pmRefresh",
    DEVICE_TYPE_SMART_ROLLER:       "srRefresh",
}

WS_SET_CMD = {
    DEVICE_TYPE_KH_KEEPER:         "khSet",
    DEVICE_TYPE_SALINITY_GUARDIAN:  "sgSet",
    DEVICE_TYPE_THERMO_VIEW:        "tvSet",
    DEVICE_TYPE_TDS_METER:          "tmSet",
    DEVICE_TYPE_PH_METER:           "pmSet",
    DEVICE_TYPE_SMART_ROLLER:       "srSet",
}

WS_COMMAND_CMD = {
    DEVICE_TYPE_KH_KEEPER:         "khCommand",
    DEVICE_TYPE_SALINITY_GUARDIAN:  "sgCommand",
    DEVICE_TYPE_THERMO_VIEW:        "tvCommand",
    DEVICE_TYPE_TDS_METER:          "tmCommand",
    DEVICE_TYPE_PH_METER:           "pmCommand",
    DEVICE_TYPE_SMART_ROLLER:       "srCommand",
}

WS_SOUND_CMD = {
    DEVICE_TYPE_SALINITY_GUARDIAN:  "sgSound",
    DEVICE_TYPE_THERMO_VIEW:        "tvSound",
    DEVICE_TYPE_TDS_METER:          "tmSound",
    DEVICE_TYPE_PH_METER:           "pmSound",
}

CONF_DEVICE_TYPE = "device_type"
DATA_CLIENT  = "client"
DATA_ENTITIES = "entities"
