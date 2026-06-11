"""MongoDB hostname DNS check from MONGODB_URI."""

from __future__ import annotations

import socket
from urllib.parse import urlparse


def hostname_from_uri(uri: str) -> str | None:
    if uri.startswith("mongodb+srv://"):
        rest = uri[len("mongodb+srv://") :]
        host_part = rest.split("@")[-1]
        return host_part.split("/")[0].split("?")[0] or None
    if uri.startswith("mongodb://"):
        return urlparse(uri).hostname
    return None


def check_mongo_dns(uri: str) -> tuple[bool, str]:
    hostname = hostname_from_uri(uri)
    if not hostname:
        return False, "Could not parse hostname from MONGODB_URI"

    if uri.startswith("mongodb+srv://"):
        try:
            import dns.resolver

            answers = dns.resolver.resolve(f"_mongodb._tcp.{hostname}", "SRV")
            targets = sorted({str(record.target).rstrip(".") for record in answers})
            preview = ", ".join(targets[:3])
            if len(targets) > 3:
                preview += f" (+{len(targets) - 3} more)"
            return True, f"SRV OK: {hostname} -> {preview}"
        except Exception as exc:
            return False, f"SRV lookup failed for {hostname}: {exc}"

    try:
        ip = socket.gethostbyname(hostname)
        return True, f"DNS OK: {hostname} -> {ip}"
    except socket.gaierror as exc:
        return False, f"DNS failed for {hostname}: {exc}"
