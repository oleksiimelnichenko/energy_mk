"""Constants for Energy MK integration."""

DOMAIN = "energy_mk"

API_URL = "https://off.energy.mk.ua/api/v2/schedule/active"
SLOT_MINUTES = 30

CONF_QUEUE_ID = "queue_id"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_QUEUE_ID = 22
DEFAULT_SCAN_INTERVAL = 15  # minutes

EVENT_OUTAGE_STARTED = f"{DOMAIN}_outage_started"
EVENT_POWER_RESTORED = f"{DOMAIN}_power_restored"

QUEUE_NAMES: dict[int, str] = {
    14: "1.1",
    15: "1.2",
    16: "2.1",
    17: "2.2",
    19: "3.1",
    20: "3.2",
    21: "4.1",
    22: "4.2",
    24: "5.1",
    25: "5.2",
    26: "6.1",
    27: "6.2",
}
