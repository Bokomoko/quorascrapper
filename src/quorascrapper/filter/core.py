"""Tabular extension export → pipeline JSONL (url, hash, seen_at)."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

_PROFILE_ANSWER_RE = re.compile(r"/profile/[^/]+/answer/\d+", re.IGNORECASE)

# Profile tab suffixes appended to /profile/<slug> that must be stripped so a
# profile maps to a single canonical URL (and therefore a single userid).
_PROFILE_TAB_SUFFIX_RE = re.compile(
    r"/(answers|questions|posts|followers|following|spaces|shares|edits|"
    r"activity|knows-about|topics|tribes|likes)/?$",
    re.IGNORECASE,
)


def url_hash(url: str) -> str:
    return hashlib.blake2s(str(url).encode("utf-8"), digest_size=16).hexdigest()


def canonical_profile_url(url: str) -> str:
    """Canonicalize a Quora profile URL so a profile maps to one stable userid.

    Forces ``https``, lowercases the host, drops query/fragment, strips a
    trailing profile tab suffix (``/answers``, ``/questions``, ...) and any
    trailing slash. The path case is preserved (Quora slugs are case-sensitive).
    Returns ``""`` for empty input and best-effort cleans scheme-less input.
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    netloc = (parts.netloc or "").lower()
    path = _PROFILE_TAB_SUFFIX_RE.sub("", parts.path or "")
    path = path.rstrip("/")
    return urlunsplit(("https", netloc, path, "", ""))


def profile_userid(profile_url: str) -> str:
    """Stable per-profile id: blake2s hash of the canonical profile URL."""
    return url_hash(canonical_profile_url(profile_url))


def answer_url_kind(url: str) -> str:
    """Classify Quora answer URL shape: profile (canonical), question (legacy/wrong), invalid."""
    u = (url or "").strip()
    if not u or "/answer/" not in u:
        return "invalid"
    if _PROFILE_ANSWER_RE.search(u):
        return "profile"
    return "question"


# Optional richer fields captured by the GraphQL extension method. Strings are
# copied as-is; numeric fields are preserved as numbers (0 is meaningful).
#
# Profile identity fields are stamped onto every answer by the extension so the
# subscriber can route docs into a per-profile collection and maintain a
# profiles registry. ``profile_url``/``profile_name``/``profile_display_name``
# are readable fields; ``userid`` (the stable hash of the canonical profile URL)
# is derived server-side in serve but also passed through if already present.
_PASSTHROUGH_STR = (
    "seen_at",
    "question_title",
    "answer_preview",
    "question_url",
    "answer_text",
    "aid",
    "userid",
    "profile_name",
    "profile_url",
    "profile_display_name",
)
_PASSTHROUGH_NUM = (
    "num_upvotes",
    "num_views",
    "num_comments",
    "creation_time",
    "profile_answer_count",
)


def normalize_row(row: dict[str, Any]) -> dict[str, Any] | None:
    url = (row.get("url") or row.get("answer_url") or "").strip()
    if not url or "/answer/" not in url:
        return None
    out: dict[str, Any] = {"url": url, "hash": url_hash(url)}
    for key in _PASSTHROUGH_STR:
        value = row.get(key)
        if value not in (None, ""):
            out[key] = str(value)
    for key in _PASSTHROUGH_NUM:
        value = row.get(key)
        if value is not None:
            out[key] = value
    return out


def parse_csv(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, str]] = []
    for raw in reader:
        if normalized := normalize_row(raw):
            rows.append(normalized)
    return rows


def parse_jsonl(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        raw = json.loads(line)
        if normalized := normalize_row(raw):
            rows.append(normalized)
    return rows


def dedupe_rows(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for row in rows:
        h = row["hash"]
        if h in seen:
            continue
        seen.add(h)
        out.append(row)
    return out


def load_export(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        rows = parse_csv(text)
    elif suffix in {".jsonl", ".ndjson"}:
        rows = parse_jsonl(text)
    elif suffix == ".json":
        data = json.loads(text)
        if isinstance(data, list):
            rows = [r for item in data if (r := normalize_row(item))]
        elif isinstance(data, dict) and isinstance(data.get("answers"), list):
            rows = [r for item in data["answers"] if (r := normalize_row(item))]
        else:
            rows = [r for item in data.get("rows", []) if (r := normalize_row(item))]
    else:
        raise ValueError(f"Unsupported format: {suffix} (use .csv, .jsonl, .json)")
    return dedupe_rows(rows)


def to_jsonl(rows: list[dict[str, str]]) -> str:
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + ("\n" if rows else "")


def to_csv(rows: list[dict[str, str]]) -> str:
    buf = io.StringIO()
    fields = ["url", "hash", "seen_at"]
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in fields})
    return buf.getvalue()
