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
3. Click the **qsbk** extension → set max and **Export format** (default **JSON**) → **Scrape this tab**
4. JSON export includes `question_title`, `answer_url`, optional `answer_preview`, and `stop_reason` in metadata

### Pagination stuck?

The scraper detects stalls (no new answers / no scroll growth) and tries recovery:
scroll nudges + optional "More answers" click. If still stuck, `stop_reason` is `pagination_stuck`.

**Recover manually:** scroll the Quora page yourself to load more, then scrape again. `qsbk ingest` skips duplicates (idempotent).

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
  → scroll + grep /answer/
  → CSV / JSONL download
  → quora-filter
  → JSONL (url, hash)
  → (optional) Kafka / subscriber
```
