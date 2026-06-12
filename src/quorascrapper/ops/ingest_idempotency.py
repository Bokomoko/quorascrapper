"""Idempotent ingest: skip URLs already in MongoDB."""

from __future__ import annotations

from dataclasses import dataclass

from quorascrapper.config import Settings
from quorascrapper.ops.known_urls import mongo_known_hashes


@dataclass
class IngestPlan:
    to_publish: list[dict[str, str]]
    skipped: int
    skipped_mongo: int


def plan_idempotent_ingest(
    rows: list[dict[str, str]],
    settings: Settings,
    *,
    force: bool = False,
) -> IngestPlan:
    if force or not rows:
        return IngestPlan(rows, 0, 0)

    candidate = {row["hash"] for row in rows}
    in_mongo = mongo_known_hashes(settings, candidate)

    to_publish: list[dict[str, str]] = []
    skipped_mongo = 0

    for row in rows:
        if row["hash"] in in_mongo:
            skipped_mongo += 1
            continue
        to_publish.append(row)

    return IngestPlan(
        to_publish=to_publish,
        skipped=skipped_mongo,
        skipped_mongo=skipped_mongo,
    )
