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

- `KAFKA_BOOTSTRAP` (default: `bokomint.local:19092`)
- `KAFKA_TOPIC` (default: `quora-answers`)
- `KAFKA_HEALTHCHECK_TOPIC` (default: `healthcheck`)
- `KAFKA_HEALTHCHECK`: set `0` to skip startup healthcheck

Example:

```bash
KAFKA_BOOTSTRAP=bokomint.local:19092 KAFKA_TOPIC=quora-answers uv run quora_scraper.py --sender kafka
```

### .env support

Variables from a local `.env` are loaded automatically. For a LAN broker:

```env
KAFKA_BOOTSTRAP=bokomint.local:19092
KAFKA_TOPIC=quora-answers
```

Then run:

```bash
SENDER=kafka MAX_RESULTS=10 uv run quora_scraper.py
```

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
uv run kafka_subscriber.py
uv run pytest -q
```

Manual integration scripts live under `scripts/` (Kafka producer test, Mongo connection test, etc.).

## Kafka Consumer - MongoDB Integration

The project includes a Kafka consumer (`kafka_subscriber.py`) that reads scraped URLs from Kafka and stores them in MongoDB Atlas.

### Setup MongoDB Subscriber

1. **Configure MongoDB Atlas**:
   - Create a MongoDB Atlas cluster
   - Get your connection string from Atlas dashboard
   - Set the `MONGODB_URI` environment variable

2. **Environment Variables**:
   ```bash
   # Copy the example and configure
   cp .env.example .env

   # Edit .env with your MongoDB Atlas connection string
   MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/?retryWrites=true&w=majority
   ```

3. **Run the subscriber**:
   ```bash
   # Install additional dependencies
   uv add pymongo

   # Run the Kafka subscriber
   uv run kafka_subscriber.py
   ```

### Consumer Features

- **Automatic deduplication**: Uses URL hash to prevent duplicate entries
- **Error handling**: Failed Mongo writes are retried; invalid messages are skipped; offsets commit after successful storage
- **Statistics**: Real-time processing statistics
- **Graceful shutdown**: Handles interruption signals properly

### Usage Example

```bash
# Terminal 1: Start the subscriber
MONGODB_URI="your-connection-string" uv run kafka_subscriber.py

# Terminal 2: Run the scraper
SENDER=kafka uv run quora_scraper.py "https://pt.quora.com/profile/USER/answers"
```

The subscriber will automatically:
1. Connect to Kafka and MongoDB Atlas
2. Consume messages from the `quora-answers` topic
3. Store URLs in MongoDB with metadata (processed_at, source)
4. Handle duplicates using the hash field
5. Log processing statistics

## Container Deployment (Podman)

For production deployment, the subscriber can run in a Podman container:

### Quick Start with Containers

1. **Configure environment**:
   ```bash
   # Copy and edit container environment
   cp .env.example .env.container
   # Edit .env.container with your MongoDB Atlas connection string
   ```

2. **Build and run**:
   ```bash
   # Build the container image
   ./podman_subscriber.sh build

   # Start the subscriber container
   ./podman_subscriber.sh start
   ```

3. **Monitor**:
   ```bash
   # View logs in real-time
   ./podman_subscriber.sh logs

   # Check status
   ./podman_subscriber.sh status
   ```

### Container Management Commands

```bash
./podman_subscriber.sh build     # Build container image
./podman_subscriber.sh start     # Start subscriber container
./podman_subscriber.sh stop      # Stop container
./podman_subscriber.sh restart   # Restart container
./podman_subscriber.sh logs      # Follow logs
./podman_subscriber.sh status    # Show status
./podman_subscriber.sh shell     # Interactive shell
./podman_subscriber.sh rebuild   # Rebuild and restart
```

### Using Docker Compose (Alternative)

```bash
# Start with docker-compose
podman-compose -f docker-compose.yml up -d

# View logs
podman-compose -f docker-compose.yml logs -f

# Stop
podman-compose -f docker-compose.yml down
```
