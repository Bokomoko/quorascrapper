"""Answer URL extraction helpers."""

from __future__ import annotations

import logging
import time
from urllib.parse import urljoin

from quorascrapper.selectors import (
    ANSWER_ANCHOR_XPATH,
    ANSWER_BLOCK_XPATHS,
    ANSWER_LINK_XPATHS,
    INITIAL_ANSWER_WAIT_SECONDS,
    LOGIN_WALL_MARKERS,
)


def retry_on_stale(func, StaleElementReferenceException, attempts=2):
    for i in range(attempts):
        try:
            return func()
        except StaleElementReferenceException:
            if i == attempts - 1:
                raise
            time.sleep(0.2)


def process_anchor(
    anchor,
    base_url: str,
    *,
    seen_links: set[str],
    send_url,
    StaleElementReferenceException,
    logger: logging.Logger,
) -> bool:
    def read_href():
        href = anchor.get_attribute("href")
        if not href:
            return None
        href = urljoin(base_url, href)
        if "/answer/" not in href:
            return None
        return href

    try:
        href = retry_on_stale(read_href, StaleElementReferenceException)
    except StaleElementReferenceException:
        logger.debug("Stale anchor during href read")
        return False
    except Exception as exc:
        logger.debug("Anchor processing error: %s", exc)
        return False

    if not href or href in seen_links:
        return False

    seen_links.add(href)
    logger.debug("Found answer URL: %s", href)
    send_url(href)
    return True


def detect_login_wall(driver, By, logger: logging.Logger) -> bool:
    try:
        title = (driver.title or "").lower()
        if any(m in title for m in LOGIN_WALL_MARKERS):
            logger.warning("Login wall suspected (title): %s", driver.title)
            return True
        body = driver.find_element(By.TAG_NAME, "body").text.lower()[:2000]
        if any(m in body for m in LOGIN_WALL_MARKERS) and "/answer/" not in body:
            logger.warning("Login wall suspected in page body")
            return True
    except Exception:
        pass
    return False


def fast_anchor_scan(driver, By, url, *, process_anchor_fn, get_processed, get_limit, logger):
    anchors = driver.find_elements(By.XPATH, ANSWER_ANCHOR_XPATH)
    logger.debug("Fast scan found %d answer anchors", len(anchors))
    for anchor in anchors:
        if get_processed() >= get_limit():
            break
        process_anchor_fn(anchor, url)


def block_fallback_scan(
    driver,
    By,
    EC,
    WebDriverWait,
    *,
    seen_links,
    send_url,
    get_processed,
    get_limit,
    debug,
    logger,
):
    found_block = False
    for xpath in ANSWER_BLOCK_XPATHS:
        try:
            WebDriverWait(driver, INITIAL_ANSWER_WAIT_SECONDS).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
            found_block = True
            break
        except Exception:
            continue

    if not found_block:
        logger.warning("No answer blocks detected; using block fallback.")

    blocks = []
    seen_ids: set[str] = set()
    for xpath in ANSWER_BLOCK_XPATHS:
        try:
            for elem in driver.find_elements(By.XPATH, xpath):
                if elem.id not in seen_ids:
                    blocks.append(elem)
                    seen_ids.add(elem.id)
        except Exception:
            continue

    logger.info("Discovered %d potential answer blocks", len(blocks))
    for block in blocks:
        if get_processed() >= get_limit():
            break
        answer_link = None
        for lx in ANSWER_LINK_XPATHS:
            try:
                l_elem = block.find_element(By.XPATH, lx)
                href = l_elem.get_attribute("href")
                if href and "/answer/" in href:
                    answer_link = href
                    break
            except Exception:
                continue
        if not answer_link:
            try:
                l_elem = block.find_element(By.XPATH, ".//a[contains(@href,'/answer/')]")
                answer_link = l_elem.get_attribute("href")
            except Exception:
                pass
        if not answer_link or answer_link in seen_links:
            continue
        seen_links.add(answer_link)
        send_url(answer_link)
