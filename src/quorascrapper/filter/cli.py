"""CLI: extension CSV/JSONL → pipeline JSONL with hashes."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from quorascrapper.filter.core import load_export, to_csv, to_jsonl


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Filter extension export (CSV/JSONL) → pipeline tabular JSONL with url+hash."
    )
    parser.add_argument("input", type=Path, help="Extension export (.csv, .jsonl, .json)")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output path (.jsonl or .csv). Default: stdout JSONL",
    )
    parser.add_argument(
        "--format",
        choices=("jsonl", "csv"),
        help="Output format (default: jsonl, or from -o extension)",
    )
    args = parser.parse_args(argv)

    if not args.input.is_file():
        print(f"Not found: {args.input}", file=sys.stderr)
        return 1

    rows = load_export(args.input)
    fmt = args.format
    if not fmt and args.output:
        fmt = "csv" if args.output.suffix.lower() == ".csv" else "jsonl"
    fmt = fmt or "jsonl"

    body = to_csv(rows) if fmt == "csv" else to_jsonl(rows)

    if args.output:
        args.output.write_text(body, encoding="utf-8")
        print(f"Wrote {len(rows)} rows → {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
