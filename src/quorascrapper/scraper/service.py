"""QuoraScraper orchestration."""

from __future__ import annotations

import time

from quorascrapper.config import Settings
from quorascrapper.exceptions import LoginWallError
from quorascrapper.logging_setup import init_logging
from quorascrapper.messaging import KafkaSender, StdoutSender
from quorascrapper.scraper.browser import create_driver, quit_driver
from quorascrapper.scraper.extract import (
    block_fallback_scan,
    detect_login_wall,
    fast_anchor_scan,
    process_anchor,
)
from quorascrapper.scraper.graphql import extract_page_context, paginate_answers
from quorascrapper.scraper.scroll import scroll_to_bottom
from quorascrapper.scraper.stats import (
    compute_answer_limit,
    extract_profile_stats,
)
from quorascrapper.selectors import ANSWER_ANCHOR_XPATH, INITIAL_ANSWER_WAIT_SECONDS

try:
    from selenium.common.exceptions import StaleElementReferenceException, WebDriverException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
except Exception:  # pragma: no cover
    StaleElementReferenceException = Exception  # type: ignore
    WebDriverException = Exception  # type: ignore
    By = EC = WebDriverWait = object()  # type: ignore


class QuoraScraper:
    def __init__(self, sender=None, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()
        self.logger = init_logging("scraper")
        self.driver = None
        self.sender = sender or StdoutSender()
        self.seen_links: set[str] = set()
        self.processed = 0
        self.profile_stats: dict = {}
        self.answer_limit = self.settings.max_results
        self.no_growth_threshold = 5
        self.debug = self.settings.debug_selectors
        self.login_wall_detected = False

        try:
            self.driver = create_driver(self.settings, self.logger)
        except WebDriverException:
            raise

    def _limit(self) -> int:
        return self.answer_limit or self.settings.max_results

    def _process_anchor_bound(self, anchor, base_url: str) -> bool:
        if process_anchor(
            anchor,
            base_url,
            seen_links=self.seen_links,
            send_url=self._send_url,
            StaleElementReferenceException=StaleElementReferenceException,
            logger=self.logger,
        ):
            self.processed += 1
            return True
        return False

    def _send_url(self, url: str) -> None:
        try:
            self.logger.debug("url_send", extra={"event": "url_send", "url": url})
            self.sender.send({"url": url})
            self.logger.debug("url_sent", extra={"event": "url_sent", "url": url})
        except Exception as exc:
            self.logger.error(
                "url_send_error",
                extra={"event": "url_send_error", "url": url, "error": str(exc)},
            )

    def _send_url_counted(self, url: str) -> None:
        self._send_url(url)
        self.processed += 1

    def _send_payload(self, payload: dict) -> None:
        url = payload.get("url", "")
        try:
            self.sender.send(payload)
            self.logger.debug("payload_sent", extra={"event": "payload_sent", "url": url})
        except Exception as exc:
            self.logger.error(
                "payload_send_error",
                extra={"event": "payload_send_error", "url": url, "error": str(exc)},
            )

    def _extract_via_graphql(self, url: str) -> int:
        ctx = extract_page_context(self.driver)
        uid, formkey = ctx.get("uid"), ctx.get("formkey")
        if not uid or not formkey:
            self.logger.error(
                "graphql_context_missing",
                extra={
                    "event": "graphql_context_missing",
                    "uid": uid,
                    "has_formkey": bool(formkey),
                },
            )
            return self.processed

        self.logger.info("GraphQL mode: uid=%s page_size=%s", uid, self.settings.graphql_page_size)
        for payload in paginate_answers(
            self.driver,
            profile_url=url,
            uid=uid,
            formkey=formkey,
            query_hash=self.settings.answers_query_hash,
            revision=ctx.get("revision"),
            page_size=self.settings.graphql_page_size,
            limit=self._limit(),
            logger=self.logger,
        ):
            self._send_payload(payload)
            self.processed += 1
        return self.processed

    def extract_content(self, url: str) -> int:
        self.logger.info("Loading profile: %s", url)
        self.driver.get(url)

        try:
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            time.sleep(2)
            title = self.driver.title
            self.logger.info("Page loaded: title='%s'", title)

            # Allow lazy-loaded answer list before login-wall heuristics.
            try:
                WebDriverWait(self.driver, INITIAL_ANSWER_WAIT_SECONDS).until(
                    EC.presence_of_element_located((By.XPATH, ANSWER_ANCHOR_XPATH))
                )
            except Exception:
                pass

            if detect_login_wall(self.driver, By, self.logger):
                self.login_wall_detected = True
                self.logger.error(
                    "LoginWallDetected: Quora requires sign-in for this page"
                )
                raise LoginWallError(
                    "Quora login wall detected. Headless scrape cannot proceed. "
                    "Use an authenticated session (future) or check preflight reachability."
                )

            try:
                self.profile_stats = extract_profile_stats(self.driver, By)
                self.answer_limit = compute_answer_limit(
                    self.profile_stats, self.settings.max_results
                )
                self.logger.info(
                    "Scraping up to %s answers (profile reports %s)",
                    self.answer_limit,
                    self.profile_stats.get("answers"),
                )
            except Exception as exc:
                self.logger.warning("Initial stats extraction failed: %s", exc)
                self.answer_limit = self.settings.max_results

            if self.settings.scrape_mode == "graphql":
                self._extract_via_graphql(url)
                self.sender.flush(15)
                self.logger.info("Captured %d answers in total", self.processed)
                return self.processed

            scroll_to_bottom(
                self.driver,
                By,
                scroll_pause=self.settings.scroll_pause,
                no_growth_threshold=self.no_growth_threshold,
                get_processed=lambda: self.processed,
                get_limit=self._limit,
                process_anchor=self._process_anchor_bound,
                logger=self.logger,
            )

            if self.processed < self._limit():
                fast_anchor_scan(
                    self.driver,
                    By,
                    url,
                    process_anchor_fn=self._process_anchor_bound,
                    get_processed=lambda: self.processed,
                    get_limit=self._limit,
                    logger=self.logger,
                )

            if self.processed < self._limit():
                block_fallback_scan(
                    self.driver,
                    By,
                    EC,
                    WebDriverWait,
                    seen_links=self.seen_links,
                    send_url=self._send_url_counted,
                    get_processed=lambda: self.processed,
                    get_limit=self._limit,
                    debug=self.debug,
                    logger=self.logger,
                )

        except KeyboardInterrupt:
            self.logger.warning("Interrupted during scrape")

        try:
            self.sender.flush(15)
        except Exception:
            pass

        self.logger.info("Captured %d answers in total", self.processed)
        return self.processed

    def kafka_healthcheck(self, timeout_sec: float = 5.0) -> bool:
        if self.settings.dry_run or not isinstance(self.sender, KafkaSender):
            self.logger.info("Skipping Kafka healthcheck (not using Kafka)")
            return True
        try:
            hc_sender = KafkaSender(
                self.settings.kafka_bootstrap,
                self.settings.kafka_healthcheck_topic,
                settings=self.settings,
            )
            hc_sender.send({"url": f"healthcheck:{int(time.time())}"})
            hc_sender.flush(timeout_sec)
            hc_sender.close()
            self.logger.info("Kafka healthcheck OK")
            return True
        except Exception as exc:
            self.logger.error("Kafka healthcheck FAILED: %s", exc)
            return False

    def close(self) -> None:
        if self.driver:
            quit_driver(self.driver)
            self.driver = None
        try:
            self.sender.close()
        except Exception:
            pass
