"""Config flow for Energy MK integration."""
from __future__ import annotations

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    API_URL,
    CONF_QUEUE_ID,
    CONF_SCAN_INTERVAL,
    CONF_WARNING_INTERVALS,
    DEFAULT_QUEUE_ID,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_WARNING_INTERVALS,
    DOMAIN,
    QUEUE_NAMES,
)
from .coordinator import entry_option

WARNING_INTERVAL_OPTIONS = [
    {"value": "15", "label": "15 min"},
    {"value": "30", "label": "30 min"},
    {"value": "60", "label": "1 hour"},
    {"value": "120", "label": "2 hours"},
]

SCAN_INTERVAL_FIELD = vol.All(vol.Coerce(int), vol.Range(min=5, max=1440))


def _warning_intervals_selector() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=WARNING_INTERVAL_OPTIONS,
            multiple=True,
            mode=SelectSelectorMode.LIST,
        )
    )


class EnergyMkConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Energy MK."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> EnergyMkOptionsFlow:
        return EnergyMkOptionsFlow()

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input[CONF_QUEUE_ID] = int(user_input[CONF_QUEUE_ID])
            user_input[CONF_WARNING_INTERVALS] = [
                int(v) for v in user_input.get(CONF_WARNING_INTERVALS, [])
            ]
            session = async_get_clientsession(self.hass)
            try:
                async with session.get(
                    API_URL, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    resp.raise_for_status()
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                queue_id = user_input[CONF_QUEUE_ID]
                await self.async_set_unique_id(f"energy_mk_{queue_id}")
                self._abort_if_unique_id_configured()
                queue_name = QUEUE_NAMES.get(queue_id, str(queue_id))
                return self.async_create_entry(
                    title=f"Energy MK {queue_name}",
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_QUEUE_ID, default=str(DEFAULT_QUEUE_ID)): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            {"value": str(qid), "label": name}
                            for qid, name in QUEUE_NAMES.items()
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                ): SCAN_INTERVAL_FIELD,
                vol.Required(
                    CONF_WARNING_INTERVALS,
                    default=[str(m) for m in DEFAULT_WARNING_INTERVALS],
                ): _warning_intervals_selector(),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )


class EnergyMkOptionsFlow(config_entries.OptionsFlow):
    """Edit scan interval and warning intervals without re-adding the entry."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            user_input[CONF_WARNING_INTERVALS] = [
                int(v) for v in user_input.get(CONF_WARNING_INTERVALS, [])
            ]
            return self.async_create_entry(title="", data=user_input)

        entry = self.config_entry
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=entry_option(entry, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): SCAN_INTERVAL_FIELD,
                vol.Required(
                    CONF_WARNING_INTERVALS,
                    default=[
                        str(m)
                        for m in entry_option(
                            entry, CONF_WARNING_INTERVALS, DEFAULT_WARNING_INTERVALS
                        )
                    ],
                ): _warning_intervals_selector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
