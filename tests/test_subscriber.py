"""Tests for KafkaMongoSubscriber message handling."""

import json
from unittest.mock import MagicMock

import mongomock
from pymongo.errors import PyMongoError

from quorascrapper.config import Settings
from quorascrapper.subscriber.consumer import KafkaMongoSubscriber
from quorascrapper.subscriber.storage import ensure_indexes, upsert_answer


def _make_subscriber():
    sub = KafkaMongoSubscriber.__new__(KafkaMongoSubscriber)
    sub.messages_stored = 0
    sub.errors_count = 0
    sub.mongo_collection = MagicMock()
    return sub


def test_process_message_stores_valid_payload():
    sub = _make_subscriber()
    sub.mongo_collection.replace_one = MagicMock(return_value=MagicMock(upserted_id="abc"))

    url = "https://example.com/answer/1"
    payload = json.dumps({"url": url, "hash": "abc123"})
    assert sub.process_message(payload) == "stored"
    assert sub.messages_stored == 1


def test_process_message_skips_invalid_json():
    sub = _make_subscriber()
    assert sub.process_message("not-json") == "skipped"
    assert sub.errors_count == 1


def test_process_message_skips_missing_url():
    sub = _make_subscriber()
    assert sub.process_message(json.dumps({"hash": "only-hash"})) == "skipped"


def test_process_message_retries_on_mongo_error():
    sub = _make_subscriber()
    sub.mongo_collection.replace_one = MagicMock(side_effect=PyMongoError("down"))

    payload = json.dumps({"url": "https://example.com/answer/2", "hash": "def456"})
    assert sub.process_message(payload) == "retry"
    assert sub.errors_count == 1


def test_storage_upsert_with_mongomock():
    client = mongomock.MongoClient()
    coll = client["quora_data"]["answers"]
    ensure_indexes(coll)
    upsert_answer(coll, {"url": "https://example.com/a/1", "hash": "hash1"})
    upsert_answer(coll, {"url": "https://example.com/a/1", "hash": "hash1"})
    assert coll.count_documents({}) == 1


def test_settings_validate_subscriber():
    s = Settings(
        kafka_bootstrap="host:9092",
        mongodb_uri="mongodb+srv://user:pass@cluster.example.net/db",
    )
    assert s.validate_subscriber() == []
