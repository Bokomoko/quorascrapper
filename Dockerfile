FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md .env.example ./
COPY src ./src
COPY extension ./extension
RUN uv sync --frozen --no-cache

RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

# Default role; compose overrides for serve vs subscriber.
CMD ["uv", "run", "qsbk", "subscriber"]
