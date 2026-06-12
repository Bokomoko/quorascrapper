from quorascrapper.filter.core import url_hash
from quorascrapper.ops.ingest_idempotency import plan_idempotent_ingest
from quorascrapper.config import Settings
from unittest.mock import MagicMock, patch


def test_force_publishes_all():
    h = url_hash("https://pt.quora.com/answer/a")
    rows = [{"url": "https://pt.quora.com/answer/a", "hash": h}]
    plan = plan_idempotent_ingest(
        rows,
        Settings(mongodb_uri="mongodb://localhost"),
        force=True,
    )
    assert len(plan.to_publish) == 1
    assert plan.skipped == 0


def test_skips_mongo_hashes():
    h1 = url_hash("https://pt.quora.com/answer/in-db")
    h2 = url_hash("https://pt.quora.com/answer/new")
    rows = [
        {"url": "https://pt.quora.com/answer/in-db", "hash": h1},
        {"url": "https://pt.quora.com/answer/new", "hash": h2},
    ]
    settings = MagicMock(mongodb_uri="mongodb+srv://x")

    with patch(
        "quorascrapper.ops.ingest_idempotency.mongo_known_hashes",
        return_value={h1},
    ):
        plan = plan_idempotent_ingest(rows, settings)

    assert len(plan.to_publish) == 1
    assert plan.to_publish[0]["hash"] == h2
    assert plan.skipped_mongo == 1
