# Critical Workspace Review

**Date:** 2026-05-27 (updated after package refactor)  
**Scope:** Full repository — scraper, Kafka pipeline, subscriber, containers, tests, documentation  
**Reviewer:** Automated workspace review (Cursor agent)

> **Refactor status (2026-05-27):** Code now lives in `src/quorascrapper/` with CLI entry points (`quora-scraper`, `quora-subscriber`, `quora-preflight`). Subscriber uses manual commit-after-write and graceful shutdown. Unified preflight replaces ad-hoc `scripts/test_*.py` for startup validation. See README for current workflows; items below marked fixed in Phase 0–2 + package refactor may be stale.

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
| 2026-06-13 | **Extension v0.9.28 — fresh reload version marker + Max-prefill sanity check.** Bumped `extension/manifest.json` 0.9.27 → 0.9.28 so a plain reload at `chrome://extensions` shows a new version (a full remove+reload still reported 0.9.27). *Sanity check (no bug found):* the Total → `#max` fill wiring is correct. The earlier click-total-to-max affordance (`applyProfileTotalToMax()`) was deliberately superseded in the working tree by a one-shot **auto-prefill** (`prefillMaxFromTotal()`): `renderStats()` writes the raw numeric `profileState.total` into `#max` once the total resolves (populated via cache → active-tab read → background-tab fetch), guarded by `maxAutoFilled` + `session.active` and reset on profile change, with `#max`/elements resolved before any render (no listener-before-element race). The standalone click listener was removed; Max now fills automatically (no click needed). Also live in the working tree: an unobtrusive on-page answer-count badge in `scrape.js`. *Files:* `extension/manifest.json` (v0.9.28), `extension/popup.js`, `extension/popup.html`, `extension/scrape.js`. |
| 2026-06-13 | **Restored click-total-to-max affordance on the new stats grid (extension v0.9.27).** The v0.9.26 overhaul only kept the click handler on the `#stat-total` number element; this widens it so the whole **"Total"** stat cell is the click target. *Fix:* `popup.html` wraps the cell as `#stat-total-cell` (`.stat-total-cell`, `title="Click to set max"`) and moves the `cursor:pointer` + dotted-underline hover affordance to the cell (number underlines on `.stat-total-cell:hover`); `popup.js` resolves `statTotalCell` and attaches the click listener to the cell (falling back to `#stat-total`), calling the existing `applyProfileTotalToMax()` which writes the raw numeric `profileState.total` (no commas) into the `#max` input. Works whether or not a session is active; no-op until the profile total resolves. *Files:* `extension/popup.html`, `extension/popup.js`, `extension/manifest.json` (v0.9.27). |
| 2026-06-13 | **Popup UI overhaul (extension v0.9.26) + new `qsbk monitor` CLI.** *Extension (v0.9.26):* reworked the popup into a single unified stats block — a green **"Saved"** live count (the Mongo-persisted per-profile total, polled mid-scrape), a blue **"New"** count, and a muted **"Total"** — and removed all user-facing **"MongoDB"** wording (the indicator now reads as a neutral "Saved" total). Added a **"Run minimized"** button: `background.js` gains a `runMinimized` handler that calls `chrome.windows.create({ tabId, state: "minimized", focused: false })` so a scrape can run in a minimized, unfocused window. *Files:* `extension/popup.html`, `extension/popup.js`, `extension/background.js`, `extension/manifest.json` (v0.9.26). *CLI:* added a new **`qsbk monitor`** command (`ops/monitor.py`) that reports Kafka queue depth + consumer-group lag, consumer-group members, and aggregated Kafka/Mongo/serve health, with selectable views (`all`/`queue`/`consumers`/`health`), a `--json` machine-readable mode, and `--ping-url`/`--no-serve`/`--timeout` flags for the serve `/ping` probe. *Files:* `src/quorascrapper/ops/monitor.py` (new), `src/quorascrapper/cli.py`, `pyproject.toml`, `tests/test_monitor.py` (new). No serve/subscriber container rebuild needed — neither change touches the running stack. |
| 2026-06-12 | **Popup "saved" = live Mongo-persisted count for the active profile.** Redefines the popup's `saved` indicator to mean *documents permanently stored in MongoDB for THIS profile's collection*, polled live (incl. mid-scrape) so it ticks up as the subscriber drains Kafka→Mongo. *Bug:* `profileSavedDisplay()` returned `session.skippedCount` (a per-run dedup number, ~0 during a scrape) and `refreshProfileSaved()` was suppressed while a session was active, so the persisted count was never surfaced live. *Fix (extension v0.9.25):* `popup.js` `profileSavedDisplay()` now always returns the Mongo-backed `profileState.saved` (the per-session skipped/dedup number stays on the separate dedupe line), and `refreshProfileSaved()` polls every health tick (~4s) including during an active session — reusing the existing `refreshServeHealth`→`refreshProfileSaved` poll. *Efficiency:* the poll no longer downloads the full known-URL list (a profile can hold ~16k URLs). Added a cheap COUNT path: `GET /known?count_only=1` (alias `counts=1`, with `profile_url`) returns just `{"count": N}` via `count_documents` on the resolved per-profile collection (falls back to the default `answers` collection when no `profile_url`), skipping the URL/key arrays; the full `/known` dedup-lookup behavior is unchanged. *Files:* `ops/known_urls.py` (`mongo_known_count` + `known_count_payload`), `ops/serve_store.py` (`ServeState.saved_count`), `ops/serve.py` (`do_GET` parses `count_only`/`counts` via a `_query_flag` helper → `saved_count`), `extension/serve-config.js` (`knownUrl(base, profileUrl, {countOnly})`), `extension/popup.js`, `extension/manifest.json` (v0.9.25). New tests cover the count helper (cheap `count_documents`, scoped reconnect, empty without URI), `saved_count` profile scoping + fallback, and the HTTP count-only endpoint (scoped, fallback, `counts` alias, profile-url forwarding). |
| 2026-06-12 | **Profile-scoped dedup + profile-URL encoding canonicalization (bugfix).** Fixes a bug where dedup/`known` was *global*: every answer already in the shared `answers` collection looked "known", so per-profile re-ingests were skipped and new profiles couldn't backfill. Now the known-lookup, classify, and publish-idempotency all scope to each profile's own `profile_<userid>` collection (falling back to `answers` when no profile is supplied). *Extension (v0.9.24):* `serve-config.js`/`scrape.js`/`popup.js`/`marks.js` send and scope by `profile_url` on the `/known` known-lookup, checkmark polling, `/check`, and `/upsert`. *Serve/subscriber/pipeline:* the filter adds a shared `profile_collection_name(userid)` helper (`PROFILE_COLLECTION_PREFIX = "profile_"`) reused by `subscriber/storage.py`; `canonical_profile_url()` now percent-decodes the path (`unquote`) so encoded `Jo%C3%A3o…` and decoded `João…` collapse to ONE canonical URL / userid; `collection_name` is threaded through `ops/known_urls.py` (`mongo_known_hashes/urls/last_ingested/known_payload` + a scoped reconnect helper) and `ops/ingest_idempotency.py` (`plan_idempotent_ingest`); `ops/serve_store.py` gains `_resolve_collection` and profile-scoped `known_snapshot`/`classify_answers`/`publish_answers`; `ops/serve.py` parses `profile_url` from the `/known` query string and the `/check`/`/upsert` bodies. New tests cover the collection-name helper, encoding canonicalization → same userid, profile-scoped known/classify, and two-profile isolation. |
| 2026-06-12 | **Per-profile userid-hash collection routing.** Answers are now partitioned per Quora profile instead of all landing in one collection. *Extension (v0.9.23):* derives a readable profile identity once and sends a canonical `profile_url` (plus `profile_name`/`profile_display_name`/`profile_answer_count`) so the backend can attribute every answer to its source profile. *Serve/subscriber/pipeline:* the filter exposes `canonical_profile_url()` + `profile_userid()` and passes the readable profile fields through; the serve publish path derives and stamps `userid = url_hash(canonical_profile_url(profile_url))` and whitelists the readable profile fields; the subscriber's new `MongoRouter` routes each doc into a `profile_<userid>` collection (lazy per-collection unique `hash` index), maintains a `profiles` registry keyed by userid, and falls back to the default `answers` collection when no userid is present. New tests cover canonicalization, userid stability, routing-by-userid, the registry, and serve derivation. **Decision:** the original `answers` collection (16,657 docs from the first full backfill) is **intentionally kept as-is as a token/record of the initial ingest** — not migrated into the new per-profile collections. |
| 2026-06-12 | **Streaming publish + serve performance.** *Extension (v0.9.21):* answers now stream-publish to `/upsert` incrementally as they are collected (batches of 100) so memory stays bounded and an interrupted run keeps its progress; `/check` + `/upsert` are batched to stay under serve's 10MB request cap; added fetch retry/backoff with pacing for deep GraphQL pagination plus context-invalidation handling; the panel shows an always-visible version footer. *Serve/pipeline:* `ServeState` now reuses **one pooled `MongoClient`** for idempotency/known-URL lookups instead of opening a fresh Atlas connection per `/upsert` batch — fixed a progressive publish slowdown (~2.3s → ~0.13s per batch); added `Access-Control-Max-Age: 7200` so streamed batch POSTs don't re-run CORS preflight each time. Deployed to the bokomint container and verified healthy; full ~16,657-answer profile now in Mongo with full content. |
| 2026-06-11 | **Refactor landed:** monorepo package (`src/quorascrapper/`), `qsbk` uv-tool CLI, startup/scrape gates, expanded `--dry-run`, subscriber/scraper split, CI (ruff + pytest). macOS Selenium now uses Chrome for Testing (avoids chromedriver → system Chrome SIGABRT). Mongo preflight fixed for Atlas `mongodb+srv` SRV DNS. Kafka + Mongo + Selenium dry-run **PASS**. |
| 2026-05-27 | Phase 0–2 hardening completed (see git history) |
