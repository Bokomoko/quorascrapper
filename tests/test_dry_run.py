from unittest.mock import MagicMock, patch

from quorascrapper.ops.dry_run import _dry_run_ok, print_dry_run_report, run_dry_run
from quorascrapper.ops.preflight import CheckResult, PreflightReport
from quorascrapper.config import Settings


def test_dry_run_ok_stdout_tolerates_kafka_fail():
    report = PreflightReport(mode="dry_run")
    report.add("kafka_broker", "fail", "down")
    report.add("chromium", "pass", "ok")
    assert _dry_run_ok(report, "stdout") is True


def test_dry_run_fail_kafka_sender():
    report = PreflightReport(mode="dry_run")
    report.add("kafka_broker", "fail", "down")
    assert _dry_run_ok(report, "kafka") is False


def test_run_dry_run_calls_preflight():
    mock_report = PreflightReport(mode="dry_run")
    mock_report.add("chromium", "pass", "ok")
    with patch("quorascrapper.ops.dry_run.run_preflight", return_value=mock_report):
        ok, report = run_dry_run(Settings(), "stdout")
    assert ok is True
    assert report is mock_report


def test_print_dry_run_report(capsys):
    report = PreflightReport(mode="dry_run")
    report.add("kafka_dns", "pass", "resolved")
    report.add("mongo_ping", "fail", "timeout")
    settings = Settings()
    print_dry_run_report(
        version="0.2.0",
        profile_url="https://example.com/answers",
        sender="stdout",
        settings=settings,
        report=report,
    )
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "kafka" in out
    assert "mongodb" in out
