import json
import os
import time

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from quora_selectors import (
    ANSWER_BLOCK_XPATHS,
    ANSWER_LINK_XPATHS,
    ANSWER_TEXT_XPATHS,
    INITIAL_ANSWER_WAIT_SECONDS,
    QUESTION_TEXT_XPATHS,
)


class QuoraScraper:
    def __init__(self):
        # Initialize Chrome WebDriver with error handling & optional fallback
        self.driver = None
        options = webdriver.ChromeOptions()
        # Modern headless for recent Chrome versions
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        # Allow user to specify a custom Chrome binary (e.g., Chromium) via env
        chrome_binary = os.environ.get("CHROME_BINARY")
        if chrome_binary:
            options.binary_location = chrome_binary
    self.debug = os.environ.get("DEBUG_SELECTORS") == "1"
    self.seen_links = set()

        try:
            self.driver = webdriver.Chrome(options=options)
            self.driver.set_page_load_timeout(30)
        except WebDriverException as e:
            print("[FATAL] Failed to start Chrome WebDriver.")
            print(f"Reason: {e}\n")
            print("Troubleshooting suggestions:")
            print(" 1. Open Google Chrome manually once (clears Gatekeeper warning).")
            print(
                " 2. If macOS blocked it: xattr -dr com.apple.quarantine /Applications/Google\\ Chrome.app"
            )
            print(
                " 3. Ensure Chrome is installed in /Applications and matches system architecture (ARM vs Intel)."
            )
            print(" 4. Update Selenium: pip install -U selenium")
            print(" 5. (Optional) Set CHROME_BINARY to an alternate Chromium path.")
            print(" 6. (Fallback) Set USE_FIREFOX=1 to try Firefox/geckodriver.")

            if os.environ.get("USE_FIREFOX") == "1":
                try:
                    from selenium.webdriver.firefox.options import (
                        Options as FirefoxOptions,
                    )

                    fopts = FirefoxOptions()
                    fopts.add_argument("-headless")
                    self.driver = webdriver.Firefox(options=fopts)
                    self.driver.set_page_load_timeout(30)
                    print("[INFO] Fallback to Firefox succeeded.")
                except Exception as fe:
                    print(f"[FATAL] Firefox fallback also failed: {fe}")
            if not self.driver:
                # Re-raise to let caller handle termination
                raise
        # Instance state
        self.results = []  # Store results as we go
        self.processed = 0
        # Limits
        self.max_results = int(os.environ.get("MAX_RESULTS", "500"))
        self.max_scrolls = int(os.environ.get("MAX_SCROLLS", "150"))
        self.no_growth_threshold = (
            5  # stop if this many consecutive scrolls yield no new content
        )
        self.output_dir = "qa_files"
        os.makedirs(self.output_dir, exist_ok=True)

    def print_status(self, message):
        """Print status message with carriage return"""
        print(f"\r{message}", end="", flush=True)

    def scroll_to_bottom(self):
        """Scroll page until no new content loads or limits hit."""
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        scroll_count = 0
        last_content_count = 0
        stagnant_scrolls = 0

        print("\nScrolling through profile...")

        while scroll_count < self.max_scrolls and self.processed < self.max_results:
            scroll_count += 1
            self.print_status(
                f"Scroll {scroll_count}/{self.max_scrolls} - Found {last_content_count} items - Saved {self.processed}/{self.max_results}"
            )

            # Scroll down
            self.driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);"
            )
            time.sleep(1.5)

            # Count current items (rough proxy; still uses q-box presence)
            current_content = len(self.driver.find_elements(By.CLASS_NAME, "q-box"))

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
                    print(
                        f"\nStopping scroll: height plateau or no growth ({stagnant_scrolls} stagnant). Items: {current_content}"
                    )
                    break
                last_height = new_height

        if scroll_count >= self.max_scrolls:
            print(f"\nReached max scrolls ({self.max_scrolls}).")
        if self.processed >= self.max_results:
            print(f"\nReached max results limit ({self.max_results}) during scrolling.")

    def extract_content(self, url):
    """Extract all questions and answers from a Quora profile"""
    print(f"\nLoading profile: {url}")
    self.driver.get(url)

    try:
            # First try to find any content on the page
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            # Give the page some time to load dynamic content
            time.sleep(5)

            # Wait for at least one answer block using any of the block XPaths
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
                print(
                    "Warning: No answer blocks detected with current XPaths before scrolling."
                )

            # Scroll to load more answers
            self.scroll_to_bottom()

            # Collect initial blocks
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
                print(f"[DEBUG] Initial block candidates: {len(blocks)}")

            # Fallback enrichment via direct answer links
            answer_link_elems = self.driver.find_elements(By.XPATH, "//a[contains(@href,'/answer/')]")
            if self.debug:
                print(f"[DEBUG] Found {len(answer_link_elems)} raw answer link elements")

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
                    print(
                        f"[DEBUG] Replacing blocks with enriched set: {len(enriched_blocks)} vs {len(blocks)}"
                    )
                blocks = enriched_blocks

            print(
                f"Discovered {len(blocks)} potential answer blocks (post-enrichment)"
            )

            # Process blocks
            for block in blocks:
                try:
                    if self.processed >= self.max_results:
                        print(
                            f"Reached max results limit ({self.max_results}); stopping block processing."
                        )
                        break
                    # Extract question text via fallbacks
                    question_text = None
                    for qx in QUESTION_TEXT_XPATHS:
                        try:
                            q_elem = block.find_element(By.XPATH, qx)
                            text = q_elem.text.strip()
                            if text:
                                question_text = text
                                break
                        except Exception:
                            continue

                    # Extract answer text (concatenate if multiple elements)
                    answer_text = None
                    for ax in ANSWER_TEXT_XPATHS:
                        try:
                            a_elems = block.find_elements(By.XPATH, ax)
                            texts = [a.text.strip() for a in a_elems if a.text.strip()]
                            if texts:
                                answer_text = "\n".join(texts)
                                break
                        except Exception:
                            continue

                    # Extract answer link (with global fallback)
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

                    # Derive question text from slug if missing
                    if not question_text and answer_link:
                        try:
                            from urllib.parse import urlparse, unquote

                            path = urlparse(answer_link).path
                            parts = path.split("/answer/")[0].strip("/").split("/")
                            if parts:
                                slug = parts[-1]
                                guess = unquote(slug).replace("-", " ")
                                if guess:
                                    question_text = guess
                        except Exception:
                            pass

                    if not answer_link or answer_link in self.seen_links:
                        continue
                    if not (question_text and answer_text):
                        if self.debug:
                            try:
                                snippet = block.get_attribute("innerHTML")[:300]
                                print(
                                    f"[DEBUG] Skipping block missing data. Snippet: {snippet}"
                                )
                            except Exception:
                                pass
                        continue

                    self.seen_links.add(answer_link)

                    print(f"\nQ [{self.processed + 1}]: {question_text[:100]}")
                    print(f"A [{self.processed + 1}]: {answer_text[:100]}")
                    print("-" * 80)

                    self.results.append(
                        {
                            "question_text": question_text,
                            "answer_text": answer_text,
                            "answer_link": answer_link,
                        }
                    )
                    self.processed += 1
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    print(f"\nError processing block: {e}")
                    continue

        except KeyboardInterrupt:
            print("\nInterrupted! Saving collected data...")

        return self.results

    def save_to_json(self, results, filename):
        """Save results to individual JSON files"""
        print(f"\nSaving {len(results)} QA pairs...")

        # Save each QA pair to a separate file
        for idx, item in enumerate(results, 1):
            qa_file = os.path.join(self.output_dir, f"qa_{idx:04d}.json")
            with open(qa_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "question": item["question_text"],
                        "answer": item["answer_text"],
                        "url": item["answer_link"],
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            print(f"Saved QA pair {idx}")

        print(f"All files saved to {self.output_dir}/")

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

        # Save results
        scraper.save_to_json(results, "")  # Filename not needed anymore
        print(f"\nExtracted and saved {len(results)} QA pairs")

    except KeyboardInterrupt:
        print("\nFinal cleanup...")
        if scraper.results:  # Save any results we have
            scraper.save_to_json(scraper.results, "")
    finally:
        # Clean up
        scraper.close()


if __name__ == "__main__":
    main()
