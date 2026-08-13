"""Browser automation helpers for ATHome blind discovery and calibration."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ResolveTarget = Callable[[dict[str, Any], int, int], tuple[dict[str, Any], dict[str, Any]]]
SessionBuilder = Callable[[dict[str, Any], str], Any]
DEFAULT_SELENIUM_BRIDGE_URL = os.environ.get("ATHOME_SELENIUM_BRIDGE_URL", "http://local_airzone_selenium_bridge:8099")


def _bridge_request_json(bridge_url: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 15.0) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{bridge_url.rstrip('/')}{path}",
        data=data,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except URLError as exc:
        raise RuntimeError(f"Unable to reach Selenium bridge at {bridge_url}{path}: {exc}") from exc
    if not raw:
        return {}
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}


def _bridge_healthcheck(bridge_url: str) -> dict[str, Any]:
    return _bridge_request_json(bridge_url, "/health", timeout=10.0)


def _bridge_is_healthy(health: dict[str, Any]) -> bool:
    return bool(health.get("ok")) or str(health.get("status") or "").lower() == "ok"


def _bridge_command(bridge_url: str, *, action: str, zone_number: int, blind_button: int | str, username: str, password: str) -> dict[str, Any]:
    return _bridge_request_json(
        bridge_url,
        "/command",
        payload={
            "action": action,
            "zone_number": int(zone_number),
            "blind_button": str(blind_button),
            "username": username,
            "password": password,
        },
        timeout=120.0,
    )


def _api_blind_is_endpoint(blind: dict[str, Any], endpoint: str) -> bool:
    position = str(blind.get("position") or "").strip().lower()
    raw_state = blind.get("state")
    try:
        numeric_state = None if raw_state is None else int(raw_state)
    except (TypeError, ValueError):
        numeric_state = None
    if endpoint == "open":
        return position in {"up", "up3", "upload", "open"} or numeric_state == 100 or raw_state == "open"
    if endpoint == "closed":
        return position in {"down", "down3", "download", "close", "closed"} or numeric_state == 0 or raw_state == "closed"
    raise ValueError(endpoint)


def _wait_for_api_endpoint(client: Any, session: Any, *, zone_id: int, component_id: int, endpoint: str, timeout: float = 180.0, poll_seconds: float = 1.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    stable = 0
    last_state: dict[str, Any] | None = None
    last_error: str | None = None
    while time.monotonic() < deadline:
        try:
            system = client.get_system(session)
            zone, blind = _resolve_target(system, zone_id, component_id)
            del zone
            last_state = blind
            last_error = None
        except Exception as exc:  # pragma: no cover - runtime guard
            last_error = str(exc)
            time.sleep(poll_seconds)
            continue
        if _api_blind_is_endpoint(last_state, endpoint):
            stable += 1
            if stable >= 2:
                return last_state
        else:
            stable = 0
        time.sleep(poll_seconds)
    raise RuntimeError(
        f"Timeout waiting for zone {zone_id} component {component_id} to reach {endpoint}. Last state: {json.dumps(last_state, ensure_ascii=False)}. Last error: {last_error}"
    )



def discover_web_context_via_browser(*, email: str, password: str, web_base_url: str, session_builder: SessionBuilder) -> tuple[dict[str, Any], Any]:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "Playwright is not available. Install it with `python3 -m pip install playwright` to use web discovery."
        ) from exc

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=os.environ.get("ATHOME_CHROMIUM") or "/usr/bin/chromium")
        context = browser.new_context(viewport={"width": 1440, "height": 1200})
        page = context.new_page()
        page.goto(web_base_url, wait_until="domcontentloaded")

        email_locator = page.locator('input[type="email"], input[placeholder*="Email" i], input[name*="email" i]').first
        password_locator = page.locator('input[type="password"], input[placeholder*="Password" i], input[name*="password" i]').first
        email_locator.fill(email)
        password_locator.fill(password)
        try:
            page.get_by_role("button", name="Sign in").click()
        except Exception:
            page.locator('button, input[type="submit"]').first.click()

        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except PlaywrightTimeoutError:
            pass

        try:
            page.wait_for_function(
                "() => document.body && document.body.innerText && (document.body.innerText.includes('Zones') || document.body.innerText.includes('Home'))",
                timeout=30000,
            )
        except PlaywrightTimeoutError:
            pass

        system = page.evaluate(
            """
            async () => {
              const inj = angular.element(document.body).injector();
              const svc = inj.get('SystemService');
              const cached = svc.getCacheSystem && svc.getCacheSystem();
              if (cached && Object.keys(cached).length) return cached;
              return await svc.getSystem();
            }
            """
        )
        session_raw = page.evaluate("localStorage.getItem('Zhome.session')")
        if not session_raw:
            href = page.evaluate("window.location.href")
            raise RuntimeError(f"Could not read localStorage['Zhome.session'] after signing in. URL: {href}")
        try:
            session_payload = json.loads(session_raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("localStorage['Zhome.session'] does not contain valid JSON.") from exc
        if isinstance(session_payload, dict) and "user" in session_payload and isinstance(session_payload["user"], dict):
            session_payload = session_payload["user"]
        session = session_builder(session_payload, email)
        context.close()
        browser.close()
        return system, session


def _read_blind_runtime_state(page: Any, blind_name: str, component_id: int | None = None) -> dict[str, Any]:
    js = """
        ({ blindName, componentId }) => {
          const needle = String(blindName || '').trim().toLowerCase();
          const wantedId = componentId == null ? null : Number(componentId);
          const cards = [...document.querySelectorAll('.switch')];
          const card = cards.find(el => {
            const comp = angular.element(el).isolateScope().component;
            if (wantedId != null && Number(comp.componentID) === wantedId) return true;
            return needle && String(comp.name || '').trim().toLowerCase().includes(needle);
          });
          if (!card) throw new Error(`Could not find blind ${blindName}`);
          const comp = angular.element(card).isolateScope().component;
          const title = card.querySelector('.switch__title');
          return {
            title: (title && title.textContent || '').trim(),
            position: comp.position ?? null,
            state: comp.state ?? null,
            actionState: comp.actionState ?? null,
            oldState: comp.oldState ?? null,
            slat: comp.slat ?? null,
            name: comp.name ?? null,
            componentID: comp.componentID ?? null,
          };
        }
    """
    return page.evaluate(js, {"blindName": blind_name, "componentId": component_id})


def _is_blind_endpoint(state: dict[str, Any], endpoint: str) -> bool:
    position = str(state.get("position") or "").strip().lower()
    raw_state = state.get("state")
    if endpoint == "open":
        return position in {"up", "up3"} or raw_state == 100
    if endpoint == "closed":
        return position in {"down", "down3"} or raw_state == 0
    raise ValueError(endpoint)


def _wait_for_blind_endpoint(page: Any, blind_name: str, endpoint: str, timeout: float = 180.0, poll_seconds: float = 1.0, component_id: int | None = None) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    stable = 0
    last_state: dict[str, Any] | None = None
    last_error: str | None = None
    while time.monotonic() < deadline:
        try:
            last_state = _read_blind_runtime_state(page, blind_name, component_id=component_id)
            last_error = None
        except Exception as exc:
            last_error = str(exc)
            time.sleep(poll_seconds)
            continue
        if _is_blind_endpoint(last_state, endpoint):
            stable += 1
            if stable >= 2:
                return last_state
        else:
            stable = 0
        time.sleep(poll_seconds)
    raise RuntimeError(
        f"Timeout waiting for {blind_name} to reach {endpoint}. Last state: {json.dumps(last_state, ensure_ascii=False)}. Last error: {last_error}"
    )


def _command_blind_action(page: Any, blind_name: str, action: str, component_id: int | None = None) -> dict[str, Any]:
    return page.evaluate(
        """
        ({ blindName, componentId, action }) => {
          const needle = String(blindName || '').trim().toLowerCase();
          const wantedId = componentId == null ? null : Number(componentId);
          const cards = [...document.querySelectorAll('.switch')];
          const card = cards.find(el => {
            const comp = angular.element(el).isolateScope().component;
            if (wantedId != null && Number(comp.componentID) === wantedId) return true;
            return needle && String(comp.name || '').trim().toLowerCase().includes(needle);
          });
          if (!card) throw new Error(`Could not find blind ${blindName}`);
          const comp = angular.element(card).isolateScope().component;
          const before = { position: comp.position, state: comp.state, actionState: comp.actionState, oldState: comp.oldState };
          const fn = comp.setBlindStatusFn || comp.turnStatusFn;
          if (!fn) throw new Error('The component does not expose setBlindStatusFn/turnStatusFn');
          fn.call(comp, action);
          return { before, after: { position: comp.position, state: comp.state, actionState: comp.actionState, oldState: comp.oldState } };
        }
        """,
        {"blindName": blind_name, "componentId": component_id, "action": action},
    )


def calibrate_blind_timing_via_browser(
    *,
    email: str,
    password: str,
    zone_id: int,
    component_id: int,
    blind_name: str,
    session_builder: SessionBuilder,
    resolve_target: ResolveTarget,
    timings: dict[str, Any] | None = None,
    web_base_url: str,
    client: Any | None = None,
    session: Any | None = None,
    system: dict[str, Any] | None = None,
    bridge_url: str | None = None,
) -> dict[str, Any]:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        bridge_url = (bridge_url or DEFAULT_SELENIUM_BRIDGE_URL).rstrip("/")
        health = _bridge_healthcheck(bridge_url)
        if not _bridge_is_healthy(health):
            raise RuntimeError(f"Selenium bridge healthcheck failed: {health}")
        if client is None or session is None:
            blind_button = component_id
            _bridge_command(bridge_url, action="open", zone_number=zone_id, blind_button=blind_button, username=email, password=password)
            _bridge_command(bridge_url, action="stop", zone_number=zone_id, blind_button=blind_button, username=email, password=password)

            close_start = time.perf_counter()
            closed_state = _bridge_command(bridge_url, action="close", zone_number=zone_id, blind_button=blind_button, username=email, password=password)
            close_seconds = round(time.perf_counter() - close_start, 3)
            _bridge_command(bridge_url, action="stop", zone_number=zone_id, blind_button=blind_button, username=email, password=password)

            open_start = time.perf_counter()
            open_state = _bridge_command(bridge_url, action="open", zone_number=zone_id, blind_button=blind_button, username=email, password=password)
            open_seconds = round(time.perf_counter() - open_start, 3)
            final_state = _bridge_command(bridge_url, action="stop", zone_number=zone_id, blind_button=blind_button, username=email, password=password)
            if timings is not None:
                timings[f"{zone_id}:{component_id}"] = {
                    **timings.get(f"{zone_id}:{component_id}", {}),
                    "open_seconds": open_seconds,
                    "close_seconds": close_seconds,
                    "current_percent": 100,
                    "last_action": "upload",
                    "updated_at": time.time(),
                    "blind_name": blind_name,
                    "calibration_stage": "bridge_measured",
                }
            return {
                "initial_state": {},
                "closed_state": closed_state,
                "open_state": open_state,
                "final_state": final_state,
                "open_seconds": open_seconds,
                "close_seconds": close_seconds,
                "bridge_health": health,
                "mode": "selenium_bridge",
            }
        if system is None:
            system = client.get_system(session)
        zone, blind = resolve_target(system, zone_id, component_id)
        del zone
        blind_button = blind.get("componentID") or component_id
        initial_state = blind
        if timings is not None:
            timings_key = f"{zone_id}:{component_id}"
            timings[timings_key] = {
                **(timings.get(timings_key, {}) if isinstance(timings, dict) else {}),
                "blind_name": blind_name,
                "current_percent": 100 if _api_blind_is_endpoint(initial_state, "open") else initial_state.get("state"),
                "last_action": "upload" if _api_blind_is_endpoint(initial_state, "open") else None,
                "updated_at": time.time(),
                "calibration_stage": "initial",
            }
        if not _api_blind_is_endpoint(initial_state, "open"):
            _bridge_command(bridge_url, action="open", zone_number=zone_id, blind_button=blind_button, username=email, password=password)
            closed_to_open = _wait_for_api_endpoint(client, session, zone_id=zone_id, component_id=component_id, endpoint="open")
            _bridge_command(bridge_url, action="stop", zone_number=zone_id, blind_button=blind_button, username=email, password=password)
            if timings is not None:
                timings[f"{zone_id}:{component_id}"] = {
                    **timings.get(f"{zone_id}:{component_id}", {}),
                    "blind_name": blind_name,
                    "current_percent": 100,
                    "last_action": "upload",
                    "updated_at": time.time(),
                    "calibration_stage": "raised",
                }
            initial_state = closed_to_open

        close_start = time.perf_counter()
        _bridge_command(bridge_url, action="close", zone_number=zone_id, blind_button=blind_button, username=email, password=password)
        closed_state = _wait_for_api_endpoint(client, session, zone_id=zone_id, component_id=component_id, endpoint="closed")
        close_seconds = round(time.perf_counter() - close_start, 3)
        _bridge_command(bridge_url, action="stop", zone_number=zone_id, blind_button=blind_button, username=email, password=password)
        if timings is not None:
            timings[f"{zone_id}:{component_id}"] = {
                **timings.get(f"{zone_id}:{component_id}", {}),
                "blind_name": blind_name,
                "current_percent": 0,
                "last_action": "download",
                "updated_at": time.time(),
                "calibration_stage": "closed",
            }

        open_start = time.perf_counter()
        _bridge_command(bridge_url, action="open", zone_number=zone_id, blind_button=blind_button, username=email, password=password)
        open_state = _wait_for_api_endpoint(client, session, zone_id=zone_id, component_id=component_id, endpoint="open")
        open_seconds = round(time.perf_counter() - open_start, 3)
        _bridge_command(bridge_url, action="stop", zone_number=zone_id, blind_button=blind_button, username=email, password=password)
        if timings is not None:
            timings[f"{zone_id}:{component_id}"] = {
                **timings.get(f"{zone_id}:{component_id}", {}),
                "open_seconds": open_seconds,
                "close_seconds": close_seconds,
                "current_percent": 100,
                "last_action": "upload",
                "updated_at": time.time(),
                "blind_name": blind_name,
                "calibration_stage": "measured",
            }

        final_state = _wait_for_api_endpoint(client, session, zone_id=zone_id, component_id=component_id, endpoint="open")
        return {
            "initial_state": initial_state,
            "closed_state": closed_state,
            "open_state": open_state,
            "final_state": final_state,
            "open_seconds": open_seconds,
            "close_seconds": close_seconds,
            "bridge_health": health,
        }

    system, session = discover_web_context_via_browser(
        email=email,
        password=password,
        web_base_url=web_base_url,
        session_builder=session_builder,
    )
    resolve_target(system, zone_id, component_id)

    query = session.to_query_params()
    url = f"{web_base_url.rstrip('/')}/athome/#/main/zone/{int(zone_id)}/blinds?{urlencode(query)}"
    chromium_path = os.environ.get("ATHOME_CHROMIUM") or "/usr/bin/chromium"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=chromium_path)
        context = browser.new_context(viewport={"width": 1440, "height": 1200})
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except PlaywrightTimeoutError:
            pass

        page.wait_for_function(
            "blindName => [...document.querySelectorAll('.switch__title')].some(x => (x.textContent || '').trim().toLowerCase().includes(String(blindName).trim().toLowerCase()))",
            arg=blind_name,
            timeout=60000,
        )

        initial_state = _read_blind_runtime_state(page, blind_name, component_id=component_id)
        if timings is not None:
            timings_key = f"{zone_id}:{component_id}"
            timings[timings_key] = {
                **(timings.get(timings_key, {}) if isinstance(timings, dict) else {}),
                "blind_name": blind_name,
                "current_percent": 100 if _is_blind_endpoint(initial_state, "open") else initial_state.get("state"),
                "last_action": "upload" if _is_blind_endpoint(initial_state, "open") else None,
                "updated_at": time.time(),
                "calibration_stage": "initial",
            }
        if not _is_blind_endpoint(initial_state, "open"):
            _command_blind_action(page, blind_name, "upload", component_id=component_id)
            _wait_for_blind_endpoint(page, blind_name, "open", component_id=component_id)
            _command_blind_action(page, blind_name, "stop", component_id=component_id)
            if timings is not None:
                timings[f"{zone_id}:{component_id}"] = {
                    **timings.get(f"{zone_id}:{component_id}", {}),
                    "blind_name": blind_name,
                    "current_percent": 100,
                    "last_action": "upload",
                    "updated_at": time.time(),
                    "calibration_stage": "raised",
                }

        close_start = time.perf_counter()
        _command_blind_action(page, blind_name, "download", component_id=component_id)
        closed_state = _wait_for_blind_endpoint(page, blind_name, "closed", component_id=component_id)
        close_seconds = round(time.perf_counter() - close_start, 3)
        _command_blind_action(page, blind_name, "stop", component_id=component_id)
        if timings is not None:
            timings[f"{zone_id}:{component_id}"] = {
                **timings.get(f"{zone_id}:{component_id}", {}),
                "blind_name": blind_name,
                "current_percent": 0,
                "last_action": "download",
                "updated_at": time.time(),
                "calibration_stage": "closed",
            }

        open_start = time.perf_counter()
        _command_blind_action(page, blind_name, "upload", component_id=component_id)
        open_state = _wait_for_blind_endpoint(page, blind_name, "open", component_id=component_id)
        open_seconds = round(time.perf_counter() - open_start, 3)
        _command_blind_action(page, blind_name, "stop", component_id=component_id)
        if timings is not None:
            timings[f"{zone_id}:{component_id}"] = {
                **timings.get(f"{zone_id}:{component_id}", {}),
                "open_seconds": open_seconds,
                "close_seconds": close_seconds,
                "current_percent": 100,
                "last_action": "upload",
                "updated_at": time.time(),
                "blind_name": blind_name,
                "calibration_stage": "measured",
            }

        final_state = _read_blind_runtime_state(page, blind_name, component_id=component_id)
        context.close()
        browser.close()
        return {
            "initial_state": initial_state,
            "closed_state": closed_state,
            "open_state": open_state,
            "final_state": final_state,
            "open_seconds": open_seconds,
            "close_seconds": close_seconds,
        }


def actuate_blind_via_browser(
    *,
    email: str,
    password: str,
    zone_id: int,
    blind_name: str,
    action: str,
    session_builder: SessionBuilder,
    resolve_target: ResolveTarget,
    hold_seconds: float | None = None,
    web_base_url: str,
) -> dict[str, Any]:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "Playwright is not available. Install it with `python3 -m pip install playwright` to control blinds."
        ) from exc

    system, session = discover_web_context_via_browser(
        email=email,
        password=password,
        web_base_url=web_base_url,
        session_builder=session_builder,
    )
    zone, blind = resolve_target(
        system,
        zone_id,
        next(
            b.get("componentID")
            for b in next(z for z in system.get("zones", []) if int(z.get("zoneID", -1)) == int(zone_id)).get("blinds", [])
            if b.get("name") == blind_name
        ),
    )
    del zone, blind

    query = session.to_query_params()
    url = f"{web_base_url.rstrip('/')}/athome/#/main/zone/{int(zone_id)}/blinds?{urlencode(query)}"
    chromium_path = os.environ.get("ATHOME_CHROMIUM") or "/usr/bin/chromium"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=chromium_path)
        context = browser.new_context(viewport={"width": 1440, "height": 1200})
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except PlaywrightTimeoutError:
            pass

        move_result = _command_blind_action(page, blind_name, action)
        stop_result = None
        if hold_seconds is not None and hold_seconds > 0:
            page.wait_for_timeout(int(hold_seconds * 1000))
            stop_result = _command_blind_action(page, blind_name, "stop")
        try:
            page.wait_for_timeout(1000)
        except Exception:
            pass
        context.close()
        browser.close()
        return {"move": move_result, "stop": stop_result, "hold_seconds": hold_seconds}
