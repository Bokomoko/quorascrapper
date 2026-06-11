"""Unified infrastructure pre-flight checks before scrape or subscriber runs."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values

from quorascrapper.config import Settings
from quorascrapper.ops.discover_mongo import check_mongo_dns
from quorascrapper.ops.mongo_check import run_mongo_checks
from quorascrapper.scraper.browser_env import (
    chromedriver_diagnostics,
    detect_browser_environment,
)
from quorascrapper.selectors import LOGIN_WALL_MARKERS

Mode = Literal["subscriber", "scraper", "all", "deploy", "dry_run"]
Severity = Literal["pass", "warn", "fail"]

_PLACEHOLDER_MARKERS = ("username:password", "your-connection", "secure_password")


@dataclass
class CheckResult:
    name: str
    status: Severity
    detail: str


@dataclass
class PreflightReport:
    mode: Mode
    results: list[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(r.status == "fail" for r in self.results)

    def add(self, name: str, status: Severity, detail: str) -> None:
        self.results.append(CheckResult(name=name, status=status, detail=detail))


def _kafka_host_port(bootstrap: str) -> tuple[str, int]:
    if ":" in bootstrap:
        host, port_s = bootstrap.rsplit(":", 1)
        return host, int(port_s)
    return bootstrap, 9092


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return {k: v for k, v in dotenv_values(path).items() if v is not None}


def check_env_files(report: PreflightReport, mode: Mode) -> Settings:
    from quorascrapper.config import load_project_env

    load_project_env()
    merged: dict[str, str] = {}
    for name in (".env", ".env.container", ".env.scraper"):
        merged.update(_load_env_file(Path(name)))
    for key, value in merged.items():
        os.environ.setdefault(key, value)

    settings = Settings.from_env()
    missing: list[str] = []
    if mode in ("subscriber", "all", "deploy"):
        if not settings.mongodb_uri:
            missing.append("MONGODB_URI")
        elif any(m in settings.mongodb_uri for m in _PLACEHOLDER_MARKERS):
            report.add("env_mongodb", "fail", "MONGODB_URI is a placeholder")
    elif mode == "dry_run" and settings.mongodb_uri:
        if any(m in settings.mongodb_uri for m in _PLACEHOLDER_MARKERS):
            report.add("env_mongodb", "fail", "MONGODB_URI is a placeholder")
    if mode in ("subscriber", "scraper", "all", "deploy", "dry_run"):
        if not settings.kafka_bootstrap:
            if mode == "dry_run":
                report.add("env_kafka", "warn", "KAFKA_BOOTSTRAP not set")
            else:
                missing.append("KAFKA_BOOTSTRAP")

    if missing:
        report.add("env_required", "fail", f"Missing: {', '.join(missing)}")
    else:
        report.add("env_required", "pass", "Required environment variables present")
    return settings


def check_kafka_dns(report: PreflightReport, settings: Settings) -> None:
    host, _ = _kafka_host_port(settings.kafka_bootstrap)
    try:
        ip = socket.gethostbyname(host)
        report.add("kafka_dns", "pass", f"{host} -> {ip}")
    except socket.gaierror as exc:
        report.add("kafka_dns", "fail", f"{host}: {exc}")


def check_mongo_dns_report(report: PreflightReport, settings: Settings) -> None:
    if not settings.mongodb_uri:
        report.add("mongo_dns", "fail", "MONGODB_URI not set")
        return
    ok, msg = check_mongo_dns(settings.mongodb_uri)
    report.add("mongo_dns", "pass" if ok else "fail", msg)


def check_mongo_all(report: PreflightReport, settings: Settings, *, full: bool = True) -> None:
    mongo = run_mongo_checks(
        settings,
        ensure_index=full,
        write_probe=full,
    )
    for check in mongo.results:
        if check.name == "mongo_host":
            continue
        report.add(check.name, "pass" if check.ok else "fail", check.detail)


def check_kafka_broker(report: PreflightReport, settings: Settings) -> list[str]:
    try:
        from confluent_kafka.admin import AdminClient  # type: ignore

        admin = AdminClient({"bootstrap.servers": settings.kafka_bootstrap})
        meta = admin.list_topics(timeout=5)
        topics = list(meta.topics.keys())
        report.add("kafka_broker", "pass", f"Broker reachable ({len(topics)} topics)")
        return topics
    except Exception as exc:
        report.add("kafka_broker", "fail", str(exc))
        return []


def check_kafka_topic(report: PreflightReport, settings: Settings, topics: list[str]) -> None:
    if settings.kafka_topic in topics:
        report.add("kafka_topic", "pass", f"Topic '{settings.kafka_topic}' exists")
    else:
        report.add(
            "kafka_topic",
            "warn",
            f"Topic '{settings.kafka_topic}' not found; may need creation",
        )


def check_chromium(report: PreflightReport, settings: Settings) -> None:
    env = detect_browser_environment(settings.chrome_binary)
    path = env.browser_binary
    if path and os.access(path, os.X_OK):
        report.add(
            "chromium",
            "pass",
            f"{env.browser_label}: {path} (runtime={env.runtime})",
        )
    elif path:
        report.add("chromium", "pass", f"Found {path} (runtime={env.runtime})")
    elif env.runtime == "macos" and env.use_selenium_manager:
        report.add(
            "chromium",
            "pass",
            f"{env.browser_label} (runtime={env.runtime}; system Chrome avoided)",
        )
    else:
        configured = settings.chrome_binary or "(auto-detect)"
        report.add(
            "chromium",
            "warn",
            f"No browser for runtime={env.runtime}: {configured}",
        )
    for hint in chromedriver_diagnostics(env):
        name = "chromedriver" if env.runtime != "macos" else "chromedriver_macos"
        report.add(name, "warn", hint)


def check_selenium_smoke(report: PreflightReport, settings: Settings) -> None:
    try:
        from quorascrapper.scraper.browser import create_driver, quit_driver

        class _Log:
            def info(self, *a, **k):
                pass

            def error(self, *a, **k):
                pass

            def debug(self, *a, **k):
                pass

        driver = create_driver(settings, _Log())
        driver.get("about:blank")
        quit_driver(driver)
        report.add("selenium_smoke", "pass", "WebDriver started")
    except Exception as exc:
        report.add("selenium_smoke", "warn", f"WebDriver smoke skipped: {exc}")


def check_quora_reachability(report: PreflightReport, settings: Settings) -> None:
    url = settings.profile_url or (
        "https://pt.quora.com/profile/Jo%C3%A3o-Eurico-de-Aguiar-Lima/answers"
    )
    try:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read(50000).decode("utf-8", errors="replace").lower()
        if any(marker in body for marker in LOGIN_WALL_MARKERS):
            report.add(
                "quora_reachability",
                "warn",
                "Login wall markers detected; headless scrape may return 0 URLs",
            )
        elif "/answer/" in body:
            report.add("quora_reachability", "pass", "Page reachable with answer links in HTML")
        else:
            report.add(
                "quora_reachability",
                "warn",
                "Page reachable but no /answer/ links in initial HTML (SPA may need scroll)",
            )
    except urllib.error.URLError as exc:
        report.add("quora_reachability", "warn", f"HTTP check failed: {exc}")


def check_container_runtime(report: PreflightReport) -> None:
    for cmd, name in (("podman", "Podman"), ("docker", "Docker")):
        try:
            proc = subprocess.run(
                [cmd, "info"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if proc.returncode == 0:
                report.add("container_runtime", "pass", f"{name} daemon OK")
                return
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    report.add("container_runtime", "warn", "Neither podman nor docker daemon reachable")


def check_image_build(report: PreflightReport, do_build: bool) -> None:
    root = Path.cwd()
    dockerfiles = [root / "Dockerfile", root / "Dockerfile.scraper"]
    missing = [str(p.name) for p in dockerfiles if not p.exists()]
    if missing:
        report.add("image_build", "fail", f"Missing Dockerfiles: {', '.join(missing)}")
        return
    if not do_build:
        report.add("image_build", "pass", "Dockerfiles present (use --build to verify)")
        return
    for df in dockerfiles:
        try:
            subprocess.run(
                ["docker", "build", "-f", str(df), "-t", f"preflight-{df.name}", "."],
                check=True,
                capture_output=True,
                timeout=600,
            )
            report.add("image_build", "pass", f"Built {df.name}")
        except Exception as exc:
            report.add("image_build", "fail", f"{df.name}: {exc}")
            return


def run_preflight(mode: Mode = "all", do_build: bool = False) -> PreflightReport:
    report = PreflightReport(mode=mode)
    settings = check_env_files(report, mode)

    if mode in ("subscriber", "scraper", "all", "deploy", "dry_run"):
        if settings.kafka_bootstrap:
            check_kafka_dns(report, settings)
            topics = check_kafka_broker(report, settings)
            check_kafka_topic(report, settings, topics)
        elif mode == "dry_run":
            report.add("kafka_dns", "warn", "Skipped (KAFKA_BOOTSTRAP not set)")

    if mode in ("subscriber", "all", "deploy"):
        check_mongo_all(report, settings, full=True)
    elif mode in ("scraper", "dry_run") and settings.mongodb_uri:
        check_mongo_all(report, settings, full=False)
    elif mode == "dry_run" and not settings.mongodb_uri:
        report.add("mongo_config", "warn", "MONGODB_URI not set (subscriber will fail)")

    if mode in ("scraper", "all", "dry_run"):
        check_chromium(report, settings)
        check_selenium_smoke(report, settings)
        check_quora_reachability(report, settings)

    if mode in ("deploy", "all"):
        check_container_runtime(report)
        check_image_build(report, do_build)

    return report


def print_report(report: PreflightReport, as_json: bool) -> None:
    if as_json:
        payload = {
            "mode": report.mode,
            "ok": report.ok,
            "checks": [
                {"name": r.name, "status": r.status, "detail": r.detail}
                for r in report.results
            ],
        }
        print(json.dumps(payload, indent=2))
        return

    print(f"Preflight mode={report.mode}")
    print("-" * 60)
    for r in report.results:
        print(f"[{r.status.upper():4}] {r.name}: {r.detail}")
    print("-" * 60)
    print("PASS" if report.ok else "FAIL")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Infrastructure pre-flight checks")
    parser.add_argument(
        "--mode",
        choices=["subscriber", "scraper", "all", "deploy"],
        default="all",
    )
    parser.add_argument("--build", action="store_true", help="Build Docker images")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args(argv)

    report = run_preflight(mode=args.mode, do_build=args.build)
    print_report(report, args.json)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
