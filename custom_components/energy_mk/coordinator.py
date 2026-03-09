"""Data update coordinator for Energy MK."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    API_URL,
    CONF_QUEUE_ID,
    CONF_SCAN_INTERVAL,
    DEFAULT_QUEUE_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class EnergyMkCoordinator(DataUpdateCoordinator):
    """Fetch outage schedule and build slot map for a given queue."""

    def __init__(self, hass: HomeAssistant, session, entry: ConfigEntry) -> None:
        self._session = session
        self.config_entry = entry
        self.queue_id: int = entry.data.get(CONF_QUEUE_ID, DEFAULT_QUEUE_ID)
        interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=interval),
        )

    async def _async_update_data(self) -> dict[int, str]:
        try:
            async with self._session.get(API_URL, timeout=15) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except Exception as err:
            raise UpdateFailed(f"Error fetching energy_mk schedule: {err}") from err

        slot_map: dict[int, str] = {}
        schedules = data if isinstance(data, list) else data.get("schedules", [])
        for schedule in schedules:
            for slot in schedule.get("series", []):
                if slot.get("outage_queue_id") == self.queue_id:
                    slot_id = slot["time_series_id"]
                    slot_type = slot.get("type", "OFF")
                    existing = slot_map.get(slot_id)
                    if existing is None or existing == "PROBABLY_OFF":
                        slot_map[slot_id] = slot_type
        return slot_map
