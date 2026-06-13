import json
import threading
from http.client import HTTPConnection
from unittest.mock import MagicMock, patch

from quorascrapper.filter.core import profile_userid, url_hash
from quorascrapper.ops.serve import QsbkHandler, QsbkHTTPServer
from quorascrapper.ops.serve_store import ServeState


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
