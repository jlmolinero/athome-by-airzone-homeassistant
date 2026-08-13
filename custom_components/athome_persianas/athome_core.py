#!/usr/bin/env python3
"""Core ATHome / Airzone Cloud API and session helpers."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

from athome_browser_utils import (
    actuate_blind_via_browser as _browser_actuate_blind_via_browser,
    calibrate_blind_timing_via_browser as _browser_calibrate_blind_timing_via_browser,
    discover_web_context_via_browser as _browser_discover_web_context_via_browser,
)


AUTH_BASE_URL = "https://m.airzonecloud.com/api/v1"
WEB_BASE_URL = "https://athome.airzonecloud.com"
BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0 Safari/537.36"
)
BLIND_TIMINGS_PATH = Path(__file__).resolve().with_name("blind_timings.json")
SESSION_JSON_PATH = Path(__file__).resolve().with_name("session.json")

BLIND_ACTION_STATES = {
    "upload": 0,
    "download": 100,
    "stop": 50,
    "slat0": 114,
    "slat45": 115,
    "slat90": 116,
}

BLIND_KEYWORDS = (
    "blind",
    "blinds",
    "persiana",
    "persianas",
    "shutter",
    "shutters",
    "louver",
    "louvers",
    "lamas",
    "slat",
    "swing",
    "blade",
    "roller",
)


def _blind_action_state(action: str, blind: dict[str, Any], override_state: int | None = None) -> int:
    if override_state is not None:
        return int(override_state)
    if action not in BLIND_ACTION_STATES:
        raise RuntimeError("Invalid action. Use upload, download, stop, slat0, slat45, or slat90.")
    slat = blind.get("slat")
    if action in {"upload", "download"} and int(slat or 0) == 1:
        return 100 if action == "upload" else 0
    return BLIND_ACTION_STATES[action]


def _blind_key(zone_id: int, component_id: int) -> str:
    return f"{int(zone_id)}:{int(component_id)}"


def _load_blind_timings() -> dict[str, Any]:
    try:
        raw = BLIND_TIMINGS_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_blind_timings(payload: dict[str, Any]) -> None:
    BLIND_TIMINGS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _get_blind_timing_profile(payload: dict[str, Any], zone_id: int, component_id: int) -> dict[str, Any]:
    return payload.get(_blind_key(zone_id, component_id), {}) if isinstance(payload, dict) else {}


def _update_blind_timing_profile(payload: dict[str, Any], zone_id: int, component_id: int, **updates: Any) -> dict[str, Any]:
    key = _blind_key(zone_id, component_id)
    profile = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(profile, dict):
        profile = {}
    profile.update(updates)
    payload[key] = profile
    return profile


@dataclass
class SessionContext:
    user_email: str
    user_token: str
    user_id: str
    device_id: str
    user_role: str = "advanced"
    user_language: str = "es"

    def to_query_params(self) -> dict[str, str]:
        return {
            "user_email": self.user_email,
            "user_token": self.user_token,
            "device_id": self.device_id,
            "user_role": self.user_role,
            "user_id": self.user_id,
            "user_language": self.user_language,
        }


@dataclass
class ApiResult:
    status: int
    headers: dict[str, str]
    body: Any


class AirzoneClient:
    def __init__(
        self,
        email: str | None = None,
        password: str | None = None,
        auth_base_url: str = AUTH_BASE_URL,
        web_base_url: str = WEB_BASE_URL,
    ) -> None:
        self.email = email
        self.password = password
        self.auth_base_url = auth_base_url.rstrip("/")
        self.web_base_url = web_base_url.rstrip("/")
        self.token: str | None = None
        self.refresh_token: str | None = None
        self.user_id: str | None = None

    def login(self) -> dict[str, Any]:
        if not self.email or not self.password:
            raise RuntimeError("Missing ATHOME_EMAIL / ATHOME_PASSWORD credentials.")
        payload = {"email": self.email, "password": self.password}
        data = self._request("POST", "/auth/login", json_body=payload, auth=False, base_url=self.auth_base_url)
        self.token = _find_first_string(data.body, ("token", "access_token", "jwt"))
        self.refresh_token = _find_first_string(data.body, ("refreshToken", "refresh_token"))
        self.user_id = _find_first_string(data.body, ("_id", "user_id", "id"))
        if not self.token:
            raise RuntimeError(
                f"Could not extract the login token. Response: {json.dumps(data.body, ensure_ascii=False)[:1000]}"
            )
        if not self.user_id:
            raise RuntimeError(
                f"Could not extract the login user_id. Response: {json.dumps(data.body, ensure_ascii=False)[:1000]}"
            )
        return data.body

    def get_system(self, session: SessionContext) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/system/",
            params=session.to_query_params(),
            json_body={},
            auth=False,
            base_url=self.web_base_url,
        ).body

    def get_components(self, session: SessionContext, zone_id: int, type_id: int) -> dict[str, Any]:
        payload = {"zoneID": int(zone_id), "typeID": int(type_id)}
        return self._request(
            "POST",
            "/api/v1/components",
            params=session.to_query_params(),
            json_body=payload,
            auth=False,
            base_url=self.web_base_url,
        ).body

    def update_component(
        self,
        session: SessionContext,
        zone_id: int,
        type_id: int,
        component_id: int,
        property_name: str,
        value: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "zoneID": int(zone_id),
            "typeID": int(type_id),
            "componentID": int(component_id),
            property_name: value,
        }
        return self._request(
            "PUT",
            "/api/v1/components",
            params=session.to_query_params(),
            json_body=payload,
            auth=False,
            base_url=self.web_base_url,
        ).body

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        auth: bool = True,
        base_url: str | None = None,
        retry_on_401: bool = True,
    ) -> ApiResult:
        url = (base_url or self.auth_base_url).rstrip("/") + path
        if params:
            url += "?" + urlencode(params)

        headers = {
            "Accept": "application/json",
            "User-Agent": BROWSER_UA,
        }
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"

        if auth:
            if not self.token:
                raise RuntimeError("No token available; call login() first.")
            headers["Authorization"] = f"Bearer {self.token}"

        body_bytes = None
        if json_body is not None:
            body_bytes = json.dumps(json_body).encode("utf-8")
        elif data is not None:
            body_bytes = urlencode(data).encode("utf-8")

        req = Request(url, data=body_bytes, headers=headers, method=method)
        try:
            with urlopen(req, timeout=30) as resp:
                raw = resp.read()
                parsed = _decode_json_or_text(raw)
                return ApiResult(resp.status, dict(resp.headers.items()), parsed)
        except HTTPError as exc:
            raw = exc.read() if hasattr(exc, "read") else b""
            parsed = _decode_json_or_text(raw)
            if exc.code == 401 and auth and retry_on_401 and self.refresh_token:
                self.refresh()
                return self._request(
                    method,
                    path,
                    params=params,
                    data=data,
                    json_body=json_body,
                    auth=auth,
                    base_url=base_url,
                    retry_on_401=False,
                )
            raise RuntimeError(
                f"HTTP {exc.code} calling {method} {path}: {json.dumps(parsed, ensure_ascii=False)[:1500]}"
            ) from None
        except URLError as exc:
            raise RuntimeError(f"Network error calling {method} {path}: {exc}") from exc

    def refresh(self) -> dict[str, Any]:
        if not self.refresh_token:
            raise RuntimeError("No refresh token available; sign in again.")
        data = self._request("GET", f"/auth/refreshToken/{quote(self.refresh_token, safe='')}", auth=False)
        self.token = _find_first_string(data.body, ("token", "access_token", "jwt"))
        self.refresh_token = _find_first_string(data.body, ("refreshToken", "refresh_token"))
        self.user_id = _find_first_string(data.body, ("_id", "user_id", "id")) or self.user_id
        if not self.token:
            raise RuntimeError(
                f"Could not extract the refreshed token. Response: {json.dumps(data.body, ensure_ascii=False)[:1000]}"
            )
        return data.body


def _decode_json_or_text(raw: bytes) -> Any:
    if not raw:
        return None
    text = raw.decode("utf-8", "replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _extract_list(obj: Any, *path: str) -> list[Any] | None:
    cur = obj
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur if isinstance(cur, list) else None


def _flatten_keys(obj: Any, prefix: str = "", depth: int = 0, max_depth: int = 3) -> list[str]:
    if depth > max_depth:
        return []
    out: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            full = f"{prefix}.{key}" if prefix else str(key)
            out.append(full)
            out.extend(_flatten_keys(value, full, depth + 1, max_depth))
    elif isinstance(obj, list):
        for i, value in enumerate(obj[:10]):
            full = f"{prefix}[{i}]" if prefix else f"[{i}]"
            out.extend(_flatten_keys(value, full, depth + 1, max_depth))
    return out


def _find_first_string(obj: Any, keys: Iterable[str]) -> str | None:
    keyset = {k.lower() for k in keys}

    def walk(value: Any) -> str | None:
        if isinstance(value, dict):
            for k, v in value.items():
                if k.lower() in keyset and isinstance(v, (str, int, float)):
                    return str(v)
            for v in value.values():
                found = walk(v)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for item in value:
                found = walk(item)
                if found is not None:
                    return found
        return None

    return walk(obj)


def _contains_keyword(value: Any) -> bool:
    text = json.dumps(value, ensure_ascii=False).lower()
    return any(keyword in text for keyword in BLIND_KEYWORDS)


def _discover_candidate_keys(obj: Any) -> list[str]:
    keys = []
    for key_path in _flatten_keys(obj, max_depth=4):
        low = key_path.lower()
        if any(keyword in low for keyword in BLIND_KEYWORDS):
            keys.append(key_path)
    return sorted(set(keys))


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def _load_credentials(args: argparse.Namespace) -> tuple[str, str]:
    email = args.email or os.environ.get("ATHOME_EMAIL")
    password = args.password or os.environ.get("ATHOME_PASSWORD")
    if not email:
        email = input("ATHome email: ").strip()
    if not password:
        password = getpass.getpass("ATHome password: ")
    return email, password


def _load_optional_credentials(args: argparse.Namespace) -> tuple[str | None, str | None]:
    return args.email or os.environ.get("ATHOME_EMAIL"), args.password or os.environ.get("ATHOME_PASSWORD")


def _session_context_from_payload(payload: dict[str, Any], fallback_email: str = "", *, user_role: str | None = None, user_language: str | None = None) -> SessionContext:
    user_email = str(payload.get("email") or fallback_email or os.environ.get("ATHOME_EMAIL") or "")
    user_token = str(payload.get("authentication_token") or payload.get("user_token") or payload.get("token") or "")
    user_id = str(payload.get("user_id") or payload.get("_id") or payload.get("id") or "")
    device_id = str(payload.get("device_id") or payload.get("deviceId") or payload.get("device") or "")
    role = str(payload.get("role") or payload.get("user_role") or user_role or os.environ.get("ATHOME_USER_ROLE") or "advanced")
    language = str(payload.get("language") or payload.get("user_language") or user_language or os.environ.get("ATHOME_USER_LANGUAGE") or "es")
    if not user_email or not user_token or not user_id or not device_id:
        raise RuntimeError(
            "The session must include email, authentication_token, user_id, and device_id (as in localStorage['Zhome.session'])."
        )
    return SessionContext(
        user_email=user_email,
        user_token=user_token,
        user_id=user_id,
        device_id=device_id,
        user_role=role,
        user_language=language,
    )


def _load_session(args: argparse.Namespace, client: AirzoneClient) -> SessionContext:
    session_raw = args.session_json or os.environ.get("ATHOME_SESSION_JSON")
    if not session_raw:
        try:
            session_raw = SESSION_JSON_PATH.read_text(encoding="utf-8").strip() or None
        except FileNotFoundError:
            session_raw = None
        except OSError:
            session_raw = None
    if session_raw:
        try:
            payload = json.loads(session_raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("ATHOME_SESSION_JSON is not valid JSON.") from exc
        if isinstance(payload, dict) and "user" in payload and isinstance(payload["user"], dict):
            payload = payload["user"]
        return _session_context_from_payload(
            payload,
            fallback_email=client.email or args.email or os.environ.get("ATHOME_EMAIL") or "",
            user_role=args.user_role,
            user_language=args.user_language,
        )

    if not client.token or not client.user_id:
        raise RuntimeError("Missing web session. Use ATHOME_SESSION_JSON or sign in with email/password.")

    device_id = args.device_id or os.environ.get("ATHOME_DEVICE_ID")
    if not device_id:
        raise RuntimeError(
            "Missing ATHOME_DEVICE_ID. For this portal, the web API needs the session device_id (see localStorage['Zhome.session'])."
        )

    user_role = args.user_role or os.environ.get("ATHOME_USER_ROLE") or "advanced"
    user_language = args.user_language or os.environ.get("ATHOME_USER_LANGUAGE") or "es"
    return SessionContext(
        user_email=client.email or args.email or os.environ.get("ATHOME_EMAIL") or "",
        user_token=client.token,
        user_id=client.user_id,
        device_id=str(device_id),
        user_role=user_role,
        user_language=user_language,
    )


def _load_system_via_api_or_browser(args: argparse.Namespace, client: AirzoneClient, *, allow_browser_fallback: bool = True) -> tuple[dict[str, Any], SessionContext]:
    has_session_json = bool(args.session_json or os.environ.get("ATHOME_SESSION_JSON"))
    has_local_session_json = SESSION_JSON_PATH.exists()
    has_device_id = bool(args.device_id or os.environ.get("ATHOME_DEVICE_ID"))
    if has_session_json or has_local_session_json or has_device_id:
        if not has_session_json and not has_local_session_json and (not client.token or not client.user_id):
            client.login()
        session = _load_session(args, client)
        client.token = session.user_token
        client.user_id = session.user_id
        return client.get_system(session), session
    if allow_browser_fallback:
        return _discover_web_context_via_browser(email=client.email or args.email or "", password=client.password or args.password or "", web_base_url=args.web_base_url)
    raise RuntimeError("Missing web session to query the system.")


def _resolve_target(system: dict[str, Any], zone_id: int, component_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
    zones = _extract_list(system, "zones") or []
    zone = next((z for z in zones if int(z.get("zoneID", -1)) == int(zone_id)), None)
    if not zone:
        raise RuntimeError(f"zoneID={zone_id} does not exist in the session.")
    blind = next((b for b in zone.get("blinds", []) if int(b.get("componentID", -1)) == int(component_id)), None)
    if not blind:
        raise RuntimeError(f"No componentID={component_id} exists in zoneID={zone_id}.")
    return zone, blind



def _discover_web_context_via_browser(email: str, password: str, web_base_url: str = WEB_BASE_URL) -> tuple[dict[str, Any], SessionContext]:
    return _browser_discover_web_context_via_browser(
        email=email,
        password=password,
        web_base_url=web_base_url,
        session_builder=_session_context_from_payload,
    )


def _calibrate_blind_timing_via_browser(
    *,
    email: str,
    password: str,
    zone_id: int,
    component_id: int,
    blind_name: str,
    timings: dict[str, Any] | None = None,
    web_base_url: str = WEB_BASE_URL,
    client: AirzoneClient | None = None,
    session: SessionContext | None = None,
    system: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _browser_calibrate_blind_timing_via_browser(
        email=email,
        password=password,
        zone_id=zone_id,
        component_id=component_id,
        blind_name=blind_name,
        session_builder=_session_context_from_payload,
        resolve_target=_resolve_target,
        timings=timings,
        web_base_url=web_base_url,
        client=client,
        session=session,
        system=system,
    )


def _actuate_blind_via_browser(
    *,
    email: str,
    password: str,
    zone_id: int,
    blind_name: str,
    action: str,
    hold_seconds: float | None = None,
    web_base_url: str = WEB_BASE_URL,
) -> dict[str, Any]:
    return _browser_actuate_blind_via_browser(
        email=email,
        password=password,
        zone_id=zone_id,
        blind_name=blind_name,
        action=action,
        session_builder=_session_context_from_payload,
        resolve_target=_resolve_target,
        hold_seconds=hold_seconds,
        web_base_url=web_base_url,
    )
