FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

# Set working directory
WORKDIR /app

# Install system dependencies needed for confluent-kafka/pymongo builds if any
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files and sync deps using uv (no pip)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-cache

# Copy application files
COPY kafka_subscriber.py ./
COPY quora_selectors.py ./
COPY senders.py ./
COPY logging_setup.py ./

# Create non-root user and set permissions
RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD uv run python -c "import sys; sys.exit(0)"

# Default command
CMD ["uv", "run", "kafka_subscriber.py"]
