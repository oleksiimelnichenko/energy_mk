"""Config flow for Energy MK integration."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_URL,
    CONF_QUEUE_ID,
    CONF_SCAN_INTERVAL,
    DEFAULT_QUEUE_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)


class EnergyMkConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Energy MK."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            try:
                async with session.get(API_URL, timeout=10) as resp:
                    resp.raise_for_status()
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                queue_id = user_input[CONF_QUEUE_ID]
                await self.async_set_unique_id(f"energy_mk_{queue_id}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Energy MK (queue {queue_id})",
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_QUEUE_ID, default=DEFAULT_QUEUE_ID): int,
                vol.Required(
                    CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                ): vol.All(int, vol.Range(min=5, max=1440)),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )
