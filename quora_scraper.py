#!/usr/bin/env python3
"""Backward-compatible entry point. Prefer: uv run qsbk"""

from quorascrapper.scraper.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
