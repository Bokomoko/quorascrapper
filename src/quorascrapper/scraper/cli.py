import argparse
import sys

from quorascrapper import __version__
from quorascrapper.config import Settings, load_project_env
from quorascrapper.exceptions import LoginWallError
from quorascrapper.messaging import KafkaSender, StdoutSender
from quorascrapper.ops.dry_run import print_dry_run_report, run_dry_run
from quorascrapper.ops.gate import (
    EXIT_LOGIN_WALL,
    abort_startup,
    require_scrape_gate,
)
from quorascrapper.ops.mongo_check import format_mongo_report, run_mongo_checks
from quorascrapper.scraper.service import QuoraScraper
from quorascrapper.scraper.stats import DEFAULT_PROFILE_URL, resolve_profile_url

try:
    from selenium.common.exceptions import WebDriverException
except Exception:  # pragma: no cover
    class WebDriverException(Exception):
        pass


def main(argv: list[str] | None = None) -> int:
    load_project_env()
    settings = Settings.from_env()

    parser = argparse.ArgumentParser(
        prog="qsbk",
        description="Quora profile answer URL scraper",
    )
    parser.add_argument("profile_url", nargs="?", help="Profile answers URL")
    parser.add_argument(
        "--sender",
        choices=["stdout", "kafka"],
        default=settings.sender,
        help="Output sender (default: stdout)",
    )
    parser.add_argument(
        "--mode",
        choices=["scroll", "graphql"],
        default=settings.scrape_mode,
        help="Extraction mode: scroll (DOM, default) or graphql (API pagination)",
    )
    parser.add_argument(
        "--check-mongo",
        action="store_true",
        help="Run MongoDB checks only (DNS + ping)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check env, Kafka, MongoDB, browser, Quora — no scrape",
    )
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip infrastructure preflight on real runs (dev/tests only)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"qsbk {__version__}",
    )
    args = parser.parse_args(argv)
    settings.scrape_mode = args.mode

    profile_url = resolve_profile_url(
        args.profile_url, settings.profile_url or None, DEFAULT_PROFILE_URL
    )

    if args.check_mongo:
        mongo = run_mongo_checks(settings, ensure_index=False, write_probe=False)
        for line in format_mongo_report(mongo):
            print(line)
        print("PASS" if mongo.ok else "FAIL")
        return 0 if mongo.ok else 1

    if args.dry_run:
        ok, report = run_dry_run(settings, args.sender)
        print_dry_run_report(
            version=__version__,
            profile_url=profile_url,
            sender=args.sender,
            settings=settings,
            report=report,
        )
        return 0 if ok else 1

    abort_startup("scraper", cli_skip=args.skip_preflight)

    if args.sender == "kafka":
        errors = settings.validate_scraper()
        if errors:
            print("; ".join(errors), file=sys.stderr)
            return 1

    try:
        scraper = QuoraScraper(sender=StdoutSender(), settings=settings)
    except WebDriverException:
        return 1

    if args.sender == "kafka":
        try:
            scraper.sender = KafkaSender(settings=settings)
        except Exception:
            scraper.close()
            return 1
    else:
        scraper.sender = StdoutSender()

    if args.sender == "kafka" and settings.kafka_healthcheck_enabled:
        if not scraper.kafka_healthcheck():
            scraper.close()
            return 1

    exit_code = 0
    try:
        processed = scraper.extract_content(profile_url)
        exit_code = require_scrape_gate(processed, scraper.login_wall_detected)
    except LoginWallError as exc:
        print(str(exc), file=sys.stderr)
        exit_code = EXIT_LOGIN_WALL
    except KeyboardInterrupt:
        pass
    finally:
        scraper.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
