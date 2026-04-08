"""Data update coordinator for Energy MK."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

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
    SLOT_MINUTES,
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

    async def _async_update_data(self) -> dict[datetime, str]:
        try:
            async with self._session.get(API_URL, timeout=15) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except Exception as err:
            raise UpdateFailed(f"Error fetching energy_mk schedule: {err}") from err

        # Keyed by absolute UTC slot start time to avoid collisions across schedules
        # that share the same 1-48 time_series_id numbering.
        slot_map: dict[datetime, str] = {}
        schedules = data if isinstance(data, list) else data.get("schedules", [])
        for schedule in schedules:
            from_str = schedule.get("from", "")
            try:
                from_utc = datetime.fromisoformat(from_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                _LOGGER.warning("energy_mk: cannot parse schedule from=%r", from_str)
                continue
            for slot in schedule.get("series", []):
                if slot.get("outage_queue_id") == self.queue_id:
                    slot_id = slot["time_series_id"]
                    slot_type = slot.get("type", "OFF")
                    slot_dt = from_utc + timedelta(minutes=(slot_id - 1) * SLOT_MINUTES)
                    existing = slot_map.get(slot_dt)
                    if existing is None or existing == "PROBABLY_OFF":
                        slot_map[slot_dt] = slot_type
        return slot_map
