#!/usr/bin/env python3
"""
MongoDB Atlas hostname DNS check.

Reads MONGODB_URI from the environment (or .env via dotenv) and verifies
the cluster hostname resolves. Never prints credentials.
"""

import os
import socket
import sys
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except ImportError:
    pass


def _hostname_from_uri(uri: str) -> str | None:
    """Extract hostname from mongodb:// or mongodb+srv:// URI."""
    if uri.startswith("mongodb+srv://"):
        rest = uri[len("mongodb+srv://") :]
        host_part = rest.split("@")[-1]
        return host_part.split("/")[0].split("?")[0] or None
    if uri.startswith("mongodb://"):
        parsed = urlparse(uri)
        return parsed.hostname
    return None


def test_dns_resolution() -> str | None:
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        print("MONGODB_URI is not set. Export it or add it to .env")
        return None

    hostname = _hostname_from_uri(uri)
    if not hostname:
        print("Could not parse hostname from MONGODB_URI")
        return None

    print("MongoDB hostname DNS check")
    print("=" * 40)
    print(f"Hostname: {hostname}")
    print()

    try:
        ip = socket.gethostbyname(hostname)
        print(f"DNS resolves to: {ip}")
        return hostname
    except socket.gaierror as e:
        print(f"DNS failed: {e}")
        print()
        print("Check Atlas dashboard: Connect > Connect your application")
        return None


if __name__ == "__main__":
    result = test_dns_resolution()
    sys.exit(0 if result else 1)
