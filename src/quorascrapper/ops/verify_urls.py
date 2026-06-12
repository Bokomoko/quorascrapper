"""Verify answer URL quality in MongoDB."""

from __future__ import annotations

import argparse
import sys

from quorascrapper.config import Settings, load_project_env
from quorascrapper.filter.core import answer_url_kind
from quorascrapper.subscriber.storage import connect_mongo


def audit_collection(settings: Settings, *, sample: int = 5) -> int:
    client, collection = connect_mongo(settings)
    try:
        total = collection.count_documents({})
        profile = 0
        question = 0
        invalid = 0
        samples: dict[str, list[str]] = {"profile": [], "question": [], "invalid": []}

        for doc in collection.find({}, {"url": 1, "_id": 0}):
            url = str(doc.get("url") or "")
            kind = answer_url_kind(url)
            if kind == "profile":
                profile += 1
            elif kind == "question":
                question += 1
            else:
                invalid += 1
            if len(samples[kind]) < sample:
                samples[kind].append(url)

        print(f"MongoDB {settings.mongodb_database}.{settings.mongodb_collection}")
        print(f"  total:    {total}")
        print(f"  profile:  {profile}  (canonical /profile/.../answer/<id>-...)")
        print(f"  question: {question}  (legacy /Question-slug/answer/Author — often broken)")
        print(f"  invalid:  {invalid}")
        print()

        for kind, label in (
            ("question", "Question-format samples (likely wrong)"),
            ("profile", "Profile-format samples (OK)"),
            ("invalid", "Invalid samples"),
        ):
            if samples[kind]:
                print(label + ":")
                for url in samples[kind]:
                    print(f"  {url[:140]}{'…' if len(url) > 140 else ''}")
                print()

        if question and not profile:
            print(
                "All stored URLs use question-slug format. Re-scrape with extension v0.9.3+ "
                "after qsbk install; old rows keep wrong URLs (different hash)."
            )
            return 1
        if question:
            print(f"Warning: {question} non-canonical URL(s) remain in MongoDB.")
            return 1
        return 0
    finally:
        client.close()


def main(argv: list[str] | None = None) -> int:
    load_project_env()
    parser = argparse.ArgumentParser(
        prog="qsbk verify-urls",
        description="Audit answer URL format stored in MongoDB.",
    )
    parser.add_argument("--sample", type=int, default=5, help="Sample URLs per category")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    if not settings.mongodb_uri:
        print("MONGODB_URI is required", file=sys.stderr)
        return 1

    try:
        return audit_collection(settings, sample=args.sample)
    except Exception as exc:
        print(f"verify-urls failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
