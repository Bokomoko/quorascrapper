"""User config path helpers for globally installed qsbk."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from importlib.resources import files
from pathlib import Path

USER_CONFIG_DIR = Path.home() / ".config" / "qsbk"
USER_ENV_FILE = USER_CONFIG_DIR / "env"
LEGACY_ENV_FILE = Path.home() / ".local" / "share" / "qsbk" / "env"


def config_paths() -> list[Path]:
    paths: list[Path] = []
    if explicit := os.environ.get("QSBK_ENV"):
        paths.append(Path(explicit))
    paths.extend([USER_ENV_FILE, LEGACY_ENV_FILE])
    return paths


def example_env_text() -> str:
    bundled = files("quorascrapper").joinpath("env.example")
    if bundled.is_file():
        return bundled.read_text(encoding="utf-8")
    repo = Path(__file__).resolve().parents[3] / ".env.example"
    if repo.is_file():
        return repo.read_text(encoding="utf-8")
    return (
        "KAFKA_BOOTSTRAP=bokomint.local:19092\n"
        "KAFKA_TOPIC=quora-answers\n"
        "MONGODB_URI=\n"
        "PROFILE_URL=\n"
        "SENDER=stdout\n"
    )


def init_config(force: bool = False) -> Path:
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if USER_ENV_FILE.exists() and not force:
        return USER_ENV_FILE
    USER_ENV_FILE.write_text(example_env_text(), encoding="utf-8")
    return USER_ENV_FILE


def copy_env(source: Path, force: bool = False) -> Path:
    if not source.is_file():
        raise FileNotFoundError(source)
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if USER_ENV_FILE.exists() and not force:
        raise FileExistsError(USER_ENV_FILE)
    shutil.copy2(source, USER_ENV_FILE)
    return USER_ENV_FILE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qsbk config")
    sub = parser.add_subparsers(dest="cmd", required=True)

    init_p = sub.add_parser("init", help="Create ~/.config/qsbk/env from template")
    init_p.add_argument("--force", action="store_true", help="Overwrite existing file")

    copy_p = sub.add_parser("copy", help="Copy a .env file to ~/.config/qsbk/env")
    copy_p.add_argument("source", type=Path, help="Path to .env or .env.container")
    copy_p.add_argument("--force", action="store_true")

    sub.add_parser("path", help="Show config file locations")

    args = parser.parse_args(argv)

    if args.cmd == "init":
        dest = init_config(force=args.force)
        if dest.exists() and not args.force and dest.stat().st_size > 0:
            print(f"Already exists: {dest}")
        else:
            print(f"Wrote {dest}")
        print("Edit KAFKA_BOOTSTRAP, MONGODB_URI, PROFILE_URL, then run: qsbk --dry-run")
        return 0

    if args.cmd == "copy":
        try:
            dest = copy_env(args.source, force=args.force)
        except FileNotFoundError:
            print(f"Not found: {args.source}", file=sys.stderr)
            return 1
        except FileExistsError as exc:
            print(f"{exc} — use --force to overwrite", file=sys.stderr)
            return 1
        print(f"Copied → {dest}")
        print("Run: qsbk --dry-run")
        return 0

    if args.cmd == "path":
        for p in config_paths():
            mark = "found" if p.is_file() else "missing"
            label = "QSBK_ENV" if os.environ.get("QSBK_ENV") == str(p) else "global"
            print(f"{p} ({mark}, {label})")
        cwd = Path.cwd()
        for name in (".env", ".env.container", ".env.scraper"):
            p = cwd / name
            if p.is_file():
                print(f"{p} (found, overrides global)")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
