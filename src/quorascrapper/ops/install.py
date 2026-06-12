"""Install qsbk Chrome extension to a stable local path."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

INSTALL_DIR = Path.home() / ".local" / "share" / "qsbk" / "chrome-extension"
BUNDLE_NAME = "bundled_extension"


def extension_source_dir() -> Path:
    """Bundled extension (wheel) or repo ``extension/`` when developing."""
    bundled = files("quorascrapper").joinpath(BUNDLE_NAME)
    if bundled.is_dir():
        return Path(str(bundled))

    # Editable / src checkout: repo_root/extension
    repo_guess = Path(__file__).resolve().parents[3] / "extension"
    if repo_guess.is_dir() and (repo_guess / "manifest.json").is_file():
        return repo_guess

    raise FileNotFoundError(
        "Chrome extension files not found in the installed package. "
        "Reinstall with: uv tool install --force /path/to/quorascrapper"
    )


def install_extension(target: Path | None = None, *, serve_url: str | None = None) -> Path:
    src = extension_source_dir()
    dest = target or INSTALL_DIR
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    if serve_url:
        config_path = dest / "config.json"
        config_path.write_text(
            json.dumps({"serveBase": serve_url.rstrip("/")}, indent=2) + "\n",
            encoding="utf-8",
        )
    return dest


def _chrome_binary() -> Path | None:
    system = platform.system()
    if system == "Darwin":
        path = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        return path if path.is_file() else None
    if system == "Linux":
        for name in (
            "google-chrome-stable",
            "google-chrome",
            "chromium-browser",
            "chromium",
        ):
            found = shutil.which(name)
            if found:
                return Path(found)
        return None
    if system == "Windows":
        for path in (
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        ):
            if path.is_file():
                return path
    return None


def _chrome_running() -> bool:
    system = platform.system()
    try:
        if system == "Darwin":
            r = subprocess.run(
                ["pgrep", "-x", "Google Chrome"],
                capture_output=True,
                check=False,
            )
            return r.returncode == 0
        if system == "Linux":
            r = subprocess.run(
                ["pgrep", "-f", "chrome"],
                capture_output=True,
                check=False,
            )
            return r.returncode == 0
    except OSError:
        pass
    return False


def launch_chrome_with_extension(ext_dir: Path) -> tuple[bool, str]:
    """Start Chrome with --load-extension (dev flag; not the same as UI Load unpacked).

    Chrome must be fully quit first, or the flag is ignored on an existing process.
    """
    binary = _chrome_binary()
    if not binary:
        return False, "Google Chrome binary not found."

    ext_dir = ext_dir.resolve()
    if _chrome_running():
        return (
            False,
            "Chrome is already running — quit Chrome completely, then run:\n"
            f'  qsbk install --load\n'
            f"Or start manually:\n"
            f'  "{binary}" --load-extension="{ext_dir}"',
        )

    subprocess.Popen(
        [str(binary), f"--load-extension={ext_dir}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return (
        True,
        "Launched Chrome with the qsbk extension loaded for this session.\n"
        "Tip: for a one-time permanent install, use --open and Load unpacked instead.",
    )


def _open_chrome_extensions() -> bool:
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(
                ["open", "-a", "Google Chrome", "chrome://extensions"],
                check=False,
            )
            return True
        if system == "Linux":
            subprocess.run(["xdg-open", "chrome://extensions"], check=False)
            return True
    except OSError:
        pass
    return False


def print_install_instructions(dest: Path) -> None:
    print(f"Extension copied to:\n  {dest}\n")
    print("Option A — load via Chrome UI (persists in your profile):")
    print("  1. Open chrome://extensions")
    print("  2. Enable Developer mode")
    print(f"  3. Load unpacked → select:\n     {dest}")
    print("\nOption B — launch with extension (quit Chrome first):")
    print("  qsbk install --load")
    print("\nThen open a logged-in Quora profile /answers tab and click the qsbk icon.")
    print("Export CSV/JSONL → quora-filter <file> -o answers.jsonl")
    print("Or publish directly: qsbk ingest <file>")
    print("\nRemote serve on bokomint:")
    print("  qsbk install --serve-url http://bokomint.local:8765")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="qsbk install",
        description="Install the qsbk Chrome extension (logged-in Quora scraping).",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=INSTALL_DIR,
        help=f"Install directory (default: {INSTALL_DIR})",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open chrome://extensions after copy (manual Load unpacked)",
    )
    parser.add_argument(
        "--load",
        action="store_true",
        help="Quit Chrome if needed, then launch with --load-extension (session load)",
    )
    parser.add_argument(
        "--serve-url",
        metavar="URL",
        help="qsbk serve base URL for extension (default: http://bokomint.local:8765)",
    )
    args = parser.parse_args(argv)

    try:
        dest = install_extension(args.dir, serve_url=args.serve_url)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print_install_instructions(dest)

    if args.load:
        ok, msg = launch_chrome_with_extension(dest)
        print(f"\n{msg}")
        return 0 if ok else 1

    if args.open:
        if _open_chrome_extensions():
            print("\nOpened Chrome extensions page.")
        else:
            print("\nCould not open Chrome automatically — use chrome://extensions")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
