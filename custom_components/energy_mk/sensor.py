"""Mykolaiv region power outage schedule sensors."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import ClassVar

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import homeassistant.util.dt as dt_util

from . import EnergyMkConfigEntry
from .const import DOMAIN, QUEUE_NAMES, SLOT_MINUTES
from .coordinator import EnergyMkCoordinator, next_slot_of_type, outage_block_end


def _dt_to_local_hm(utc: datetime) -> str:
    return dt_util.as_local(utc).strftime("%H:%M")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EnergyMkConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            EnergyMkStatusSensor(coordinator),
            EnergyMkNextOutageSensor(coordinator),
            EnergyMkNextRestorationSensor(coordinator),
            EnergyMkNextProbableOutageSensor(coordinator),
        ]
    )


class EnergyMkEntity(CoordinatorEntity[EnergyMkCoordinator], SensorEntity):
    """Base entity: shared unique_id scheme, naming, and device grouping."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: EnergyMkCoordinator, key: str) -> None:
        super().__init__(coordinator)
        queue_name = QUEUE_NAMES.get(coordinator.queue_id, str(coordinator.queue_id))
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"queue_{coordinator.queue_id}")},
            name=f"Energy MK {queue_name}",
            manufacturer="Mykolaivoblenergo",
            model=f"Queue {queue_name}",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://off.energy.mk.ua/",
        )


class EnergyMkStatusSensor(EnergyMkEntity):
    """Current 30-min slot power status."""

    _attr_icon = "mdi:transmission-tower"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = ["ON", "OFF", "PROBABLY_OFF"]

    def __init__(self, coordinator: EnergyMkCoordinator) -> None:
        super().__init__(coordinator, "status")

    @property
    def native_value(self) -> str:
        return self.coordinator.current_state()

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


class EnergyMkNextOutageSensor(EnergyMkEntity):
    """Start time of the next confirmed (OFF) outage slot."""

    _attr_icon = "mdi:clock-alert-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: EnergyMkCoordinator) -> None:
        super().__init__(coordinator, "next_outage")

    @property
    def native_value(self) -> datetime | None:
        slot_map: dict[datetime, str] = self.coordinator.data or {}
        return next_slot_of_type(slot_map, dt_util.utcnow(), ("OFF",))


class EnergyMkNextRestorationSensor(EnergyMkEntity):
    """Time when power returns after the next confirmed outage block."""

    _attr_icon = "mdi:clock-check-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: EnergyMkCoordinator) -> None:
        super().__init__(coordinator, "next_restoration")

    @property
    def native_value(self) -> datetime | None:
        slot_map: dict[datetime, str] = self.coordinator.data or {}
        next_outage = next_slot_of_type(slot_map, dt_util.utcnow(), ("OFF",))
        if next_outage is None:
            return None
        return outage_block_end(slot_map, next_outage)


class EnergyMkNextProbableOutageSensor(EnergyMkEntity):
    """Start time of the next possible (PROBABLY_OFF) outage slot."""

    _attr_icon = "mdi:clock-question-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: EnergyMkCoordinator) -> None:
        super().__init__(coordinator, "next_probable_outage")

    @property
    def native_value(self) -> datetime | None:
        slot_map: dict[datetime, str] = self.coordinator.data or {}
        return next_slot_of_type(slot_map, dt_util.utcnow(), ("PROBABLY_OFF",))
