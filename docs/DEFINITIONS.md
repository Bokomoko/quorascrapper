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

- run: execute the scraper (uv run)
- test: run the test suite (uvx pytest -q)
- build: build the project distribution (uv build)

## Environment variables

- PROFILE_URL: profile answers URL (optional; CLI arg takes precedence)
- KAFKA_BOOTSTRAP: Kafka bootstrap servers (default: 192.168.1.116:9092)
- KAFKA_TOPIC: Kafka topic (default: quora-answers)
- LOG_LEVEL: Logging level (default: INFO)
- SCROLL_PAUSE: Delay between scrolls in seconds (default: 1.5)
- MAX_RESULTS: Max answers to collect (default: capped by profile stats)

## Notes

- Ensure Chrome is installed locally for Selenium; headless mode is used by default.
