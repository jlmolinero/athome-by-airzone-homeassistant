#!/usr/bin/env python3
"""ATHome / Airzone Cloud client for discovering and controlling blinds."""

from __future__ import annotations

from athome_cli_utils import build_parser as _build_cli_parser, run_cli as _run_cli
from athome_commands import (
    cmd_calibrate_blind_timings,
    cmd_discover_blinds,
    cmd_discover_lights,
    cmd_inspect_blind,
    cmd_seed_blind_timings,
    cmd_session_help,
    cmd_set_blind,
    cmd_set_light,
)
from athome_core import *  # noqa: F401,F403


def main(argv: list[str] | None = None) -> int:
    parser = _build_cli_parser(
        auth_base_url=AUTH_BASE_URL,
        web_base_url=WEB_BASE_URL,
        cmd_discover_blinds=cmd_discover_blinds,
        cmd_discover_lights=cmd_discover_lights,
        cmd_seed_blind_timings=cmd_seed_blind_timings,
        cmd_session_help=cmd_session_help,
        cmd_calibrate_blind_timings=cmd_calibrate_blind_timings,
        cmd_inspect_blind=cmd_inspect_blind,
        cmd_set_blind=cmd_set_blind,
        cmd_set_light=cmd_set_light,
    )
    return _run_cli(parser, argv)


if __name__ == "__main__":
    raise SystemExit(main())
