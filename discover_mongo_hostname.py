#!/usr/bin/env python3
"""Backward-compatible MongoDB DNS check."""

import sys

from dotenv import load_dotenv

from quorascrapper.config import Settings
from quorascrapper.ops.discover_mongo import check_mongo_dns

load_dotenv()


def main() -> int:
    uri = Settings.from_env().mongodb_uri
    if not uri:
        print("MONGODB_URI is not set")
        return 1
    ok, msg = check_mongo_dns(uri)
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
