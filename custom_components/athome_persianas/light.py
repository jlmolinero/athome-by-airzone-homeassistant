"""Light platform for AtHome by Airzone lights."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .common import LightEntry, ScriptConfig, async_run_script
from .const import ATTR_COMPONENT_ID, ATTR_DIMMER, ATTR_LIGHT_NAME, ATTR_ZONE_ID, DOMAIN
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
        lights = data.get("lights", []) or []
        new_entities = []
        for light in lights:
            unique_id = f"{light.unique_id_base}:light"
            if unique_id in seen:
                continue
            seen.add(unique_id)
            LOGGER.debug(
                "Creating light entity for zone_id=%s component_id=%s light=%s unique_id=%s",
                light.zone_id,
                light.component_id,
                light.name,
                unique_id,
            )
            new_entities.append(AthomeAirzoneLight(coordinator, script_config, light))
        if new_entities:
            created += len(new_entities)
            async_add_entities(new_entities)
            LOGGER.info("Added %d light entities in this refresh (total=%d)", len(new_entities), created)

    await _async_add_missing_entities()

    def _schedule_add_missing_entities() -> None:
        hass.async_create_task(_async_add_missing_entities())

    entry.async_on_unload(coordinator.async_add_listener(_schedule_add_missing_entities))


class AthomeAirzoneLight(CoordinatorEntity[AthomePersianasCoordinator], RestoreEntity, LightEntity):
    _attr_has_entity_name = True
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(
        self,
        coordinator: AthomePersianasCoordinator,
        script_config: ScriptConfig,
        light: LightEntry,
    ) -> None:
        super().__init__(coordinator)
        self._script = script_config
        self._light = light
        self._state: int | None = light.state
        self._attr_name = light.name
        self._attr_unique_id = f"{light.unique_id_base}:light"
        self._attr_icon = "mdi:lightbulb"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._light.unique_id_base)},
            manufacturer="AtHome by Airzone",
            name=self._light.name,
            model=f"Light zone {self._light.zone_id} component {self._light.component_id}",
        )

    @property
    def is_on(self) -> bool | None:
        if self._state is None:
            return None
        return int(self._state) > 0

    @property
    def brightness(self) -> int | None:
        if self._state is None:
            return None
        return round(max(0, min(100, int(self._state))) * 255 / 100)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            ATTR_ZONE_ID: self._light.zone_id,
            ATTR_COMPONENT_ID: self._light.component_id,
            ATTR_LIGHT_NAME: self._light.name,
            ATTR_DIMMER: self._light.dimmer,
        }

    async def async_added_to_hass(self) -> None:
        last_state = await self.async_get_last_state()
        if last_state is None:
            return
        if last_state.state == "on":
            restored = last_state.attributes.get(ATTR_BRIGHTNESS)
            if restored is not None:
                try:
                    self._state = round(int(restored) * 100 / 255)
                    return
                except (TypeError, ValueError):
                    pass
            if self._state is None:
                self._state = 100
        elif last_state.state == "off":
            self._state = 0

    async def async_turn_on(self, **kwargs: Any) -> None:
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        if brightness is not None:
            target_state = round(int(brightness) * 100 / 255)
        elif self._state is None or self._state <= 0:
            target_state = 100
        else:
            target_state = int(self._state)
        await self._set_state(target_state)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set_state(0)

    async def _set_state(self, state: int) -> None:
        state = max(0, min(100, int(state)))
        result = await async_run_script(
            self._script,
            "set-light",
            "--zone-id",
            str(self._light.zone_id),
            "--component-id",
            str(self._light.component_id),
            "--state",
            str(state),
        )
        if isinstance(result, dict) and result.get("state") is not None:
            self._state = int(result["state"])
        else:
            self._state = state
        self.async_write_ha_state()
