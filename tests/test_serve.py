import json
import threading
from http.client import HTTPConnection
from unittest.mock import MagicMock, patch

import mongomock

from quorascrapper.filter.core import (
    profile_collection_name,
    profile_userid,
    url_hash,
)
from quorascrapper.ops.serve import QsbkHandler, QsbkHTTPServer
from quorascrapper.ops.serve_store import ServeState


def _mongomock_state():
    """ServeState wired to an in-memory Mongo with a default + per-profile setup."""
    client = mongomock.MongoClient()
    settings = MagicMock(
        mongodb_uri="mongodb://localhost",
        mongodb_database="quora_data",
        mongodb_collection="answers",
        kafka_bootstrap="host:9092",
    )
    state = ServeState(settings=settings)
    state._mongo_client = client
    state._mongo_collection = client["quora_data"]["answers"]
    return state, client["quora_data"]


def _start_server(state: ServeState):
    server = QsbkHTTPServer(("127.0.0.1", 0), QsbkHandler, state)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port, thread


def test_ping_endpoint(tmp_path, monkeypatch):
    state = ServeState(settings=MagicMock(kafka_bootstrap="host:9092"))
    server, port, thread = _start_server(state)
    try:
        for path in ("/ping", "/health"):
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", path)
            response = conn.getresponse()
            body = json.loads(response.read().decode("utf-8"))
            conn.close()
            assert response.status == 200
            assert body["ok"] is True
            assert body["service"] == "qsbk-serve"
            assert body["kafka"] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_known_endpoint_returns_urls():
    settings = MagicMock(mongodb_uri="mongodb://localhost")
    state = ServeState(settings=settings)
    server, port, thread = _start_server(state)
    try:
        payload = {
            "urls": ["https://pt.quora.com/profile/u/answer/a"],
            "keys": ["a"],
            "count": 1,
            "last_ingested": {"url": "https://pt.quora.com/profile/u/answer/a"},
        }
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        with patch("quorascrapper.ops.serve_store.known_payload", return_value=payload):
            conn.request("GET", "/known")
            response = conn.getresponse()
            body = json.loads(response.read().decode("utf-8"))
        conn.close()

        assert response.status == 200
        assert body["count"] == 1
        assert body["last_ingested"]["url"].endswith("/answer/a")
        assert "a" in body["keys"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_check_endpoint_classifies_against_mongo():
    settings = MagicMock(mongodb_uri="mongodb://localhost")
    state = ServeState(settings=settings)
    state.sender = MagicMock()

    url_new = "https://pt.quora.com/profile/u/answer/new"
    url_old = "https://pt.quora.com/profile/u/answer/old"
    h_old = url_hash(url_old)

    server, port, thread = _start_server(state)
    try:
        payload = json.dumps(
            {
                "answers": [
                    {"url": url_new, "hash": url_hash(url_new)},
                    {"url": url_old, "hash": h_old},
                ]
            }
        )
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        with patch(
            "quorascrapper.ops.ingest_idempotency.mongo_known_hashes",
            return_value={h_old},
        ):
            conn.request(
                "POST",
                "/check",
                body=payload,
                headers={"Content-Type": "application/json"},
            )
            response = conn.getresponse()
            body = json.loads(response.read().decode("utf-8"))
        conn.close()

        assert response.status == 200
        assert body["new_count"] == 1
        assert body["skipped_count"] == 1
        assert body["skipped_mongo"] == 1
        assert body["new"][0]["url"] == url_new
        assert url_old in body["skipped_urls"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_upsert_endpoint_publishes_to_kafka():
    mock_sender = MagicMock()
    state = ServeState(settings=MagicMock(mongodb_uri="mongodb://localhost"))
    state.sender = mock_sender

    url = "https://pt.quora.com/profile/u/answer/new"
    server, port, thread = _start_server(state)
    try:
        payload = json.dumps(
            {"answers": [{"url": url, "hash": url_hash(url), "question_title": "Q"}]}
        )
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        with patch("quorascrapper.ops.ingest_idempotency.mongo_known_hashes", return_value=set()):
            conn.request(
                "POST",
                "/upsert",
                body=payload,
                headers={"Content-Type": "application/json"},
            )
            response = conn.getresponse()
            body = json.loads(response.read().decode("utf-8"))
        conn.close()

        assert response.status == 200
        assert body["published"] == 1
        mock_sender.send.assert_called_once()
        mock_sender.flush.assert_called_once()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_upsert_derives_userid_and_publishes_profile_fields():
    mock_sender = MagicMock()
    state = ServeState(settings=MagicMock(mongodb_uri="mongodb://localhost"))
    state.sender = mock_sender

    url = "https://pt.quora.com/profile/alice/answer/new"
    # Extension sends the /answers tab URL; serve must canonicalize before hashing.
    profile_url = "https://pt.quora.com/profile/alice/answers"
    server, port, thread = _start_server(state)
    try:
        payload = json.dumps(
            {
                "answers": [
                    {
                        "url": url,
                        "hash": url_hash(url),
                        "profile_name": "alice",
                        "profile_url": profile_url,
                        "profile_display_name": "Alice A.",
                        "profile_answer_count": 42,
                    }
                ]
            }
        )
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        with patch("quorascrapper.ops.ingest_idempotency.mongo_known_hashes", return_value=set()):
            conn.request(
                "POST",
                "/upsert",
                body=payload,
                headers={"Content-Type": "application/json"},
            )
            response = conn.getresponse()
            body = json.loads(response.read().decode("utf-8"))
        conn.close()

        assert response.status == 200
        assert body["published"] == 1
        sent = mock_sender.send.call_args[0][0]
        assert sent["profile_name"] == "alice"
        assert sent["profile_url"] == profile_url
        assert sent["profile_display_name"] == "Alice A."
        assert sent["profile_answer_count"] == 42
        # userid derived from the CANONICAL profile url (suffix stripped)
        assert sent["userid"] == profile_userid(profile_url)
        assert sent["userid"] == profile_userid("https://pt.quora.com/profile/alice")
        assert "profile_collection" not in sent
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_known_snapshot_scopes_to_profile_collection():
    """GET /known scoping: a profile_url reads from its own collection only."""
    state, db = _mongomock_state()

    profile_a = "https://pt.quora.com/profile/_qsbk_scopetest_A/answers"
    name_a = profile_collection_name(profile_userid(profile_a))
    url_a = "https://pt.quora.com/profile/_qsbk_scopetest_A/answer/aaa"
    db[name_a].insert_one({"url": url_a, "hash": url_hash(url_a)})

    # Global "answers" holds an unrelated legacy doc (e.g. João Eurico's data).
    url_legacy = "https://pt.quora.com/profile/legacy/answer/zzz"
    db["answers"].insert_one({"url": url_legacy, "hash": url_hash(url_legacy)})

    # (a) Profile A → only its own answer, not the legacy one.
    snap_a = state.known_snapshot(profile_url=profile_a)
    assert snap_a["count"] == 1
    assert url_a in snap_a["urls"]
    assert url_legacy not in snap_a["urls"]

    # (b) Profile B (never published) → EMPTY (isolation; not contaminated).
    snap_b = state.known_snapshot(
        profile_url="https://pt.quora.com/profile/_qsbk_scopetest_B"
    )
    assert snap_b["count"] == 0
    assert snap_b["urls"] == []

    # (c) No profile_url → global default ("answers") behavior preserved.
    snap_default = state.known_snapshot()
    assert snap_default["count"] == 1
    assert url_legacy in snap_default["urls"]


def test_classify_dedup_scoped_per_profile():
    """The dedup bug fix: a hash present only in the global "answers" collection
    must NOT mark a profile's re-scrape as a known duplicate."""
    state, db = _mongomock_state()

    url = "https://pt.quora.com/profile/_qsbk_scopetest_A/answer/dup"
    h = url_hash(url)
    profile_a = "https://pt.quora.com/profile/_qsbk_scopetest_A"

    # The hash exists ONLY in the legacy global "answers" collection.
    db["answers"].insert_one({"url": url, "hash": h})

    # Scoped to profile A (its own collection is empty) → counts as NEW.
    report_a = state.classify_answers([{"url": url, "hash": h}], profile_url=profile_a)
    assert report_a.new_count == 1
    assert report_a.skipped_mongo == 0

    # No profile (global) → the legacy duplicate is found and skipped.
    report_default = state.classify_answers([{"url": url, "hash": h}])
    assert report_default.new_count == 0
    assert report_default.skipped_mongo == 1


def test_known_endpoint_passes_profile_url_query_to_state():
    """do_GET parses ?profile_url= and forwards it to known_snapshot."""
    state = ServeState(settings=MagicMock(mongodb_uri="mongodb://localhost"))
    captured = {}

    def fake_snapshot(*, profile_url=None):
        captured["profile_url"] = profile_url
        return {"urls": [], "keys": [], "count": 0, "last_ingested": None}

    state.known_snapshot = fake_snapshot  # type: ignore[method-assign]
    server, port, thread = _start_server(state)
    try:
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(
            "GET",
            "/known?profile_url=https%3A%2F%2Fpt.quora.com%2Fprofile%2Falice",
        )
        response = conn.getresponse()
        response.read()
        conn.close()
        assert response.status == 200
        assert captured["profile_url"] == "https://pt.quora.com/profile/alice"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_check_endpoint_forwards_profile_url_to_classify():
    """POST /check forwards a body-level profile_url into classify_answers."""
    state = ServeState(settings=MagicMock(mongodb_uri="mongodb://localhost"))
    captured = {}
    real_classify = state.classify_answers

    def wrapper(raw_rows, *, force=False, profile_url=None, userid=None):
        captured["profile_url"] = profile_url
        return real_classify(
            raw_rows, force=force, profile_url=profile_url, userid=userid
        )

    state.classify_answers = wrapper  # type: ignore[method-assign]
    url = "https://pt.quora.com/profile/alice/answer/x"
    server, port, thread = _start_server(state)
    try:
        payload = json.dumps(
            {
                "answers": [{"url": url, "hash": url_hash(url)}],
                "profile_url": "https://pt.quora.com/profile/alice",
            }
        )
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        with patch(
            "quorascrapper.ops.ingest_idempotency.mongo_known_hashes",
            return_value=set(),
        ):
            conn.request(
                "POST",
                "/check",
                body=payload,
                headers={"Content-Type": "application/json"},
            )
            response = conn.getresponse()
            response.read()
        conn.close()
        assert response.status == 200
        assert captured["profile_url"] == "https://pt.quora.com/profile/alice"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_upsert_skips_duplicate():
    mock_sender = MagicMock()
    state = ServeState(settings=MagicMock(mongodb_uri="mongodb://localhost"))
    state.sender = mock_sender

    url = "https://pt.quora.com/profile/u/answer/existing"
    h = url_hash(url)
    server, port, thread = _start_server(state)
    try:
        payload = json.dumps({"answers": [{"url": url, "hash": h}]})
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        with patch(
            "quorascrapper.ops.ingest_idempotency.mongo_known_hashes",
            return_value={h},
        ):
            conn.request(
                "POST",
                "/upsert",
                body=payload,
                headers={"Content-Type": "application/json"},
            )
            response = conn.getresponse()
            body = json.loads(response.read().decode("utf-8"))
        conn.close()

        assert response.status == 200
        assert body["published"] == 0
        assert body["skipped"] == 1
        mock_sender.send.assert_not_called()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
