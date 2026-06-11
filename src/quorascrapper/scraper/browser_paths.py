"""Backward-compatible re-exports. Prefer browser_env."""

from quorascrapper.scraper.browser_env import (
    chromedriver_diagnostics,
    detect_browser_environment,
    resolve_browser_binary,
    selenium_manager_path,
)

# Legacy name used by preflight
resolve_chrome_binary = resolve_browser_binary

__all__ = [
    "chromedriver_diagnostics",
    "detect_browser_environment",
    "resolve_chrome_binary",
    "resolve_browser_binary",
    "selenium_manager_path",
]
