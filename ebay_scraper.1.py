#!/usr/bin/env python3
"""ebay_absolute_scraper.py
Scrape eBay listing cards using the **exact absolute XPath** pattern and save the
results to a JSON file – all without any command‑line arguments. Just edit the
CONFIG section below when you need to change keywords, page limits, delays, or
output filename.

The card location pattern is:
    /html/body/div[5]/div[4]/div[3]/div[1]/div[3]/ul/li[N]/div
where N starts at 1 and increments until a card is missing.

Configuration
-------------
Edit these four variables and run the script:

    KEYWORDS     – list[str] of query phrases.
    MAX_PAGES    – int, how many pagination pages per keyword.
    DELAY        – float, optional pause (seconds) between pages/keywords.
    OUTPUT_FILE  – str or None.  If None, JSON is printed to stdout.

Example: simply run
    python ebay_absolute_scraper.py
and find the results in the OUTPUT_FILE (default: `ebay_results.json`).
"""

from __future__ import annotations

import json
import sys
import time
from typing import List, Dict
from urllib.parse import quote_plus

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# -----------------------------------------------------------------------------
# CONFIG – edit these values only
# -----------------------------------------------------------------------------
KEYWORDS: List[str] = [
    "Playstation 5",
    "Grafikkarte",
    "Nintendo Switch",
    "iPhone 14 Pro Max",
    "Samsung Galaxy S23 Ultra",
]
MAX_PAGES: int = 1               # how many pages per keyword
DELAY: float = 0.0               # seconds between pages/keywords
OUTPUT_FILE: str | None = "ebay_results1.json"  # None → print JSON to stdout

# -----------------------------------------------------------------------------
# Constants (do not edit unless eBay changes layout)
# -----------------------------------------------------------------------------
EBAY_SEARCH_TEMPLATE = (
    "https://www.ebay.de/sch/i.html?_from=R40&_nkw={query}&_sacat=139971"
    "&_sop=10&LH_BIN=1&rt=nc&LH_PrefLoc=3"
)
XPATH_BASE = "/html/body/div[5]/div[4]/div[3]/div[1]/div[3]/ul/li[{}]/div"
PAGE_READY_XPATH = XPATH_BASE.format(1)

# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------

def build_url(keyword: str) -> str:
    """Return the eBay search URL for *keyword*."""
    return EBAY_SEARCH_TEMPLATE.format(query=quote_plus(keyword))


def extract_links(elem) -> List[str]:
    """Return all distinct href values inside the element."""
    return sorted(
        {
            a.get_attribute("href")
            for a in elem.find_elements(By.TAG_NAME, "a")
            if a.get_attribute("href")
        }
    )

# -----------------------------------------------------------------------------
# Scraping core
# -----------------------------------------------------------------------------

def scrape_keyword(
    driver: webdriver.Chrome,
    keyword: str,
    max_pages: int,
    delay: float,
) -> List[Dict]:
    """Scrape *keyword* and return list of listing dicts."""
    results: List[Dict] = []
    page_num = 1
    next_url = build_url(keyword)

    while page_num <= max_pages and next_url:
        driver.get(next_url)

        # Wait until at least the first card is present (max 10 s)
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, PAGE_READY_XPATH))
            )
        except Exception as exc:
            print(f"[WARN] '{keyword}' page {page_num}: {exc}", file=sys.stderr)
            break

        # Iterate li[1], li[2], ... until not found
        index = 1
        while True:
            xpath = XPATH_BASE.format(index)
            try:
                card = driver.find_element(By.XPATH, xpath)
            except Exception:
                break  # missing card → end of current page

            results.append(
                {
                    "keyword": keyword,
                    "page": page_num,
                    "rank": index,
                    "text": card.text.strip(),
                    "links": extract_links(card),
                }
            )
            index += 1

        # Prepare next page if requested
        if page_num >= max_pages:
            break
        try:
            next_btn = driver.find_element(By.CSS_SELECTOR, "a.pagination__next")
            next_url = next_btn.get_attribute("href")
        except Exception:
            next_url = None

        page_num += 1
        if delay:
            time.sleep(delay)

    return results

# -----------------------------------------------------------------------------
# Main routine – runs once when you execute the file
# -----------------------------------------------------------------------------

def main() -> None:
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=options
    )

    all_results: List[Dict] = []
    try:
        for kw in KEYWORDS:
            all_results.extend(
                scrape_keyword(driver, kw, max_pages=MAX_PAGES, delay=DELAY)
            )
            if DELAY:
                time.sleep(DELAY)
    finally:
        driver.quit()

    # Serialize JSON either to file or stdout
    if OUTPUT_FILE:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as fp:
            json.dump(all_results, fp, ensure_ascii=False, indent=2)
        print(f"Saved {len(all_results)} listings to {OUTPUT_FILE}")
    else:
        json.dump(all_results, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
