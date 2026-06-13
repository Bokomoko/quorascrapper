"""Dispatch qsbk subcommands (install, filter) or default scrape."""

from __future__ import annotations

import sys

_SUBCOMMANDS = frozenset(
    {
        "install",
        "filter",
        "ingest",
        "config",
        "serve",
        "subscriber",
        "verify-urls",
        "monitor",
    }
)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in _SUBCOMMANDS:
        cmd = argv[0]
        rest = argv[1:]
        if cmd == "install":
            from quorascrapper.ops.install import main as install_main

            return install_main(rest)
        if cmd == "filter":
            from quorascrapper.filter.cli import main as filter_main

            return filter_main(rest)
        if cmd == "ingest":
            from quorascrapper.ops.ingest import main as ingest_main

            return ingest_main(rest)
        if cmd == "config":
            from quorascrapper.ops.config_cmd import main as config_main

            return config_main(rest)
        if cmd == "serve":
            from quorascrapper.ops.serve import main as serve_main

            return serve_main(rest)
        if cmd == "subscriber":
            from quorascrapper.subscriber.cli import main as subscriber_main

            return subscriber_main(rest)
        if cmd == "verify-urls":
            from quorascrapper.ops.verify_urls import main as verify_main

            return verify_main(rest)
        if cmd == "monitor":
            from quorascrapper.ops.monitor import main as monitor_main

            return monitor_main(rest)

    from quorascrapper.scraper.cli import main as scrape_main

    return scrape_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
