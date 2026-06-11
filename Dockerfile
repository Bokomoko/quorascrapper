FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-cache

RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD ["uv", "run", "quora-healthcheck", "subscriber"]

CMD ["uv", "run", "quora-subscriber"]
