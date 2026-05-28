# Project Definitions

- Language: English only. All code, comments, documentation, commit messages, and identifiers must be written in English.
- Platform Manager: uv — manages Python, virtual environments, dependency resolution, scripts, and build tooling.
- Python Runtime: Python 3.13 (provisioned by uv; no pre-install of Python or pip required).
- Core Libraries:
  - Selenium (>= 4.30.0)
  - confluent-kafka (>= 2.3.0)

## Conventions

- Use uv for all developer workflows: create venvs, install dependencies, run scripts, and build packages.
- Prefer XPath selectors with semantic anchors; avoid brittle auto-generated class names.
- Log with environment-driven levels (LOG_LEVEL) and keep user-facing output concise.
- No local persistence: all answer URLs are streamed to Kafka.

## Scripts (pyproject)

- `uv run quora_scraper.py` — run the scraper
- `uv run kafka_subscriber.py` — run the Kafka→MongoDB subscriber
- `uv run pytest -q` — run unit tests (`tests/` only; integration scripts in `scripts/`)
- `uv build` — build the project distribution (if packaging is added later)

## Environment variables

- KAFKA_HEALTHCHECK_TOPIC: Kafka topic for health checks (default: healthcheck)

## Notes

- Ensure Chrome is installed locally for Selenium; headless mode is used by default.
