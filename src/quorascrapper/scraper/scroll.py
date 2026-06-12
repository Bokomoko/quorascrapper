"""Infinite scroll with incremental URL extraction."""

from __future__ import annotations

import logging
import time
from typing import Callable

from quorascrapper.selectors import ANSWER_ANCHOR_XPATH


def scroll_to_bottom(
    driver,
    By,
    *,
    scroll_pause: float,
    no_growth_threshold: int,
    get_processed: Callable[[], int],
    get_limit: Callable[[], int],
    process_anchor: Callable,
    logger: logging.Logger,
) -> None:
    last_height = driver.execute_script("return document.body.scrollHeight")
    last_content_count = 0
    stagnant_scrolls = 0
    last_processed_at_count = 0

    logger.info("Starting scroll...")
    while get_processed() < get_limit():
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(scroll_pause)
        anchors = driver.find_elements(By.XPATH, ANSWER_ANCHOR_XPATH)
        current_content = len(anchors)

        if current_content > last_content_count:
            last_content_count = current_content
            stagnant_scrolls = 0
        else:
            stagnant_scrolls += 1
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height != last_height:
                last_height = new_height
                stagnant_scrolls = 0
            elif stagnant_scrolls >= no_growth_threshold:
                logger.info(
                    "Stopping scroll: plateau or no growth (%s stagnant)",
                    stagnant_scrolls,
                )
                break

        if current_content > last_processed_at_count:
            for anchor in anchors[last_processed_at_count:]:
                if get_processed() >= get_limit():
                    break
                process_anchor(anchor, driver.current_url)
            last_processed_at_count = current_content
