"""Tests for KafkaMongoSubscriber message handling."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import kafka_subscriber as ks


class _FakeReplaceResult:
    def __init__(self, upserted_id=None):
        self.upserted_id = upserted_id


def _make_subscriber():
    sub = ks.KafkaMongoSubscriber.__new__(ks.KafkaMongoSubscriber)
    sub.messages_stored = 0
    sub.errors_count = 0
    sub.mongo_collection = MagicMock()
    return sub


def test_process_message_stores_valid_payload():
    sub = _make_subscriber()
    sub.mongo_collection.replace_one.return_value = _FakeReplaceResult(
        upserted_id="abc"
    )

    payload = json.dumps({"url": "https://example.com/answer/1", "hash": "abc123"})
    assert sub.process_message(payload) == "stored"
    assert sub.messages_stored == 1
    sub.mongo_collection.replace_one.assert_called_once()


def test_process_message_skips_invalid_json():
    sub = _make_subscriber()
    assert sub.process_message("not-json") == "skipped"
    assert sub.errors_count == 1
    sub.mongo_collection.replace_one.assert_not_called()


def test_process_message_skips_missing_url():
    sub = _make_subscriber()
    assert sub.process_message(json.dumps({"hash": "only-hash"})) == "skipped"
    sub.mongo_collection.replace_one.assert_not_called()


def test_process_message_retries_on_mongo_error():
    from pymongo.errors import PyMongoError

    sub = _make_subscriber()
    sub.mongo_collection.replace_one.side_effect = PyMongoError("down")

    payload = json.dumps({"url": "https://example.com/answer/2", "hash": "def456"})
    assert sub.process_message(payload) == "retry"
    assert sub.errors_count == 1
