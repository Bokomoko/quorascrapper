# Quora Profile Scraper (qsbk)

Collect Quora answer URLs from a logged-in browser or headless Selenium, dedupe against MongoDB, and stream new rows to Kafka. A subscriber upserts each message into MongoDB Atlas.

Two ways to collect URLs:

| Method | Best for |
|--------|----------|
| **Chrome extension** | Day-to-day use on your `/answers` tab while logged into Quora |
| **`qsbk` CLI (Selenium)** | Automation, containers, profiles you drive headlessly |

## Architecture

```
Chrome extension (Mac)
    → qsbk serve (:8765)  — check / upsert / known
        → Kafka (bokomint)
            → qsbk subscriber
                → MongoDB Atlas

Optional: Quora profile → qsbk (Selenium) → Kafka → subscriber → MongoDB
```

Message contract: `{"url": "...", "hash": "<blake2s-16>"}` per answer URL.

---

## Chrome extension

### Purpose

The qsbk Chrome extension scrolls a **logged-in** Quora **`/answers`** page and:

- Collects answer URLs (profile-style `/answer/<id>-…` links preferred)
- **Dedupes against MongoDB** via `qsbk serve` (`POST /check` while scrolling, `POST /upsert` at the end)
- **Publishes only new answers to Kafka** (default output) for the subscriber to persist
- Shows **live session stats** (count, rate, new/skipped, ETA)
- Marks **already ingested** answers with a green ✓ on the avatar (from `GET /known`, no scrape needed)

The control panel opens when you click the qsbk icon. Checkmarks and `/known` polling run automatically on `/answers` pages as long as the extension is enabled.

### Install the extension

**1. Install the CLI** (once, or after Python/package changes):

```bash
uv tool install --force /path/to/quorascrapper
```

**2. Copy the extension** and point it at `qsbk serve`:

```bash
# Direct LAN (if port 8765 is open on bokomint)
qsbk install --serve-url http://bokomint.local:8765

# Or via SSH tunnel (Mac terminal — leave running)
ssh -N -L 8765:127.0.0.1:8765 bokomint.local
qsbk install --serve-url http://127.0.0.1:8765
```

`qsbk install` prints the extension **version** and **source path**. Reload Chrome after every install.

**3. Load in Chrome**

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. **Load unpacked** → `~/.local/share/qsbk/chrome-extension`
4. Click **Reload** on the qsbk card after updates

Confirm the panel header shows the expected version (e.g. `v0.9.8`).

**Fast dev loop** (skip CLI reinstall): load unpacked directly from `extension/` in the repo, or set `QSBK_EXTENSION_DIR=/path/to/quorascrapper/extension` before `qsbk install`.

### Use the extension

1. Log into Quora in Chrome
2. Open a profile answers tab, e.g. `https://pt.quora.com/profile/<user>/answers`
3. Ensure **qsbk serve** is reachable (tunnel or LAN) — status line should show **online**
4. Click the **qsbk** icon → set **Max answers** (click the profile total to copy it into max)
5. **Output** defaults to **Kafka**; choose **JSON file download** or **CSV** if you only want a local export
6. Click **Scrape this tab**

While scraping, the panel shows collected count, answers/min, **new · skipped**, start time (local), and ETA. At the end, Kafka mode sends only **new** rows; skipped rows were already in Mongo.

### Download a JSON file

1. Open the qsbk panel on an `/answers` tab
2. Set **Output** → **JSON file download**
3. Click **Scrape this tab**
4. Chrome downloads `qsbk-answers-<timestamp>.json` with:
   - `answers[]` — `answer_url`, `question_title`, `question_url`, `answer_preview`, `seen_at`
   - `meta` — `stop_reason`, session timing, new/skipped counts (when serve is online)
   - `profile_url`, `exported_at`, `count`

With serve online, the JSON contains **new answers only** (same set that would go to Kafka). For a offline export of everything visible, turn serve off or use CSV/JSON without dedupe (serve offline).

**Optional:** pipe through the filter CLI for Kafka-style hashes:

```bash
quora-filter qsbk-answers-....json -o answers.jsonl
```

### Check the data

**Serve (via tunnel or LAN)**

```bash
curl http://127.0.0.1:8765/ping
curl http://127.0.0.1:8765/known | python3 -m json.tool | head -30
```

**MongoDB** (use your env file or `~/.config/qsbk/env`):

```bash
export $(grep -v '^#' ~/.config/qsbk/env | xargs)
uv run python -c "
from quorascrapper.config import Settings
from pymongo import MongoClient
s = Settings.from_env()
c = MongoClient(s.mongodb_uri)[s.mongodb_database][s.mongodb_collection]
print('documents:', c.count_documents({}))
print('latest:', c.find_one(sort=[('_id', -1)]))
"
```

**Live Mongo watch**

```bash
export $(grep -v '^#' ~/.config/qsbk/env | xargs)
uv run python monitor_mongodb.py
```

**Stack on bokomint**

```bash
./deploy_bokomint.sh status
./deploy_bokomint.sh logs
./deploy_bokomint.sh logs subscriber
./deploy_bokomint.sh logs serve
```

**Audit URL formats in Mongo**

```bash
qsbk verify-urls
```

**On the Quora page:** green ✓ badges = already in Mongo (`/known`). They appear on page load (and after ingest + ~2.5s poll), not only after you run a scrape.

### Extension troubleshooting

| Symptom | Fix |
|---------|-----|
| Chrome still shows old version (e.g. 0.9.6) | `uv tool install --force .` then `qsbk install …`; **Reload** in `chrome://extensions`. Or load unpacked from `extension/` in the repo. |
| `qsbk install: unrecognized arguments: --serve-url` | CLI is stale — `uv tool install --force /path/to/quorascrapper` |
| `qsbk serve: offline` in panel | Start tunnel: `ssh -N -L 8765:127.0.0.1:8765 bokomint.local` or open port 8765 on bokomint (`sudo ufw allow 8765/tcp`) |
| `bind [127.0.0.1]:8765: Address already in use` | Tunnel already running — use it, or `kill $(lsof -ti:8765)` and restart one tunnel |
| `curl bokomint.local:8765` times out from Mac | Use SSH tunnel + `http://127.0.0.1:8765`, or fix LAN firewall |
| Kafka option disabled | Serve not reachable — fix tunnel/serve first |
| No ✓ badges | Serve offline or answer not in Mongo yet; current-session rows get badges after upsert + subscriber + poll |
| Mongo count stuck during scrape | Normal — `/upsert` runs when the scrape **finishes**; subscriber then writes to Atlas |
| Subscriber warnings `non_canonical_answer_url` | Old question-slug URLs in Kafka payload; re-scrape with current extension for profile-style URLs |

More detail: [`extension/README.md`](extension/README.md).

### Feedback

This extension and pipeline are evolving. If something is confusing, broken, or missing:

- Open an issue or PR on [GitHub](https://github.com/Bokomoko/quorascrapper)
- Note your setup: extension version, serve URL (tunnel vs LAN), output mode, and what you expected vs what happened

Comments on UX (panel layout, defaults, checkmarks, ETA) are especially welcome.

---

## Setup

### Install `qsbk` anywhere (uv tool / uvx)

```bash
# One-time install — adds qsbk to your PATH (~/.local/bin)
uv tool install /path/to/quorascrapper

# Or from git (after push)
uv tool install git+https://github.com/bokomoko/quorascrapper.git

# Run without installing (ephemeral)
uvx --from /path/to/quorascrapper qsbk --version
uvx --from /path/to/quorascrapper qsbk --dry-run --skip-preflight
```

Then use from any directory:

```bash
qsbk --version
qsbk --dry-run --skip-preflight
qsbk --sender stdout --skip-preflight "https://pt.quora.com/profile/<USER>/answers"
```

**Linux host:** install Chrome or Chromium (`google-chrome-stable`, `chromium`) — `qsbk` auto-detects it.  
**Linux container:** uses `/usr/bin/chromium` + bundled chromedriver (see `Dockerfile.scraper`).  
**macOS:** uses Google Chrome + Selenium Manager for chromedriver.

### Development (this repo)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync --group dev
uv run qsbk --version
```

## Gates (automatic)

`quora-scraper` and `quora-subscriber` **run preflight automatically** before starting. If checks fail, they exit without scraping or consuming.

| Exit code | Meaning |
|-----------|---------|
| `1` | Preflight failed (Kafka, Mongo, Chrome, etc.) |
| `2` | Quora login wall detected |
| `3` | Scrape finished with zero URLs |

Skip only for local dev/tests:

```bash
uv run quora-scraper --skip-preflight --sender stdout
SKIP_PREFLIGHT=1 uv run quora-subscriber
```

Manual preflight (same checks):

```bash
uv run quora-preflight --mode all
uv run quora-preflight --mode subscriber
uv run quora-preflight --mode scraper
```

Copy and configure env files (never commit these):

```bash
cp .env.example .env.container   # subscriber: KAFKA_BOOTSTRAP, MONGODB_URI
cp .env.example .env.scraper     # scraper: PROFILE_URL, SENDER, KAFKA_BOOTSTRAP
```

`KAFKA_BOOTSTRAP` and `MONGODB_URI` have no in-code defaults — set them in env files.

**Browser:** the scraper auto-detects OS/runtime and picks the right Chrome binary and flags:

| Runtime | Browser | ChromeDriver |
|---------|---------|--------------|
| macOS | Google Chrome | Selenium Manager (auto-download) |
| Linux container | `/usr/bin/chromium` | system `chromedriver` |
| Linux host | chromium/google-chrome | PATH or Selenium Manager |

Override only when needed: `CHROME_BINARY`, `CHROMEDRIVER_PATH`, `USE_PATH_CHROMEDRIVER=1`.

## CLI entry points

| Command | Role |
|---------|------|
| `uv run qsbk` | Scrape answer URLs (primary CLI) |
| `uv run quora-scraper` | Alias for `qsbk` |
| `uv run quora-subscriber` | Consume Kafka → MongoDB |
| `uv run quora-preflight` | Infrastructure checks |
| `uv run quora-healthcheck` | Container liveness probes |

Legacy root shims (`quora_scraper.py`, `kafka_subscriber.py`) delegate to the package.

### Scraper (`qsbk`)

```bash
uv run qsbk --version
uv run qsbk --dry-run              # full infra check (Kafka, Mongo, browser, Quora)
uv run qsbk --dry-run --sender kafka   # strict: Kafka/Mongo failures = FAIL
uv run qsbk "https://pt.quora.com/profile/<USER>/answers"
MAX_RESULTS=10 uv run qsbk --sender stdout --skip-preflight
SENDER=kafka uv run qsbk --sender kafka
```

### Subscriber

```bash
uv run quora-subscriber
```

## Container deployment

Backend stack (**serve + subscriber**) runs on **bokomint** (Linux). The Chrome extension on your Mac talks to `http://bokomint.local:8765`. Both services use host networking so they reach Kafka on the same host.

### Remote (bokomint)

One-time on bokomint:

```bash
ssh bokomint.local
mkdir -p ~/quorascrapper
cd ~/quorascrapper
cp .env.example .env.container
# KAFKA_BOOTSTRAP=127.0.0.1:19092
# MONGODB_URI=...
```

From your Mac (sync + start):

```bash
./deploy_bokomint.sh up
./deploy_bokomint.sh logs
./deploy_bokomint.sh status
./deploy_bokomint.sh down
```

Install extension pointing at bokomint:

```bash
# Reinstall CLI first if --serve-url is missing
uv tool install --force /path/to/quorascrapper

qsbk install --serve-url http://bokomint.local:8765
# reload extension in chrome://extensions
```

If `curl http://bokomint.local:8765/ping` times out from the Mac, port 8765 is blocked on the LAN.
Either open the firewall on bokomint:

```bash
ssh bokomint.local
sudo ufw allow 8765/tcp
```

Or use an SSH tunnel (no firewall change):

```bash
./deploy_bokomint.sh tunnel   # leave running
qsbk install --serve-url http://127.0.0.1:8765
curl http://127.0.0.1:8765/ping
```

### Local (dev only)

```bash
cp .env.example .env.container   # KAFKA_BOOTSTRAP, MONGODB_URI

# Start subscriber + qsbk serve (preflight first)
./podman_qsbk.sh up
./podman_qsbk.sh logs            # both
./podman_qsbk.sh logs serve      # HTTP API only
./podman_qsbk.sh status
```

Or with compose directly:

```bash
docker compose run --rm preflight
docker compose up -d kafka-subscriber qsbk-serve
docker compose logs -f qsbk-serve kafka-subscriber
```

On-demand Selenium scraper (optional profile):

```bash
./podman_scraper.sh run --sender kafka
# or: docker compose --profile scraper run --rm quora-scraper
```

## Configuration

See [`.env.example`](.env.example). Key groups:

- **Kafka:** `KAFKA_BOOTSTRAP`, `KAFKA_TOPIC`, `KAFKA_GROUP_ID`
- **Mongo:** `MONGODB_URI`, `MONGODB_DATABASE`, `MONGODB_COLLECTION`
- **Scraper:** `PROFILE_URL`, `MAX_RESULTS`, `SCROLL_PAUSE`, `SENDER`, `CHROME_BINARY`

## Development

```bash
uv run pytest -q
uv run ruff check src tests
```

Integration helpers remain under `scripts/` for manual debugging.

## Package layout

```
src/quorascrapper/
  config.py           # Settings from env
  messaging/          # stdout + Kafka senders
  scraper/            # browser, scroll, extract, service
  subscriber/         # consumer, storage
  ops/                # preflight, healthcheck, discover_mongo
```
