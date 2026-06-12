from pathlib import Path
from unittest.mock import MagicMock, patch

from quorascrapper.filter.core import url_hash
from quorascrapper.ops import ingest_idempotency as idem
from quorascrapper.ops.ingest import main, publish_rows


def test_publish_rows_sends_each_row():
    sender = MagicMock()
    publish_rows([{"url": "https://pt.quora.com/answer/x", "hash": "abc"}], sender)
    sender.send.assert_called_once()
    sender.flush.assert_called_once()


def test_plan_skips_mongo_hashes():
    h1 = url_hash("https://pt.quora.com/answer/in-db")
    rows = [{"url": "https://pt.quora.com/answer/in-db", "hash": h1}]
    settings = MagicMock(mongodb_uri="mongodb+srv://x")

    with patch("quorascrapper.ops.ingest_idempotency.mongo_known_hashes", return_value={h1}):
        plan = idem.plan_idempotent_ingest(rows, settings)

    assert plan.to_publish == []
    assert plan.skipped_mongo == 1


def test_ingest_dry_run_reports_skips(tmp_path):
    export = tmp_path / "out.jsonl"
    export.write_text(
        '{"url":"https://pt.quora.com/answer/abc"}\n',
        encoding="utf-8",
    )
    with patch(
        "quorascrapper.ops.ingest.plan_idempotent_ingest",
        return_value=idem.IngestPlan([], 1, 1),
    ):
        assert main(["--dry-run", str(export)]) == 0


def test_ingest_all_skipped_returns_zero(tmp_path, capsys):
    export = tmp_path / "out.jsonl"
    export.write_text(
        '{"url":"https://pt.quora.com/answer/abc"}\n',
        encoding="utf-8",
    )
    with patch(
        "quorascrapper.ops.ingest.plan_idempotent_ingest",
        return_value=idem.IngestPlan([], 1, 1),
    ):
        assert main([str(export)]) == 0
    assert "Nothing to publish" in capsys.readouterr().out


def test_ingest_kafka_publishes_without_local_ledger(tmp_path):
    export = tmp_path / "out.jsonl"
    export.write_text(
        '{"url":"https://pt.quora.com/answer/abc"}\n',
        encoding="utf-8",
    )
    h = url_hash("https://pt.quora.com/answer/abc")
    mock_sender = MagicMock()
    with (
        patch("quorascrapper.ops.ingest.KafkaSender", return_value=mock_sender),
        patch("quorascrapper.ops.ingest.Settings.validate_scraper", return_value=[]),
        patch(
            "quorascrapper.ops.ingest.plan_idempotent_ingest",
            return_value=idem.IngestPlan(
                [{"url": "https://pt.quora.com/answer/abc", "hash": h}],
                0,
                0,
            ),
        ),
    ):
        assert main([str(export)]) == 0
    mock_sender.send.assert_called_once()


def test_ingest_via_serve(tmp_path, capsys):
    export = tmp_path / "out.jsonl"
    export.write_text(
        '{"url":"https://pt.quora.com/answer/abc"}\n',
        encoding="utf-8",
    )
    h = url_hash("https://pt.quora.com/answer/abc")
    mock_sender = MagicMock()
    mock_sender.last_report = {"published": 1, "skipped": 0}
    with (
        patch("quorascrapper.ops.ingest.ServeSender", return_value=mock_sender),
        patch(
            "quorascrapper.ops.ingest.plan_idempotent_ingest",
            return_value=idem.IngestPlan(
                [{"url": "https://pt.quora.com/answer/abc", "hash": h}],
                0,
                0,
            ),
        ),
    ):
        assert main([str(export), "--sender", "serve"]) == 0
    out = capsys.readouterr().out
    assert "Published 1 messages via serve" in out
    mock_sender.flush.assert_called_once()
