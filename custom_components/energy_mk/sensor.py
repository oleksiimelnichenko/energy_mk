"""Mykolaiv region power outage schedule sensors."""
from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import homeassistant.util.dt as dt_util

from .const import DOMAIN, SLOT_MINUTES
from .coordinator import EnergyMkCoordinator


def _current_slot_id(local_now: datetime) -> int:
    return (local_now.hour * 60 + local_now.minute) // SLOT_MINUTES + 1


def _slot_to_time(slot_id: int) -> str:
    minutes = (slot_id - 1) * SLOT_MINUTES
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


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
        self._attr_name = "Energy MK Status"
        self._attr_unique_id = f"{entry_id}_status"

    @property
    def native_value(self) -> str:
        slot_map: dict[int, str] = self.coordinator.data or {}
        slot = _current_slot_id(dt_util.now())
        return slot_map.get(slot, "ON")

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
        return {"schedule": windows, "queue": self.coordinator.queue_id}


class EnergyMkNextOutageSensor(CoordinatorEntity, SensorEntity):
    """Start time of the next outage slot."""

    _attr_icon = "mdi:clock-alert-outline"
    _attr_device_class = "timestamp"

    def __init__(self, coordinator: EnergyMkCoordinator) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_name = "Energy MK Next Outage"
        self._attr_unique_id = f"{entry_id}_next_outage"

    @property
    def native_value(self) -> datetime | None:
        slot_map: dict[int, str] = self.coordinator.data or {}
        now = dt_util.now()
        current_slot = _current_slot_id(now)
        for offset in range(1, 49):
            slot_id = current_slot + offset
            if slot_map.get(slot_id) in ("OFF", "PROBABLY_OFF"):
                minutes = (slot_id - 1) * SLOT_MINUTES
                midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
                return midnight + timedelta(minutes=minutes)
        return None
