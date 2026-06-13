"""Kafka publish + idempotency for ``qsbk serve`` (no direct Mongo writes)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from quorascrapper.config import Settings
from quorascrapper.filter.core import (
    normalize_row,
    profile_collection_name,
    profile_userid,
    url_hash,
)
from quorascrapper.messaging.kafka import KafkaSender
from quorascrapper.ops.ingest_idempotency import plan_idempotent_ingest
from quorascrapper.ops.known_urls import known_count_payload, known_payload

logger = logging.getLogger(__name__)


@dataclass
class ClassifyReport:
    new_count: int
    skipped_count: int
    skipped_mongo: int
    new: list[dict[str, str]]
    skipped_urls: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "new_count": self.new_count,
            "skipped_count": self.skipped_count,
            "skipped_mongo": self.skipped_mongo,
            "new": self.new,
            "skipped_urls": self.skipped_urls,
        }


@dataclass
class PublishReport:
    published: int
    skipped: int
    skipped_mongo: int
    urls: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "published": self.published,
            "skipped": self.skipped,
            "skipped_mongo": self.skipped_mongo,
            "urls": self.urls,
        }


def validate_serve_settings(settings: Settings) -> list[str]:
    return settings.validate_scraper()


def normalize_answers(raw: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if item.get("url") and not item.get("hash"):
            item = {**item, "hash": url_hash(str(item["url"]))}
        row = normalize_row(item)
        if row:
            rows.append(row)
    return rows


def validate_check_settings(settings: Settings) -> list[str]:
    if not settings.mongodb_uri:
        return ["MONGODB_URI is required to check answers against MongoDB"]
    return []


class ServeState:
    """Kafka publisher for serve; ``GET /known`` reads from MongoDB."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()
        self.sender: KafkaSender | None = None
        self._mongo_client: Any | None = None
        self._mongo_collection: Any | None = None

    def connect(self) -> None:
        errors = validate_serve_settings(self.settings)
        if errors:
            raise ValueError("; ".join(errors))
        self.sender = KafkaSender(settings=self.settings)
        logger.info("qsbk serve connected to Kafka at %s", self.settings.kafka_bootstrap)
        self._connect_mongo()

    def _connect_mongo(self) -> None:
        """Open one pooled MongoDB connection reused across all requests.

        Opening a fresh ``MongoClient`` per ``/upsert`` batch costs seconds of
        handshake/topology-discovery against Atlas and is the dominant cause of
        progressive throughput decay during a bulk publish. A single pooled
        client is thread-safe and shared across the ThreadingHTTPServer workers.
        """
        if not self.settings.mongodb_uri:
            return
        try:
            from quorascrapper.subscriber.storage import connect_mongo

            self._mongo_client, self._mongo_collection = connect_mongo(self.settings)
            logger.info("qsbk serve reusing pooled MongoDB connection for lookups")
        except Exception as exc:
            logger.warning(
                "qsbk serve could not open pooled MongoDB connection; "
                "idempotency lookups will reconnect per batch: %s",
                exc,
            )
            self._mongo_client = None
            self._mongo_collection = None

    def close(self) -> None:
        if self.sender is not None:
            self.sender.close()
            self.sender = None
        if self._mongo_client is not None:
            try:
                self._mongo_client.close()
            finally:
                self._mongo_client = None
                self._mongo_collection = None

    def _resolve_collection(
        self,
        *,
        profile_url: str | None = None,
        userid: str | None = None,
    ) -> tuple[Any | None, str | None]:
        """Resolve the ``(collection, collection_name)`` to read dedup/known from.

        Scopes to the profile's own ``profile_<userid>`` collection when a
        ``profile_url``/``userid`` is given; otherwise returns the default
        ("answers") pooled collection and ``None`` name (global behavior).

        When a pooled Mongo connection exists, returns the concrete per-profile
        collection object off the same client. When it does not (degraded
        reconnect-per-call path), returns ``(None, name)`` so the lookup helpers
        still scope their reconnect via ``collection_name``.
        """
        if not userid and profile_url:
            userid = profile_userid(str(profile_url))
        if not userid:
            return self._mongo_collection, None
        name = profile_collection_name(userid)
        if self._mongo_collection is not None:
            return self._mongo_collection.database[name], name
        return None, name

    def known_snapshot(self, *, profile_url: str | None = None) -> dict[str, Any]:
        collection, collection_name = self._resolve_collection(profile_url=profile_url)
        return known_payload(
            settings=self.settings,
            collection=collection,
            collection_name=collection_name,
        )

    def saved_count(self, *, profile_url: str | None = None) -> dict[str, Any]:
        """Cheap ``{"count": <int>}`` of docs persisted for this profile.

        Scopes to the profile's own ``profile_<userid>`` collection (falls back
        to the default ``answers`` collection when no ``profile_url``). Used by
        the popup's periodic "saved" poll; avoids serializing the full URL list.
        """
        collection, collection_name = self._resolve_collection(profile_url=profile_url)
        return known_count_payload(
            settings=self.settings,
            collection=collection,
            collection_name=collection_name,
        )

    def classify_answers(
        self,
        raw_rows: list[dict[str, Any]],
        *,
        force: bool = False,
        profile_url: str | None = None,
        userid: str | None = None,
    ) -> ClassifyReport:
        errors = validate_check_settings(self.settings)
        if errors:
            raise ValueError("; ".join(errors))

        rows = normalize_answers(raw_rows)
        if not rows:
            return ClassifyReport(0, 0, 0, [], [])

        collection, collection_name = self._resolve_collection(
            profile_url=profile_url, userid=userid
        )
        plan = plan_idempotent_ingest(
            rows,
            self.settings,
            force=force,
            collection=collection,
            collection_name=collection_name,
        )
        publish_hashes = {row["hash"] for row in plan.to_publish}
        new_rows = [row for row in rows if row["hash"] in publish_hashes]
        skipped_urls = [row["url"] for row in rows if row["hash"] not in publish_hashes]

        return ClassifyReport(
            new_count=len(new_rows),
            skipped_count=plan.skipped,
            skipped_mongo=plan.skipped_mongo,
            new=new_rows,
            skipped_urls=skipped_urls,
        )

    def publish_answers(
        self,
        raw_rows: list[dict[str, Any]],
        *,
        force: bool = False,
        profile_url: str | None = None,
        userid: str | None = None,
    ) -> PublishReport:
        if self.sender is None:
            raise RuntimeError("ServeState is not connected")

        report = self.classify_answers(
            raw_rows, force=force, profile_url=profile_url, userid=userid
        )
        if not report.new:
            return PublishReport(
                0,
                report.skipped_count,
                report.skipped_mongo,
                [],
            )

        published_urls: list[str] = []
        str_keys = (
            "question_title",
            "answer_preview",
            "question_url",
            "seen_at",
            "answer_text",
            "aid",
            # Readable profile identity fields carried through to Kafka/Mongo.
            "profile_name",
            "profile_url",
            "profile_display_name",
        )
        num_keys = (
            "num_upvotes",
            "num_views",
            "num_comments",
            "creation_time",
            "profile_answer_count",
        )
        for row in report.new:
            payload: dict[str, Any] = {"url": row["url"]}
            if row.get("hash"):
                payload["hash"] = row["hash"]
            for key in str_keys:
                if row.get(key):
                    payload[key] = row[key]
            for key in num_keys:
                if row.get(key) is not None:
                    payload[key] = row[key]
            # Derive a stable per-profile userid server-side from the canonical
            # profile URL; the subscriber routes by this (collection profile_<userid>).
            profile_url = row.get("profile_url")
            if profile_url:
                payload["userid"] = profile_userid(str(profile_url))
            elif row.get("userid"):
                payload["userid"] = row["userid"]
            self.sender.send(payload)
            published_urls.append(row["url"])
        self.sender.flush()

        return PublishReport(
            published=len(report.new),
            skipped=report.skipped_count,
            skipped_mongo=report.skipped_mongo,
            urls=published_urls,
        )
