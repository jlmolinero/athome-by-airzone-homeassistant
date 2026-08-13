"""Coordinator for AtHome by Airzone blinds discovery."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .common import ScriptConfig, async_discover_blinds, async_run_script
from .const import DOMAIN

LOGGER = logging.getLogger(__name__)


@dataclass
class AthomePersianasRuntime:
    config: ScriptConfig
    blinds: list[Any]


class AthomePersianasCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, config: ScriptConfig) -> None:
        self.script_config = config
        super().__init__(hass, logger=LOGGER, name=DOMAIN)

    async def _async_update_data(self) -> dict[str, Any]:
        blinds, source = await async_discover_blinds(self.script_config)
        LOGGER.info("Coordinator refresh discovered %d blinds via %s", len(blinds), source)
        return {"blinds": blinds}

    async def async_calibrate_all(self) -> Any:
        return await async_run_script(self.script_config, "calibrate-blind-timings")
