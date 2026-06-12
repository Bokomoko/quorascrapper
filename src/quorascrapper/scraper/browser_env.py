"""Detect host OS/runtime and configure Chrome + ChromeDriver accordingly."""

from __future__ import annotations

import os
import platform
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Runtime = Literal["macos", "linux", "linux_container", "windows", "unknown"]

def _chrome_base_args() -> tuple[str, ...]:
    base = (
        "--disable-gpu",
        "--disable-extensions",
        "--disable-default-apps",
        "--remote-allow-origins=*",
    )
    if _truthy(os.environ.get("HEADLESS", "1")):
        return ("--headless=new",) + base
    return base


_SYSTEM_CHROME_MACOS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)

_RUNTIME_CHROME_CANDIDATES: dict[Runtime, tuple[str, ...]] = {
    "macos": _SYSTEM_CHROME_MACOS,
    "linux_container": (
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
    ),
    "linux": (
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        "/snap/bin/chromium",
        "/usr/lib/chromium/chromium",
        "/usr/lib/chromium-browser/chromium-browser",
    ),
    "windows": (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ),
    "unknown": (
        "/usr/bin/chromium",
        "/usr/bin/google-chrome",
    ),
}

_RUNTIME_EXTRA_ARGS: dict[Runtime, tuple[str, ...]] = {
    "macos": (
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-sync",
        "--disable-features=TranslateUI",
        # Automation subprocess; avoids some macOS WindowServer registration crashes.
        "--no-sandbox",
    ),
    "linux": (),
    "linux_container": ("--no-sandbox", "--disable-dev-shm-usage"),
    "windows": (),
    "unknown": ("--no-sandbox", "--disable-dev-shm-usage"),
}


def _truthy(value: str | None) -> bool:
    return (value or "").lower() in {"1", "true", "yes", "y", "on"}


def use_system_chrome() -> bool:
    return _truthy(os.environ.get("USE_SYSTEM_CHROME"))


def is_container() -> bool:
    if os.path.exists("/.dockerenv"):
        return True
    if _truthy(os.environ.get("RUNNING_IN_CONTAINER")):
        return True
    try:
        with open("/proc/1/cgroup", encoding="utf-8") as fh:
            content = fh.read()
        return "docker" in content or "containerd" in content or "podman" in content
    except OSError:
        return False


def detect_runtime() -> Runtime:
    system = platform.system()
    if system == "Darwin":
        return "macos"
    if system == "Windows":
        return "windows"
    if system == "Linux":
        return "linux_container" if is_container() else "linux"
    return "unknown"


_LINUX_PATH_BINS = (
    "google-chrome-stable",
    "google-chrome",
    "chromium",
    "chromium-browser",
)


def _first_existing(paths: tuple[str, ...]) -> str | None:
    for path in paths:
        if path and os.path.isfile(path):
            return path
    return None


def _linux_path_binaries() -> tuple[str, ...]:
    found: list[str] = []
    for name in _LINUX_PATH_BINS:
        path = shutil.which(name)
        if path and path not in found:
            found.append(path)
    return tuple(found)


def _selenium_cached_browser_macos() -> str | None:
    """Chrome for Testing / headless-shell already downloaded by Selenium Manager."""
    cache = Path.home() / ".cache" / "selenium"
    if not cache.is_dir():
        return None
    patterns = (
        "**/chrome-headless-shell",
        "**/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    )
    found: list[str] = []
    for pattern in patterns:
        for path in cache.glob(pattern):
            if path.is_file() and os.access(path, os.X_OK):
                found.append(str(path))
    for prefer in ("chrome-headless-shell", "Google Chrome for Testing"):
        for path in found:
            if prefer in path:
                return path
    return found[0] if found else None


def resolve_browser_binary(explicit: str | None, runtime: Runtime) -> str | None:
    if explicit:
        return explicit if os.path.isfile(explicit) else None

    if runtime == "macos":
        if use_system_chrome():
            return _first_existing(_SYSTEM_CHROME_MACOS)
        return _selenium_cached_browser_macos()

    candidates: list[str] = []
    candidates.extend(_RUNTIME_CHROME_CANDIDATES.get(runtime, ()))
    if runtime in ("linux", "linux_container"):
        candidates.extend(_linux_path_binaries())
    return _first_existing(tuple(candidates))


def browser_label_for(runtime: Runtime, binary: str | None) -> str:
    if runtime == "macos":
        if binary and "Chrome for Testing" in binary:
            return "Chrome for Testing (cached)"
        if binary and "headless-shell" in binary:
            return "chrome-headless-shell (cached)"
        if binary and use_system_chrome():
            return "Google Chrome (system — USE_SYSTEM_CHROME=1)"
        return "Chrome for Testing (Selenium Manager)"
    return {
        "linux": "Chromium/Chrome (Linux)",
        "linux_container": "Chromium (container)",
        "windows": "Google Chrome (Windows)",
    }.get(runtime, "Chrome/Chromium")


def should_use_selenium_manager(runtime: Runtime) -> bool:
    if _truthy(os.environ.get("USE_PATH_CHROMEDRIVER")):
        return False
    if os.environ.get("CHROMEDRIVER_PATH"):
        return False
    if runtime == "macos":
        return True
    if runtime == "linux_container":
        return False
    if runtime == "linux":
        return shutil.which("chromedriver") is None
    return True


@dataclass(frozen=True)
class BrowserEnvironment:
    runtime: Runtime
    system: str
    browser_binary: str | None
    browser_label: str
    chrome_args: tuple[str, ...]
    use_selenium_manager: bool

    def as_log_extra(self) -> dict[str, str | bool]:
        return {
            "runtime": self.runtime,
            "system": self.system,
            "browser_binary": self.browser_binary or "",
            "browser_label": self.browser_label,
            "use_selenium_manager": self.use_selenium_manager,
        }


def detect_browser_environment(explicit_binary: str = "") -> BrowserEnvironment:
    runtime = detect_runtime()
    binary = resolve_browser_binary(explicit_binary or None, runtime)
    args = _chrome_base_args() + _RUNTIME_EXTRA_ARGS.get(runtime, ())
    return BrowserEnvironment(
        runtime=runtime,
        system=platform.system(),
        browser_binary=binary,
        browser_label=browser_label_for(runtime, binary),
        chrome_args=args,
        use_selenium_manager=should_use_selenium_manager(runtime),
    )


def path_without_chromedriver() -> str:
    kept: list[str] = []
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        candidate = os.path.join(directory, "chromedriver")
        if os.path.isfile(candidate) or os.path.islink(candidate):
            continue
        kept.append(directory)
    return os.pathsep.join(kept)


@contextmanager
def selenium_manager_path(env: BrowserEnvironment):
    if not env.use_selenium_manager:
        yield
        return
    previous = os.environ.get("PATH", "")
    os.environ["PATH"] = path_without_chromedriver()
    try:
        yield
    finally:
        os.environ["PATH"] = previous


def chromedriver_diagnostics(env: BrowserEnvironment | None = None) -> list[str]:
    env = env or detect_browser_environment()
    hints: list[str] = []
    if env.runtime == "linux_container" and not shutil.which("chromedriver"):
        hints.append(
            "No chromedriver in container PATH; ensure chromium-driver is installed "
            "(Dockerfile.scraper)."
        )
        return hints

    if env.runtime == "linux" and not shutil.which("chromedriver"):
        hints.append(
            "No chromedriver in PATH; Selenium Manager will download a matching driver."
        )
        return hints

    if env.runtime != "macos":
        return hints

    if not use_system_chrome():
        hints.append(
            "macOS automation uses Chrome for Testing via Selenium Manager, not "
            "/Applications/Google Chrome.app (avoids GUI registration crashes). "
            "Set USE_SYSTEM_CHROME=1 only if you know you need the system browser."
        )

    path = shutil.which("chromedriver")
    if not path:
        hints.append("Selenium Manager will download a matching chromedriver.")
        return hints

    if env.use_selenium_manager:
        hints.append(
            "PATH chromedriver ignored; Selenium Manager supplies the driver."
        )
        return hints

    return hints
