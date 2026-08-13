"""Select platform for AtHome by Airzone louver control."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .common import BlindEntry, ScriptConfig, async_run_script, load_timing_profiles
from .const import ATTR_BLIND_NAME, ATTR_COMPONENT_ID, ATTR_ZONE_ID, DOMAIN, SLAT_ACTIONS, SLAT_OPTIONS
from .coordinator import AthomePersianasCoordinator

LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator: AthomePersianasCoordinator = hass.data[DOMAIN][entry.entry_id]
    script_config = ScriptConfig.from_dict(entry.data)
    seen: set[str] = set()
    created = 0

    async def _async_add_missing_entities() -> None:
        nonlocal created
        data = coordinator.data or {}
        blinds = data.get("blinds", []) or []
        timing_profiles = await hass.async_add_executor_job(load_timing_profiles, script_config.timings_path)
        new_entities = []
        for blind in blinds:
            profile = timing_profiles.get(f"{blind.zone_id}:{blind.component_id}")
            profile = profile if isinstance(profile, dict) else {}
            if not _supports_slat_control(blind, profile):
                entity_registry = er.async_get(hass)
                entity_id = entity_registry.async_get_entity_id("select", DOMAIN, f"{blind.unique_id_base}:slat")
                if entity_id is not None:
                    entity_registry.async_remove(entity_id)
                    LOGGER.info(
                        "Removed stale slat select entity for non-louver blind zone_id=%s component_id=%s blind=%s entity_id=%s",
                        blind.zone_id,
                        blind.component_id,
                        blind.name,
                        entity_id,
                    )
                LOGGER.debug(
                    "Skipping slat select for non-louver blind zone_id=%s component_id=%s blind=%s",
                    blind.zone_id,
                    blind.component_id,
                    blind.name,
                )
                continue
            unique_id = f"{blind.unique_id_base}:slat"
            if unique_id in seen:
                continue
            seen.add(unique_id)
            LOGGER.debug(
                "Creating select entity for zone_id=%s component_id=%s blind=%s unique_id=%s",
                blind.zone_id,
                blind.component_id,
                blind.name,
                unique_id,
            )
            new_entities.append(
                AthomePersianasSlatSelect(
                    coordinator,
                    script_config,
                    blind,
                    profile,
                )
            )
        if new_entities:
            created += len(new_entities)
            async_add_entities(new_entities)
            LOGGER.info("Added %d select entities in this refresh (total=%d)", len(new_entities), created)

    await _async_add_missing_entities()

    def _schedule_add_missing_entities() -> None:
        hass.async_create_task(_async_add_missing_entities())

    entry.async_on_unload(coordinator.async_add_listener(_schedule_add_missing_entities))


def _supports_slat_control(blind: BlindEntry, profile: dict[str, Any]) -> bool:
    if blind.slat is not None:
        return int(blind.slat) == 1
    if profile.get("supports_slats") is not None:
        return bool(profile.get("supports_slats"))
    calibration = profile.get("calibration")
    if isinstance(calibration, dict):
        for key in ("initial_state", "closed_state", "open_state", "final_state"):
            state = calibration.get(key)
            if isinstance(state, dict) and state.get("slat") is not None:
                return int(state.get("slat") or 0) == 1
    return False


class AthomePersianasSlatSelect(CoordinatorEntity[AthomePersianasCoordinator], RestoreEntity, SelectEntity):
    _attr_has_entity_name = True
    _attr_options = list(SLAT_OPTIONS)

    def __init__(
        self,
        coordinator: AthomePersianasCoordinator,
        script_config: ScriptConfig,
        blind: BlindEntry,
        profile: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._script = script_config
        self._blind = blind
        self._current_option: str | None = None
        self._attr_name = f"{blind.name} Slats"
        self._attr_unique_id = f"{blind.unique_id_base}:slat"
        self._attr_icon = "mdi:angle-acute"
        if profile.get("last_slat") in self._attr_options:
            self._current_option = str(profile["last_slat"])

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._blind.unique_id_base)},
            manufacturer="AtHome by Airzone",
            name=self._blind.name,
            model=f"Blind zone {self._blind.zone_id} component {self._blind.component_id}",
        )

    @property
    def current_option(self) -> str | None:
        return self._current_option

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            ATTR_ZONE_ID: self._blind.zone_id,
            ATTR_COMPONENT_ID: self._blind.component_id,
            ATTR_BLIND_NAME: self._blind.name,
        }

    async def async_added_to_hass(self) -> None:
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in self._attr_options:
            self._current_option = last_state.state

    async def async_select_option(self, option: str) -> None:
        action = SLAT_ACTIONS.get(option)
        if action is None:
            raise ValueError(f"Invalid slat option: {option}")
        await async_run_script(
            self._script,
            "set-blind",
            "--zone-id",
            str(self._blind.zone_id),
            "--component-id",
            str(self._blind.component_id),
            "--action",
            action,
        )
        self._current_option = option
        self.async_write_ha_state()
