"""Runtime container health probes."""

import os
import sys

from quorascrapper.config import Settings


def check_subscriber(settings: Settings | None = None) -> int:
    cfg = settings or Settings.from_env()
    if not cfg.kafka_bootstrap:
        print("KAFKA_BOOTSTRAP not set", file=sys.stderr)
        return 1
    if not cfg.mongodb_uri:
        print("MONGODB_URI not set", file=sys.stderr)
        return 1

    try:
        from confluent_kafka.admin import AdminClient  # type: ignore

        admin = AdminClient({"bootstrap.servers": cfg.kafka_bootstrap})
        admin.list_topics(timeout=5)
    except Exception as exc:
        print(f"Kafka check failed: {exc}", file=sys.stderr)
        return 1

    try:
        from pymongo import MongoClient  # type: ignore

        client = MongoClient(cfg.mongodb_uri, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        client.close()
    except Exception as exc:
        print(f"MongoDB check failed: {exc}", file=sys.stderr)
        return 1

    return 0


def check_scraper(settings: Settings | None = None) -> int:
    cfg = settings or Settings.from_env()
    try:
        import selenium  # noqa: F401
    except ImportError as exc:
        print(f"Selenium check failed: {exc}", file=sys.stderr)
        return 1

    from quorascrapper.scraper.browser_env import detect_browser_environment

    env = detect_browser_environment(cfg.chrome_binary)
    if not env.browser_binary:
        print(
            f"No Chrome/Chromium binary for runtime={env.runtime} (system={env.system})",
            file=sys.stderr,
        )
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
