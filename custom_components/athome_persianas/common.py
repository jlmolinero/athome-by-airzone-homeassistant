"""Shared helpers for the AtHome by Airzone custom integration."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_AUTH_BASE_URL,
    CONF_CHROMIUM_PATH,
    CONF_DEVICE_ID,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_PYTHON_PATH,
    CONF_SCRIPT_PATH,
    CONF_SESSION_JSON,
    CONF_TIMINGS_PATH,
    CONF_WEB_BASE_URL,
    DEFAULT_AUTH_BASE_URL,
    DEFAULT_PYTHON_PATH,
    DEFAULT_TIMINGS_PATH,
    DEFAULT_WEB_BASE_URL,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class BlindEntry:
    name: str
    zone_id: int
    component_id: int
    slat: int | None = None
    zone_name: str | None = None

    @property
    def unique_id_base(self) -> str:
        return f"{self.zone_id}:{self.component_id}"


@dataclass(frozen=True)
class LightEntry:
    name: str
    zone_id: int
    component_id: int
    state: int | None = None
    dimmer: int | None = None
    zone_name: str | None = None

    @property
    def unique_id_base(self) -> str:
        return f"light:{self.zone_id}:{self.component_id}"


@dataclass(frozen=True)
class ScriptConfig:
    script_path: str
    python_path: str = DEFAULT_PYTHON_PATH
    email: str | None = None
    password: str | None = None
    session_json: str | None = None
    device_id: str | None = None
    auth_base_url: str = DEFAULT_AUTH_BASE_URL
    web_base_url: str = DEFAULT_WEB_BASE_URL
    chromium_path: str | None = None
    timings_path: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScriptConfig":
        script_path = str(data.get(CONF_SCRIPT_PATH) or "").strip()
        if not script_path:
            raise HomeAssistantError("Missing script_path in the configuration")
        timings_path = str(data.get(CONF_TIMINGS_PATH) or "").strip() or None
        if timings_path is None:
            timings_path = str(Path(DEFAULT_TIMINGS_PATH))
        session_json = str(data.get(CONF_SESSION_JSON) or "").strip() or None
        return cls(
            script_path=script_path,
            python_path=str(data.get(CONF_PYTHON_PATH) or DEFAULT_PYTHON_PATH),
            email=data.get(CONF_EMAIL),
            password=data.get(CONF_PASSWORD),
            session_json=session_json,
            device_id=data.get(CONF_DEVICE_ID),
            auth_base_url=str(data.get(CONF_AUTH_BASE_URL) or DEFAULT_AUTH_BASE_URL),
            web_base_url=str(data.get(CONF_WEB_BASE_URL) or DEFAULT_WEB_BASE_URL),
            chromium_path=data.get(CONF_CHROMIUM_PATH),
            timings_path=timings_path,
        )

    def to_env(self) -> dict[str, str]:
        env = os.environ.copy()
        for key, value in {
            "ATHOME_EMAIL": self.email,
            "ATHOME_PASSWORD": self.password,
            "ATHOME_SESSION_JSON": self.session_json,
            "ATHOME_DEVICE_ID": self.device_id,
            "ATHOME_AUTH_BASE_URL": self.auth_base_url,
            "ATHOME_WEB_BASE_URL": self.web_base_url,
            "ATHOME_CHROMIUM": self.chromium_path,
        }.items():
            if value not in (None, ""):
                env[key] = str(value)
        env.setdefault("PYTHONUNBUFFERED", "1")
        return env


async def async_run_script(script: ScriptConfig, *args: str) -> Any:
    proc = await asyncio.create_subprocess_exec(
        script.python_path,
        script.script_path,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=script.to_env(),
        cwd=str(Path(script.script_path).resolve().parent),
    )
    stdout_b, stderr_b = await proc.communicate()
    stdout = stdout_b.decode("utf-8", errors="replace").strip()
    stderr = stderr_b.decode("utf-8", errors="replace").strip()

    if proc.returncode != 0:
        raise HomeAssistantError(
            "The AtHome by Airzone script returned an error"
            f" (exit={proc.returncode}).\nSTDOUT:\n{stdout or '(empty)'}\nSTDERR:\n{stderr or '(empty)'}"
        )

    if not stdout:
        return None

    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return stdout


def _blind_entries_from_json(result: Any) -> list[BlindEntry]:
    blinds: list[BlindEntry] = []
    if not isinstance(result, dict):
        return blinds
    for raw in result.get("blinds", []) or []:
        try:
            zone_id = int(raw.get("zone_id") or raw.get("zoneID") or 0)
            component_id = int(raw.get("component_id") or raw.get("componentID") or 0)
        except Exception:
            continue
        if not zone_id or not component_id:
            continue
        slat = raw.get("slat")
        blinds.append(
            BlindEntry(
                name=str(raw.get("blind_name") or raw.get("name") or f"Blind {component_id}"),
                zone_id=zone_id,
                component_id=component_id,
                slat=int(slat) if slat is not None else None,
                zone_name=str(raw.get("zone_name") or "") or None,
            )
        )
    return blinds


def _light_entries_from_json(result: Any) -> list[LightEntry]:
    lights: list[LightEntry] = []
    if not isinstance(result, dict):
        return lights
    for raw in result.get("lights", []) or []:
        try:
            zone_id = int(raw.get("zone_id") or raw.get("zoneID") or 0)
            component_id = int(raw.get("component_id") or raw.get("componentID") or 0)
        except Exception:
            continue
        if not zone_id or not component_id:
            continue
        state = raw.get("state")
        dimmer = raw.get("dimmer")
        lights.append(
            LightEntry(
                name=str(raw.get("light_name") or raw.get("name") or f"Light {component_id}"),
                zone_id=zone_id,
                component_id=component_id,
                state=int(state) if state is not None else None,
                dimmer=int(dimmer) if dimmer is not None else None,
                zone_name=str(raw.get("zone_name") or "") or None,
            )
        )
    return lights


def load_timing_profiles(timings_path: str | None) -> dict[str, Any]:
    if not timings_path:
        return {}
    path = Path(timings_path)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


async def async_discover_blinds(script: ScriptConfig) -> tuple[list[BlindEntry], str]:
    try:
        result = await async_run_script(script, "discover-blinds", "--json")
        blinds = _blind_entries_from_json(result)
        if blinds:
            LOGGER.info("Discovered %d blinds from live portal data", len(blinds))
            return blinds, "live portal"
        LOGGER.warning("Live portal discovery returned no blinds")
    except Exception:
        LOGGER.info("Live portal discovery failed; trying blind_timings.json fallback", exc_info=True)

    if script.timings_path:
        timings_path = Path(script.timings_path)
        profiles = await asyncio.to_thread(load_timing_profiles, str(timings_path))
        if profiles:
            blinds = _blind_entries_from_timing_profiles(profiles)
            if blinds:
                LOGGER.info(
                    "Loaded %d blinds from timings fallback %s",
                    len(blinds),
                    timings_path,
                )
                return blinds, f"timings fallback {timings_path}"
            LOGGER.info("Timings fallback file exists but did not yield any blinds: %s", timings_path)
        else:
            LOGGER.info("Timings fallback file not found: %s", timings_path)
    else:
        LOGGER.info("No timings fallback path configured")

    LOGGER.warning("No blinds discovered from live portal or timings fallback")
    return [], "none"


async def async_discover_lights(script: ScriptConfig) -> tuple[list[LightEntry], str]:
    try:
        result = await async_run_script(script, "discover-lights", "--json")
        lights = _light_entries_from_json(result)
        if lights:
            LOGGER.info("Discovered %d lights from live portal data", len(lights))
            return lights, "live portal"
        LOGGER.warning("Live portal discovery returned no lights")
    except Exception:
        LOGGER.info("Live portal light discovery failed", exc_info=True)
    return [], "none"


def _blind_entries_from_timing_profiles(payload: dict[str, Any]) -> list[BlindEntry]:
    blinds: list[BlindEntry] = []
    for key, profile in payload.items():
        if not isinstance(profile, dict):
            continue
        try:
            zone_s, component_s = str(key).split(":", 1)
            zone_id = int(zone_s)
            component_id = int(component_s)
        except Exception:
            continue
        slat = profile.get("slat")
        blinds.append(
            BlindEntry(
                name=str(profile.get("blind_name") or profile.get("name") or f"Blind {zone_id}:{component_id}"),
                zone_id=zone_id,
                component_id=component_id,
                slat=int(slat) if slat is not None else None,
                zone_name=str(profile.get("zone_name") or "") or None,
            )
        )
    blinds.sort(key=lambda item: (item.zone_id, item.component_id))
    return blinds



def load_timing_profile(timings_path: str | None, zone_id: int, component_id: int) -> dict[str, Any]:
    payload = load_timing_profiles(timings_path)
    profile = payload.get(f"{zone_id}:{component_id}")
    return profile if isinstance(profile, dict) else {}
