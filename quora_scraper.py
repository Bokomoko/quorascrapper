import json
import logging
import os
import re
import time

from selenium import webdriver
from selenium.common.exceptions import (
    StaleElementReferenceException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from quora_selectors import (
    ANSWER_BLOCK_XPATHS,
    ANSWER_LINK_XPATHS,
    INITIAL_ANSWER_WAIT_SECONDS,
    PROFILE_STATS_XPATHS,
)


class QuoraScraper:
    def __init__(self):
        # Initialize Chrome WebDriver with error handling & optional fallback
        self.driver = None
        # Logging setup
        log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
        logging.basicConfig(
            level=getattr(logging, log_level, logging.INFO),
            format="%(asctime)s [%(levelname)s] %(message)s",
        )
        self.logger = logging.getLogger("QuoraScraper")
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
        try:
            self.driver = webdriver.Chrome(options=options)
            self.driver.set_page_load_timeout(30)
        except WebDriverException as e:
            self.logger.error("Failed to start Chrome WebDriver: %s", e)
            print("Troubleshooting suggestions:")
            print(" 1. Open Google Chrome manually once (clears Gatekeeper warning).")
            print(
                " 2. If macOS blocked it: xattr -dr com.apple.quarantine /Applications/Google\\ Chrome.app"
            )
            print(
                " 3. Ensure Chrome is installed in /Applications and matches architecture."
            )
            print(" 4. Update Selenium: pip install -U selenium")
            print(" 5. Optionally set CHROME_BINARY to alternate Chromium.")
            print(" 6. Set USE_FIREFOX=1 for Firefox fallback.")
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
        self.output_dir = "qa_files"
        os.makedirs(self.output_dir, exist_ok=True)
        self.incremental = os.environ.get("INCREMENTAL_SAVE") == "1"
        self.aggregate_filename = os.environ.get("QA_OUTPUT_FILE", "qa_all.json")
        self.answer_limit = None  # dynamic limit based on profile answers count

    def print_status(self, message):
        """Print status message with carriage return"""
        print(f"\r{message}", end="", flush=True)

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
                self.driver.find_elements(By.XPATH, "//a[contains(@href,'/answer/')]")
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

    def _normalize_number(self, txt):
        if not txt:
            return None
        txt = txt.replace("\u00a0", " ").replace(",", "").strip()
        # Handle formats like '14,7 mil' or '14.7 mil'
        mil_match = re.match(r"([0-9]+)[\.,]?([0-9]+)?\s*mil", txt, re.IGNORECASE)
        if mil_match:
            whole = int(mil_match.group(1))
            frac = mil_match.group(2)
            value = whole * 1000 + (
                int(frac) * (1000 // (10 ** len(frac))) if frac else 0
            )
            return value
        # Plain integer
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
        """Extract all answer URLs from a Quora profile"""
        self.logger.info("Loading profile: %s", url)
        self.driver.get(url)
        try:
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            time.sleep(2)
            # Extract stats BEFORE any scrolling or block discovery
            try:
                self._extract_profile_stats()
                print(f"Profile stats (pre-scroll): {self.profile_stats}")
                self.logger.info("Answer limit set to %s", self.answer_limit)
            except Exception as e:
                self.logger.warning("Initial stats extraction failed: %s", e)
                self.answer_limit = self.max_results
            found_block = False
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
                    for e in elems:
                        if e.id not in seen_ids:
                            blocks.append(e)
                            seen_ids.add(e.id)
                except Exception:
                    continue
            if self.debug:
                self.logger.debug("Initial block candidates: %d", len(blocks))
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
                    # Only extract answer link now
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
                    self.results.append(answer_link)
                    self.processed += 1
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    self.logger.error("Error processing block: %s", e)
                    continue
        except KeyboardInterrupt:
            self.logger.warning("Interrupted! Saving collected data...")
        results = self.results  # keep original reference
        # After processing blocks extract stats
        try:
            # Re-extract at end to refresh (optional)
            self._extract_profile_stats()
        except Exception as e:
            self.logger.warning("Failed to refresh profile stats: %s", e)
        return results

    def _retry(self, func, attempts=2):
        for i in range(attempts):
            try:
                return func()
            except StaleElementReferenceException:
                if i == attempts - 1:
                    raise
                time.sleep(0.2)

    def save_to_json(self, results, filename):
        out_path = os.path.join(self.output_dir, self.aggregate_filename)
        tmp_path = out_path + ".tmp"
        data = {
            "profile_stats": self.profile_stats,
            "answer_limit": self.answer_limit or self.max_results,
            "collected": len(results),
            "urls": results,
        }
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, out_path)
            size = os.path.getsize(out_path)
            with open(out_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            count = len(loaded.get("urls", []))
            if count != len(results):
                self.logger.warning(
                    "URL count mismatch after save: expected %d got %d",
                    len(results),
                    count,
                )
            self.logger.info(
                "Saved %d URLs to %s (size %d bytes, limit %s)",
                len(results),
                out_path,
                size,
                data["answer_limit"],
            )
        except Exception as e:
            self.logger.error("Failed saving aggregated file: %s", e)
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

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
        scraper = QuoraScraper()
    except WebDriverException:
        print("Exiting due to WebDriver initialization failure.")
        return
    try:
        # URL of the Quora profile with proper encoding
        profile_url = (
            "https://pt.quora.com/profile/Jo%C3%A3o-Eurico-de-Aguiar-Lima/answers"
        )
        print("\nPress Ctrl+C at any time to stop and save current progress\n")
        # Extract content
        print("Starting extraction...")
        results = scraper.extract_content(profile_url)
        scraper.save_to_json(results, "")
        print(f"\nExtracted and saved {len(results)} QA pairs")
        if scraper.profile_stats:
            print("Profile stats:", scraper.profile_stats)
    except KeyboardInterrupt:
        print("\nFinal cleanup...")
        if scraper.results:
            scraper.save_to_json(scraper.results, "")
    finally:
        scraper.close()


if __name__ == "__main__":
    main()
