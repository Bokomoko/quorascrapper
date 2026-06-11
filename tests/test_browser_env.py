from unittest.mock import patch

from quorascrapper.scraper.browser_env import (
    detect_browser_environment,
    detect_runtime,
    is_container,
    resolve_browser_binary,
    should_use_selenium_manager,
)


def test_detect_runtime_macos():
    with patch("quorascrapper.scraper.browser_env.platform.system", return_value="Darwin"):
        assert detect_runtime() == "macos"


def test_detect_runtime_linux_container():
    with (
        patch("quorascrapper.scraper.browser_env.platform.system", return_value="Linux"),
        patch("quorascrapper.scraper.browser_env.is_container", return_value=True),
    ):
        assert detect_runtime() == "linux_container"


def test_detect_runtime_linux_host():
    with (
        patch("quorascrapper.scraper.browser_env.platform.system", return_value="Linux"),
        patch("quorascrapper.scraper.browser_env.is_container", return_value=False),
    ):
        assert detect_runtime() == "linux"


def test_resolve_browser_binary_macos_explicit(tmp_path):
    chrome = tmp_path / "Google Chrome"
    chrome.write_text("")
    path = resolve_browser_binary(str(chrome), "macos")
    assert path == str(chrome)


def test_resolve_browser_binary_linux_from_path(tmp_path):
    chrome = tmp_path / "google-chrome-stable"
    chrome.write_text("")
    with patch(
        "quorascrapper.scraper.browser_env._linux_path_binaries",
        return_value=(str(chrome),),
    ):
        path = resolve_browser_binary(None, "linux")
        assert path == str(chrome)


def test_macos_uses_selenium_manager():
    with patch.dict("os.environ", {}, clear=True):
        assert should_use_selenium_manager("macos") is True


def test_linux_container_skips_selenium_manager():
    with patch.dict("os.environ", {}, clear=True):
        assert should_use_selenium_manager("linux_container") is False


def test_linux_host_uses_selenium_manager_without_path_driver():
    with (
        patch.dict("os.environ", {}, clear=True),
        patch("quorascrapper.scraper.browser_env.shutil.which", return_value=None),
    ):
        assert should_use_selenium_manager("linux") is True


def test_linux_container_adds_sandbox_args():
    with (
        patch("quorascrapper.scraper.browser_env.detect_runtime", return_value="linux_container"),
        patch(
            "quorascrapper.scraper.browser_env.resolve_browser_binary",
            return_value="/usr/bin/chromium",
        ),
    ):
        env = detect_browser_environment()
        assert "--no-sandbox" in env.chrome_args
        assert "--disable-dev-shm-usage" in env.chrome_args
        assert env.browser_binary == "/usr/bin/chromium"


def test_macos_avoids_system_chrome_by_default():
    with (
        patch.dict("os.environ", {}, clear=True),
        patch("quorascrapper.scraper.browser_env._selenium_cached_browser_macos", return_value=None),
    ):
        assert resolve_browser_binary(None, "macos") is None


def test_macos_system_chrome_when_requested():
    with patch.dict("os.environ", {"USE_SYSTEM_CHROME": "1"}, clear=True):
        with patch(
            "quorascrapper.scraper.browser_env._first_existing",
            return_value="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ):
            path = resolve_browser_binary(None, "macos")
            assert "Google Chrome" in (path or "")


def test_macos_automation_has_no_sandbox_and_selenium_manager():
    with (
        patch("quorascrapper.scraper.browser_env.detect_runtime", return_value="macos"),
        patch("quorascrapper.scraper.browser_env.resolve_browser_binary", return_value=None),
    ):
        env = detect_browser_environment()
        assert "--no-sandbox" in env.chrome_args
        assert env.use_selenium_manager is True
        assert "Chrome for Testing" in env.browser_label


def test_is_container_dockerenv():
    with patch("quorascrapper.scraper.browser_env.os.path.exists") as exists:
        exists.side_effect = lambda p: p == "/.dockerenv"
        assert is_container() is True
