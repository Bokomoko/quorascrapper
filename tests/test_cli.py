from unittest.mock import patch

import pytest

from quorascrapper.ops.preflight import PreflightReport
from quorascrapper.scraper.cli import main


def test_version_exits_zero():
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_dry_run_skips_browser(capsys):
    mock_report = PreflightReport(mode="dry_run")
    mock_report.add("chromium", "pass", "ok")
    with (
        patch("quorascrapper.scraper.cli.run_dry_run", return_value=(True, mock_report)),
        patch("quorascrapper.scraper.cli.print_dry_run_report"),
    ):
        code = main(["--dry-run", "--skip-preflight"])
    assert code == 0
