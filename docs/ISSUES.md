# Issues & Fix Plan (2025-09-16)

This document tracks identified issues and planned fixes for the project. Language: English only.

## 1) CLI and Environment Configuration

- Add PROFILE_URL support (done): CLI arg > PROFILE_URL env > default.
- Document precedence and examples (done in README).

## 2) uv-only Workflow and Hygiene

- Python managed by uv (>=3.13); no need to pre-install Python/pip.
- .venv/ and .python-version should not be tracked (updated .gitignore; untracked .python-version).
- Optional: add a short Quickstart block at top of README.

## 3) Kafka Connectivity UX

- Optional health check: on startup, produce a small message to the topic with a key `healthcheck` and short timeout to surface broker issues early.
- Consider environment variable `KAFKA_LINGER_MS` / `KAFKA_ACKS` (advanced) or keep defaults for simplicity.

## 4) Scraper Robustness

- Fast anchor scan in place using ANSWER_ANCHOR_XPATH (done).
- Scroll stagnation detection uses anchor count (done).
- Consider retry on transient WebDriver exceptions during anchor processing.
- Consider rate limiting sends if broker under backpressure.

## 5) Tests

- Add a minimal unit test for number normalization `_normalize_number`.
- Add a smoke test for CLI/env URL resolution.
- (Optional) Integration test stub that skips real browser if CHROME not available.

## 6) Documentation

- README now emphasizes uv-only setup (done).
- docs/DEFINITIONS.md tracks language, platform, runtime, libraries, and env vars (done).
- Add badges or a short “Try it” snippet (optional).

## 7) CI (Optional Next)

- Add GitHub Actions workflow using uv for install/build/test.
- Cache uv and ChromeDriver if needed.

## Tracking

- Branch: `chore/issues-2025-09-16`
- After implementing selected items, open a PR into `main`.
