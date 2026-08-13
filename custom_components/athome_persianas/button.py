"""Button platform for global blind calibration."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .common import ScriptConfig, async_run_script
from .const import DOMAIN
from .coordinator import AthomePersianasCoordinator

LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator: AthomePersianasCoordinator = hass.data[DOMAIN][entry.entry_id]
    LOGGER.debug("Creating calibration button entity for entry %s", entry.entry_id)
    async_add_entities([AthomePersianasCalibrateButton(coordinator, entry.data)])
    LOGGER.info("Added 1 calibration button entity for entry %s", entry.entry_id)


class AthomePersianasCalibrateButton(CoordinatorEntity[AthomePersianasCoordinator], ButtonEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:shutter-auto"

    def __init__(self, coordinator: AthomePersianasCoordinator, config: dict[str, Any]) -> None:
        super().__init__(coordinator)
        self._script = ScriptConfig.from_dict(config)
        self._attr_name = "Calibrate timings"
        self._attr_unique_id = "athome_persianas:calibrate"
        self._last_run: datetime | None = None
        self._last_started: datetime | None = None
        self._last_error: str | None = None
        self._last_result: Any | None = None
        self._running = False

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, "athome_persianas_hub")},
            manufacturer="AtHome by Airzone",
            name="AtHome by Airzone",
            model="Blind calibration hub",
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "last_started": self._last_started.isoformat() if self._last_started else None,
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "last_error": self._last_error,
            "last_result_count": self._last_result.get("count") if isinstance(self._last_result, dict) else None,
        }

    async def async_press(self) -> None:
        if self._running:
            LOGGER.info("AtHome by Airzone timing calibration is already running")
            return
        self._running = True
        self._last_started = datetime.utcnow()
        self._last_error = None
        self.async_write_ha_state()
        self.hass.async_create_task(self._async_run_calibration())

    async def _async_run_calibration(self) -> None:
        try:
            self._last_result = await async_run_script(self._script, "calibrate-blind-timings")
            self._last_run = datetime.utcnow()
            LOGGER.info("AtHome by Airzone timing calibration completed")
        except Exception as exc:  # noqa: BLE001 - surfaced via entity attributes/logs
            self._last_error = str(exc)
            LOGGER.exception("AtHome by Airzone timing calibration failed")
        finally:
            self._running = False
            self.async_write_ha_state()
