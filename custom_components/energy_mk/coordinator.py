"""Data update coordinator for Energy MK."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import homeassistant.util.dt as dt_util

from .const import (
    API_URL,
    CONF_QUEUE_ID,
    CONF_SCAN_INTERVAL,
    CONF_WARNING_INTERVALS,
    DEFAULT_QUEUE_ID,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_WARNING_INTERVALS,
    DOMAIN,
    EVENT_OUTAGE_STARTED,
    EVENT_OUTAGE_WARNING,
    EVENT_POWER_RESTORED,
    SLOT_MINUTES,
)

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)

OUTAGE_TYPES = ("OFF", "PROBABLY_OFF")


def entry_option(entry: ConfigEntry, key: str, default):
    """Read a setting from options (UI-editable) with fallback to setup data."""
    if key in entry.options:
        return entry.options[key]
    return entry.data.get(key, default)


def floor_to_slot(utc: datetime) -> datetime:
    """Round a UTC datetime down to the nearest slot boundary."""
    floored = ((utc.hour * 60 + utc.minute) // SLOT_MINUTES) * SLOT_MINUTES
    return utc.replace(hour=floored // 60, minute=floored % 60, second=0, microsecond=0)


def next_slot_of_type(
    slot_map: dict[datetime, str],
    after_utc: datetime,
    types: tuple[str, ...],
) -> datetime | None:
    """Return the earliest future slot matching one of *types*, or None."""
    candidates = [dt for dt, t in slot_map.items() if dt > after_utc and t in types]
    return min(candidates) if candidates else None


def outage_block_end(slot_map: dict[datetime, str], outage_start: datetime) -> datetime:
    """Return the UTC datetime when the outage block beginning at *outage_start* ends."""
    end = outage_start + timedelta(minutes=SLOT_MINUTES)
    while slot_map.get(end) in OUTAGE_TYPES:
        end += timedelta(minutes=SLOT_MINUTES)
    return end


class EnergyMkCoordinator(DataUpdateCoordinator[dict[datetime, str]]):
    """Fetch outage schedule, build the slot map, and drive slot-boundary events.

    Besides polling the API, the coordinator re-evaluates state at every
    30-minute slot boundary, so the status/timestamp sensors and the
    outage_started/power_restored events are accurate to the slot edge
    instead of lagging behind the poll interval.
    """

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, session, entry: ConfigEntry) -> None:
        self._session = session
        self.queue_id: int = entry.data.get(CONF_QUEUE_ID, DEFAULT_QUEUE_ID)
        interval = entry_option(entry, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=interval),
        )
        self._previous_state: str | None = None
        self._boundary_unsub: CALLBACK_TYPE | None = None
        self._warning_unsubs: list[CALLBACK_TYPE] = []

    async def _async_update_data(self) -> dict[datetime, str]:
        try:
            async with self._session.get(API_URL, timeout=REQUEST_TIMEOUT) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except Exception as err:
            # The published schedule extends hours ahead; while cached slots
            # still cover the future, keep serving them instead of flipping
            # all entities to unavailable on a transient API failure.
            now_utc = dt_util.utcnow()
            if self.data and max(self.data) + timedelta(minutes=SLOT_MINUTES) > now_utc:
                _LOGGER.warning(
                    "energy_mk: API fetch failed (%s); serving cached schedule", err
                )
                return self.data
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
                if slot.get("outage_queue_id") != self.queue_id:
                    continue
                slot_type = slot.get("type", "OFF")
                slot_dt = from_utc + timedelta(
                    minutes=(slot["time_series_id"] - 1) * SLOT_MINUTES
                )
                existing = slot_map.get(slot_dt)
                if existing is None or existing == "PROBABLY_OFF":
                    slot_map[slot_dt] = slot_type
                elif existing != slot_type:
                    # Deliberate: OFF wins over a conflicting duplicate. Logged so
                    # that real-world schedule revisions (e.g. an outage cancelled
                    # to ON in a later schedule) become visible and the merge rule
                    # can be revisited with actual API evidence.
                    _LOGGER.debug(
                        "energy_mk: conflicting slot %s: keeping %s, ignoring %s",
                        slot_dt,
                        existing,
                        slot_type,
                    )
        return slot_map

    def current_state(self) -> str:
        """Return the power state of the current 30-min slot (ON when no data)."""
        slot_map = self.data or {}
        return slot_map.get(floor_to_slot(dt_util.utcnow()), "ON")

    @callback
    def async_handle_data_updated(self) -> None:
        """Re-evaluate state, fire events, and (re)arm timers.

        Runs after every successful refresh and at every slot boundary
        (registered as a coordinator listener in __init__.py).
        """
        self._async_evaluate_events()
        self._async_schedule_warnings()
        self._async_schedule_boundary_tick()

    @callback
    def _async_evaluate_events(self) -> None:
        new_state = self.current_state()
        if self._previous_state is not None and new_state != self._previous_state:
            if new_state in OUTAGE_TYPES:
                slot_map = self.data or {}
                restoration = outage_block_end(
                    slot_map, floor_to_slot(dt_util.utcnow())
                )
                self.hass.bus.async_fire(
                    EVENT_OUTAGE_STARTED,
                    {
                        "queue": self.queue_id,
                        "state": new_state,
                        "restoration_at": dt_util.as_local(restoration).isoformat(),
                    },
                )
            elif new_state == "ON":
                self.hass.bus.async_fire(
                    EVENT_POWER_RESTORED,
                    {"queue": self.queue_id},
                )
        self._previous_state = new_state

    @callback
    def _async_schedule_warnings(self) -> None:
        self._cancel_warnings()
        slot_map = self.data or {}
        next_outage = next_slot_of_type(slot_map, dt_util.utcnow(), OUTAGE_TYPES)
        if next_outage is None:
            return
        outage_type = slot_map[next_outage]
        outage_at_local = dt_util.as_local(next_outage).isoformat()
        now_utc = dt_util.utcnow()
        intervals = entry_option(
            self.config_entry, CONF_WARNING_INTERVALS, DEFAULT_WARNING_INTERVALS
        )
        for minutes in intervals:
            fire_at = next_outage - timedelta(minutes=minutes)
            if fire_at > now_utc:
                self._warning_unsubs.append(
                    async_track_point_in_time(
                        self.hass,
                        lambda _, m=minutes: self.hass.bus.async_fire(
                            EVENT_OUTAGE_WARNING,
                            {
                                "queue": self.queue_id,
                                "minutes_before": m,
                                "type": outage_type,
                                "outage_at": outage_at_local,
                            },
                        ),
                        fire_at,
                    )
                )

    @callback
    def _async_schedule_boundary_tick(self) -> None:
        if self._boundary_unsub is not None:
            self._boundary_unsub()
            self._boundary_unsub = None
        slot_map = self.data or {}
        now_utc = dt_util.utcnow()
        # Nothing changes at slot boundaries once the schedule is exhausted.
        if not slot_map or max(slot_map) + timedelta(minutes=SLOT_MINUTES) <= now_utc:
            return
        next_boundary = floor_to_slot(now_utc) + timedelta(minutes=SLOT_MINUTES)
        self._boundary_unsub = async_track_point_in_time(
            self.hass, self._async_handle_boundary, next_boundary
        )

    @callback
    def _async_handle_boundary(self, _now: datetime) -> None:
        self._boundary_unsub = None
        # Re-renders the entities and re-enters async_handle_data_updated
        # via the coordinator listeners.
        self.async_update_listeners()

    def _cancel_warnings(self) -> None:
        for unsub in self._warning_unsubs:
            unsub()
        self._warning_unsubs.clear()

    async def async_shutdown(self) -> None:
        """Cancel all timers when the config entry is unloaded."""
        self._cancel_warnings()
        if self._boundary_unsub is not None:
            self._boundary_unsub()
            self._boundary_unsub = None
        await super().async_shutdown()
