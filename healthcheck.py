#!/usr/bin/env python3
"""Container health probes for subscriber and scraper services."""

import os
import sys


def check_subscriber() -> int:
    """Verify Kafka broker reachability and MongoDB ping."""
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP", "bokomint.local:19092")
    mongodb_uri = os.environ.get("MONGODB_URI")

    if not mongodb_uri:
        print("MONGODB_URI not set", file=sys.stderr)
        return 1

    try:
        from confluent_kafka.admin import AdminClient  # type: ignore

        admin = AdminClient({"bootstrap.servers": bootstrap})
        admin.list_topics(timeout=5)
    except Exception as exc:
        print(f"Kafka check failed: {exc}", file=sys.stderr)
        return 1

    try:
        from pymongo import MongoClient  # type: ignore

        client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        client.close()
    except Exception as exc:
        print(f"MongoDB check failed: {exc}", file=sys.stderr)
        return 1

    return 0


def check_scraper() -> int:
    """Verify Selenium import and Chrome/Chromium binary availability."""
    try:
        import selenium  # noqa: F401
    except ImportError as exc:
        print(f"Selenium check failed: {exc}", file=sys.stderr)
        return 1

    chrome = os.environ.get("CHROME_BINARY", "/usr/bin/chromium")
    if not os.path.isfile(chrome):
        print(f"Chrome binary not found: {chrome}", file=sys.stderr)
        return 1

    return 0


def main() -> int:
    mode = (
        sys.argv[1]
        if len(sys.argv) > 1
        else os.environ.get("HEALTHCHECK_MODE", "subscriber")
    )
    if mode == "subscriber":
        return check_subscriber()
    if mode == "scraper":
        return check_scraper()
    print(f"Unknown mode: {mode}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
