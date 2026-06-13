"""MongoDB storage for subscriber messages.

Docs are routed into a per-profile collection named ``profile_<userid>`` where
``userid`` is the stable blake2s hash of the canonical profile URL (derived
server-side in ``qsbk serve``; see ``filter.core.profile_userid``). Using the
hash as the collection name keeps names Mongo-safe and fixed-length, free of
slug/Unicode edge cases. When a doc carries no ``userid`` (e.g. legacy
scroll-mode rows) it falls back to ``settings.mongodb_collection`` ("answers").
A small ``profiles`` registry collection (keyed by ``userid`` as ``_id``)
records each scraped profile.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, MongoClient  # type: ignore
from pymongo.collection import Collection  # type: ignore

from quorascrapper.config import Settings
from quorascrapper.filter.core import answer_url_kind, profile_collection_name
from quorascrapper.logging_setup import init_logging

logger = init_logging("subscriber")

# Registry collection name (fixed; not derived from a profile).
PROFILES_COLLECTION = "profiles"


def collection_name_for_doc(data: dict[str, Any], default: str) -> str:
    """Pick the target collection for a doc.

    Routes by the server-derived ``userid`` (``profile_<userid>`` via the shared
    :func:`profile_collection_name` helper); falls back to ``default``
    ("answers") when no profile identity is present.
    """
    userid = data.get("userid")
    if userid:
        return profile_collection_name(str(userid))
    return default


def connect_mongo(settings: Settings) -> tuple[MongoClient, Collection]:
    """Open a Mongo connection and return the default ("answers") collection.

    Retained for callers that only need the single fixed collection (e.g.
    ``qsbk serve`` idempotency lookups). The subscriber uses :func:`connect_router`.
    """
    client = MongoClient(settings.mongodb_uri)
    client.admin.command("ping")
    collection = client[settings.mongodb_database][settings.mongodb_collection]
    return client, collection


def connect_router(settings: Settings) -> tuple[MongoClient, "MongoRouter"]:
    client = MongoClient(settings.mongodb_uri)
    client.admin.command("ping")
    router = MongoRouter(
        client,
        database=settings.mongodb_database,
        default_collection=settings.mongodb_collection,
    )
    return client, router


def ensure_indexes(collection: Collection) -> None:
    collection.create_index(
        [("hash", ASCENDING)],
        unique=True,
        sparse=True,
        name="hash_unique",
    )


def build_document(data: dict[str, Any]) -> dict[str, Any]:
    return {
        **data,
        "processed_at": datetime.now(timezone.utc),
        "source": "quora_scraper",
    }


def upsert_answer(collection: Collection, data: dict[str, Any]) -> bool:
    """Upsert document. Returns True on success, raises PyMongoError on transient failure."""
    url = str(data.get("url") or "")
    kind = answer_url_kind(url)
    if kind == "question":
        logger.warning(
            "non_canonical_answer_url",
            extra={"event": "non_canonical_answer_url", "url": url[:200], "kind": kind},
        )
    elif kind == "invalid":
        logger.warning(
            "invalid_answer_url",
            extra={"event": "invalid_answer_url", "url": url[:200]},
        )

    document = build_document(data)
    filter_key = (
        {"hash": data["hash"]} if "hash" in data else {"url": data.get("url")}
    )
    collection.replace_one(filter_key, document, upsert=True)
    return True


class MongoRouter:
    """Routes answer docs into per-profile collections and tracks a registry.

    A single router instance is reused across all consumed messages. The unique
    ``hash`` index is created lazily the first time a collection is touched and
    cached in ``_initialized`` so we don't re-issue ``create_index`` per message.
    """

    def __init__(
        self,
        client: MongoClient,
        *,
        database: str,
        default_collection: str,
        profiles_collection: str = PROFILES_COLLECTION,
    ) -> None:
        self.client = client
        self.db = client[database]
        self.default_collection = default_collection
        self.profiles_collection_name = profiles_collection
        self._initialized: set[str] = set()

    def _collection(self, name: str) -> Collection:
        collection = self.db[name]
        if name not in self._initialized:
            ensure_indexes(collection)
            self._initialized.add(name)
        return collection

    def _profiles(self) -> Collection:
        # Registry uses userid as _id, so no extra unique index is needed.
        return self.db[self.profiles_collection_name]

    def store(self, data: dict[str, Any]) -> str:
        """Upsert the answer into its target collection and update the registry.

        Returns the collection name the doc was written to.
        """
        name = collection_name_for_doc(data, self.default_collection)
        upsert_answer(self._collection(name), data)
        self._update_registry(data, name)
        return name

    def _update_registry(self, data: dict[str, Any], collection_name: str) -> None:
        """Upsert a per-profile metadata record keyed by userid (as ``_id``).

        Only runs when the doc carries a ``userid``, so fallback ("answers")
        docs never create registry noise.
        """
        userid = data.get("userid")
        if not userid:
            return
        update: dict[str, Any] = {
            "userid": str(userid),
            "collection": collection_name,
            "updated_at": datetime.now(timezone.utc),
        }
        if data.get("profile_name"):
            update["name"] = str(data["profile_name"])
        if data.get("profile_display_name"):
            update["display_name"] = str(data["profile_display_name"])
        if data.get("profile_url"):
            update["profile_url"] = str(data["profile_url"])
        if data.get("profile_answer_count") is not None:
            update["answer_count"] = data["profile_answer_count"]
        self._profiles().update_one(
            {"_id": str(userid)},
            {"$set": update},
            upsert=True,
        )
