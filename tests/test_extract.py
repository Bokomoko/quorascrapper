"""Scraper extraction tests using HTML fixtures (no live browser)."""

from pathlib import Path
from unittest.mock import MagicMock

from quorascrapper.scraper.extract import detect_login_wall, process_anchor
from quorascrapper.selectors import LOGIN_WALL_MARKERS

FIXTURES = Path(__file__).parent / "fixtures"


def _mock_driver_from_html(html: str, title: str = ""):
    driver = MagicMock()
    driver.title = title
    body = MagicMock()
    body.text = html
    driver.find_element.return_value = body
    return driver


def test_detect_login_wall_from_fixture():
    html = (FIXTURES / "login_wall.html").read_text()
    driver = _mock_driver_from_html(html, title="Quora - Sign In")
    By = MagicMock()
    By.TAG_NAME = "body"
    logger = MagicMock()
    assert detect_login_wall(driver, By, logger) is True


def test_detect_login_wall_absent_on_answers_snippet():
    html = (FIXTURES / "answers_snippet.html").read_text()
    driver = _mock_driver_from_html(html, title="Answers - Quora")
    By = MagicMock()
    By.TAG_NAME = "body"
    logger = MagicMock()
    assert detect_login_wall(driver, By, logger) is False


def test_login_wall_markers_cover_sign_in():
    assert any("sign in" in m for m in LOGIN_WALL_MARKERS)


def test_process_anchor_sends_new_urls():
    seen: set[str] = set()
    sent: list[str] = []

    anchor = MagicMock()
    anchor.get_attribute.return_value = "https://pt.quora.com/profile/u/answer/1-Test"

    ok = process_anchor(
        anchor,
        "https://pt.quora.com/profile/u/answers",
        seen_links=seen,
        send_url=sent.append,
        StaleElementReferenceException=Exception,
        logger=MagicMock(),
    )
    assert ok is True
    assert len(sent) == 1
    assert "/answer/" in sent[0]
