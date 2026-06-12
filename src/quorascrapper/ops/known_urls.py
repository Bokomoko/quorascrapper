"""Known ingested answers — MongoDB collection is the source of truth."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

from quorascrapper.config import Settings

logger = logging.getLogger(__name__)

_ANSWER_SLUG = re.compile(r"/answer/([^/?#]+)", re.IGNORECASE)


def answer_slug(url: str) -> str | None:
    match = _ANSWER_SLUG.search(url or "")
    return match.group(1).lower() if match else None


def canonical_answer_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    path = parsed.path.rstrip("/") or parsed.path
    return f"{parsed.scheme}://{parsed.netloc.lower()}{path}"


def _query_known_hashes(collection: Any, hashes: set[str]) -> set[str]:
    cursor = collection.find(
        {"hash": {"$in": list(hashes)}},
        {"hash": 1, "_id": 0},
    )
    return {doc["hash"] for doc in cursor if doc.get("hash")}


def mongo_known_hashes(
    settings: Settings,
    hashes: set[str],
    *,
    collection: Any | None = None,
) -> set[str]:
    if not hashes:
        return set()
    if collection is not None:
        try:
            return _query_known_hashes(collection, hashes)
        except Exception as exc:
            logger.warning("Mongo hash lookup skipped: %s", exc)
            return set()
    if not settings.mongodb_uri:
        return set()
    try:
        from quorascrapper.subscriber.storage import connect_mongo

        client, coll = connect_mongo(settings)
        try:
            return _query_known_hashes(coll, hashes)
        finally:
            client.close()
    except Exception as exc:
        logger.warning("Mongo hash lookup skipped: %s", exc)
        return set()


def _query_known_urls(collection: Any) -> set[str]:
    cursor = collection.find({}, {"url": 1, "_id": 0})
    return {doc["url"] for doc in cursor if doc.get("url")}


def mongo_known_urls(
    settings: Settings,
    *,
    collection: Any | None = None,
) -> set[str]:
    if collection is not None:
        try:
            return _query_known_urls(collection)
        except Exception as exc:
            logger.warning("Mongo known-url load skipped: %s", exc)
            return set()
    if not settings.mongodb_uri:
        return set()
    try:
        from quorascrapper.subscriber.storage import connect_mongo

        client, coll = connect_mongo(settings)
        try:
            return _query_known_urls(coll)
        finally:
            client.close()
    except Exception as exc:
        logger.warning("Mongo known-url load skipped: %s", exc)
        return set()


def _query_last_ingested(collection: Any) -> dict[str, Any] | None:
    doc = collection.find_one(
        {},
        {
            "url": 1,
            "hash": 1,
            "question_title": 1,
            "processed_at": 1,
            "_id": 0,
        },
        sort=[("processed_at", -1)],
    )
    if not doc:
        return None
    ingested_at = doc.get("processed_at")
    return {
        "url": doc.get("url"),
        "hash": doc.get("hash"),
        "question_title": doc.get("question_title"),
        "ingested_at": ingested_at.isoformat() if ingested_at else None,
    }


def mongo_last_ingested(
    settings: Settings,
    *,
    collection: Any | None = None,
) -> dict[str, Any] | None:
    if collection is not None:
        try:
            return _query_last_ingested(collection)
        except Exception as exc:
            logger.warning("Mongo last-ingested lookup skipped: %s", exc)
            return None
    if not settings.mongodb_uri:
        return None
    try:
        from quorascrapper.subscriber.storage import connect_mongo

        client, coll = connect_mongo(settings)
        try:
            return _query_last_ingested(coll)
        finally:
            client.close()
    except Exception as exc:
        logger.warning("Mongo last-ingested lookup skipped: %s", exc)
        return None


def known_payload(
    settings: Settings | None = None,
    *,
    collection: Any | None = None,
) -> dict[str, Any]:
    """JSON body for ``GET /known`` (MongoDB-backed).

    Pass ``collection`` to reuse an already-open pooled connection instead of
    opening (and closing) two fresh MongoDB connections per call.
    """
    settings = settings or Settings.from_env()
    urls = mongo_known_urls(settings, collection=collection)
    canonical = sorted({canonical_answer_url(u) for u in urls})
    keys = sorted({slug for u in canonical if (slug := answer_slug(u))})
    return {
        "urls": canonical,
        "keys": keys,
        "count": len(canonical),
        "last_ingested": mongo_last_ingested(settings, collection=collection),
    }


def load_known_urls(settings: Settings | None = None) -> set[str]:
    settings = settings or Settings.from_env()
    return mongo_known_urls(settings)
