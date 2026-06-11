# Quora Profile Scraper

Scrape Quora profile answer URLs and stream them to Kafka (or stdout). A Kafka subscriber upserts each message into MongoDB Atlas.

## Architecture

```
Quora profile → quora-scraper → Kafka (LAN) → quora-subscriber → MongoDB Atlas
```

Message contract (unchanged): `{"url": "...", "hash": "<blake2s-16>"}` per answer URL.

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

Uses host networking (required for LAN Kafka DNS).

```bash
# Subscriber stack (preflight → subscriber)
./podman_subscriber.sh up
./podman_subscriber.sh logs

# On-demand scraper
./podman_scraper.sh run --sender kafka
```

Or with compose directly:

```bash
docker compose run --rm preflight
docker compose up -d kafka-subscriber
docker compose --profile scraper run --rm quora-scraper
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
