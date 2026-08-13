"""AtHome by Airzone integration entry point."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .common import ScriptConfig
from .const import DOMAIN, PLATFORMS
from .coordinator import AthomePersianasCoordinator

LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    LOGGER.info("Setting up AtHome by Airzone blinds integration for entry %s", entry.entry_id)
    if entry.title != "Athome by Airzone blinds":
        hass.config_entries.async_update_entry(entry, title="Athome by Airzone blinds")
    script_config = ScriptConfig.from_dict(entry.data)
    coordinator = AthomePersianasCoordinator(hass, script_config)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, [Platform(platform) for platform in PLATFORMS])

    async def _async_first_refresh() -> None:
        LOGGER.info("Starting background discovery refresh for entry %s", entry.entry_id)
        try:
            await coordinator.async_config_entry_first_refresh()
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Background discovery refresh failed for entry %s", entry.entry_id)
            return
        LOGGER.info("Background discovery refresh completed for entry %s", entry.entry_id)

    refresh_task = hass.async_create_task(_async_first_refresh())
    entry.async_on_unload(refresh_task.cancel)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, [Platform(platform) for platform in PLATFORMS])
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok
