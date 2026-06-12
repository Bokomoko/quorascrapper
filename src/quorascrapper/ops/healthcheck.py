"""Runtime container health probes."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

from quorascrapper.config import Settings

DEFAULT_SERVE_PING = os.environ.get("QSBK_SERVE_PING_URL", "http://127.0.0.1:8765/ping")


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


def check_serve_liveness(*, ping_url: str | None = None, timeout_sec: float = 5.0) -> int:
    """Fast probe: is the HTTP serve process responding on /ping?"""
    url = ping_url or DEFAULT_SERVE_PING
    try:
        with urllib.request.urlopen(url, timeout=timeout_sec) as resp:
            if resp.status != 200:
                print(f"serve ping returned {resp.status}", file=sys.stderr)
                return 1
            body = json.loads(resp.read().decode("utf-8"))
            if not body.get("ok"):
                print(f"serve ping body not ok: {body!r}", file=sys.stderr)
                return 1
            if body.get("service") not in (None, "qsbk-serve"):
                print(f"unexpected serve ping service: {body!r}", file=sys.stderr)
                return 1
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        print(f"serve ping failed ({url}): {exc}", file=sys.stderr)
        return 1
    return 0


def check_serve(settings: Settings | None = None, *, ping_url: str | None = None) -> int:
    """Container health for qsbk-serve: HTTP liveness only.

    Kafka/Mongo are validated by preflight and the subscriber healthcheck.
    A full dependency probe here routinely exceeds the 10s compose timeout.
    """
    _ = settings
    return check_serve_liveness(ping_url=ping_url)


def check_serve_deps(settings: Settings | None = None, *, ping_url: str | None = None) -> int:
    """Deep probe: Kafka + Mongo + HTTP ping (manual / troubleshooting)."""
    if check_subscriber(settings) != 0:
        return 1
    return check_serve_liveness(ping_url=ping_url)


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
    if mode == "serve":
        return check_serve()
    if mode == "serve-deps":
        return check_serve_deps()
    if mode == "scraper":
        return check_scraper()
    print(f"Unknown mode: {mode}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
