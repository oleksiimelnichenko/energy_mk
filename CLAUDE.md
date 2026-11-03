# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Home Assistant custom integration that tracks power outage schedules for Mykolaiv region (Ukraine) from `off.energy.mk.ua`. Distributed via HACS (Home Assistant Community Store). Minimum HA version: 2024.11 (see `hacs.json`).

## Development & Installation

There is no build system. Development workflow:
- Copy `energy_mk/custom_components/energy_mk/` into a Home Assistant instance's `config/custom_components/` directory
- Restart Home Assistant to load changes
- View logs via Home Assistant's Developer Tools > Logs

CI (`.github/workflows/validate.yml`) runs hassfest, HACS validation, and ruff on every push. No project-level test suite exists.

## Architecture

**Pattern:** Home Assistant coordinator-based integration (standard HA extension pattern), `entry.runtime_data` for coordinator storage (no `hass.data`).

**Data flow:**
1. User configures a queue, poll interval, and warning lead times via `config_flow.py` (HA UI). Interval and warnings are editable later through an **OptionsFlow** (`entry.options` overrides `entry.data` — see `entry_option()` in `coordinator.py`); options changes reload the entry.
2. `EnergyMkCoordinator` (`coordinator.py`) fetches `https://off.energy.mk.ua/api/v2/schedule/active` on the configured interval (default 15 min, range 5–1440 min). On fetch failure it keeps serving the cached slot map while it still covers the future, instead of going unavailable.
3. The coordinator builds a slot map `{slot_start_utc: type}` filtered by `outage_queue_id`. Keys are **absolute UTC datetimes** (`schedule.from + (time_series_id − 1) × 30 min`), so multiple schedules sharing the same 1–48 numbering don't collide and midnight wrap is a non-issue. Slot types: `OFF` and `SURE_OFF` (new in the API on 2026-11-03) are confirmed outages, `PROBABLY_OFF` is possible; an unknown type is logged once and treated as `OFF`. On duplicate slots, a confirmed type wins over `PROBABLY_OFF`; conflicting revisions are logged at debug level (merge rule deliberately unverified against real revisions — revisit when the debug log shows one).
4. **Slot-boundary ticks**: after every refresh the coordinator arms an `async_track_point_in_time` timer at the next 30-min boundary, which calls `async_update_listeners()`. So sensors and events are accurate to the slot edge, independent of the poll interval. The listener chain (`async_handle_data_updated`, registered in `__init__.py`) re-evaluates state, fires events, and re-arms timers.
5. **Next-outage sensors and warnings use block starts** (`next_block_start`): a slot counts only if the slot before it is not of the same kind, so a block in progress is never reported as "next" (fixed 2026-11-03, v1.2.2; before that, during an outage `next_outage` showed the next 30-min slot of the same outage, and warnings were re-armed for every slot). `next_restoration` returns the end of the current confirmed block while one is in progress.
6. **Events** fire from the coordinator (not from an entity, so disabling sensors doesn't kill them): `energy_mk_outage_warning` (`queue`, `minutes_before`, `type`, `outage_at`), `energy_mk_outage_started` (`queue`, `state`, `restoration_at`), `energy_mk_power_restored` (`queue`). All timers are cancelled in `async_shutdown()` on entry unload.
7. Four sensor entities in `sensor.py`, all `CoordinatorEntity` subclasses sharing the `EnergyMkEntity` base (has_entity_name, translation keys, one `DeviceInfo` per queue):
   - `EnergyMkStatusSensor` — enum sensor (`ON`/`OFF`/`SURE_OFF`/`PROBABLY_OFF`); exposes consolidated outage windows in the `schedule` attribute
   - `EnergyMkNextOutageSensor` / `EnergyMkNextRestorationSensor` / `EnergyMkNextProbableOutageSensor` — timestamp sensors

**Key files:**
- `const.py` — constants (API URL, slot duration, config keys, defaults, event names, queue id→name map)
- `coordinator.py` — fetching, slot map construction, slot-boundary timers, event firing, `entry_option()` helper, shared slot helpers (`floor_to_slot`, `next_slot_of_type`, `outage_block_end`)
- `sensor.py` — four sensor entities reading from the coordinator
- `config_flow.py` — config flow + options flow; enforces unique entry per queue ID
- `__init__.py` — entry lifecycle, coordinator listener registration, options update listener

**Graceful degradation:** Returns `ON` (power available) when no schedule data is present; timestamp sensors return `unknown` when no matching slot is found.

## Home Assistant Integration Conventions

- All I/O must be `async`/`await`; use `aiohttp.ClientSession` with `aiohttp.ClientTimeout` (never a bare int timeout)
- Use `homeassistant.helpers.update_coordinator.DataUpdateCoordinator` for shared data fetching; pass `config_entry=` to its constructor
- Sensor entities extend `CoordinatorEntity` for automatic coordinator binding
- Translations live in `translations/en.json` (mirrors `strings.json`) and `translations/uk.json` — keep all three in sync
- `manifest.json` must be kept in sync with version bumps; min HA version lives in `hacs.json`
- **Compatibility constraint**: entity `unique_id`s (`<entry_id>_status`, `_next_outage`, `_next_restoration`, `_next_probable_outage`), state values (`ON`/`OFF`/`SURE_OFF`/`PROBABLY_OFF`, uppercase), and event names/payload keys are referenced by the user's ha-config repo (`sensor.energy_mk_4_2_next_outage` drives the inverter pre-outage logic) — never rename them; only add.
