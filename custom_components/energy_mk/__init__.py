"""Energy MK — Mykolaiv region power outage schedule integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .coordinator import EnergyMkCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

EnergyMkConfigEntry = ConfigEntry[EnergyMkCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: EnergyMkConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    coordinator = EnergyMkCoordinator(hass, session, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # Slot-boundary ticks and event firing live on the coordinator, not on an
    # entity, so they keep working even if the status sensor is disabled.
    entry.async_on_unload(
        coordinator.async_add_listener(coordinator.async_handle_data_updated)
    )
    coordinator.async_handle_data_updated()

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: EnergyMkConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: EnergyMkConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok
