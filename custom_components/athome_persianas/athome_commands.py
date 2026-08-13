"""CLI command implementations for the ATHome blind client."""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any

from athome_core import (
    AUTH_BASE_URL,
    WEB_BASE_URL,
    AirzoneClient,
    BLIND_ACTION_STATES,
    BLIND_KEYWORDS,
    _actuate_blind_via_browser,
    _blind_action_state,
    _blind_key,
    _calibrate_blind_timing_via_browser,
    _contains_keyword,
    _discover_candidate_keys,
    _discover_web_context_via_browser,
    _extract_list,
    _get_blind_timing_profile,
    _load_blind_timings,
    _load_credentials,
    _load_optional_credentials,
    _load_session,
    _load_system_via_api_or_browser,
    _print_json,
    _resolve_target,
    _save_blind_timings,
    _update_blind_timing_profile,
)
from athome_cli_utils import build_parser as _build_cli_parser, run_cli as _run_cli


def _direct_calibrate_blind_timing(
    *,
    client: AirzoneClient,
    session: Any,
    system: dict[str, Any],
    zone_id: int,
    component_id: int,
    blind_name: str,
) -> dict[str, Any]:
    def _is_target_state(blind: dict[str, Any], target_state: int) -> bool:
        raw_state = blind.get("state")
        try:
            numeric_state = None if raw_state is None else int(raw_state)
        except (TypeError, ValueError):
            numeric_state = None
        return numeric_state == int(target_state)

    def _wait_for_state(target_state: int, timeout: float = 180.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        stable = 0
        last_state: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            components = client.get_components(session, zone_id, 3)
            fresh_blind = next((item for item in components if int(item.get("componentID", -1)) == int(component_id)), None)
            if fresh_blind is None:
                raise RuntimeError(f"No componentID={component_id} exists in zoneID={zone_id} components response.")
            last_state = fresh_blind
            if _is_target_state(fresh_blind, target_state):
                stable += 1
                if stable >= 2:
                    return fresh_blind
            else:
                stable = 0
            time.sleep(1.0)
        raise RuntimeError(
            f"Timeout waiting for {blind_name} (zone {zone_id}, component {component_id}) to reach state {target_state}. "
            f"Last state: {last_state}"
        )

    _zone, system_blind = _resolve_target(system, zone_id, component_id)
    components = client.get_components(session, zone_id, 3)
    initial_blind = next((item for item in components if int(item.get("componentID", -1)) == int(component_id)), system_blind)
    initial_state = initial_blind
    open_state_value = _blind_action_state("upload", initial_blind)
    close_state_value = _blind_action_state("download", initial_blind)
    if not _is_target_state(initial_blind, open_state_value):
        client.update_component(
            session=session,
            zone_id=zone_id,
            type_id=3,
            component_id=component_id,
            property_name="state",
            value=open_state_value,
        )
        initial_state = _wait_for_state(open_state_value)
        client.update_component(
            session=session,
            zone_id=zone_id,
            type_id=3,
            component_id=component_id,
            property_name="state",
            value=_blind_action_state("stop", initial_state),
        )

    close_start = time.perf_counter()
    client.update_component(
        session=session,
        zone_id=zone_id,
        type_id=3,
        component_id=component_id,
        property_name="state",
        value=close_state_value,
    )
    closed_state = _wait_for_state(close_state_value)
    close_seconds = round(time.perf_counter() - close_start, 3)
    client.update_component(
        session=session,
        zone_id=zone_id,
        type_id=3,
        component_id=component_id,
        property_name="state",
        value=_blind_action_state("stop", closed_state),
    )

    open_start = time.perf_counter()
    client.update_component(
        session=session,
        zone_id=zone_id,
        type_id=3,
        component_id=component_id,
        property_name="state",
        value=open_state_value,
    )
    open_state = _wait_for_state(open_state_value)
    open_seconds = round(time.perf_counter() - open_start, 3)
    final_components = client.get_components(session, zone_id, 3)
    final_blind = next((item for item in final_components if int(item.get("componentID", -1)) == int(component_id)), open_state)
    client.update_component(
        session=session,
        zone_id=zone_id,
        type_id=3,
        component_id=component_id,
        property_name="state",
        value=_blind_action_state("stop", final_blind),
    )
    return {
        "initial_state": initial_state,
        "closed_state": closed_state,
        "open_state": open_state,
        "final_state": final_blind,
        "open_seconds": open_seconds,
        "close_seconds": close_seconds,
        "mode": "direct_api",
    }


def cmd_seed_blind_timings(args: argparse.Namespace) -> int:
    email, password = _load_credentials(args)
    client = AirzoneClient(email=email, password=password, auth_base_url=args.auth_base_url, web_base_url=args.web_base_url)
    system, session = _load_system_via_api_or_browser(args, client)
    zones = _extract_list(system, "zones") or []
    timings = _load_blind_timings()
    reference = None
    for profile in timings.values():
        if isinstance(profile, dict) and profile.get("open_seconds") and profile.get("close_seconds"):
            reference = profile
            break
    if reference is None:
        reference = {"open_seconds": 30.0, "close_seconds": 30.0, "current_percent": 100, "source": "default"}
    filled = []
    for zone in zones:
        zone_id = zone.get("zoneID")
        for blind in zone.get("blinds") or []:
            component_id = blind.get("componentID")
            key = _blind_key(zone_id, component_id)
            if key in timings and isinstance(timings[key], dict) and timings[key].get("open_seconds") and timings[key].get("close_seconds"):
                continue
            blind_name = blind.get("name") or "(unnamed)"
            timings[key] = {
                "open_seconds": float(reference["open_seconds"]),
                "close_seconds": float(reference["close_seconds"]),
                "current_percent": int(reference.get("current_percent", 100)),
                "source": reference.get("source", "reference"),
                "reference_blind": reference.get("reference_blind", "19:3"),
                "blind_name": blind_name,
                "updated_at": time.time(),
            }
            filled.append({"zone_id": zone_id, "component_id": component_id, "blind_name": blind_name})
    _save_blind_timings(timings)
    _print_json({"ok": True, "filled": filled, "count": len(filled), "reference": reference, "session": session.to_query_params()})
    return 0


def cmd_calibrate_blind_timings(args: argparse.Namespace) -> int:
    email, password = _load_credentials(args)
    client = AirzoneClient(email=email, password=password, auth_base_url=args.auth_base_url, web_base_url=args.web_base_url)
    system: dict[str, Any] | None = None
    session: Any | None = None
    try:
        system, session = _load_system_via_api_or_browser(args, client)
    except RuntimeError as exc:
        if "Playwright is not available" not in str(exc):
            raise
        print(
            "Live web discovery needs Playwright; falling back to blind_timings.json targets and Selenium bridge calibration.",
            file=sys.stderr,
        )
    zones = _extract_list(system, "zones") if system is not None else []
    targets: list[tuple[int, int, str]] = []
    if zones:
        for zone in zones:
            zone_id = int(zone.get("zoneID"))
            if args.zone_id is not None and int(args.zone_id) != zone_id:
                continue
            for blind in zone.get("blinds") or []:
                component_id = int(blind.get("componentID"))
                if args.component_id is not None and int(args.component_id) != component_id:
                    continue
                targets.append((zone_id, component_id, blind.get("name") or f"component-{component_id}"))
    else:
        for key, profile in _load_blind_timings().items():
            if not isinstance(profile, dict):
                continue
            try:
                zone_s, component_s = str(key).split(":", 1)
                zone_id = int(zone_s)
                component_id = int(component_s)
            except Exception:
                continue
            if args.zone_id is not None and int(args.zone_id) != zone_id:
                continue
            if args.component_id is not None and int(args.component_id) != component_id:
                continue
            targets.append((zone_id, component_id, str(profile.get("blind_name") or f"component-{component_id}")))

    if not targets:
        raise RuntimeError("No blinds matched the provided filters for calibration.")

    timings = _load_blind_timings()
    results = []
    for idx, (zone_id, component_id, blind_name) in enumerate(targets, start=1):
        print(f"[calibrating {idx}/{len(targets)}] {blind_name} (zone {zone_id}, component {component_id})", file=sys.stderr)
        try:
            if client is not None and session is not None and system is not None:
                measured = _direct_calibrate_blind_timing(
                    client=client,
                    session=session,
                    system=system,
                    zone_id=zone_id,
                    component_id=component_id,
                    blind_name=blind_name,
                )
            else:
                measured = _calibrate_blind_timing_via_browser(
                    email=email,
                    password=password,
                    zone_id=zone_id,
                    component_id=component_id,
                    blind_name=blind_name,
                    timings=timings,
                    web_base_url=args.web_base_url,
                    client=client,
                    session=session,
                    system=system,
                )
        except RuntimeError as exc:
            message = str(exc)
            if "Unable to reach Selenium bridge" not in message and "Selenium bridge healthcheck failed" not in message:
                raise
            key = _blind_key(zone_id, component_id)
            existing = timings.get(key) if isinstance(timings.get(key), dict) else {}
            open_seconds = existing.get("open_seconds")
            close_seconds = existing.get("close_seconds")
            if not open_seconds or not close_seconds:
                raise RuntimeError(
                    f"Selenium bridge is unavailable and no cached timing profile exists for {blind_name} "
                    f"(zone {zone_id}, component {component_id}). Last bridge error: {message}"
                ) from exc
            print(
                f"Selenium bridge is unavailable; reusing cached timings for {blind_name} "
                f"(open={float(open_seconds):.3f}s, close={float(close_seconds):.3f}s).",
                file=sys.stderr,
            )
            measured = {
                "initial_state": {},
                "closed_state": {},
                "open_state": {},
                "final_state": {},
                "open_seconds": float(open_seconds),
                "close_seconds": float(close_seconds),
                "mode": "cached_timings_bridge_unavailable",
                "bridge_error": message,
            }
        profile = _update_blind_timing_profile(
            timings,
            zone_id,
            component_id,
            open_seconds=measured["open_seconds"],
            close_seconds=measured["close_seconds"],
            current_percent=100,
            source="measured",
            blind_name=blind_name,
            updated_at=time.time(),
            calibration=measured,
        )
        results.append({
            "zone_id": zone_id,
            "component_id": component_id,
            "blind_name": blind_name,
            "profile": profile,
            "measured": measured,
        })
        _save_blind_timings(timings)

    _print_json({"ok": True, "count": len(results), "results": results})
    return 0


def cmd_discover_blinds(args: argparse.Namespace) -> int:
    email, password = _load_optional_credentials(args)
    client = AirzoneClient(email=email, password=password, auth_base_url=args.auth_base_url, web_base_url=args.web_base_url)
    system, _session = _load_system_via_api_or_browser(args, client)
    zones = _extract_list(system, "zones") or []
    if not zones:
        if getattr(args, "json", False):
            _print_json({"ok": True, "count": 0, "zones": [], "blinds": []})
        else:
            print("No zones were found in the system.")
        return 0

    blind_count = 0
    blind_entries: list[dict[str, Any]] = []
    json_mode = bool(getattr(args, "json", False))
    if not json_mode:
        print(f"Zones found: {len(zones)}")
    for zone in zones:
        zone_id = zone.get("zoneID")
        zone_name = zone.get("name") or f"Zone {zone_id}"
        blinds = zone.get("blinds") or []
        if not blinds:
            continue
        if not json_mode:
            print(f"\n== {zone_name} [{zone_id}] ==")
        for blind in blinds:
            blind_count += 1
            component_id = blind.get("componentID")
            blind_name = blind.get("name") or "(unnamed)"
            slat = blind.get("slat")
            marker = "[BLIND]" if _contains_keyword(blind) or any(k in blind_name.lower() for k in BLIND_KEYWORDS) else ""
            if not json_mode:
                print(f"  {marker} {blind_name} [componentID={component_id}] slat={slat}")
            candidates = _discover_candidate_keys(blind)
            if candidates and not json_mode:
                print(f"     candidate keys: {', '.join(candidates[:10])}")
            blind_entries.append(
                {
                    "zone_id": zone_id,
                    "zone_name": zone_name,
                    "component_id": component_id,
                    "blind_name": blind_name,
                    "slat": slat,
                    "candidate_keys": candidates,
                }
            )

    if blind_count == 0:
        if json_mode:
            _print_json({"ok": True, "count": 0, "zones": [], "blinds": []})
        else:
            print("No blinds were found in the system.")
    else:
        if json_mode:
            _print_json({"ok": True, "count": blind_count, "zones": zones, "blinds": blind_entries})
        else:
            print(f"\nTotal blinds/blind-like devices: {blind_count}")
    return 0


def cmd_inspect_blind(args: argparse.Namespace) -> int:
    email, password = _load_optional_credentials(args)
    client = AirzoneClient(email=email, password=password, auth_base_url=args.auth_base_url, web_base_url=args.web_base_url)
    _system, session = _load_system_via_api_or_browser(args, client)
    client.token = session.user_token
    client.user_id = session.user_id
    zone, blind = _resolve_target(_system, args.zone_id, args.component_id)
    result = {
        "zone": zone,
        "blind": blind,
        "session": {
            "user_email": session.user_email,
            "user_id": session.user_id,
            "device_id": session.device_id,
            "user_role": session.user_role,
            "user_language": session.user_language,
        },
        "candidate_keys": _discover_candidate_keys({"zone": zone, "blind": blind}),
    }
    _print_json(result)
    return 0



def cmd_set_blind(args: argparse.Namespace) -> int:
    email, password = _load_optional_credentials(args)
    action = args.action.lower().strip()
    if action not in BLIND_ACTION_STATES:
        raise RuntimeError("Invalid action. Use upload, download, stop, slat0, slat45, or slat90.")

    client = AirzoneClient(email=email, password=password, auth_base_url=args.auth_base_url, web_base_url=args.web_base_url)
    system: dict[str, Any] | None = None
    timings = _load_blind_timings()
    try:
        session = _load_session(args, client)
        client.token = session.user_token
        client.user_id = session.user_id
        system = client.get_system(session)
    except RuntimeError as exc:
        raise RuntimeError(
            "AtHome web session is missing or could not query the portal. Home Assistant OS cannot use Playwright "
            "browser discovery; create or refresh /config/custom_components/athome_persianas/session.json from "
            f"localStorage['Zhome.session'] in the AtHome portal. Detail: {exc}"
        ) from exc

    zone, blind = _resolve_target(system, args.zone_id, args.component_id)
    blind_name = blind.get("name") or f"component-{args.component_id}"

    profile = _get_blind_timing_profile(timings, args.zone_id, args.component_id)
    target_percent = args.state
    if target_percent is not None and 0 < target_percent < 100:
        current_percent = profile.get("current_percent")
        if current_percent is None:
            raise RuntimeError(
                f"No percent calibration available for {zone.get('name') or args.zone_id}/{blind_name}. "
                "First store open_seconds/close_seconds and current_percent in blind_timings.json."
            )
        open_seconds = profile.get("open_seconds") or profile.get("close_seconds")
        close_seconds = profile.get("close_seconds") or profile.get("open_seconds")
        if not open_seconds or not close_seconds:
            raise RuntimeError(
                f"open_seconds/close_seconds are missing from the calibration for {zone.get('name') or args.zone_id}/{blind_name}."
            )
        current_percent = int(current_percent)
        target_percent = int(target_percent)
        move_up = target_percent > current_percent
        direction_action = "upload" if move_up else "download"
        total_seconds = float(open_seconds if move_up else close_seconds)
        hold_seconds = abs(target_percent - current_percent) * total_seconds / 100.0
        move_result = client.update_component(
            session=session,
            zone_id=args.zone_id,
            type_id=3,
            component_id=args.component_id,
            property_name="state",
            value=_blind_action_state(direction_action, blind),
        )
        if hold_seconds > 0:
            time.sleep(hold_seconds)
        stop_result = client.update_component(
            session=session,
            zone_id=args.zone_id,
            type_id=3,
            component_id=args.component_id,
            property_name="state",
            value=_blind_action_state("stop", blind),
        )
        result = {"move": move_result, "stop": stop_result, "hold_seconds": hold_seconds}
        actual_percent = target_percent
        _update_blind_timing_profile(
            timings,
            args.zone_id,
            args.component_id,
            open_seconds=float(open_seconds),
            close_seconds=float(close_seconds),
            current_percent=actual_percent,
            last_action=direction_action,
            last_hold_seconds=hold_seconds,
            updated_at=time.time(),
        )
        _save_blind_timings(timings)
        _print_json(
            {
                "ok": True,
                "action": "set-percent",
                "direction": direction_action,
                "zone_id": args.zone_id,
                "component_id": args.component_id,
                "blind_name": blind_name,
                "current_percent": current_percent,
                "target_percent": target_percent,
                "hold_seconds": hold_seconds,
                "timing_profile": _get_blind_timing_profile(timings, args.zone_id, args.component_id),
                "result": result,
            }
        )
        return 0

    state_value = _blind_action_state(action, blind, args.state)
    result = client.update_component(
        session=session,
        zone_id=args.zone_id,
        type_id=3,
        component_id=args.component_id,
        property_name="state",
        value=state_value,
    )
    if action == "upload" or state_value == 100:
        _update_blind_timing_profile(
            timings,
            args.zone_id,
            args.component_id,
            current_percent=100,
            last_action=action,
            updated_at=time.time(),
        )
    elif action == "download" or state_value == 0:
        _update_blind_timing_profile(
            timings,
            args.zone_id,
            args.component_id,
            current_percent=0,
            last_action=action,
            updated_at=time.time(),
        )
    _save_blind_timings(timings)
    _print_json(
        {
            "ok": True,
            "zone_id": args.zone_id,
            "component_id": args.component_id,
            "blind_name": blind_name,
            "action": action,
            "state": state_value,
            "result": result,
            "timing_profile": _get_blind_timing_profile(timings, args.zone_id, args.component_id),
        }
    )
    return 0


def cmd_session_help(_args: argparse.Namespace) -> int:
    print(
        """AtHome by Airzone - session.json help

Expected location in Home Assistant:
  /config/custom_components/athome_persianas/session.json

Example template:
  /config/custom_components/athome_persianas/session.example.json

Exact example path in this installation:
  /config/custom_components/athome_persianas/session.example.json

Steps:
  1. Open the ATHome portal in your browser and sign in.
  2. Open the browser console.
  3. Run: localStorage.getItem('Zhome.session')
  4. Copy the full JSON and paste it into session.json.
  5. Restart or reload the integration.

Minimum fields expected in the JSON:
  - email
  - authentication_token
  - user_id
  - device_id

Notes:
  - Do not store passwords here.
  - session.example.json is only a guide.
  - timings_path is resolved automatically to blind_timings.json.
""".strip()
    )
    return 0
