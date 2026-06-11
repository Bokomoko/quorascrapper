"""MongoDB connectivity checks (DNS, ping, index, write probe)."""

from __future__ import annotations

from dataclasses import dataclass, field

from quorascrapper.config import Settings
from quorascrapper.ops.discover_mongo import check_mongo_dns, hostname_from_uri

_PLACEHOLDER_MARKERS = ("username:password", "your-connection", "secure_password")


@dataclass
class MongoCheck:
    name: str
    ok: bool
    detail: str


@dataclass
class MongoCheckReport:
    results: list[MongoCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.results.append(MongoCheck(name=name, ok=ok, detail=detail))


def run_mongo_checks(
    settings: Settings,
    *,
    ensure_index: bool = False,
    write_probe: bool = False,
) -> MongoCheckReport:
    report = MongoCheckReport()
    uri = settings.mongodb_uri

    if not uri:
        report.add("mongo_config", False, "MONGODB_URI not set")
        return report

    if any(m in uri for m in _PLACEHOLDER_MARKERS):
        report.add("mongo_config", False, "MONGODB_URI appears to be a placeholder")
        return report

    host = hostname_from_uri(uri)
    report.add("mongo_host", True, host or "(unknown)")

    dns_ok, dns_msg = check_mongo_dns(uri)
    report.add("mongo_dns", dns_ok, dns_msg)
    if not dns_ok:
        return report

    client = None
    try:
        from pymongo import MongoClient  # type: ignore

        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        report.add("mongo_ping", True, "Ping OK")
    except Exception as exc:
        report.add("mongo_ping", False, str(exc))
        return report

    if ensure_index:
        try:
            coll = client[settings.mongodb_database][settings.mongodb_collection]
            indexes = {idx["name"] for idx in coll.list_indexes()}
            if "hash_unique" in indexes:
                report.add("mongo_index", True, "hash_unique index present")
            else:
                coll.create_index(
                    [("hash", 1)], unique=True, sparse=True, name="hash_unique"
                )
                report.add("mongo_index", True, "hash_unique index created")
        except Exception as exc:
            report.add("mongo_index", False, str(exc))

    if write_probe:
        try:
            coll = client[settings.mongodb_database][settings.mongodb_collection]
            probe = {"hash": "preflight_probe", "url": "https://preflight.local/probe"}
            coll.replace_one({"hash": probe["hash"]}, probe, upsert=True)
            coll.delete_one({"hash": probe["hash"]})
            report.add("mongo_write", True, "Upsert/delete probe OK")
        except Exception as exc:
            report.add("mongo_write", False, str(exc))

    if client is not None:
        try:
            client.close()
        except Exception:
            pass

    return report


def format_mongo_report(report: MongoCheckReport) -> list[str]:
    lines: list[str] = []
    for check in report.results:
        if check.name == "mongo_host":
            lines.append(f"mongo_host: {check.detail}")
            continue
        status = "pass" if check.ok else "FAIL"
        lines.append(f"{check.name}: {status} — {check.detail}")
    return lines


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    from quorascrapper.config import Settings, load_project_env

    parser = argparse.ArgumentParser(description="MongoDB connectivity check")
    parser.add_argument("--full", action="store_true", help="Index + write probe")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args(argv)

    load_project_env()
    settings = Settings.from_env()
    report = run_mongo_checks(
        settings,
        ensure_index=args.full,
        write_probe=args.full,
    )

    if args.json:
        import json

        payload = {
            "ok": report.ok,
            "checks": [
                {"name": c.name, "ok": c.ok, "detail": c.detail} for c in report.results
            ],
        }
        print(json.dumps(payload, indent=2))
    else:
        for line in format_mongo_report(report):
            print(line)
        print("PASS" if report.ok else "FAIL")

    return 0 if report.ok else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())

