# Energy MK — Mykolaiv Power Outage Schedule

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

A Home Assistant integration that tracks the **Mykolaiv (Миколаїв) regional power outage schedule** from [off.energy.mk.ua](https://off.energy.mk.ua/).

## Features

- **Status sensor** — current 30-minute slot state: `ON`, `OFF`, or `PROBABLY_OFF`
- **Next outage sensor** — timestamp of the next scheduled outage (device class `timestamp`)
- Consolidated outage windows exposed as attributes (start time, end time, type)
- Configurable queue ID and polling interval via the UI

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
| Outage queue ID | `22` | Your outage queue number (find it on off.energy.mk.ua) |
| Update interval | `15` | How often to poll the API (minutes, 5–1440) |

## Sensors

### `sensor.energy_mk_status`

| Attribute | Description |
|-----------|-------------|
| `schedule` | List of outage windows `{start, end, type}` for today |
| `queue` | Configured queue ID |

States: `ON` · `OFF` · `PROBABLY_OFF`

### `sensor.energy_mk_next_outage`

Timestamp of the next `OFF` or `PROBABLY_OFF` slot within the next 24 hours. Returns `unknown` if no outage is scheduled.

## Finding Your Queue ID

Visit [off.energy.mk.ua](https://off.energy.mk.ua/), select your address, and note the numeric queue ID shown in the URL or schedule table. Queue **4.2** corresponds to ID `22`.
