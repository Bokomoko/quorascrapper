"""Unified dry-run: validate full pipeline infra without scraping."""

from __future__ import annotations

from quorascrapper.config import Settings
from quorascrapper.ops.preflight import PreflightReport, run_preflight
from quorascrapper.scraper.browser_env import detect_browser_environment


def _status_symbol(status: str) -> str:
    return {"pass": "OK", "warn": "WARN", "fail": "FAIL"}.get(status, status.upper())


def _group_results(report: PreflightReport) -> dict[str, list]:
    groups: dict[str, list] = {
        "config": [],
        "kafka": [],
        "mongo": [],
        "browser": [],
        "quora": [],
        "other": [],
    }
    for r in report.results:
        if r.name.startswith(("env_", "kafka")):
            groups["kafka" if r.name.startswith("kafka") else "config"].append(r)
        elif r.name.startswith("mongo"):
            groups["mongo"].append(r)
        elif r.name.startswith(("chromium", "chromedriver", "selenium")):
            groups["browser"].append(r)
        elif r.name == "quora_reachability":
            groups["quora"].append(r)
        else:
            groups["other"].append(r)
    return groups


def _dry_run_ok(report: PreflightReport, sender: str) -> bool:
    """Fail on hard errors; stdout sender tolerates kafka/mongo failures."""
    hard_fail_names = {
        "env_required",
        "chromium",
        "selenium_smoke",
    }
    if sender == "kafka":
        hard_fail_names.update({"kafka_dns", "kafka_broker"})

    for r in report.results:
        if r.status != "fail":
            continue
        if r.name in hard_fail_names:
            return False
        if sender == "kafka" and r.name.startswith("mongo"):
            return False
    return True


def print_dry_run_report(
    *,
    version: str,
    profile_url: str,
    sender: str,
    settings: Settings,
    report: PreflightReport,
) -> None:
    env = detect_browser_environment(settings.chrome_binary)
    print(f"qsbk {version} (dry-run)")
    print("--- config ---")
    print(f"profile_url: {profile_url}")
    print(f"sender: {sender}")
    print(f"max_results: {settings.max_results}")
    print(f"kafka_bootstrap: {settings.kafka_bootstrap or '(not set)'}")
    print(f"kafka_topic: {settings.kafka_topic}")
    print(f"mongodb_uri: {'set' if settings.mongodb_uri else '(not set)'}")
    print(f"runtime: {env.runtime} ({env.system})")
    print(f"browser: {env.browser_binary or '(not found)'}")

    groups = _group_results(report)
    labels = {
        "config": "environment",
        "kafka": "kafka",
        "mongo": "mongodb",
        "browser": "browser / selenium",
        "quora": "quora",
        "other": "other",
    }
    for key, title in labels.items():
        items = groups[key]
        if not items and key != "browser":
            continue
        print(f"--- {title} ---")
        if key == "browser" and not items:
            print(f"selenium_manager: {env.use_selenium_manager}")
            continue
        for r in items:
            print(f"{r.name}: {_status_symbol(r.status)} — {r.detail}")

    print("--- summary ---")
    fails = [r.name for r in report.results if r.status == "fail"]
    warns = [r.name for r in report.results if r.status == "warn"]
    if fails:
        print(f"failures: {', '.join(fails)}")
    if warns:
        print(f"warnings: {', '.join(warns)}")
    print("PASS" if _dry_run_ok(report, sender) else "FAIL")


def run_dry_run(settings: Settings, sender: str) -> tuple[bool, PreflightReport]:
    report = run_preflight(mode="dry_run")
    return _dry_run_ok(report, sender), report
