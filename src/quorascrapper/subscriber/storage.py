"""MongoDB storage for subscriber messages."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, MongoClient  # type: ignore
from pymongo.collection import Collection  # type: ignore

from quorascrapper.config import Settings
from quorascrapper.filter.core import answer_url_kind
from quorascrapper.logging_setup import init_logging

logger = init_logging("subscriber")


def connect_mongo(settings: Settings) -> tuple[MongoClient, Collection]:
    client = MongoClient(settings.mongodb_uri)
    client.admin.command("ping")
    collection = client[settings.mongodb_database][settings.mongodb_collection]
    return client, collection


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
