# ebay_telegram_watcher.py
"""A headless‑Selenium bot that watches eBay search results and pushes every
brand‑new listing to a Telegram chat.

How it works
------------
1.  Scrapes the first *n* pages for each keyword (default 1).
2.  Remembers the freshest `listed_at` timestamp **per keyword** in a tiny
    JSON state file (`state.json`).
3.  Every `POLL_INTERVAL` seconds (default 120 s) it reruns the scrape and
    sends only the cards that have appeared since the last run.
4.  Each new card is formatted like the sample screenshot and delivered via
    the Telegram Bot API.
5.  If you stop the bot and start it again it continues where it left off,
    thanks to the persisted timestamps.

Prerequisites
-------------
```bash
pip install selenium webdriver‑manager requests python‑telegram‑bot~=20.0
```
Set two environment variables **before** running the script:
```bash
export TG_BOT_TOKEN="123456:ABC…"
export TG_CHAT_ID="‑987654321"      # positive for user‑ID, negative for group
```
Then just run:
```bash
python ebay_telegram_watcher.py
```

PROXY / stealth note: placeholders are left in place (see `configure_driver`).
Insert your rotation logic later.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

###############################################################################
# ----- USER CONFIG -----------------------------------------------------------
###############################################################################
KEYWORDS: List[str] = [
    "Playstation 5",
    "Grafikkarte",
    "Nintendo Switch",
]

MAX_PAGES: int = 1            # depth per keyword (1 is usually enough)
POLL_INTERVAL: int = 120      # seconds between successive scans
STATE_PATH = Path("state.json")

# Telegram -----------------------------------------------------------
TG_BOT_TOKEN = "7639063889:AAFBQ1zxgiFQZn7FcdrSkSJQ821CXjrjTFU"
TG_CHAT_ID = "7335015078"
if not TG_BOT_TOKEN or not TG_CHAT_ID:
    sys.exit("[FATAL] TG_BOT_TOKEN and TG_CHAT_ID must be set as env vars!")

###############################################################################
# ----- CONSTANTS -------------------------------------------------------------
###############################################################################
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

###############################################################################
# ----- UTILITIES -------------------------------------------------------------
###############################################################################
GERMAN_MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mär": 3,
    "Mar": 3,  # fallback in case eBay drops the umlaut
    "Apr": 4,
    "Mai": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Okt": 10,
    "Nov": 11,
    "Dez": 12,
}

KNOWN_CONDITIONS = {
    "Neu", "Brandneu", "Gebraucht", "Defekt", "Nur Ersatzteile",
}

MONTH_RE = "|".join(GERMAN_MONTHS.keys())
DATE_RE = re.compile(
    rf"(?P<day>\d{{1,2}})\.\s*(?P<mon>{MONTH_RE})\.?(?:\s*(?P<year>\d{{4}}))?\s*(?P<hour>\d{{2}}):(?P<minute>\d{{2}})"
)

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

log = logging.getLogger(__name__)

def parse_ebay_datetime(ts: str) -> datetime:
    """Convert eBay's German timestamp to a :class:`datetime` (local time).

    Examples accepted::
        16. Jun. 08:19
        06. Mär. 22:36
        22. Feb. 2024 14:02
    """
    m = DATE_RE.search(ts)
    if not m:
        raise ValueError(f"Unparsable timestamp: {ts!r}")
    day = int(m["day"])
    month = GERMAN_MONTHS[m["mon"]]
    year = int(m["year"] or datetime.now().year)
    hour = int(m["hour"])
    minute = int(m["minute"])
    return datetime(year, month, day, hour, minute)


# ---- price helpers -------------------------------------------------
EUR_AMOUNT_RE = re.compile(r"EUR\s*([\d\.,]+)")

def parse_eur_amounts(raw: str) -> List[float]:
    return [float(a.replace(".", "").replace(",", ".")) for a in EUR_AMOUNT_RE.findall(raw)]


# ---- seller feedback ----------------------------------------------
SELLER_RE = re.compile(r"(?P<seller>.+?)\s*\((?P<count>[\d\.,]+)\)\s*(?P<pct>[\d\.,]+)%")

def parse_seller_feedback(line: str):
    m = SELLER_RE.match(line)
    if not m:
        return None
    seller = m["seller"].strip()
    count = int(m["count"].replace(".", "").replace(",", ""))
    pct = float(m["pct"].replace(",", "."))
    return seller, count, pct


###############################################################################
# ----- CORE PARSER (single card) --------------------------------------------
###############################################################################

def parse_card_text(raw_text: str) -> Dict:
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
    if not lines:
        return {}

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
        "text": lines,
    }

    for ln in lines[1:]:
        # ➊ condition / seller type
        if any(c in ln for c in KNOWN_CONDITIONS):
            parts = [p.strip() for p in ln.split("|")]
            out["condition"] = parts[0] or None
            if len(parts) > 1:
                out["seller_type"] = parts[1] or None
            continue

        # ➋ price line(s)
        if ln.lstrip().startswith("EUR"):
            prices = parse_eur_amounts(ln)
            if prices:
                out["price_eur"] = prices[0]
                if len(prices) == 2:
                    out["price_eur_max"] = prices[1]
            out["price_raw"] = ln
            continue

        # ➌ best offer
        if "Preisvorschlag" in ln:
            out["best_offer"] = True
            continue

        # ➍ shipping
        if any(tok in ln for tok in ("Versand", "Lieferung", "+EUR", "Kostenlos")):
            out["shipping_raw"] = ln
            prices = parse_eur_amounts(ln)
            out["shipping_eur"] = prices[0] if prices else 0.0
            continue

        # ➎ location
        if ln.lower().startswith("aus "):
            out["location"] = ln[4:].strip()
            continue

        # ➏ date / time
        if DATE_RE.search(ln):
            out["listed_at"] = ln
            continue

        # ➐ seller
        fb = parse_seller_feedback(ln)
        if fb:
            out["seller"], out["feedback_count"], out["feedback_percent"] = fb
            continue

    return out

###############################################################################
# ----- SCRAPER ---------------------------------------------------------------
###############################################################################

def configure_driver() -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1200,800")
    # ➡️  PLACEHOLDER for proxy / stealth extensions
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)


def build_url(keyword: str) -> str:
    from urllib.parse import quote_plus

    return EBAY_SEARCH_TEMPLATE.format(query=quote_plus(keyword))


def extract_links(elem) -> List[str]:
    return sorted({a.get_attribute("href") for a in elem.find_elements(By.TAG_NAME, "a") if a.get_attribute("href")})


def scrape_keyword(driver: webdriver.Chrome, keyword: str, max_pages: int) -> List[Dict]:
    """Scrape *up to* ``max_pages`` and return a list of parsed cards."""
    results: List[Dict] = []
    page_num = 1
    next_url = build_url(keyword)

    while page_num <= max_pages and next_url:
        driver.get(next_url)
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, PAGE_READY_XPATH))
            )
        except Exception:
            break  # this page failed – return what we already have

        idx = 1
        while True:
            xpath = XPATH_BASE.format(idx)
            try:
                card = driver.find_element(By.XPATH, xpath)
            except Exception:
                break
            parsed = parse_card_text(card.text.strip())
            parsed.update({
                "keyword": keyword,
                "page": page_num,
                "rank": idx,
                "links": extract_links(card),
            })
            results.append(parsed)
            idx += 1

        # next page link
        if page_num >= max_pages:
            break
        try:
            next_btn = driver.find_element(By.CSS_SELECTOR, "a.pagination__next")
            next_url = next_btn.get_attribute("href")
        except Exception:
            next_url = None
        page_num += 1
    return results

###############################################################################
# ----- TELEGRAM --------------------------------------------------------------
###############################################################################
API_BASE = f"https://api.telegram.org/bot{TG_BOT_TOKEN}"


def fmt_listing_for_telegram(lst: Dict) -> str:
    best_offer = "🟢" if lst.get("best_offer") else "🔴"
    price = lst.get("price_eur") or lst.get("price_raw") or "‑"
    cond = lst.get("condition") or "‑"
    fb = lst.get("feedback_count") or 0
    ts = lst.get("listed_at") or "?"
    title_html = html.escape(lst.get("title") or "(kein Titel)")
    # first link that contains "/itm/" is best bet
    link = next((l for l in lst["links"] if "/itm/" in l), lst["links"][0] if lst["links"] else "")
    link_html = html.escape(link)

    return (
        f"<b>Name:</b> {title_html}\n\n"
        f"<b>Preis:</b> {price}\n"
        f"<b>Preisvorschlag:</b> {best_offer}\n"
        f"<b>Artikelzustand:</b> {cond}\n"
        f"<b>Bewertungen:</b> {fb}\n"
        f"<b>Veröffentlicht:</b> {ts}\n\n"
        f"<a href=\"{link_html}\">Öffne Link</a>"
    )

def send_telegram_message(html_text: str):
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": html_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    # Proxy setup
    proxy_host = "72.9.168.192"
    proxy_port = "12323"
    proxy_user = "14acfa7f9a57c"
    proxy_pass = "74f453f102"

    proxies = {
        "http": f"http://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}",
        "https": f"http://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}",
    }

    try:
        r = requests.post(f"{API_BASE}/sendMessage", json=payload, proxies=proxies, timeout=30)
        if not r.ok:
            log.warning(f"Telegram API error {r.status_code}: {r.text}")

    except requests.RequestException as e:
        log.error(f"Failed to send Telegram message: {e}")


###############################################################################
# ----- STATE HANDLING --------------------------------------------------------
###############################################################################

def load_state() -> Dict[str, str]:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text("utf‑8"))
        except Exception:
            pass
    return {}


def save_state(state: Dict[str, str]):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf‑8")

###############################################################################
# ----- MAIN LOOP -------------------------------------------------------------
###############################################################################

def main():
    state = load_state()  # keyword -> ISO timestamp str
    driver = configure_driver()
    log.info("🔄 Starting eBay watcher loop...")


    try:
        while True:
            for kw in KEYWORDS:
                last_iso = state.get(kw)
                log.info(f"🔍 Checking keyword: '{kw}' (last seen: {last_iso or 'never'})")
                first_run = last_iso is None
                last_dt   = datetime.fromisoformat(last_iso) if last_iso else datetime(1970, 1, 1)

                # ---- scrape --------------------------------------------------------
                try:
                    listings = scrape_keyword(driver, kw, MAX_PAGES)
                    log.info(f"✅ Found {len(listings)} listings for '{kw}'")
                except WebDriverException as exc:
                    log.error(f"WebDriver crashed: {exc}")
                    driver.quit()
                    driver = configure_driver()
                    continue

                # ---- decide what to do with the results ---------------------------
                newest_seen = last_dt          # will hold freshest timestamp we saw
                fresh: List[tuple[datetime, Dict]] = []

                for lst in listings:
                    ts_raw = lst.get("listed_at")
                    if not ts_raw:
                        continue
                    try:
                        dt = parse_ebay_datetime(ts_raw)
                    except ValueError:
                        log.warning(f"⚠️ Could not parse timestamp: {ts_raw}")
                        continue


                    if dt > newest_seen:
                        newest_seen = dt

                    # only collect for sending if we are *past* the first run
                    if not first_run and dt > last_dt:
                        fresh.append((dt, lst))

                # ---- update state --------------------------------------------------
                if newest_seen > last_dt:
                    state[kw] = newest_seen.isoformat()
                    save_state(state)
                    log.info(f"📝 Updated last_seen for '{kw}' to {newest_seen.isoformat()}")

                # ---- send messages (if any) ----------------------------------------
                for _dt, lst in sorted(fresh, key=lambda t: t[0]):
                    log.info(f"📤 Sending new listing: {lst.get('title')[:60]}")
                    send_telegram_message(fmt_listing_for_telegram(lst))
                    time.sleep(1)          # be polite with Telegram API

            # ----- wait before next poll -------------------------------------------
            log.info(f"⏱ Sleeping for {POLL_INTERVAL} seconds...\n")
            time.sleep(POLL_INTERVAL)

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
