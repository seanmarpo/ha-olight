"""Constants for the Olight integration."""

DOMAIN = "olight"
MANUFACTURER = "Olight"
DEFAULT_MODEL = "Ostation 2 Pro"

CONF_DEVICE_ID = "device_id"
CONF_LOCAL_KEY = "local_key"
CONF_HOST = "host"
CONF_MODEL = "model"

# Tuya datapoints. Confirmed against real Ostation 2 / 2 Pro units (Tuya product ids seen in the
# wild: 1fnensm6, v8znljza, rcj4z3pdmhkzflio) and the upstream tuya-local config.
DP_POWER = 101              # bool   - charging enabled
DP_FULLY_CHARGED = 102      # int    - cells finished this cycle
DP_REJECT_BIN_FULL = 103    # bool   - rejected-battery bin full
DP_AA_BIN_FULL = 104        # bool   - AA storage compartment full
DP_WAKE_SENSITIVITY = 105   # int    - proximity wake sensitivity, 1-5
DP_AAA_BIN_FULL = 106       # bool   - AAA storage compartment full
DP_REJECTED = 108           # int    - cells rejected as unusable
DP_TELEMETRY = 110          # raw    - per-bay live telemetry (see protocol.py)
DP_PAUSE_ENABLED = 111      # bool   - honour the quiet-hours window
DP_PAUSE_WINDOW = 112       # raw    - quiet-hours window: start h, start m, end h, end m
DP_DIAGNOSTIC = 113         # int    - purpose unknown; always 0 so far; exposed as a diagnostic

WAKE_SENSITIVITY_MIN = 1
WAKE_SENSITIVITY_MAX = 5

# A status reply never carries the bay telemetry (the station pushes that, and heartbeats collect
# it every few seconds), so a full poll only re-confirms the station-level datapoints. No need to
# query a low-power device more often than this.
UPDATE_INTERVAL_SECONDS = 60
