from unittest.mock import MagicMock, patch

from quorascrapper.filter.core import url_hash
from quorascrapper.ops.known_urls import (
    answer_slug,
    known_payload,
    load_known_urls,
    mongo_known_urls,
)


def test_mongo_known_urls_empty_without_uri():
    settings = MagicMock(mongodb_uri="")
    assert mongo_known_urls(settings) == set()


def test_load_known_urls_from_mongo_only():
    settings = MagicMock(mongodb_uri="mongodb+srv://x")
    with patch(
        "quorascrapper.ops.known_urls.mongo_known_urls",
        return_value={"https://pt.quora.com/answer/mongo"},
    ):
        urls = load_known_urls(settings)
    assert urls == {"https://pt.quora.com/answer/mongo"}


def test_known_payload_from_mongo():
    settings = MagicMock(mongodb_uri="mongodb+srv://x")
    with (
        patch(
            "quorascrapper.ops.known_urls.mongo_known_urls",
            return_value={"https://pt.quora.com/profile/x/answer/abc-Title"},
        ),
        patch(
            "quorascrapper.ops.known_urls.mongo_last_ingested",
            return_value={
                "url": "https://pt.quora.com/profile/x/answer/abc-Title",
                "hash": "h1",
                "ingested_at": "2026-01-01T00:00:00Z",
            },
        ),
    ):
        payload = known_payload(settings)

    assert payload["count"] == 1
    assert payload["last_ingested"]["url"].endswith("/answer/abc-Title")
    assert answer_slug("https://pt.quora.com/profile/x/answer/abc-Title") == "abc-title"


def test_mongo_known_hashes(tmp_path):
    from quorascrapper.ops.known_urls import mongo_known_hashes

    settings = MagicMock(mongodb_uri="mongodb://localhost")
    h = url_hash("https://pt.quora.com/answer/a")
    with patch(
        "quorascrapper.subscriber.storage.connect_mongo",
    ) as connect:
        collection = MagicMock()
        collection.find.return_value = [{"hash": h}]
        client = MagicMock()
        connect.return_value = (client, collection)
        found = mongo_known_hashes(settings, {h})
    assert found == {h}
    client.close.assert_called_once()


def test_mongo_known_hashes_reconnect_scopes_to_collection_name():
    """A reconnect (no pooled collection) reads from the per-profile collection."""
    import mongomock

    from quorascrapper.ops.known_urls import mongo_known_hashes

    settings = MagicMock(mongodb_uri="mongodb://localhost", mongodb_database="quora_data")
    h = url_hash("https://pt.quora.com/profile/x/answer/scoped")
    client = mongomock.MongoClient()
    # The hash exists ONLY in the per-profile collection, not the default one.
    client["quora_data"]["profile_uid"].insert_one({"hash": h})
    with patch("quorascrapper.subscriber.storage.connect_mongo") as connect:
        connect.return_value = (client, client["quora_data"]["answers"])
        found = mongo_known_hashes(settings, {h}, collection_name="profile_uid")
        # Without scoping it would read the (empty) default collection.
        unscoped = mongo_known_hashes(settings, {h})
    assert found == {h}
    assert unscoped == set()
