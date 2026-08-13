"""Config flow for AtHome by Airzone."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant import config_entries

from .common import ScriptConfig, async_discover_blinds
from .const import (
    CONF_AUTH_BASE_URL,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_SCRIPT_PATH,
    CONF_WEB_BASE_URL,
    DEFAULT_AUTH_BASE_URL,
    DEFAULT_SCRIPT_PATH,
    DEFAULT_WEB_BASE_URL,
    DOMAIN,
)

LOGGER = logging.getLogger(__name__)


class AthomePersianasConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                user_input = dict(user_input)
                script_config = ScriptConfig.from_dict(user_input)
                blinds, source = await async_discover_blinds(script_config)
                if not blinds:
                    errors["base"] = "no_blinds_found"
                else:
                    LOGGER.info("Config flow discovery found %d blinds via %s", len(blinds), source)
                    await self.async_set_unique_id(DOMAIN)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(title="Athome by Airzone blinds", data=user_input)
            except Exception:
                errors["base"] = "cannot_connect"

        schema = vol.Schema(
            {
                vol.Required(CONF_SCRIPT_PATH, default=DEFAULT_SCRIPT_PATH): str,
                vol.Optional(CONF_EMAIL, default=""): str,
                vol.Optional(CONF_PASSWORD, default=""): str,
                vol.Required(CONF_WEB_BASE_URL, default=DEFAULT_WEB_BASE_URL): str,
                vol.Required(CONF_AUTH_BASE_URL, default=DEFAULT_AUTH_BASE_URL): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
