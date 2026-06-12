"""Tabular extension export → pipeline JSONL (url, hash, seen_at)."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any, Iterable

_PROFILE_ANSWER_RE = re.compile(r"/profile/[^/]+/answer/\d+", re.IGNORECASE)


def url_hash(url: str) -> str:
    return hashlib.blake2s(str(url).encode("utf-8"), digest_size=16).hexdigest()


def answer_url_kind(url: str) -> str:
    """Classify Quora answer URL shape: profile (canonical), question (legacy/wrong), invalid."""
    u = (url or "").strip()
    if not u or "/answer/" not in u:
        return "invalid"
    if _PROFILE_ANSWER_RE.search(u):
        return "profile"
    return "question"


def normalize_row(row: dict[str, Any]) -> dict[str, str] | None:
    url = (row.get("url") or row.get("answer_url") or "").strip()
    if not url or "/answer/" not in url:
        return None
    out: dict[str, str] = {"url": url, "hash": url_hash(url)}
    if seen := row.get("seen_at"):
        out["seen_at"] = str(seen)
    if title := row.get("question_title"):
        out["question_title"] = str(title)
    if preview := row.get("answer_preview"):
        out["answer_preview"] = str(preview)
    if qurl := row.get("question_url"):
        out["question_url"] = str(qurl)
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
