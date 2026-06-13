"""Tests for KafkaMongoSubscriber message handling."""

import json
from unittest.mock import MagicMock

import mongomock
from pymongo.errors import PyMongoError

from quorascrapper.config import Settings
from quorascrapper.subscriber.consumer import KafkaMongoSubscriber
from quorascrapper.subscriber.storage import (
    MongoRouter,
    collection_name_for_doc,
    ensure_indexes,
    upsert_answer,
)


def _make_subscriber(router=None):
    sub = KafkaMongoSubscriber.__new__(KafkaMongoSubscriber)
    sub.messages_stored = 0
    sub.errors_count = 0
    sub.router = router if router is not None else MagicMock()
    return sub


def _mongomock_router():
    client = mongomock.MongoClient()
    return MongoRouter(client, database="quora_data", default_collection="answers")


def test_process_message_stores_valid_payload():
    sub = _make_subscriber()

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
    sub.router.store = MagicMock(side_effect=PyMongoError("down"))

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


# ---- routing by userid -----------------------------------------------------


def test_collection_name_for_doc_routes_by_userid_then_fallback():
    assert collection_name_for_doc({"userid": "abc123"}, "answers") == "profile_abc123"
    assert collection_name_for_doc({}, "answers") == "answers"
    # no userid -> fallback even if readable profile fields are present
    assert collection_name_for_doc({"profile_name": "alice"}, "answers") == "answers"


def test_router_routes_to_userid_collection_and_registry():
    router = _mongomock_router()
    uid = "deadbeefdeadbeefdeadbeefdeadbeef"
    name = router.store(
        {
            "url": "https://pt.quora.com/profile/alice/answer/1",
            "hash": "h1",
            "userid": uid,
            "profile_name": "alice",
            "profile_display_name": "Alice A.",
            "profile_url": "https://pt.quora.com/profile/alice",
            "profile_answer_count": 42,
        }
    )
    assert name == f"profile_{uid}"
    assert router.db[name].count_documents({}) == 1
    assert router.db["answers"].count_documents({}) == 0
    # rich readable fields survive into the doc
    doc = router.db[name].find_one({"hash": "h1"})
    assert doc["profile_name"] == "alice"
    assert doc["profile_answer_count"] == 42
    assert doc["profile_url"] == "https://pt.quora.com/profile/alice"
    # profiles registry keyed by userid (_id == userid)
    reg = router.db["profiles"].find_one({"_id": uid})
    assert reg["userid"] == uid
    assert reg["collection"] == name
    assert reg["name"] == "alice"
    assert reg["display_name"] == "Alice A."
    assert reg["answer_count"] == 42
    assert reg["profile_url"] == "https://pt.quora.com/profile/alice"
    assert "updated_at" in reg


def test_router_falls_back_without_userid():
    router = _mongomock_router()
    name = router.store({"url": "https://example.com/answer/9", "hash": "h9"})
    assert name == "answers"
    assert router.db["answers"].count_documents({}) == 1
    # no registry noise for fallback docs
    assert router.db["profiles"].count_documents({}) == 0


def test_router_upsert_is_idempotent_per_collection():
    router = _mongomock_router()
    uid = "cafef00dcafef00dcafef00dcafef00d"
    doc = {
        "url": "https://pt.quora.com/profile/alice/answer/1",
        "hash": "h1",
        "userid": uid,
        "profile_name": "alice",
    }
    router.store(doc)
    router.store(doc)
    assert router.db[f"profile_{uid}"].count_documents({}) == 1
    # registry stays a single doc keyed by userid
    assert router.db["profiles"].count_documents({"_id": uid}) == 1


def test_settings_validate_subscriber():
    s = Settings(
        kafka_bootstrap="host:9092",
        mongodb_uri="mongodb+srv://user:pass@cluster.example.net/db",
    )
    assert s.validate_subscriber() == []
