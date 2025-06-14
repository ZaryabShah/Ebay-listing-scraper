#!/usr/bin/env python3
"""ebay_absolute_scraper.py
Scrape eBay listing cards using an **absolute XPath** pattern, *parse* the raw
text into structured fields, and save everything to a JSON file.

CONFIG section – edit in place:
--------------------------------
* **KEYWORDS** – search phrases.
* **MAX_PAGES** – pagination depth per keyword.
* **DELAY** – polite pause (seconds) between requests.
* **OUTPUT_FILE** – `None` → print JSON to stdout; otherwise write to file.

Each card lives at:
    /html/body/div[5]/div[4]/div[3]/div[1]/div[3]/ul/li[N]/div
with N = 1, 2, 3 … until the element is missing.

The parser tries to extract the following fields (if present):
* **title**            – listing headline (without “NEUES ANGEBOT”, Sponsored, …)
* **condition**        – e.g. *Neu*, *Gebraucht* …
* **seller_type**      – *Privat* or *Gewerblich* (if present after the pipe)
* **price_eur**        – numeric float
* **price_raw**        – original string for reference
* **best_offer**       – boolean
* **shipping_eur**     – numeric float or `null` (if free/unknown)
* **shipping_raw**     – original shipping line
* **location**         – seller location
* **listed_at**        – date‑time string as shown by eBay
* **seller**           – seller username
* **feedback_count**   – integer feedback count
* **feedback_percent** – float (e.g. 96.4)
* **links**            – list of URLs inside the card (unchanged)

Missing fields are left `null` or empty.
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from typing import List, Dict, Optional
from urllib.parse import quote_plus

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# -----------------------------------------------------------------------------
# CONFIG – edit these values only
# -----------------------------------------------------------------------------
KEYWORDS: List[str] = [
    "Playstation 5",
    # "Grafikkarte",
    # "Nintendo Switch",
    # "iPhone 14 Pro Max",
    # "Samsung Galaxy S23 Ultra",    
]
MAX_PAGES: int = 1               # how many pages per keyword
DELAY: float = 5.0               # seconds between pages/keywords
OUTPUT_FILE: str | None = "ebay_results.json"  # None → print JSON to stdout

# -----------------------------------------------------------------------------
# Constants (do not edit unless eBay changes layout)
# -----------------------------------------------------------------------------
EBAY_SEARCH_TEMPLATE = (
    "https://www.ebay.de/sch/i.html?_from=R40&_nkw={query}&_sacat=139971"
    "&_sop=10&LH_BIN=1&rt=nc&LH_PrefLoc=3"
)
XPATH_BASE = "/html/body/div[5]/div[4]/div[3]/div[1]/div[3]/ul/li[{}]/div"
PAGE_READY_XPATH = XPATH_BASE.format(1)

PREFIXES_TO_STRIP = [
    "NEUES ANGEBOT",
    "SPONSORED",
    "Sponsored",
    "Anzeige",
]

# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------

def build_url(keyword: str) -> str:
    return EBAY_SEARCH_TEMPLATE.format(query=quote_plus(keyword))


def parse_eur_amount(raw: str) -> Optional[float]:
    """Convert strings like "EUR 1.234,56" → 1234.56 (float)."""
    m = re.search(r"EUR\s*([0-9\.,]+)", raw)
    if not m:
        return None
    num = m.group(1).replace(".", "").replace(",", ".")
    try:
        return float(num)
    except ValueError:
        return None


def extract_links(elem) -> List[str]:
    return sorted({a.get_attribute("href") for a in elem.find_elements(By.TAG_NAME, "a") if a.get_attribute("href")})


def parse_card_text(raw_text: str) -> Dict:
    """Parse raw multiline text from an eBay listing card into a dict."""
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
    if not lines:
        return {}

    # 1️⃣ Title (remove prefixes on first line)
    first_line = lines[0]
    for pfx in PREFIXES_TO_STRIP:
        if first_line.startswith(pfx):
            first_line = first_line[len(pfx):].strip()
            break
    out: Dict = {
        "title": first_line or None,
        "condition": None,
        "seller_type": None,
        "price_eur": None,
        "price_raw": None,
        "best_offer": False,
        "shipping_eur": None,
        "shipping_raw": None,
        "location": None,
        "listed_at": None,
        "seller": None,
        "feedback_count": None,
        "feedback_percent": None,
    }

    # walk the rest of lines detecting patterns
    for ln in lines[1:]:
        # Condition & seller type  e.g. "Gebraucht | Privat" or "Neu"
        if "|" in ln and ("Gebraucht" in ln or "Neu" in ln or "Defekt" in ln):
            parts = [p.strip() for p in ln.split("|")]
            out["condition"] = parts[0]
            if len(parts) > 1:
                out["seller_type"] = parts[1]
            continue
        elif any(word in ln for word in ("Gebraucht", "Neu", "Defekt")) and out["condition"] is None:
            out["condition"] = ln
            continue

        # Price line e.g. "EUR 432,94"
        if ln.startswith("EUR") and out["price_raw"] is None:
            out["price_raw"] = ln
            out["price_eur"] = parse_eur_amount(ln)
            continue

        # Best offer line contains "Preisvorschlag"
        if "Preisvorschlag" in ln:
            out["best_offer"] = True
            continue

        # Shipping line – look for "+EUR" or "Kostenlos"
        if (ln.startswith("+EUR") or "Lieferung" in ln or "Versand" in ln) and out["shipping_raw"] is None:
            out["shipping_raw"] = ln
            out["shipping_eur"] = parse_eur_amount(ln)
            continue

        # Location – starts with "aus "
        if ln.lower().startswith("aus ") and out["location"] is None:
            out["location"] = ln[4:].strip()
            continue

        # Listing date/time – contains a dot after day and month abbrev followed by time
        if re.match(r"\d{1,2}\.\s*[A-Za-z]{3}\.?\s*\d{2}:\d{2}", ln):
            out["listed_at"] = ln
            continue

        # Seller info e.g. "di3hard76 (40) 96,4%"
        m = re.match(r"(?P<seller>.+?)\s*\((?P<count>\d+)\)\s*(?P<percent>[0-9.,]+)%", ln)
        if m:
            out["seller"] = m.group("seller").strip()
            out["feedback_count"] = int(m.group("count"))
            out["feedback_percent"] = float(m.group("percent").replace(",", "."))
            continue

    return out

# -----------------------------------------------------------------------------
# Scraping core
# -----------------------------------------------------------------------------

def scrape_keyword(driver: webdriver.Chrome, keyword: str, max_pages: int, delay: float) -> List[Dict]:
    results: List[Dict] = []
    page_num = 1
    next_url = build_url(keyword)

    while page_num <= max_pages and next_url:
        driver.get(next_url)

        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, PAGE_READY_XPATH)))
        except Exception as exc:
            print(f"[WARN] '{keyword}' page {page_num}: {exc}", file=sys.stderr)
            break

        index = 1
        while True:
            xpath = XPATH_BASE.format(index)
            try:
                card = driver.find_element(By.XPATH, xpath)
            except Exception:
                break  # no more cards on this page

            raw_text = card.text.strip()
            parsed = parse_card_text(raw_text)
            parsed.update({
                "keyword": keyword,
                "page": page_num,
                "rank": index,
                "links": extract_links(card),
            })
            results.append(parsed)
            index += 1

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
# Main routine
# -----------------------------------------------------------------------------

def main() -> None:
    options = webdriver.ChromeOptions()
    # options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    all_results: List[Dict] = []
    try:
        for kw in KEYWORDS:
            all_results.extend(scrape_keyword(driver, kw, max_pages=MAX_PAGES, delay=DELAY))
            if DELAY:
                time.sleep(DELAY)
    finally:
        driver.quit()

    if OUTPUT_FILE:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as fp:
            json.dump(all_results, fp, ensure_ascii=False, indent=2)
        print(f"Saved {len(all_results)} listings to {OUTPUT_FILE}")
    else:
        json.dump(all_results, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
