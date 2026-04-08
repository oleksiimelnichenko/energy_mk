"""Mykolaiv region power outage schedule sensors."""
from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import homeassistant.util.dt as dt_util

from .const import (
    CONF_WARNING_INTERVALS,
    DEFAULT_WARNING_INTERVALS,
    DOMAIN,
    EVENT_OUTAGE_STARTED,
    EVENT_OUTAGE_WARNING,
    EVENT_POWER_RESTORED,
    QUEUE_NAMES,
    SLOT_MINUTES,
)
from .coordinator import EnergyMkCoordinator


def _floor_to_slot(utc: datetime) -> datetime:
    """Round a UTC datetime down to the nearest slot boundary."""
    slot_index = (utc.hour * 60 + utc.minute) // SLOT_MINUTES
    return utc.replace(minute=slot_index * SLOT_MINUTES, second=0, microsecond=0)


def _next_slot_of_type(
    slot_map: dict[datetime, str],
    after_utc: datetime,
    types: tuple[str, ...],
) -> datetime | None:
    """Return the earliest future slot matching one of *types*, or None."""
    candidates = [dt for dt, t in slot_map.items() if dt > after_utc and t in types]
    return min(candidates) if candidates else None


def _outage_block_end(slot_map: dict[datetime, str], outage_start: datetime) -> datetime:
    """Return the UTC datetime when the outage block beginning at *outage_start* ends."""
    end = outage_start + timedelta(minutes=SLOT_MINUTES)
    while slot_map.get(end) in ("OFF", "PROBABLY_OFF"):
        end += timedelta(minutes=SLOT_MINUTES)
    return end


def _dt_to_local_hm(utc: datetime) -> str:
    return dt_util.as_local(utc).strftime("%H:%M")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EnergyMkCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            EnergyMkStatusSensor(coordinator),
            EnergyMkNextOutageSensor(coordinator),
            EnergyMkNextRestorationSensor(coordinator),
            EnergyMkNextProbableOutageSensor(coordinator),
        ]
    )


class EnergyMkStatusSensor(CoordinatorEntity, SensorEntity):
    """Current 30-min slot power status."""

    _attr_icon = "mdi:transmission-tower"

    def __init__(self, coordinator: EnergyMkCoordinator) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        queue_name = QUEUE_NAMES.get(coordinator.queue_id, str(coordinator.queue_id))
        self._attr_name = f"Energy MK {queue_name} Status"
        self._attr_unique_id = f"{entry_id}_status"
        self._previous_state: str | None = None
        self._warning_unsubs: list = []

    def _cancel_warnings(self) -> None:
        for unsub in self._warning_unsubs:
            unsub()
        self._warning_unsubs.clear()

    def _schedule_warnings(self, outage_at: datetime) -> None:
        self._cancel_warnings()
        now = dt_util.now()
        intervals = self.coordinator.config_entry.data.get(
            CONF_WARNING_INTERVALS, DEFAULT_WARNING_INTERVALS
        )
        for minutes in intervals:
            fire_at = outage_at - timedelta(minutes=minutes)
            if fire_at > now:
                self._warning_unsubs.append(
                    async_track_point_in_time(
                        self.hass,
                        lambda _, m=minutes: self.hass.bus.async_fire(
                            EVENT_OUTAGE_WARNING,
                            {"queue": self.coordinator.queue_id, "minutes_before": m},
                        ),
                        fire_at,
                    )
                )

    def _handle_coordinator_update(self) -> None:
        new_state = self._compute_state()
        if self._previous_state is not None and new_state != self._previous_state:
            if new_state in ("OFF", "PROBABLY_OFF"):
                self.hass.bus.async_fire(
                    EVENT_OUTAGE_STARTED,
                    {"queue": self.coordinator.queue_id, "state": new_state},
                )
            elif new_state == "ON":
                self.hass.bus.async_fire(
                    EVENT_POWER_RESTORED,
                    {"queue": self.coordinator.queue_id},
                )
        self._previous_state = new_state

        slot_map: dict[datetime, str] = self.coordinator.data or {}
        now_utc = dt_util.utcnow()
        next_outage = _next_slot_of_type(slot_map, now_utc, ("OFF", "PROBABLY_OFF"))
        if next_outage is not None:
            self._schedule_warnings(dt_util.as_local(next_outage))
        else:
            self._cancel_warnings()

        super()._handle_coordinator_update()

    def _compute_state(self) -> str:
        slot_map: dict[datetime, str] = self.coordinator.data or {}
        current_dt = _floor_to_slot(dt_util.utcnow())
        return slot_map.get(current_dt, "ON")

    @property
    def native_value(self) -> str:
        return self._compute_state()

    @property
    def extra_state_attributes(self) -> dict:
        slot_map: dict[datetime, str] = self.coordinator.data or {}
        windows: list[dict] = []
        if slot_map:
            sorted_dts = sorted(slot_map.keys())
            window_start = window_type = prev_dt = None
            slot_dur = timedelta(minutes=SLOT_MINUTES)
            for slot_dt in sorted_dts:
                slot_type = slot_map[slot_dt]
                if window_start is None:
                    window_start, window_type, prev_dt = slot_dt, slot_type, slot_dt
                elif slot_dt == prev_dt + slot_dur and slot_type == window_type:
                    prev_dt = slot_dt
                else:
                    windows.append(
                        {
                            "start": _dt_to_local_hm(window_start),
                            "end": _dt_to_local_hm(prev_dt + slot_dur),
                            "type": window_type,
                        }
                    )
                    window_start, window_type, prev_dt = slot_dt, slot_type, slot_dt
            if window_start is not None:
                windows.append(
                    {
                        "start": _dt_to_local_hm(window_start),
                        "end": _dt_to_local_hm(prev_dt + slot_dur),
                        "type": window_type,
                    }
                )
        return {
            "schedule": windows,
            "queue": self.coordinator.queue_id,
        }


class EnergyMkNextOutageSensor(CoordinatorEntity, SensorEntity):
    """Start time of the next confirmed (OFF) outage slot."""

    _attr_icon = "mdi:clock-alert-outline"
    _attr_device_class = "timestamp"

    def __init__(self, coordinator: EnergyMkCoordinator) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        queue_name = QUEUE_NAMES.get(coordinator.queue_id, str(coordinator.queue_id))
        self._attr_name = f"Energy MK {queue_name} Next Outage"
        self._attr_unique_id = f"{entry_id}_next_outage"

    @property
    def native_value(self) -> datetime | None:
        slot_map: dict[datetime, str] = self.coordinator.data or {}
        return _next_slot_of_type(slot_map, dt_util.utcnow(), ("OFF",))


class EnergyMkNextRestorationSensor(CoordinatorEntity, SensorEntity):
    """Time when power returns after the next confirmed outage block."""

    _attr_icon = "mdi:clock-check-outline"
    _attr_device_class = "timestamp"

    def __init__(self, coordinator: EnergyMkCoordinator) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        queue_name = QUEUE_NAMES.get(coordinator.queue_id, str(coordinator.queue_id))
        self._attr_name = f"Energy MK {queue_name} Next Restoration"
        self._attr_unique_id = f"{entry_id}_next_restoration"

    @property
    def native_value(self) -> datetime | None:
        slot_map: dict[datetime, str] = self.coordinator.data or {}
        next_outage = _next_slot_of_type(slot_map, dt_util.utcnow(), ("OFF",))
        if next_outage is None:
            return None
        return _outage_block_end(slot_map, next_outage)


class EnergyMkNextProbableOutageSensor(CoordinatorEntity, SensorEntity):
    """Start time of the next possible (PROBABLY_OFF) outage slot."""

    _attr_icon = "mdi:clock-question-outline"
    _attr_device_class = "timestamp"

    def __init__(self, coordinator: EnergyMkCoordinator) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        queue_name = QUEUE_NAMES.get(coordinator.queue_id, str(coordinator.queue_id))
        self._attr_name = f"Energy MK {queue_name} Next Probable Outage"
        self._attr_unique_id = f"{entry_id}_next_probable_outage"

    @property
    def native_value(self) -> datetime | None:
        slot_map: dict[datetime, str] = self.coordinator.data or {}
        return _next_slot_of_type(slot_map, dt_util.utcnow(), ("PROBABLY_OFF",))
