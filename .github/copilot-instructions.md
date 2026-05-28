# Copilot Instructions for Quora Scraper

This repo is a streaming Quora profile scraper that emits answer URLs to stdout or Kafka with no local persistence. Keep code/docs/logs English-only.

## Architecture and key files
- `quora_scraper.py`: `QuoraScraper` + CLI. Streams URLs during scroll; dedups with `seen_links`; caps via `answer_limit` derived from profile stats. URL resolution via `resolve_profile_url(cli, env, default)` (CLI > env > default). Select sender with `--sender stdout|kafka` or `SENDER`. Always `sender.flush(15)` before exit.
- `senders.py`: `BaseSender.send()` injects 16‑byte BLAKE2s hash (32‑char hex) into `obj["hash"]`. `StdoutSender` writes JSONL; `KafkaSender` uses `confluent_kafka.Producer`, produces JSON value, `poll(0)` per send, `flush(timeout)` on close.
- `quora_selectors.py`: Semantic XPath sets (`ANSWER_ANCHOR_XPATH`, `ANSWER_BLOCK_XPATHS`, `ANSWER_LINK_XPATHS`, `PROFILE_STATS_XPATHS` with PT labels). Prefer anchors like `//a[contains(@href,'/answer/')]`; avoid brittle class names.
- `logging_setup.py`: `init_logging(service)` configures JSON logs to stdout by default; envs: `LOG_LEVEL`, `LOG_FORMAT` json|text, optional file sink via `LOG_FILE_ENABLED`, `LOG_FILE_PATH`.
- `kafka_subscriber.py`: Kafka→MongoDB consumer. Upserts by `hash` (fallback `url`) with metadata (`processed_at`, `source`). Requires `MONGODB_URI`.

## Run & dev workflow (uv)
- Run scraper: `uv run quora_scraper.py [PROFILE_URL]` or `PROFILE_URL=... uv run quora_scraper.py`. Choose sender via `--sender` or `SENDER`. `.env` is auto‑loaded.
- Tests: `uvx pytest -q` (see `tests/test_sender_hash.py`, `tests/test_utils.py`).
- Add deps: `uv add <package>`.

## Selenium & scraping strategy
- Chrome headless (`--headless=new`) by default; optional Firefox fallback when `USE_FIREFOX=1`. `SCROLL_PAUSE` controls pacing.
- Incremental scroll until plateau (anchor count growth stalls) or `answer_limit`. `_retry()` handles `StaleElementReferenceException`.
- Prefer anchor-first extraction (`ANSWER_ANCHOR_XPATH`), then block fallbacks via `ANSWER_BLOCK_XPATHS`/`ANSWER_LINK_XPATHS`.

## Kafka & Mongo integration
- Kafka envs: `KAFKA_BOOTSTRAP` (default `bokomint.local:19092`), `KAFKA_TOPIC`, `KAFKA_HEALTHCHECK_TOPIC`. Healthcheck only when using Kafka and `KAFKA_HEALTHCHECK` not disabled.
- Subscriber envs: `KAFKA_BOOTSTRAP`, `KAFKA_TOPIC`, `KAFKA_GROUP_ID`, `MONGODB_URI` (required), `MONGODB_DATABASE`, `MONGODB_COLLECTION`.

## Conventions & tips for agents
- No file persistence for scraped data; emit via sender. Keep prints minimal—use `init_logging()` with structured fields (`event`, etc.).
- When adding a new sender, subclass `BaseSender`, implement `_send`, and honor `flush()`/`close()` lifecycle.
- If changing URL resolution or number parsing, update tests in `tests/` accordingly (see `_normalize_number` and precedence tests).
- Adjust selectors only in `quora_selectors.py`; keep semantic anchors and multiple fallbacks.
