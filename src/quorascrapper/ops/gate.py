"""Startup and scrape outcome gates."""

from __future__ import annotations

import os
import sys
from typing import Literal

from quorascrapper.logging_setup import init_logging

logger = init_logging("gate")

StartupMode = Literal["scraper", "subscriber"]
EXIT_PREFLIGHT_FAIL = 1
EXIT_LOGIN_WALL = 2
EXIT_ZERO_URLS = 3


def skip_preflight_enabled(cli_skip: bool = False) -> bool:
    if cli_skip:
        return True
    return os.environ.get("SKIP_PREFLIGHT", "").lower() in ("1", "true", "yes")


def require_startup_gate(mode: StartupMode, *, cli_skip: bool = False) -> int:
    """Run preflight for mode. Return 0 to continue, 1 to abort."""
    if skip_preflight_enabled(cli_skip):
        logger.warning(
            "startup_gate_skipped",
            extra={"event": "startup_gate_skipped", "mode": mode},
        )
        return 0

    from quorascrapper.ops.preflight import print_report, run_preflight

    report = run_preflight(mode=mode)
    if report.ok:
        logger.info(
            "startup_gate_pass",
            extra={"event": "startup_gate_pass", "mode": mode},
        )
        return 0

    print_report(report, as_json=False)
    logger.error(
        "startup_gate_fail",
        extra={"event": "startup_gate_fail", "mode": mode},
    )
    return EXIT_PREFLIGHT_FAIL


def abort_startup(mode: StartupMode, *, cli_skip: bool = False) -> None:
    code = require_startup_gate(mode, cli_skip=cli_skip)
    if code != 0:
        sys.exit(code)


class LoginWallError(Exception):
    """Raised when Quora blocks anonymous/headless access."""


def require_scrape_gate(processed: int, login_wall: bool) -> int:
    """Validate scrape outcome. Return process exit code."""
    if login_wall:
        logger.error(
            "scrape_gate_login_wall",
            extra={"event": "scrape_gate_login_wall", "processed": processed},
        )
        return EXIT_LOGIN_WALL
    if processed == 0:
        logger.error(
            "scrape_gate_zero_urls",
            extra={"event": "scrape_gate_zero_urls"},
        )
        return EXIT_ZERO_URLS
    return 0
