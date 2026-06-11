#!/usr/bin/env python3
"""Backward-compatible entry point. Prefer: uv run quora-subscriber"""

from quorascrapper.subscriber.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
