# Quora Profile Scraper

Scrape Quora profile answer URLs and stream them to Kafka.

## Setup (uv-only)

- You do not need to pre-install Python or pip. Install only uv; it will manage Python 3.13, the virtual environment, and dependencies.

Install uv (one-time):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# then restart your shell or source your profile if needed
```

That's it. You can skip creating a venv or syncing dependencies manually—`uv run` will handle it automatically on first use.

## Running the Scraper

Run (uv will create the environment and install deps automatically on first run):

```bash
uv run quora_scraper.py "https://pt.quora.com/profile/<USER>/answers"
# or: uv run -m quora_scraper "https://pt.quora.com/profile/<USER>/answers" if packaged as a module later
```

Alternatively, set the URL via environment variable (takes effect if no CLI arg is passed):

```bash
PROFILE_URL="https://pt.quora.com/profile/<USER>/answers" uv run quora_scraper.py
```

The script will:

- Start a headless Chrome browser
- Load the profile's answer page (parameter)
- Scroll down through all the pages (page down)
- Extract the answers url from the page
- Send it to a Kafka topic (default as coded)

## Output

No output file is generated. All answer URLs are sent as messages to Kafka.

## Kafka Configuration

You can customize the Kafka broker and topic using environment variables:

- `KAFKA_BOOTSTRAP` (default: `192.168.1.116:9092`)
- `KAFKA_TOPIC` (default: `quora-answers`)
- `PROFILE_URL` (optional): profile answers URL if you prefer env-based configuration

Example (zsh/bash):

```bash
KAFKA_BOOTSTRAP=192.168.1.116:9092 KAFKA_TOPIC=quora-answers uv run quora_scraper.py
```

## Other Environment Variables

- `MAX_RESULTS`: Maximum number of answers to collect (default: profile's answer count)
- `LOG_LEVEL`: Set logging level (INFO, DEBUG, etc)
- `SCROLL_PAUSE`: Seconds to wait between scrolls (default: 1.5)

## Notes

- No data is saved locally; all persistence is via Kafka.
- Make sure your Kafka server is reachable from the machine running the scraper.

## Using uv scripts

This project defines uv scripts in `pyproject.toml`:

- Run scraper: `uv run`
- Test (pytest): `uv run test`
- Build distribution: `uv run build`

If you prefer calling the commands explicitly:

```bash
uv run quora_scraper.py
uvx pytest -q
uv build
```
