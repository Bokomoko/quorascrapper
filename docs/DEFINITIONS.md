# Project Definitions

- Language: English only. All code, comments, documentation, commit messages, and identifiers must be written in English.
- Platform Manager: uv — manages Python, virtual environments, dependency resolution, scripts, and build tooling.
- Python Runtime: Python 3.13 (provisioned by uv).
- Package: `quorascrapper` (installable via hatchling, `src/` layout).

## Core Libraries

- Selenium (>= 4.30.0)
- confluent-kafka (>= 2.3.0)
- pymongo (>= 4.15.3)

## CLI entry points

- `uv run quora-scraper` — scrape answer URLs
- `uv run quora-subscriber` — Kafka → MongoDB consumer
- `uv run quora-preflight` — infrastructure pre-flight checks
- `uv run quora-healthcheck` — container liveness (subscriber | scraper)
- `uv run pytest -q` — unit tests (no live Kafka/Mongo/Chrome)

## Conventions

- Use uv for all developer workflows.
- Prefer XPath selectors with semantic anchors; avoid brittle auto-generated class names.
- Configuration via `quorascrapper.config.Settings` — no hardcoded broker hostnames in library code.
- Run `quora-preflight` before subscriber/scraper starts (local or container).
- No local persistence for scraped URLs; data flows to stdout or Kafka.

## Environment files

- `.env.container` — subscriber (Kafka + MongoDB Atlas)
- `.env.scraper` — scraper (profile URL, sender, Kafka)
- `.env.example` — documented template only (safe to commit)

## Notes

- Kafka broker is external (LAN); compose uses `network_mode: host`.
- Headless Quora may hit a login wall; preflight warns via `quora_reachability` check.
