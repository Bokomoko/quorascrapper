# qsbk Chrome extension

Collect answer URLs from a **logged-in** Quora profile `/answers` tab.  
Prefilters with grep-style `/answer/` matching — no full-page parsing.

## Install (unpacked)

**From the CLI (recommended):**

```bash
uv tool install /path/to/quorascrapper   # or uv tool install --force .
qsbk install --open
```

After `qsbk install`, go to `chrome://extensions` → **Remove** any old qsbk entry → **Load unpacked** → `~/.local/share/qsbk/chrome-extension` → **Reload** on the new card.

Choose export format in the popup: **CSV**, **JSONL**, or **Both**.

## Use

1. Log into Quora in Chrome
2. Open e.g. `https://pt.quora.com/profile/<user>/answers`
3. Click the **qsbk** extension → set max, **Method**, and **Output** → **Scrape this tab**
4. Export includes `question_title`, `answer_url`, optional `answer_preview`, and `stop_reason` in metadata

### Method: API (GraphQL) vs Scroll

- **API (GraphQL)** — *default, recommended.* Calls Quora's own paginated answers
  endpoint (`UserProfileAnswersMostRecent_RecentAnswers_Query`) directly from the
  page using your live session. It walks the cursor (`after` → `endCursor`) until
  the feed is exhausted — no scrolling, no stalls — and returns full content:
  `answer_text`, `aid`, `num_upvotes`, `num_views`, `num_comments`, `creation_time`.
- **Scroll (DOM)** — legacy fallback that scrolls the page and scrapes answer
  anchors. Use only if the API method reports `context_missing` (e.g. the page
  shape changed) or `api_error`.

The API method reconstructs nothing it can't read from the page: `uid`, `formkey`
and `revision` are parsed from the page's inline bootstrap script, and the
persisted-query hash defaults to a known value (override per request if Quora
rotates it). If Quora updates the query, re-capture the hash from a fresh HAR and
set `QUORA_ANSWERS_QUERY_HASH` (CLI) or pass `queryHash` in the message.

### Pagination stuck? (Scroll method only)

The scroll scraper detects stalls (no new answers / no scroll growth) and tries
recovery: scroll nudges + optional "More answers" click. If still stuck,
`stop_reason` is `pagination_stuck`. The API method does not stall — it reports
`exhausted` (reached the end), `all_known` (caught up with already-ingested
answers), or `max_reached`.

**Recover manually:** switch to the API method, or scroll the Quora page yourself
to load more and scrape again. `qsbk ingest` skips duplicates (idempotent).

## Pipeline (add hashes for Kafka/Mongo)

Extension export has **no hash** (keeps the browser side tiny). Run:

```bash
quora-filter qsbk-answers-....csv -o answers.jsonl
# or
quora-filter qsbk-answers-....jsonl -o answers-with-hash.jsonl
```

Output columns: `url`, `hash`, `seen_at` — same `blake2s` hash as `qsbk` Kafka messages.

## Data flow

```
Quora tab (logged in)
  → API (GraphQL pagination)  ──┐   default
  → or scroll + grep /answer/ ──┤   fallback
                                ↓
  → CSV / JSONL download → quora-filter → JSONL (url, hash)
  → or Kafka (via qsbk serve) → subscriber → MongoDB
```
