# Quora Profile Scraper

Scrape Quora profile answer URLs and stream them to Kafka (or stdout).

## Setup (uv-only)

Install uv (one-time):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# then restart your shell or source your profile if needed
```

`uv run` will create the environment and install dependencies on first use.

## Running the Scraper

Run with a profile URL:

```bash
uv run quora_scraper.py "https://pt.quora.com/profile/<USER>/answers"
```

Or via env var if no CLI arg is passed:

```bash
PROFILE_URL="https://pt.quora.com/profile/<USER>/answers" uv run quora_scraper.py
```

Choose the output sender:

```bash
# stdout (default)
uv run quora_scraper.py --sender stdout

# Kafka
SENDER=kafka uv run quora_scraper.py --sender kafka
```

## Output

Emits one JSON line per answer URL to the selected sender:

- stdout: JSONL to stdout
- Kafka: JSONL messages to the configured topic

## Kafka Configuration

Environment variables:

- `KAFKA_BOOTSTRAP` (default: `192.168.1.116:9092`)
- `KAFKA_TOPIC` (default: `quora-answers`)
- `KAFKA_HEALTHCHECK`: set `0` to skip startup healthcheck

Example:

```bash
KAFKA_BOOTSTRAP=192.168.1.116:9092 KAFKA_TOPIC=quora-answers uv run quora_scraper.py --sender kafka
```

### .env support

Variables from a local `.env` are loaded automatically. For a LAN broker:

```env
KAFKA_BOOTSTRAP=bokodell14.local:19092
KAFKA_TOPIC=quora-answers
```

Then run:

```bash
SENDER=kafka MAX_RESULTS=10 uv run quora_scraper.py
```

If `bokodell14.local` should resolve to `192.168.1.116`, ensure your DNS or `/etc/hosts` has that mapping.

## Other Environment Variables

- `PROFILE_URL`: profile URL (if not passed via CLI)
- `MAX_RESULTS`: cap on number of answers to send
- `LOG_LEVEL`: logging level (default WARNING)
- `SCROLL_PAUSE`: seconds to wait between scrolls (default 1.5)
- `DRY_RUN`: `1` to skip Kafka produce (mostly for legacy; stdout sender is preferred)

## Notes

- No files are written; data flows to stdout or Kafka.
- Ensure the Kafka broker is reachable from your machine.

## Dev quick commands

```bash
uv run quora_scraper.py
uvx pytest -q
```
