"""WebDriver lifecycle for the scraper."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile

from quorascrapper.config import Settings
from quorascrapper.scraper.browser_env import detect_browser_environment, selenium_manager_path

try:
    from selenium import webdriver  # type: ignore
    from selenium.common.exceptions import WebDriverException  # type: ignore
    from selenium.webdriver.chrome.service import Service as ChromeService  # type: ignore
except Exception:  # pragma: no cover
    webdriver = None  # type: ignore

    class WebDriverException(Exception):
        pass


def _isolated_profile_dir() -> str:
    return tempfile.mkdtemp(prefix="qsbk-chrome-")


def quit_driver(driver) -> None:
    """Quit WebDriver and remove any isolated Chrome profile directory."""
    profile_dir = getattr(driver, "_qsbk_profile_dir", None)
    try:
        driver.quit()
    except Exception:
        pass
    if profile_dir and os.path.isdir(profile_dir):
        shutil.rmtree(profile_dir, ignore_errors=True)


def create_driver(settings: Settings, logger: logging.Logger):
    if webdriver is None:
        raise WebDriverException("Selenium not installed")

    env = detect_browser_environment(settings.chrome_binary)
    logger.info(
        "browser_environment",
        extra={"event": "browser_environment", **env.as_log_extra()},
    )

    if env.runtime != "macos" and not env.browser_binary:
        raise WebDriverException(
            f"No Chrome/Chromium binary found for runtime={env.runtime} "
            f"(system={env.system}). Set CHROME_BINARY explicitly."
        )

    profile_dir = _isolated_profile_dir()
    options = webdriver.ChromeOptions()
    for arg in env.chrome_args:
        options.add_argument(arg)
    if env.browser_binary:
        options.binary_location = env.browser_binary
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--disable-extensions")

    try:
        chromedriver_path = os.environ.get("CHROMEDRIVER_PATH")
        with selenium_manager_path(env):
            if chromedriver_path:
                service = ChromeService(executable_path=chromedriver_path)
                driver = webdriver.Chrome(service=service, options=options)
            else:
                driver = webdriver.Chrome(options=options)
        driver._qsbk_profile_dir = profile_dir  # type: ignore[attr-defined]
        driver.set_page_load_timeout(30)
        return driver
    except WebDriverException as exc:
        shutil.rmtree(profile_dir, ignore_errors=True)
        logger.error("Failed to start Chrome WebDriver: %s", exc)
        if settings.use_firefox:
            try:
                from selenium.webdriver.firefox.options import Options as FirefoxOptions

                fopts = FirefoxOptions()
                fopts.add_argument("-headless")
                driver = webdriver.Firefox(options=fopts)
                driver.set_page_load_timeout(30)
                logger.info("Fallback to Firefox succeeded.")
                return driver
            except Exception as fe:
                logger.error("Firefox fallback failed: %s", fe)
        raise
