# Energy MK — Mykolaiv Power Outage Schedule

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

A Home Assistant integration that tracks the **Mykolaiv (Миколаїв) regional power outage schedule** from [off.energy.mk.ua](https://off.energy.mk.ua/).

Requires Home Assistant **2024.11** or newer.

## Features

- **Status sensor** — current 30-minute slot state: `ON`, `OFF`, or `PROBABLY_OFF` (enum sensor, updates exactly at slot boundaries, not just on poll)
- **Next outage / Next restoration / Next probable outage** — `timestamp` sensors for the next confirmed outage, when power returns after it, and the next possible outage
- Consolidated outage windows exposed as attributes (start time, end time, type)
- **Events** for automations: outage warnings, outage started, power restored
- Configurable queue, polling interval, and warning lead times via the UI (editable later via the integration's **Configure** dialog)
- Keeps serving the cached schedule if the API is temporarily unreachable

## Installation via HACS

1. In HACS → **Integrations** → ⋮ menu → **Custom repositories**
2. Add this repo URL, category **Integration**, click **Add**
3. Find **Energy MK** in HACS and click **Download**
4. Restart Home Assistant

## Manual Installation

Copy the `custom_components/energy_mk/` directory into your HA `config/custom_components/` folder and restart.

## Configuration

After installation go to **Settings → Devices & Services → Add Integration** and search for **Energy MK**.

| Field | Default | Description |
|-------|---------|-------------|
| Outage queue | `4.2` | Your outage queue (find it on off.energy.mk.ua) |
| Update interval | `15` | How often to poll the API (minutes, 5–1440) |
| Warn before an outage | `30, 60` | Lead times for `energy_mk_outage_warning` events |

The update interval and warning lead times can be changed later via **Configure** on the integration card — no need to remove and re-add it.

## Sensors

All sensors are grouped under one device per queue (e.g. **Energy MK 4.2**).

### `sensor.energy_mk_<queue>_status`

Current slot state. States: `ON` · `OFF` · `PROBABLY_OFF`

| Attribute | Description |
|-----------|-------------|
| `schedule` | List of outage windows `{start, end, type}` (local `HH:MM`) |
| `queue` | Configured queue ID |

### `sensor.energy_mk_<queue>_next_outage`

Timestamp of the next confirmed `OFF` slot. `unknown` if none is scheduled.

### `sensor.energy_mk_<queue>_next_restoration`

Timestamp when power returns after the next confirmed outage block.

### `sensor.energy_mk_<queue>_next_probable_outage`

Timestamp of the next `PROBABLY_OFF` slot.

## Events

| Event | Payload | When |
|-------|---------|------|
| `energy_mk_outage_warning` | `queue`, `minutes_before`, `type`, `outage_at` | At each configured lead time before the next outage |
| `energy_mk_outage_started` | `queue`, `state`, `restoration_at` | When the current slot turns `OFF`/`PROBABLY_OFF` |
| `energy_mk_power_restored` | `queue` | When the current slot turns back `ON` |

Example automation trigger:

```yaml
triggers:
  - trigger: event
    event_type: energy_mk_outage_warning
    event_data:
      minutes_before: 30
```

## Finding Your Queue

Visit [off.energy.mk.ua](https://off.energy.mk.ua/), select your address, and note your queue (e.g. **4.2**). The config flow offers all known queues in a dropdown.
