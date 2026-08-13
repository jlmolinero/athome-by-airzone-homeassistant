"""Cover platform for AtHome by Airzone blinds."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import ATTR_CURRENT_POSITION, CoverEntity, CoverEntityFeature
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .common import BlindEntry, ScriptConfig, async_run_script, load_timing_profiles
from .const import ATTR_BLIND_NAME, ATTR_COMPONENT_ID, ATTR_ZONE_ID, DOMAIN
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
            unique_id = f"{blind.unique_id_base}:cover"
            if unique_id in seen:
                continue
            seen.add(unique_id)
            LOGGER.debug(
                "Creating cover entity for zone_id=%s component_id=%s blind=%s unique_id=%s",
                blind.zone_id,
                blind.component_id,
                blind.name,
                unique_id,
            )
            profile = timing_profiles.get(f"{blind.zone_id}:{blind.component_id}")
            new_entities.append(
                AthomePersianasCover(
                    coordinator,
                    script_config,
                    blind,
                    profile if isinstance(profile, dict) else {},
                )
            )
        if new_entities:
            created += len(new_entities)
            async_add_entities(new_entities)
            LOGGER.info("Added %d cover entities in this refresh (total=%d)", len(new_entities), created)

    await _async_add_missing_entities()

    def _schedule_add_missing_entities() -> None:
        hass.async_create_task(_async_add_missing_entities())

    entry.async_on_unload(coordinator.async_add_listener(_schedule_add_missing_entities))


class AthomePersianasCover(CoordinatorEntity[AthomePersianasCoordinator], RestoreEntity, CoverEntity):
    _attr_has_entity_name = True
    _attr_supported_features = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP | CoverEntityFeature.SET_POSITION
    )

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
        self._position: int | None = None
        self._attr_name = blind.name
        self._attr_unique_id = f"{blind.unique_id_base}:cover"
        self._attr_icon = "mdi:window-shutter"
        if profile.get("current_percent") is not None:
            try:
                self._position = int(float(profile["current_percent"]))
            except (TypeError, ValueError):
                self._position = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._blind.unique_id_base)},
            manufacturer="AtHome by Airzone",
            name=self._blind.name,
            model=f"Blind zone {self._blind.zone_id} component {self._blind.component_id}",
        )

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def current_cover_position(self) -> int | None:
        return self._position

    @property
    def is_closed(self) -> bool | None:
        if self._position is None:
            return None
        return self._position == 0

    @property
    def is_open(self) -> bool | None:
        if self._position is None:
            return None
        return self._position == 100

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = {
            ATTR_ZONE_ID: self._blind.zone_id,
            ATTR_COMPONENT_ID: self._blind.component_id,
            ATTR_BLIND_NAME: self._blind.name,
        }
        if self._position is not None:
            attrs[ATTR_CURRENT_POSITION] = self._position
        return attrs

    async def async_added_to_hass(self) -> None:
        last_state = await self.async_get_last_state()
        if last_state is not None:
            restored = last_state.attributes.get(ATTR_CURRENT_POSITION)
            if restored is None and last_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                restored = last_state.attributes.get("current_position")
            if restored is not None:
                try:
                    self._position = int(float(restored))
                except (TypeError, ValueError):
                    pass

    async def _call(self, action: str, state: int | None = None) -> None:
        args = [
            "set-blind",
            "--zone-id",
            str(self._blind.zone_id),
            "--component-id",
            str(self._blind.component_id),
            "--action",
            action,
        ]
        if state is not None:
            args.extend(["--state", str(int(state))])
        result = await async_run_script(self._script, *args)
        if isinstance(result, dict):
            if result.get("target_percent") is not None:
                self._position = int(result["target_percent"])
            elif result.get("state") is not None:
                try:
                    self._position = int(result["state"])
                except (TypeError, ValueError):
                    pass
        if action == "upload":
            self._position = 100 if state is None else int(state)
        elif action == "download":
            self._position = 0 if state is None else int(state)
        elif action == "stop" and self._position is None:
            self._position = None
        self.async_write_ha_state()

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._call("upload")

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._call("download")

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self._call("stop")

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        position = kwargs.get("position")
        if position is None:
            return
        await self._call("upload" if int(position) >= 50 else "download", int(position))
