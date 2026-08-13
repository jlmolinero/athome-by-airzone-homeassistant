"""CLI parser helpers for the ATHome blind client."""

from __future__ import annotations

import argparse
from typing import Callable

CommandHandler = Callable[[argparse.Namespace], int]


def build_parser(
    *,
    auth_base_url: str,
    web_base_url: str,
    cmd_discover_blinds: CommandHandler,
    cmd_discover_lights: CommandHandler,
    cmd_seed_blind_timings: CommandHandler,
    cmd_session_help: CommandHandler,
    cmd_calibrate_blind_timings: CommandHandler,
    cmd_inspect_blind: CommandHandler,
    cmd_set_blind: CommandHandler,
    cmd_set_light: CommandHandler,
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Client for discovering and controlling blinds in ATHome / Airzone Cloud.")
    parser.add_argument("--email", help="ATHome email (if ATHOME_EMAIL is not set)")
    parser.add_argument("--password", help="ATHome password (if ATHOME_PASSWORD is not set)")
    parser.add_argument("--session-json", help="Full localStorage['Zhome.session'] JSON")
    parser.add_argument("--device-id", help="Session device_id if --session-json is not used")
    parser.add_argument("--user-role", help="Web session role (default: advanced)")
    parser.add_argument("--user-language", help="Web session language (default: es)")
    parser.add_argument("--auth-base-url", default=auth_base_url, help=f"Auth base URL (default: {auth_base_url})")
    parser.add_argument("--web-base-url", default=web_base_url, help=f"Web API base URL (default: {web_base_url})")

    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("discover-blinds", help="Discover zones and list detected blinds")
    p.add_argument("--json", action="store_true", help="Return JSON output")
    p.set_defaults(func=cmd_discover_blinds)

    p = sub.add_parser("discover-lights", help="Discover zones and list detected lights")
    p.add_argument("--json", action="store_true", help="Return JSON output")
    p.set_defaults(func=cmd_discover_lights)

    p = sub.add_parser("seed-blind-timings", help="Populate the timing file for all blinds using a base profile")
    p.set_defaults(func=cmd_seed_blind_timings)

    p = sub.add_parser("session-help", help="Show how to create session.json for Home Assistant")
    p.set_defaults(func=cmd_session_help)

    p = sub.add_parser("calibrate-blind-timings", help="Measure and store the real open/close timings for blinds")
    p.add_argument("--installation-id", "--zone-id", dest="zone_id", type=int, help="Zone ID to calibrate (optional)")
    p.add_argument("--device-id", "--component-id", dest="component_id", type=int, help="Component ID to calibrate (optional)")
    p.set_defaults(func=cmd_calibrate_blind_timings)

    p = sub.add_parser("inspect-device", aliases=("inspect-blind",), help="Show the JSON for a specific blind")
    p.add_argument("--installation-id", "--zone-id", dest="zone_id", type=int, required=True, help="Zone ID")
    p.add_argument("--device-id", "--component-id", dest="component_id", type=int, required=True, help="Component ID")
    p.set_defaults(func=cmd_inspect_blind)

    p = sub.add_parser("set-param", aliases=("set-blind",), help="Send an action to a specific blind")
    p.add_argument("--installation-id", "--zone-id", dest="zone_id", type=int, required=True, help="Zone ID")
    p.add_argument("--device-id", "--component-id", dest="component_id", type=int, required=True, help="Component ID")
    p.add_argument("--action", required=True, help="upload, download, stop, slat0, slat45, or slat90")
    p.add_argument("--state", type=int, help="Target percentage 0-100; intermediate values use calibrated timings")
    p.set_defaults(func=cmd_set_blind)

    p = sub.add_parser("set-light", help="Set a specific AtHome light on, off, or to a brightness percent")
    p.add_argument("--zone-id", dest="zone_id", type=int, required=True, help="Zone ID")
    p.add_argument("--component-id", dest="component_id", type=int, required=True, help="Component ID")
    p.add_argument("--state", type=int, help="Light state/brightness percentage 0-100")
    p.add_argument("--on", dest="turn_on", action="store_true", help="Turn the light on")
    p.add_argument("--off", dest="turn_off", action="store_true", help="Turn the light off")
    p.set_defaults(func=cmd_set_light)

    return parser


def run_cli(parser: argparse.ArgumentParser, argv: list[str] | None = None) -> int:
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("Interrupted by the user.")
        return 130
