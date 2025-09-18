import logging
import os
import re
import time
from urllib.parse import urljoin

try:
    from confluent_kafka import Producer  # type: ignore
except Exception:  # pragma: no cover
    Producer = None  # type: ignore

try:
    from selenium import webdriver  # type: ignore
    from selenium.common.exceptions import (
        StaleElementReferenceException,
        WebDriverException,
    )
    from selenium.webdriver.common.by import By  # type: ignore
    from selenium.webdriver.support import expected_conditions as EC  # type: ignore
    from selenium.webdriver.support.ui import WebDriverWait  # type: ignore
except Exception:  # pragma: no cover
    webdriver = None  # type: ignore

    class WebDriverException(Exception):
        pass

    class StaleElementReferenceException(Exception):
        pass

    class _Dummy:
        pass

    By = EC = WebDriverWait = _Dummy()

from quora_selectors import (
    ANSWER_ANCHOR_XPATH,
    ANSWER_BLOCK_XPATHS,
    ANSWER_LINK_XPATHS,
    INITIAL_ANSWER_WAIT_SECONDS,
    PROFILE_STATS_XPATHS,
)
from senders import KafkaSender, StdoutSender

# Load .env if present to bring in KAFKA_BOOTSTRAP, KAFKA_TOPIC, etc.
try:  # lightweight optional import
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except Exception:
    pass

# Default profile URL (Portuguese answers tab)
DEFAULT_PROFILE_URL = (
    "https://pt.quora.com/profile/Jo%C3%A3o-Eurico-de-Aguiar-Lima/answers"
)


def resolve_profile_url(
    cli_arg: str | None, env_url: str | None, default_url: str = DEFAULT_PROFILE_URL
) -> str:
    """Resolve profile URL based on precedence: CLI > env > default.

    Inputs:
      - cli_arg: first CLI positional argument (may be None)
      - env_url: value of PROFILE_URL env var (may be None)
      - default_url: fallback when both are missing

    Returns the chosen URL string.
    """
    return cli_arg or env_url or default_url


class QuoraScraper:
    def __init__(self, sender=None):
        # Initialize Chrome WebDriver with error handling & optional fallback
        self.driver = None
        # Logging setup (default to WARNING to minimize noise)
        log_level = os.environ.get("LOG_LEVEL", "WARNING").upper()
        logging.basicConfig(
            level=getattr(logging, log_level, logging.INFO),
            format="%(asctime)s [%(levelname)s] %(message)s",
        )
        self.logger = logging.getLogger("QuoraScraper")
        if webdriver is None:
            # Allow constructing in test environments; actual run will fail early
            self.logger.warning(
                "Selenium not available; QuoraScraper will not run without it."
            )
            options = None
        else:
            options = webdriver.ChromeOptions()
        # Modern headless for recent Chrome versions
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        chrome_binary = os.environ.get("CHROME_BINARY")
        if chrome_binary:
            options.binary_location = chrome_binary
        self.debug = os.environ.get("DEBUG_SELECTORS") == "1"
        self.seen_links = set()
        # Dry-run mode (skip Kafka sends; still parse and print)
        self.dry_run = os.environ.get("DRY_RUN", "0").lower() in {
            "1",
            "true",
            "yes",
            "y",
        }
        # Sender setup: default to stdout, unless a sender was provided
        self.sender = sender or StdoutSender()
        try:
            if webdriver is None:
                raise WebDriverException("Selenium not installed")
            self.driver = webdriver.Chrome(options=options)
            self.driver.set_page_load_timeout(30)
        except WebDriverException as e:
            self.logger.error("Failed to start Chrome WebDriver: %s", e)
            if os.environ.get("USE_FIREFOX") == "1":
                try:
                    from selenium.webdriver.firefox.options import (
                        Options as FirefoxOptions,
                    )

                    fopts = FirefoxOptions()
                    fopts.add_argument("-headless")
                    self.driver = webdriver.Firefox(options=fopts)
                    self.driver.set_page_load_timeout(30)
                    self.logger.info("Fallback to Firefox succeeded.")
                except Exception as fe:
                    self.logger.error("Firefox fallback failed: %s", fe)
            if not self.driver:
                raise
        # Instance state
        self.results = []  # Store results as we go
        self.processed = 0
        self.profile_stats = {}
        # Limits
        self.max_results = int(os.environ.get("MAX_RESULTS", "16000"))
        self.no_growth_threshold = 5
        self.scroll_pause = float(os.environ.get("SCROLL_PAUSE", "1.5"))
        # Legacy Kafka settings retained for compatibility, but sending now goes through sender
        self.kafka_bootstrap = os.environ.get("KAFKA_BOOTSTRAP", "192.168.1.116:9092")
        self.kafka_topic = os.environ.get("KAFKA_TOPIC", "quora-answers")

    # File output logic was removed; Kafka streaming only

    def print_status(self, message):
        """No-op to avoid showing progress."""
        return

    def scroll_to_bottom(self):
        """Scroll page until no new content loads or limits hit."""
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        scroll_count = 0
        last_content_count = 0
        stagnant_scrolls = 0
        self.logger.info("Starting scroll (no max scroll limit)...")
        # Infinite scroll until stagnation or item limit
        while self.processed < (self.answer_limit or self.max_results):
            scroll_count += 1
            self.print_status(
                f"Scroll {scroll_count} - Items {last_content_count} - Collected {self.processed}/{self.answer_limit or self.max_results}"
            )
            self.driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);"
            )
            time.sleep(self.scroll_pause)
            current_content = len(
                self.driver.find_elements(By.XPATH, ANSWER_ANCHOR_XPATH)
            )
            if current_content > last_content_count:
                last_content_count = current_content
                stagnant_scrolls = 0
            else:
                stagnant_scrolls += 1
                new_height = self.driver.execute_script(
                    "return document.body.scrollHeight"
                )
                if (
                    new_height == last_height
                    or stagnant_scrolls >= self.no_growth_threshold
                ):
                    self.logger.info(
                        "Stopping scroll: plateau or no growth (%s stagnant)",
                        stagnant_scrolls,
                    )
                    break
                last_height = new_height
        if self.processed >= (self.answer_limit or self.max_results):
            self.logger.info(
                "Reached answer limit (%s) during scroll",
                self.answer_limit or self.max_results,
            )

    @staticmethod
    def _normalize_number(txt):
        if not txt:
            return None
        # Normalize whitespace but keep punctuation for 'mil' detection
        txt = txt.replace("\u00a0", " ").strip()
        # Handle formats like '14,7 mil' or '14.7 mil' (Portuguese thousands)
        mil_match = re.match(r"([0-9]+)[\.,]?([0-9]+)?\s*mil", txt, re.IGNORECASE)
        if mil_match:
            whole = int(mil_match.group(1))
            frac = mil_match.group(2)
            value = whole * 1000 + (
                int(frac) * (1000 // (10 ** len(frac))) if frac else 0
            )
            return value
        # Plain integer
        txt = txt.replace(",", "")
        digits = re.findall(r"\d+", txt)
        if digits:
            try:
                return int("".join(digits))
            except Exception:
                return None
        return None

    def _extract_profile_stats(self):
        stats = {}
        for key, xp in PROFILE_STATS_XPATHS.items():
            if key not in ("answers", "questions", "following", "followers"):
                continue
            try:
                elem = self.driver.find_element(By.XPATH, xp)
                raw = elem.text.strip()
                stats[key] = self._normalize_number(raw)
            except Exception:
                stats[key] = None
        # Meta fallback
        if stats.get("answers") is None or stats.get("questions") is None:
            try:
                meta_desc = self.driver.find_element(
                    By.XPATH, "//meta[@property='og:description']"
                )
                content = meta_desc.get_attribute("content") or ""
                answers_match = re.search(
                    r"(\d+[\.,]?\d*(?:\s*mil)?)\s+respostas", content, re.IGNORECASE
                )
                questions_match = re.search(
                    r"(\d+[\.,]?\d*(?:\s*mil)?)\s+perguntas", content, re.IGNORECASE
                )
                if stats.get("answers") is None and answers_match:
                    stats["answers"] = self._normalize_number(answers_match.group(1))
                if stats.get("questions") is None and questions_match:
                    stats["questions"] = self._normalize_number(
                        questions_match.group(1)
                    )
            except Exception:
                pass
        # Drop followers/following from final stats per request
        for drop_key in ("followers", "following"):
            if drop_key in stats:
                stats.pop(drop_key)
        self.profile_stats = stats
        # Set dynamic answer limit (min of answers count and max_results)
        answers_total = stats.get("answers")
        if answers_total and isinstance(answers_total, int):
            self.answer_limit = min(answers_total, self.max_results)
        else:
            self.answer_limit = self.max_results
        return stats

    def extract_content(self, url):
        """Extract all answer URLs from a Quora profile and send to Kafka"""
        self.logger.info("Loading profile: %s", url)
        self.driver.get(url)
        try:
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            time.sleep(2)
            # Stats first
            try:
                self._extract_profile_stats()
                if self.debug:
                    self.logger.debug(
                        "Profile stats (pre-scroll): %s", self.profile_stats
                    )
                self.logger.debug("Answer limit set to %s", self.answer_limit)
            except Exception as e:
                self.logger.warning("Initial stats extraction failed: %s", e)
                self.answer_limit = self.max_results
            # Scroll
            self.scroll_to_bottom()
            # Fast pass: grab all anchors that look like answer links
            anchors = self.driver.find_elements(By.XPATH, ANSWER_ANCHOR_XPATH)
            self.logger.debug("Fast scan found %d answer anchors", len(anchors))
            for a in anchors:
                if self.processed >= (self.answer_limit or self.max_results):
                    break
                try:
                    href = a.get_attribute("href")
                    if not href:
                        continue
                    # Normalize to absolute URL (handles potential relative)
                    href = urljoin(url, href)
                    if "/answer/" not in href:
                        continue
                    if href in self.seen_links:
                        continue
                    self.seen_links.add(href)
                    self._send_url(href)
                    self.processed += 1
                except Exception as ex:
                    self.logger.debug(f"Anchor processing error: {ex}")
                    continue
            if self.processed < (self.answer_limit or self.max_results):
                # Fallback to block-based parsing if needed
                found_block = False
                if self.debug:
                    self.logger.debug(
                        "Trying ANSWER_BLOCK_XPATHS: %s", ANSWER_BLOCK_XPATHS
                    )
                for xpath in ANSWER_BLOCK_XPATHS:
                    try:
                        WebDriverWait(self.driver, INITIAL_ANSWER_WAIT_SECONDS).until(
                            EC.presence_of_element_located((By.XPATH, xpath))
                        )
                        found_block = True
                        break
                    except Exception:
                        continue
                if not found_block:
                    self.logger.warning("No answer blocks detected before scrolling.")
                self.scroll_to_bottom()
                blocks = []
                seen_ids = set()
                for xpath in ANSWER_BLOCK_XPATHS:
                    try:
                        elems = self.driver.find_elements(By.XPATH, xpath)
                        if self.debug:
                            self.logger.debug(
                                "XPath %s found %d elements", xpath, len(elems)
                            )
                        for e in elems:
                            if e.id not in seen_ids:
                                blocks.append(e)
                                seen_ids.add(e.id)
                    except Exception as ex:
                        if self.debug:
                            self.logger.debug("Error with XPath %s: %s", xpath, ex)
                        continue
                if self.debug:
                    self.logger.debug("Total blocks found: %d", len(blocks))
                # Dump outerHTML of first 3 blocks for inspection
                for i, block in enumerate(blocks[:3]):
                    try:
                        html = block.get_attribute("outerHTML")
                        if self.debug:
                            self.logger.debug(
                                "Block %d outerHTML (first 500 chars): %s ---",
                                i,
                                html[:500],
                            )
                    except Exception as ex:
                        if self.debug:
                            self.logger.debug(
                                "Could not get outerHTML for block %d: %s", i, ex
                            )
                answer_link_elems = self.driver.find_elements(
                    By.XPATH, "//a[contains(@href,'/answer/')]"
                )
                if self.debug:
                    self.logger.debug(
                        "Found %d raw answer link elements", len(answer_link_elems)
                    )
                enriched_blocks = []
                for link in answer_link_elems:
                    try:
                        href = link.get_attribute("href") or ""
                        if not href or href in self.seen_links:
                            continue
                        ancestor = link
                        container = None
                        for _ in range(6):
                            ancestor = ancestor.find_element(By.XPATH, "..")
                            tag = ancestor.tag_name.lower()
                            if tag in ("article", "div"):
                                try:
                                    ancestor.find_element(
                                        By.XPATH,
                                        ".//*[contains(@class,'q-text') or contains(@href,'/question/')]",
                                    )
                                    container = ancestor
                                    break
                                except Exception:
                                    continue
                        if container and container.id not in seen_ids:
                            enriched_blocks.append(container)
                            seen_ids.add(container.id)
                    except Exception:
                        continue
                if len(enriched_blocks) > len(blocks):
                    if self.debug:
                        self.logger.debug(
                            "Replacing blocks with enriched set: %d vs %d",
                            len(enriched_blocks),
                            len(blocks),
                        )
                    blocks = enriched_blocks
                self.logger.info("Discovered %d potential answer blocks", len(blocks))
                # Process blocks
                for block in blocks:
                    try:
                        if self.processed >= (self.answer_limit or self.max_results):
                            self.logger.info(
                                "Reached answer limit; stopping block processing."
                            )
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
                                l_elem = block.find_element(
                                    By.XPATH, ".//a[contains(@href,'/answer/')]"
                                )
                                answer_link = l_elem.get_attribute("href")
                            except Exception:
                                pass
                        if not answer_link or answer_link in self.seen_links:
                            continue
                        self.seen_links.add(answer_link)
                        self._send_url(answer_link)
                        self.processed += 1
                    except KeyboardInterrupt:
                        raise
                    except Exception as e:
                        self.logger.error("Error processing block: %s", e)
                        continue
        except KeyboardInterrupt:
            self.logger.warning("Interrupted! Saving collected data...")
        try:
            # Re-extract at end to refresh (optional)
            self._extract_profile_stats()
        except Exception as e:
            self.logger.warning("Failed to refresh profile stats: %s", e)
        # Ensure all messages are delivered via sender
        try:
            self.sender.flush(2)
        except Exception:
            pass
        return self.processed

    def _retry(self, func, attempts=2):
        for i in range(attempts):
            try:
                return func()
            except StaleElementReferenceException:
                if i == attempts - 1:
                    raise
                time.sleep(0.2)

    def _send_url(self, url):
        try:
            self.sender.send(url)
            self.results.append(url)
        except Exception as e:
            self.logger.error("Sender failed for URL %s: %s", url, e)

    def kafka_healthcheck(self, timeout_sec: float = 5.0) -> bool:
        """Try a minimal produce+flush to validate broker connectivity.

        Returns True on success, False on failure. Skips in dry-run.
        """
        if self.dry_run or not isinstance(self.sender, KafkaSender):
            self.logger.info("Skipping Kafka healthcheck (not using Kafka)")
            return True
        try:
            # Send a healthcheck message via sender; nothing is printed to stdout
            self.sender.send(f"healthcheck:{int(time.time())}")
            self.sender.flush(timeout_sec)
            self.logger.info("Kafka healthcheck OK")
            return True
        except Exception as e:
            self.logger.error("Kafka healthcheck FAILED: %s", e)
            return False

    def close(self):
        """Close the browser"""
        if getattr(self, "driver", None):
            try:
                self.driver.quit()
            except Exception:
                pass


def main():
    # Create scraper instance with guarded startup
    try:
        # Select sender via CLI/env in the next block; start with stdout
        scraper = QuoraScraper(sender=StdoutSender())
    except WebDriverException:
        return
    try:
        import argparse

        parser = argparse.ArgumentParser(description="Quora profile scraper")
        parser.add_argument("profile_url", nargs="?", help="Profile answers URL")
        parser.add_argument(
            "--sender",
            choices=["stdout", "kafka"],
            default=os.environ.get("SENDER", "stdout"),
            help="Output sender (default: stdout)",
        )
        args = parser.parse_args()

        # Determine profile URL from CLI arg, env var, or default
        env_url = os.environ.get("PROFILE_URL")
        profile_url = resolve_profile_url(
            args.profile_url, env_url, DEFAULT_PROFILE_URL
        )
        # no printing of resolved URL

        # Configure sender based on flag
        if args.sender == "kafka":
            try:
                sender_obj = KafkaSender(scraper.kafka_bootstrap, scraper.kafka_topic)
            except Exception:
                return
        else:
            sender_obj = StdoutSender()
        scraper.sender = sender_obj

        # Optional Kafka healthcheck only if Kafka selected
        if args.sender == "kafka" and os.environ.get("KAFKA_HEALTHCHECK", "1") not in {
            "0",
            "false",
            "no",
            "n",
        }:
            ok = scraper.kafka_healthcheck()
            if not ok:
                return

        # no start print
        scraper.extract_content(profile_url)
        # no completion prints
    except KeyboardInterrupt:
        # no prints on interrupt
        pass
    finally:
        scraper.close()


if __name__ == "__main__":
    main()
