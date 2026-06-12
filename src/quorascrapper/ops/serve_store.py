"""Kafka publish + idempotency for ``qsbk serve`` (no direct Mongo writes)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from quorascrapper.config import Settings
from quorascrapper.filter.core import normalize_row, url_hash
from quorascrapper.messaging.kafka import KafkaSender
from quorascrapper.ops.ingest_idempotency import plan_idempotent_ingest
from quorascrapper.ops.known_urls import known_payload

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

    def connect(self) -> None:
        errors = validate_serve_settings(self.settings)
        if errors:
            raise ValueError("; ".join(errors))
        self.sender = KafkaSender(settings=self.settings)
        logger.info("qsbk serve connected to Kafka at %s", self.settings.kafka_bootstrap)

    def close(self) -> None:
        if self.sender is not None:
            self.sender.close()
            self.sender = None

    def known_snapshot(self) -> dict[str, Any]:
        return known_payload(settings=self.settings)

    def classify_answers(
        self,
        raw_rows: list[dict[str, Any]],
        *,
        force: bool = False,
    ) -> ClassifyReport:
        errors = validate_check_settings(self.settings)
        if errors:
            raise ValueError("; ".join(errors))

        rows = normalize_answers(raw_rows)
        if not rows:
            return ClassifyReport(0, 0, 0, [], [])

        plan = plan_idempotent_ingest(rows, self.settings, force=force)
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
    ) -> PublishReport:
        if self.sender is None:
            raise RuntimeError("ServeState is not connected")

        report = self.classify_answers(raw_rows, force=force)
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
        )
        num_keys = ("num_upvotes", "num_views", "num_comments", "creation_time")
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
            self.sender.send(payload)
            published_urls.append(row["url"])
        self.sender.flush()

        return PublishReport(
            published=len(report.new),
            skipped=report.skipped_count,
            skipped_mongo=report.skipped_mongo,
            urls=published_urls,
        )
