from unittest.mock import patch

from quorascrapper.ops.gate import (
    EXIT_LOGIN_WALL,
    EXIT_PREFLIGHT_FAIL,
    EXIT_ZERO_URLS,
    require_scrape_gate,
    require_startup_gate,
)
from quorascrapper.ops.preflight import PreflightReport


def test_startup_gate_skipped():
    assert require_startup_gate("scraper", cli_skip=True) == 0


def test_startup_gate_fails_on_bad_report():
    report = PreflightReport(mode="scraper")
    report.add("kafka_dns", "fail", "unreachable")
    with patch("quorascrapper.ops.preflight.run_preflight", return_value=report):
        assert require_startup_gate("scraper") == EXIT_PREFLIGHT_FAIL


def test_startup_gate_passes():
    report = PreflightReport(mode="scraper")
    report.add("env_required", "pass", "ok")
    with patch("quorascrapper.ops.preflight.run_preflight", return_value=report):
        assert require_startup_gate("scraper") == 0


def test_scrape_gate_login_wall():
    assert require_scrape_gate(0, login_wall=True) == EXIT_LOGIN_WALL


def test_scrape_gate_zero_urls():
    assert require_scrape_gate(0, login_wall=False) == EXIT_ZERO_URLS


def test_scrape_gate_ok():
    assert require_scrape_gate(3, login_wall=False) == 0
