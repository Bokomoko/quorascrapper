from unittest.mock import MagicMock, patch

from quorascrapper.config import Settings
from quorascrapper.ops.mongo_check import format_mongo_report, run_mongo_checks


def test_mongo_check_no_uri():
    settings = Settings(mongodb_uri="")
    report = run_mongo_checks(settings)
    assert not report.ok
    assert report.results[0].name == "mongo_config"


def test_mongo_check_dns_fail():
    settings = Settings(mongodb_uri="mongodb+srv://u:p@bad.example.net/db")
    with patch(
        "quorascrapper.ops.mongo_check.check_mongo_dns",
        return_value=(False, "DNS failed"),
    ):
        report = run_mongo_checks(settings)
    assert not report.ok
    assert any(r.name == "mongo_dns" and not r.ok for r in report.results)


def test_mongo_check_ping_ok():
    settings = Settings(
        mongodb_uri="mongodb+srv://u:p@cluster.example.net/db",
        mongodb_database="quora_data",
        mongodb_collection="answers",
    )
    mock_client = MagicMock()
    mock_client.admin.command.return_value = {"ok": 1}
    with (
        patch(
            "quorascrapper.ops.mongo_check.check_mongo_dns",
            return_value=(True, "DNS OK"),
        ),
        patch(
            "quorascrapper.ops.mongo_check.hostname_from_uri",
            return_value="cluster.example.net",
        ),
        patch("pymongo.MongoClient", return_value=mock_client),
    ):
        report = run_mongo_checks(settings)
    assert report.ok
    assert any(r.name == "mongo_ping" and r.ok for r in report.results)


def test_format_mongo_report():
    settings = Settings(mongodb_uri="")
    report = run_mongo_checks(settings)
    lines = format_mongo_report(report)
    assert any("mongo_config" in line for line in lines)
