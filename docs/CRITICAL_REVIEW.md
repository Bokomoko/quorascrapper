# Critical Workspace Review

**Date:** 2026-05-27  
**Scope:** Full repository — scraper, Kafka pipeline, subscriber, containers, tests, documentation  
**Reviewer:** Automated workspace review (Cursor agent)

## Prior reviews

| When | Where | Notes |
|------|--------|--------|
| 2025-09-16 | `docs/ISSUES.md` | Fix plan / backlog, not a full critical review |
| Earlier chat | Agent transcript only | Broad review (patterns, security, performance, forward plan) was produced in conversation but **not saved under `docs/`** until this file |

This document supersedes informal chat output and should be updated when major architecture or security changes land.

---

## Executive summary

**Quorascrapper** is a small, script-oriented data pipeline: Selenium scrapes Quora profile answer URLs → optional Kafka → MongoDB subscriber, with Podman/Docker packaging for the consumer.

**Verdict:** The core design is sound (streaming, sender abstraction, semantic selectors, hash-based deduplication), but the project is **prototype / dev-integration** maturity—not production-ready. Blockers are **secrets hygiene**, **uncommitted integration work**, **operational gaps** (subscriber offset semantics, signal handling), and **repository hygiene** (flat scripts, weak healthchecks, docs vs code drift).

**Tests (2026-05-27):** `uv run pytest -q` → **7 passed** (includes root-level `test_*.py` scripts collected as tests; see Testing).

---

## Tech stack

| Layer | Choice | Assessment |
|--------|--------|------------|
| Runtime | Python 3.13 + **uv** | Modern; `pyproject.toml` is minimal (no scripts, no dev group) |
| Scraping | Selenium 4 + headless Chrome/Chromium | Appropriate for infinite-scroll SPAs; heavy and brittle to DOM changes |
| Messaging | confluent-kafka | Fits streaming URLs; no TLS/SASL in config |
| Storage | MongoDB Atlas via pymongo | Simple `replace_one` upsert model |
| Ops | Podman scripts, `docker-compose.yml`, two Dockerfiles | Useful; host networking is LAN-specific |
| Logging | `python-json-logger` + `logging_setup.py` | Good direction for structured ops logs |

**Gaps vs `docs/DEFINITIONS.md`:** Definitions mention `uv run` / `uv build` scripts that are **not** defined in `pyproject.toml`. `main.py` is an empty stub.

---

## Architecture and design

### Strengths

1. **Sender pattern** (`senders.py`) — `BaseSender` injects BLAKE2s hash; `StdoutSender` / `KafkaSender` share one contract.
2. **Selector centralization** (`quora_selectors.py`) — Semantic XPaths (`/answer/`, Portuguese stats labels) instead of brittle generated class names.
3. **URL resolution** — CLI > `PROFILE_URL` > default (`resolve_profile_url`).
4. **Incremental emit** — URLs sent while scrolling, not only at end of run.
5. **Subscriber upsert** — `replace_one` on `hash` (fallback `url`) with `processed_at` / `source` metadata.

### Weaknesses

| Issue | Detail |
|--------|--------|
| **Monolithic scraper** | `quora_scraper.py` (~650 lines) mixes WebDriver lifecycle, scrolling, stats parsing, fallbacks, CLI, and Kafka healthcheck. |
| **Dead code** | `_retry()` is never called despite stale-element handling being a known Selenium issue. |
| **Duplicate scroll paths** | `scroll_to_bottom()` may run twice; block-based fallback re-scrolls and re-processes. |
| **Flat layout** | Many top-level `.py` files; no installable package namespace. |
| **Logging singleton** | `_CONFIGURED` in `logging_setup.py` — first `init_logging()` wins for the process. |
| **Signal handling** | `kafka_subscriber.py` `signal_handler` calls `sys.exit(0)` without setting `shutdown` or running `cleanup()` — risk of leaked connections and lost final stats. |
| **README overclaims** | “Robust error handling with retry logic” on subscriber — errors are logged and counted; no retry. |

```311:314:kafka_subscriber.py
def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info(f"Received signal {signum}, shutting down...")
    sys.exit(0)
```

---

## Security (highest priority)

### Critical: credentials in the workspace

1. **`discover_mongo_hostname.py`** — Hardcoded MongoDB username and password; builds and prints full URIs. **Rotate credentials** if this file was ever committed or shared. Rewrite to read `MONGODB_URI` from environment only.
2. **`.env.container`** (untracked) — Contains a real `mongodb+srv://…` connection string. Ensure it never enters git; extend `.gitignore` to `.env.*` except `.env.example`.
3. **Audit history** — Run `git log -p --all -S 'mongodb+srv'` (and password fragments) before any public push.

Do **not** copy real secrets into documentation or commits.

### High / medium

| Risk | Notes |
|------|--------|
| **Kafka plain text** | Producer/consumer use `bootstrap.servers` only — OK on trusted LAN, unsafe on public networks. |
| **Default hostnames** | `bokomint.local:19092` baked into code defaults — fine for personal infra, confusing for other environments. |
| **Scraping Quora** | No rate limiting, robots.txt, or ToS discussion — legal/operational risk at scale. |
| **Container healthchecks** | `python -c "import sys; sys.exit(0)"` does not verify Kafka or MongoDB. |
| **`profile.html`** | Large saved page (~940 KB) — noise/PII risk if committed. |
| **`scraper_output.jsonl`** | Local scrape output; should be gitignored if used routinely. |

---

## Performance and reliability

| Area | Observation |
|------|-------------|
| **Scroll loop** | Each scroll: full `find_elements` on anchor XPath + iterate all anchors → costly for large profiles. |
| **Logging** | Two `INFO` logs per URL (`url_send` + `url_sent`) — noisy at thousands of URLs. |
| **Memory** | `self.results` and `self.seen_links` grow without bound on full profiles. |
| **Kafka producer** | `poll(0)` per message; no batching or keyed messages. |
| **Subscriber offsets** | `enable.auto.commit: True` with commit **before** guaranteed Mongo write → possible **message loss** on crash after commit. Prefer manual commit after successful upsert. |
| **MongoDB** | No documented unique index on `hash`; upserts slow as collection grows. |
| **Selenium** | Fixed `SCROLL_PAUSE` (default 1.5s); no adaptive backoff. |

---

## Testing and CI

| Item | Status |
|------|--------|
| `tests/test_utils.py` | Good unit tests for `_normalize_number` and URL precedence |
| `tests/test_sender_hash.py` | Validates hash on stdout sender |
| Root `test_kafka_producer.py`, `test_subscriber.py`, `test_mongo_connection.py` | Manual/integration scripts; collected by pytest (7 tests total) |
| `pytest` in `pyproject.toml` | **Not** declared as dev dependency |
| CI (GitHub Actions) | Planned in `docs/ISSUES.md` §7 — **not implemented** |
| Integration tests | None for live browser/Kafka/Mongo in CI |

**Recommendation:** `pytest.ini` with `testpaths = tests`; move manual scripts to `scripts/`; add `[dependency-groups] dev` with pytest and ruff.

---

## Documentation vs reality

| Document says | Reality |
|---------------|---------|
| Subscriber has “retry logic” (README) | No retry; failed messages increment `errors_count` |
| “No files written” (README) | `scraper_output.jsonl` may exist locally; optional log files under `/logs` |
| `docs/ISSUES.md` (2025-09-16) | Several items done; CI, subscriber hardening still open |
| `uvx pytest -q` (README) | Works if deps installed; root scripts inflate test surface |
| `docs/DEFINITIONS.md` scripts | Not wired in `pyproject.toml` |

---

## Repository and delivery status

Per git status at review time: **large uncommitted/staged addition** (Kafka subscriber, Dockerfiles, compose, monitoring scripts, env templates). Pipeline appears **built and run locally** but **not fully integrated on `main`**.

**Maturity model:**

```
[Scraper + senders] ──► [Kafka] ──► [Subscriber] ──► [MongoDB Atlas]
     stable locally        LAN        works            needs indexes + commit semantics
```

---

## Priority matrix

| Priority | Item |
|----------|------|
| **P0** | Remove hardcoded Mongo credentials from `discover_mongo_hostname.py`; rotate Atlas password |
| **P0** | Never commit `.env.production`, `.env.container`, `.env.scraper`; broaden `.gitignore` |
| **P1** | Commit and merge pipeline (subscriber, Docker, logging) via reviewed PR |
| **P1** | Subscriber: graceful shutdown; commit offsets after successful Mongo write |
| **P1** | Fix pytest layout; add dev dependencies and `testpaths` |
| **P2** | Mongo unique index on `hash`; reduce scraper log/DOM churn |
| **P2** | CI: `uv sync`, `pytest tests/`, lint |
| **P3** | Package layout (`quorascrapper/`); optional second phase for full answer text |

---

## Recommended forward plan

Aligned with `docs/ISSUES.md` but ordered by risk.

### Phase 0 — Security (immediate)

1. Rewrite or delete `discover_mongo_hostname.py` (env-only credentials).
2. Rotate any exposed Atlas passwords.
3. Update `.gitignore`: `.env.*`, `*.jsonl`, `profile.html`, `logs/`.
4. Audit git history for leaked secrets.

### Phase 1 — Stabilize repo (1–2 days)

1. Land subscriber, Docker, and lockfile on a feature branch → PR to `main`.
2. Add pytest dev group and `pytest.ini` (`testpaths = tests`).
3. Relocate root `test_*.py` manual scripts to `scripts/`.
4. Either remove `main.py` or add `[project.scripts]` entry points.

### Phase 2 — Reliability (3–5 days)

1. Subscriber graceful shutdown and post-write offset commit.
2. MongoDB unique index on `hash`.
3. Scraper: use or remove `_retry`; dedupe scroll paths; demote per-URL logs to DEBUG.
4. Real container healthchecks (Kafka/Mongo probe).

### Phase 3 — Structure and CI (about 1 week)

1. Optional package refactor.
2. Unit tests for `process_message` (mongomock) and Kafka sender mocks.
3. GitHub Actions workflow with uv cache.

### Phase 4 — Product direction (ongoing)

- URLs only vs full answer body scraping.
- Scheduling (cron/Podman timer) vs on-demand runs.
- Compliance: rate limits, retention, ToS.

---

## Bottom line

The project has a **coherent streaming design** and a **working local path** from scraper to MongoDB. Carrying on safely means treating **Phase 0–1 as mandatory**: secrets, git hygiene, and subscriber commit/shutdown semantics before scaling volume or adding content extraction.

For tactical backlog items, see **`docs/ISSUES.md`**. For conventions and env var catalog, see **`docs/DEFINITIONS.md`**.

---

## Changelog

| Date | Change |
|------|--------|
| 2026-05-27 | Phase 0–2 hardening completed (see git history) |
