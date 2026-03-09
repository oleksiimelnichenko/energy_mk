"""Mykolaiv region power outage schedule sensors."""
from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import homeassistant.util.dt as dt_util

from .const import DOMAIN, EVENT_OUTAGE_STARTED, EVENT_POWER_RESTORED, QUEUE_NAMES, SLOT_MINUTES
from .coordinator import EnergyMkCoordinator


def _current_slot_id(local_now: datetime) -> int:
    return (local_now.hour * 60 + local_now.minute) // SLOT_MINUTES + 1


def _slot_to_time(slot_id: int) -> str:
    minutes = (slot_id - 1) * SLOT_MINUTES
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _next_outage_slot(slot_map: dict[int, str], current_slot: int) -> int | None:
    for offset in range(1, 49):
        slot_id = current_slot + offset
        if slot_map.get(slot_id) in ("OFF", "PROBABLY_OFF"):
            return slot_id
    return None


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
        super()._handle_coordinator_update()

    def _compute_state(self) -> str:
        slot_map: dict[int, str] = self.coordinator.data or {}
        return slot_map.get(_current_slot_id(dt_util.now()), "ON")

    @property
    def native_value(self) -> str:
        return self._compute_state()

    @property
    def extra_state_attributes(self) -> dict:
        slot_map: dict[int, str] = self.coordinator.data or {}
        windows: list[dict] = []
        if slot_map:
            sorted_slots = sorted(slot_map.keys())
            window_start = window_type = prev_slot = None
            for slot_id in sorted_slots:
                slot_type = slot_map[slot_id]
                if window_start is None:
                    window_start, window_type, prev_slot = slot_id, slot_type, slot_id
                elif slot_id == prev_slot + 1 and slot_type == window_type:
                    prev_slot = slot_id
                else:
                    windows.append(
                        {
                            "start": _slot_to_time(window_start),
                            "end": _slot_to_time(prev_slot + 1),
                            "type": window_type,
                        }
                    )
                    window_start, window_type, prev_slot = slot_id, slot_type, slot_id
            if window_start is not None:
                windows.append(
                    {
                        "start": _slot_to_time(window_start),
                        "end": _slot_to_time(prev_slot + 1),
                        "type": window_type,
                    }
                )
        next_slot = _next_outage_slot(slot_map, _current_slot_id(dt_util.now()))
        next_outage_time = _slot_to_time(next_slot) if next_slot is not None else None
        return {
            "schedule": windows,
            "queue": self.coordinator.queue_id,
            "next_outage_time": next_outage_time,
        }


class EnergyMkNextOutageSensor(CoordinatorEntity, SensorEntity):
    """Start time of the next outage slot."""

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
        slot_map: dict[int, str] = self.coordinator.data or {}
        now = dt_util.now()
        slot_id = _next_outage_slot(slot_map, _current_slot_id(now))
        if slot_id is None:
            return None
        minutes = (slot_id - 1) * SLOT_MINUTES
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return midnight + timedelta(minutes=minutes)
