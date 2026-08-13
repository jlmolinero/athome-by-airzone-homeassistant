"""Constants for the AtHome by Airzone custom integration."""

from __future__ import annotations

DOMAIN = "athome_persianas"
PLATFORMS = ["cover", "select", "button", "light"]

CONF_SCRIPT_PATH = "script_path"
CONF_PYTHON_PATH = "python_path"
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_SESSION_JSON = "session_json"
CONF_DEVICE_ID = "device_id"
CONF_AUTH_BASE_URL = "auth_base_url"
CONF_WEB_BASE_URL = "web_base_url"
CONF_CHROMIUM_PATH = "chromium_path"
CONF_TIMINGS_PATH = "timings_path"

DEFAULT_PYTHON_PATH = "python3"
DEFAULT_AUTH_BASE_URL = "https://m.airzonecloud.com/api/v1"
DEFAULT_WEB_BASE_URL = "https://athome.airzonecloud.com"
DEFAULT_SCRIPT_PATH = "/config/custom_components/athome_persianas/athome_persianas.py"
DEFAULT_TIMINGS_FILENAME = "blind_timings.json"
DEFAULT_TIMINGS_PATH = "/config/custom_components/athome_persianas/blind_timings.json"
DEFAULT_SESSION_JSON_PATH = "/config/custom_components/athome_persianas/session.json"

ATTR_ZONE_ID = "zone_id"
ATTR_COMPONENT_ID = "component_id"
ATTR_SLAT = "slat"
ATTR_BLIND_NAME = "blind_name"
ATTR_LIGHT_NAME = "light_name"
ATTR_DIMMER = "dimmer"

SLAT_OPTIONS = ["0°", "45°", "90°"]
SLAT_ACTIONS = {
    "0°": "slat0",
    "45°": "slat45",
    "90°": "slat90",
}
