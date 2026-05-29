"""Config flow for Reef Factory integration."""
from __future__ import annotations
import asyncio
import logging
from typing import Any
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.data_entry_flow import FlowResult
from .const import (
    CONF_DEVICE_TYPE,
    DEVICE_TYPES,
    DEVICE_TYPE_KH_KEEPER,
    DEVICE_TYPE_SALINITY_GUARDIAN,
    DEVICE_TYPE_THERMO_VIEW,
    DEVICE_TYPE_TDS_METER,
    DEVICE_TYPE_PH_METER,
    DEVICE_TYPE_SMART_ROLLER,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class ReefFactoryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Reef Factory."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            device_type = user_input[CONF_DEVICE_TYPE]
            name = user_input.get(CONF_NAME) or DEVICE_TYPES[device_type]
            await self.async_set_unique_id(f"{device_type}_{host}")
            self._abort_if_unique_id_configured()
            try:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, 80), timeout=5
                )
                writer.close()
                await writer.wait_closed()
                return self.async_create_entry(
                    title=f"{name} ({host})",
                    data={CONF_HOST: host, CONF_DEVICE_TYPE: device_type, CONF_NAME: name},
                )
            except Exception:
                errors["base"] = "cannot_connect"

        schema = vol.Schema({
            vol.Required(CONF_DEVICE_TYPE, default=DEVICE_TYPE_KH_KEEPER): vol.In(DEVICE_TYPES),
            vol.Required(CONF_HOST): str,
            vol.Optional(CONF_NAME): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
