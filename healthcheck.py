#!/usr/bin/env python3
"""Backward-compatible entry point. Prefer: uv run quora-healthcheck"""

from quorascrapper.ops.healthcheck import main

if __name__ == "__main__":
    raise SystemExit(main())
