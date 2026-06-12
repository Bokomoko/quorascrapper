"""Send extension export (CSV/JSONL) to Kafka."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from quorascrapper.config import Settings, load_project_env
from quorascrapper.filter.core import load_export
from quorascrapper.messaging import KafkaSender, ServeSender, StdoutSender
from quorascrapper.ops.ingest_idempotency import plan_idempotent_ingest


def publish_rows(rows: list[dict[str, str]], sender) -> int:
    sent = 0
    for row in rows:
        payload = {"url": row["url"]}
        if row.get("hash"):
            payload["hash"] = row["hash"]
        sender.send(payload)
        sent += 1
    sender.flush()
    return sent


def main(argv: list[str] | None = None) -> int:
    load_project_env()
    settings = Settings.from_env()

    parser = argparse.ArgumentParser(
        prog="qsbk ingest",
        description="Idempotently publish extension export to Kafka (skips URLs in MongoDB).",
    )
    parser.add_argument("input", type=Path, help="Extension export (.csv, .jsonl, .json)")
    parser.add_argument(
        "--sender",
        choices=("kafka", "stdout", "serve"),
        default="kafka",
        help="Where to publish (default: kafka). Use serve when qsbk serve is running.",
    )
    parser.add_argument(
        "--serve-url",
        default="",
        help="qsbk serve base URL for --sender serve (default: QSBK_SERVE_URL or http://127.0.0.1:8765)",
    )
    parser.add_argument(
        "--topic",
        default="",
        help="Kafka topic override (default: KAFKA_TOPIC env)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Publish all rows even if already in MongoDB",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report publish/skip counts only",
    )
    args = parser.parse_args(argv)

    if not args.input.is_file():
        print(f"Not found: {args.input}", file=sys.stderr)
        return 1

    rows = load_export(args.input)
    if not rows:
        print("No /answer/ URLs found in export.", file=sys.stderr)
        return 1

    plan = plan_idempotent_ingest(rows, settings, force=args.force)

    if args.dry_run:
        print(
            f"Would publish {len(plan.to_publish)}, "
            f"skip {plan.skipped} already in MongoDB"
        )
        return 0

    if not plan.to_publish:
        print(
            f"Nothing to publish — all {len(rows)} URLs already in MongoDB "
            f"({plan.skipped_mongo} skipped)."
        )
        return 0

    if args.sender == "kafka":
        errors = settings.validate_scraper()
        if errors:
            print("; ".join(errors), file=sys.stderr)
            return 1
        topic = args.topic or settings.kafka_topic
        try:
            sender = KafkaSender(topic=topic or None, settings=settings)
        except Exception as exc:
            print(f"Kafka setup failed: {exc}", file=sys.stderr)
            return 1
    elif args.sender == "serve":
        topic = "(serve)"
        try:
            sender = ServeSender(base_url=args.serve_url or None)
        except Exception as exc:
            print(f"Serve sender setup failed: {exc}", file=sys.stderr)
            return 1
    else:
        sender = StdoutSender()
        topic = "(stdout)"

    try:
        count = publish_rows(plan.to_publish, sender)
    finally:
        sender.close()

    if args.sender == "serve":
        report = getattr(sender, "last_report", None) or {}
        dest = args.serve_url or "http://127.0.0.1:8765"
        print(
            f"Published {report.get('published', count)} messages via serve, "
            f"skipped {report.get('skipped', plan.skipped)} in MongoDB "
            f"→ Kafka (via {dest})"
        )
        return 0

    dest = settings.kafka_bootstrap if args.sender == "kafka" else "stdout"
    print(
        f"Published {count} messages, skipped {plan.skipped} in MongoDB "
        f"→ {args.sender} ({dest}, topic={topic})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
