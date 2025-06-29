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
import signal
import psutil
import traceback
import shutil
import tempfile
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
from selenium.common.exceptions import TimeoutException

###############################################################################
# ----- USER CONFIG -----------------------------------------------------------
###############################################################################
KEYWORDS: List[str] = [
    "Playstation 5",
    "xbox series x",
    "xbox series s",
    "steam deck",
    "playstation 4",
]

# Complete eBay URLs to monitor (alongside keywords)
COMPLETE_URLS: List[str] = [
    "https://www.ebay.de/b/Spielekonsolen/139971/bn_466720?LH_BIN=1&LH_ItemCondition=1000&_sop=10&mag=1&rt=nc",
    # Add your complete eBay search URLs here
]

MAX_PAGES: int = 1            # depth per keyword/URL (1 is usually enough)
POLL_INTERVAL: int = 120      # seconds between successive scans
# ---- Path setup --------------------------------------------------
from pathlib import Path
BASE_DIR   = Path(__file__).resolve().parent
STATE_PATH = BASE_DIR / "state.json"
LOG_FILE   = BASE_DIR / "scraper.log"
PID_FILE   = BASE_DIR / "scraper.pid"

# Telegram -----------------------------------------------------------
TG_BOT_TOKEN = "7639063889:AAFBQ1zxgiFQZn7FcdrSkSJQ821CXjrjTFU"
TG_CHAT_ID = "1341792260"
if not TG_BOT_TOKEN or not TG_CHAT_ID:
    sys.exit("[FATAL] TG_BOT_TOKEN and TG_CHAT_ID must be set as env vars!")

###############################################################################
# ----- CONSTANTS -------------------------------------------------------------
###############################################################################
EBAY_SEARCH_TEMPLATE = (
    "https://www.ebay.de/sch/i.html?_from=R40&_nkw={query}&_sacat=139971"
    "&_sop=10&LH_BIN=1&rt=nc&LH_PrefLoc=3"
)

# XPath for keyword searches
XPATH_BASE_KEYWORD = "/html/body/div[5]/div[4]/div[3]/div[1]/div[3]/ul/li[{}]/div"
PAGE_READY_XPATH_KEYWORD = XPATH_BASE_KEYWORD.format(1)

# XPath for complete URL searches
XPATH_BASE_URL = "/html/body/div[2]/div[2]/section[3]/section[3]/ul/li[{}]"
PAGE_READY_XPATH_URL = XPATH_BASE_URL.format(1)

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
import codecs, io, logging, sys

def _safe_stdout() -> io.TextIOWrapper:
    """
    Return a TextIOWrapper that always **encodes UTF-8** and replaces
    unprintable characters (prevents UnicodeEncodeError on Windows).
    """
    return io.TextIOWrapper(
        sys.stdout.buffer,
        encoding="utf-8",
        errors="replace",      # <-- ♥  key line
        line_buffering=True,
    )

# Install safer stdout/stderr wrappers before logging
sys.stdout = _safe_stdout()
sys.stderr = _safe_stdout()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        # logging.FileHandler(LOG_FILE, encoding="utf-8"),   # full UTF-8 logs
        logging.StreamHandler(sys.stdout),                 # safe console
    ],
)

log = logging.getLogger(__name__)

# Global flag for graceful shutdown
running = True

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
# ------------------------------------------------------------------
# Configure Selenium so every page-load goes through the
# StormProxies back-connect gateway ( => fresh IP each request )
# ------------------------------------------------------------------
import requests, time
from typing import Optional

EU_CC = {           # accept only these ISO-2 codes  (put {"DE"} for Germany-only)
    "DE","AT","CH","NL","BE","LU","FR","IT","ES","PT","DK","SE","NO","FI",
    "PL","CZ","SK","HU","IE","GB","GR","RO","BG","HR","SI","EE","LV","LT"
}
MAX_ATTEMPTS = 6    # new StormProxies sessions to try each time we create a driver
GEO_TIMEOUT  = 7    # seconds for ip-api lookup

STORM_HOST = "37.48.118.4"   # your back-connect gateway
STORM_PORT = 13010
STORM_USER = None            # fill in if Storm gave you user/pass
STORM_PASS = None

_last_good_proxy: Optional[str] = None   # ✨ remembered across calls


def _build_proxy_arg() -> str:
    if STORM_USER and STORM_PASS:
        return f"http://{STORM_USER}:{STORM_PASS}@{STORM_HOST}:{STORM_PORT}"
    return f"http://{STORM_HOST}:{STORM_PORT}"


def _proxy_country(proxy: str) -> Optional[str]:
    """ISO-2 country for exit IP *through* this proxy (or None on error)."""
    try:
        r = requests.get("http://ip-api.com/json",
                         proxies={"http": proxy, "https": proxy},
                         timeout=GEO_TIMEOUT)
        if r.ok:
            return r.json().get("countryCode")
    except requests.RequestException:
        pass
    return None

def configure_driver() -> webdriver.Chrome:
    """
    Keep dialling StormProxies until we land on an **EU exit IP**.
    • Tries MAX_ATTEMPTS quick spins in a row
    • If still non-EU, sleeps WAIT_BETWEEN_ROUNDS seconds and starts over
    • Never falls back to a non-EU proxy
    """
    WAIT_BETWEEN_ROUNDS = 30   # seconds to pause before a new round of spins

    round_nr = 0
    while True:                                  # repeat until we succeed
        round_nr += 1
        for attempt in range(1, MAX_ATTEMPTS + 1):
            proxy = _build_proxy_arg()           # new exit IP each call
            cc = _proxy_country(proxy)
            print(f"{cc or 'unknown'} proxy: {proxy} ")
            if cc in EU_CC:
                log.info(f"✅ EU proxy acquired – {cc} "
                         f"(round {round_nr}, attempt {attempt})")
                return _start_chrome(proxy)

            log.warning(f"↻ Non-EU exit {cc or 'unknown'} "
                        f"(round {round_nr}, attempt {attempt}) – retrying…")
            time.sleep(1)

        # we’ve exhausted MAX_ATTEMPTS without an EU node
        log.error(f"❌ No EU proxy after {MAX_ATTEMPTS} spins; "
                  f"waiting {WAIT_BETWEEN_ROUNDS}s before next round")
        time.sleep(WAIT_BETWEEN_ROUNDS)
from selenium.common.exceptions import WebDriverException, TimeoutException

def safe_get(drv: webdriver.Chrome, url: str) -> webdriver.Chrome:
    """Try to load *url*. If the driver is dead, spin up a fresh one and return it."""
    try:
        drv.get(url)
        return drv
    except (TimeoutException, WebDriverException):
        log.warning("🧨 Driver died or hung – rebuilding …")
        _safe_quit(drv)
        new_drv = configure_driver()
        new_drv.get(url)
        return new_drv

import tempfile, shutil

def _kill_chrome_processes():
    """Kill all Chrome processes to prevent resource leaks"""
    try:
        killed_count = 0
        for proc in psutil.process_iter(['name', 'pid']):
            try:
                proc_name = proc.info['name']
                if proc_name and ('chrome' in proc_name.lower() or 'chromedriver' in proc_name.lower()):
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                        killed_count += 1
                    except psutil.TimeoutExpired:
                        proc.kill()
                        killed_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if killed_count > 0:
            log.info(f"🧹 Force-killed {killed_count} Chrome processes")
    except Exception as e:
        log.warning(f"⚠️ Chrome cleanup failed: {str(e)}")

def _safe_quit(drv: Optional[webdriver.Chrome]):
    if drv:
        try:
            drv.quit()
        except Exception as e:
            log.warning(f"⚠️ Driver quit failed: {str(e)}")
        finally:
            _kill_chrome_processes()
            time.sleep(1)
            profile_dir = getattr(drv, "_profile_dir", "")
            if profile_dir:
                shutil.rmtree(profile_dir, ignore_errors=True)

def _start_chrome(proxy_arg: str) -> webdriver.Chrome:
    MAX_RETRIES = 3
    for attempt in range(MAX_RETRIES):
        try:
            profile_dir = tempfile.mkdtemp(prefix="chrome-profile-")
            opts = webdriver.ChromeOptions()
            opts.add_argument("--headless=new")
            opts.add_argument("--disable-gpu")
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--disable-features=NetworkService")
            opts.add_argument("--window-size=1200,800")
            opts.add_argument(f"--proxy-server={proxy_arg}")
            opts.add_argument(f"--user-data-dir={profile_dir}")

            # Add crash prevention flags
            opts.add_argument("--disable-extensions")
            opts.add_argument("--disable-browser-side-navigation")
            opts.add_argument("--disable-gpu-sandbox")
            opts.add_argument("--no-zygote")
            opts.add_argument("--single-process")
            opts.add_argument("--disk-cache-size=0")
            opts.add_argument("--disable-infobars")
            opts.add_argument("--disable-breakpad")
            opts.add_argument("--disable-background-timer-throttling")
            opts.add_argument("--disable-backgrounding-occluded-windows")
            opts.add_argument("--disable-renderer-backgrounding")

            service = Service(
                ChromeDriverManager().install(),
                service_args=["--verbose", "--log-path=chromedriver.log"]
            )

            drv = webdriver.Chrome(service=service, options=opts)
            drv._profile_dir = profile_dir
            drv.set_page_load_timeout(25)  # Reduced timeout
            drv.set_script_timeout(20)
            log.info(f"✅ Chrome driver started successfully (attempt {attempt+1})")
            return drv

        except Exception as e:
            error_msg = str(e)
            if "DevToolsActivePort" in error_msg and attempt < MAX_RETRIES - 1:
                log.warning(f"⚠️ Chrome startup failed (attempt {attempt+1}): DevToolsActivePort error, retrying...")
                _kill_chrome_processes()
                time.sleep(3)
                continue
            elif attempt < MAX_RETRIES - 1:
                log.warning(f"⚠️ Chrome startup failed (attempt {attempt+1}): {error_msg}, retrying...")
                time.sleep(2)
                continue
            else:
                log.error(f"❌ Chrome startup failed after {MAX_RETRIES} attempts: {traceback.format_exc()}")
                shutil.rmtree(profile_dir, ignore_errors=True)
                raise

    raise Exception("Failed to start Chrome after all retries")

# ---------------------------------------------------------------------------
# Quick currency-check helpers
# ---------------------------------------------------------------------------
PRICE_XPATH = (
    "/html/body/div[2]/main/div[1]/div[1]/div[4]/div/div/div[2]/div/"
    "div[1]/div[3]/div/div/div[1]"
)

def _first_itm_link(card: Dict) -> str | None:
    """Return the first /itm/ link from a parsed card dict."""
    for url in card.get("links", []):
        if "/itm/" in url:
            return url
    return None

def _proxy_passes_currency_check(driver: webdriver.Chrome, itm_url: str) -> bool:
    """
    Open the listing page and look at PRICE_XPATH.
    Return True only if the text contains 'EUR' or the '€' sign.
    """
    for attempt in range(2):
        try:
            try:
                driver = safe_get(driver, itm_url)
            except TimeoutException:
                if attempt == 0:
                    log.warning("⏱ Timeout while checking currency page – retrying with new driver")
                    _safe_quit(driver)
                    driver = configure_driver()
                    continue
                else:
                    log.warning("💤 Currency check timed out completely")
                    return False

            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, PRICE_XPATH))
            )
            price_text = driver.find_element(By.XPATH, PRICE_XPATH).text.upper()
            log.info(f"💶 Detected price text: {price_text!r}")

            if "Ca.EUR" in price_text:
                log.info("❌ Currency check not passed with 'Ca.EUR'")
                return False
            if "EUR" in price_text:
                log.info("✅ Currency check passed with symbol: 'EUR' or '€'")
                return True
            if "GEBOTE" in price_text:
                log.info("✅ Currency check passed with bids – assuming EUR")
                return True
            log.warning("❌ Currency check failed – no 'EUR' found")
            return False

        except TimeoutException:
            if attempt == 0:
                log.warning("⏱ Currency check timeout, retrying with new driver...")
                _safe_quit(driver)
                driver = configure_driver()
                continue
            log.warning("💤 Currency check timed out completely")
            return False
        except Exception as e:
            log.error(f"⚠️ Currency check failed: {str(e)}")
            if attempt == 0:
                log.warning("🔄 Retrying currency check with new driver...")
                _safe_quit(driver)
                driver = configure_driver()
                continue
            return False

    return False
# ---------------------------------------------------------------------------
# Validate the current driver for the given keyword
# ---------------------------------------------------------------------------
def _ensure_eur_for_keyword(driver: webdriver.Chrome, keyword: str) -> bool:
    """
    • Scrape page 1 for *keyword*.
    • Pick the first /itm/ link.
    • Return True iff the listing shows EUR (via _proxy_passes_currency_check).
    """
    try:
        page1 = scrape_keyword(driver, keyword, 1)
        if not page1:
            log.warning(f"💤 No results for '{keyword}' – cannot validate currency")
            return False

        itm = _first_itm_link(page1[0])
        if not itm:
            log.warning(f"🕳  Couldn't extract /itm/ link for '{keyword}'")
            return False

        return _proxy_passes_currency_check(driver, itm)
    except Exception as exc:
        log.error(f"⚠️  Currency-validation failed for '{keyword}': {exc}")
        return False


def _ensure_eur_for_search_input(driver: webdriver.Chrome, search_input: str) -> bool:
    """
    Universal currency validation for both keywords and complete URLs.
    • For keywords: scrape page 1 and pick the first /itm/ link.
    • For URLs: scrape page 1 and pick the first /itm/ link.
    • Return True iff the listing shows EUR (via _proxy_passes_currency_check).
    """
    try:
        page1 = scrape_search_input(driver, search_input, 1)
        if not page1:
            identifier = search_input[:50] + "..." if len(search_input) > 50 else search_input
            log.warning(f"💤 No results for '{identifier}' – cannot validate currency")
            return False

        itm = _first_itm_link(page1[0])
        if not itm:
            identifier = search_input[:50] + "..." if len(search_input) > 50 else search_input
            log.warning(f"🕳  Couldn't extract /itm/ link for '{identifier}'")
            return False

        return _proxy_passes_currency_check(driver, itm)
    except Exception as exc:
        identifier = search_input[:50] + "..." if len(search_input) > 50 else search_input
        log.error(f"⚠️  Currency-validation failed for '{identifier}': {exc}")
        return False


def build_url(keyword: str) -> str:
    from urllib.parse import quote_plus

    return EBAY_SEARCH_TEMPLATE.format(query=quote_plus(keyword))


def extract_links(elem) -> List[str]:
    return sorted({a.get_attribute("href") for a in elem.find_elements(By.TAG_NAME, "a") if a.get_attribute("href")})


def is_complete_url(input_str: str) -> bool:
    """Check if input is a complete eBay URL"""
    return input_str.startswith(("http://", "https://")) and "ebay" in input_str.lower()


def scrape_url(driver: webdriver.Chrome, url: str, max_pages: int, url_identifier: str) -> List[Dict]:
    """Scrape *up to* ``max_pages`` from a complete eBay URL and return a list of parsed cards."""
    results: List[Dict] = []
    page_num = 1
    next_url = url

    while page_num <= max_pages and next_url:
        try:
            driver = safe_get(driver, next_url)

        except TimeoutException:
            log.warning("⏱ Page-load timed-out in scrape_url, recycling driver")
            _safe_quit(driver)
            driver = configure_driver()
            continue  # retry with new driver

        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, PAGE_READY_XPATH_URL))
            )
        except Exception:
            break  # this page failed – return what we already have

        idx = 1
        while True:
            xpath = XPATH_BASE_URL.format(idx)
            try:
                card = driver.find_element(By.XPATH, xpath)
            except Exception:
                break
            parsed = parse_card_text(card.text.strip())
            parsed.update({
                "url_source": url,
                "url_identifier": url_identifier,
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


def scrape_keyword(driver: webdriver.Chrome, keyword: str, max_pages: int) -> List[Dict]:
    """Scrape *up to* ``max_pages`` for a keyword and return a list of parsed cards."""
    results: List[Dict] = []
    page_num = 1
    next_url = build_url(keyword)

    while page_num <= max_pages and next_url:
        try:
            driver = safe_get(driver, next_url)
        except TimeoutException:
            log.warning("⏱ Page-load timed-out in scrape_keyword, recycling driver")
            _safe_quit(driver)
            driver = configure_driver()
            continue

        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, PAGE_READY_XPATH_KEYWORD))
            )
        except Exception:
            break

        idx = 1
        while True:
            xpath = XPATH_BASE_KEYWORD.format(idx)
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

        if page_num >= max_pages:
            break
        try:
            next_btn = driver.find_element(By.CSS_SELECTOR, "a.pagination__next")
            next_url = next_btn.get_attribute("href")
        except Exception:
            next_url = None
        page_num += 1
    return results


def scrape_search_input(driver: webdriver.Chrome, search_input: str, max_pages: int) -> List[Dict]:
    """Universal function to scrape either keyword or complete URL"""
    if is_complete_url(search_input):
        # Extract identifier from URL for state tracking
        url_identifier = f"URL_{hash(search_input) % 100000}"
        log.info(f"🔗 Scraping complete URL: {search_input[:100]}...")
        return scrape_url(driver, search_input, max_pages, url_identifier)
    else:
        log.info(f"🔍 Scraping keyword: {search_input}")
        return scrape_keyword(driver, search_input, max_pages)

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
        f"<a href=\"{link_html}\">Öffne Link</a>"
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
        r = requests.post(f"{API_BASE}/sendMessage", json=payload, timeout=30)
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
            # Create atomic read to prevent partial reads
            with open(STATE_PATH, 'r', encoding='utf-8') as f:
                data = f.read()
            if data.strip():  # Check if file is not empty
                return json.loads(data)
            else:
                log.warning("⚠️ Empty state file, starting fresh")
                return {}
        except json.JSONDecodeError as e:
            log.error(f"❌ Corrupt state file (JSON error): {str(e)}")
            # Backup corrupted file
            corrupt_file = STATE_PATH.with_name(f"state_corrupt_{int(time.time())}.json")
            try:
                shutil.copy(STATE_PATH, corrupt_file)
                log.info(f"📁 Backed up corrupt state to: {corrupt_file}")
            except Exception:
                pass
            return {}
        except Exception as e:
            log.error(f"❌ Failed to load state file: {str(e)}")
            return {}
    return {}


def save_state(state: Dict[str, str]):
    try:
        # Atomic write to prevent corruption
        temp_path = STATE_PATH.with_name(f"state_temp_{os.getpid()}.json")
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

        # Atomic rename (works on both Windows and Unix)
        if os.name == 'nt':  # Windows
            if STATE_PATH.exists():
                STATE_PATH.unlink()
        os.rename(temp_path, STATE_PATH)
        log.debug(f"💾 State saved successfully with {len(state)} keywords")
    except Exception as e:
        log.error(f"❌ Failed to save state: {str(e)}")
        # Clean up temp file if it exists
        temp_path = STATE_PATH.with_name(f"state_temp_{os.getpid()}.json")
        if temp_path.exists():
            temp_path.unlink()

###############################################################################
# ----- MAIN LOOP -------------------------------------------------------------
###############################################################################

def cleanup_on_exit():
    """Clean up resources when shutting down"""
    global running

    # Clean up PID file
    if PID_FILE.exists():
        try:
            PID_FILE.unlink()
            log.info("🧹 Cleaned up PID file")
        except Exception as e:
            log.warning(f"⚠️ Failed to remove PID file: {e}")

    # Clean up state.json file
    if STATE_PATH.exists():
        try:
            STATE_PATH.unlink()
            log.info("🧹 Cleaned up state.json file")
        except Exception as e:
            log.warning(f"⚠️ Failed to remove state.json file: {e}")

def check_system_resources():
    """Monitor system resources and return False if critical"""
    try:
        mem = psutil.virtual_memory()
        if mem.percent > 90:
            log.warning(f"⚠️ High memory usage: {mem.percent}%")
            return False

        # Check available disk space
        disk = psutil.disk_usage('.')
        if disk.percent > 95:
            log.warning(f"⚠️ Low disk space: {disk.percent}% used")
            return False

        return True
    except Exception as e:
        log.warning(f"⚠️ Resource monitoring failed: {str(e)}")
        return True  # Don't block if monitoring fails

def main():
    import os
    from pathlib import Path

    # Global flag for graceful shutdown
    global running
    running = True

    def signal_handler(sig, frame):
        global running
        log.info("🛑 Shutdown signal received - stopping scraper gracefully...")
        running = False
        cleanup_on_exit()
        sys.exit(0)

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Write PID file for process tracking
    pid_file = Path("scraper.pid")
    with open(pid_file, 'w') as f:
        f.write(str(os.getpid()))

    log.info(f"🚀 eBay scraper started with PID {os.getpid()}")

    state = load_state()  # keyword -> ISO timestamp str
    if not STATE_PATH.exists():
        STATE_PATH.write_text("{}", encoding="utf-8")

    log.info("🔄 Starting eBay watcher loop...")
    try:
        cycle_count = 0
        driver = None

        while running:  # Changed from 'while True' to respect shutdown signal
            cycle_count += 1

            # Check system resources before starting cycle
            if not check_system_resources():
                log.error("🚨 Critical resource shortage, cleaning up and restarting driver")
                if driver:
                    _safe_quit(driver)
                    driver = None
                _kill_chrome_processes()
                time.sleep(10)
                continue

            # Periodic driver restart to prevent memory leaks
            if cycle_count % 10 == 0 or driver is None:  # Every 10 cycles or first time
                log.info(f"🔄 {'Periodic' if driver else 'Initial'} driver refresh (cycle #{cycle_count})")
                if driver:
                    _safe_quit(driver)
                driver = configure_driver()
                time.sleep(2)

            # If no driver exists, create one
            if driver is None:
                driver = configure_driver()

            # Combine keywords and URLs for processing
            all_search_inputs = KEYWORDS + COMPLETE_URLS
            log.info(f"🔄 Starting scraping cycle #{cycle_count} for {len(KEYWORDS)} keywords and {len(COMPLETE_URLS)} URLs")   

            for search_input in all_search_inputs:
                # Check if we should stop before processing each search input
                if not running:
                    log.info("🛑 Stop requested - exiting search loop")
                    break

                # Create identifier for state tracking
                if is_complete_url(search_input):
                    state_key = f"URL_{hash(search_input) % 100000}"
                    log_identifier = f"URL: {search_input[:60]}..." if len(search_input) > 60 else f"URL: {search_input}"       
                else:
                    state_key = search_input
                    log_identifier = f"keyword: '{search_input}'"

                # -------------------------------------------------------------------
                # keep trying NEW proxies until this search input shows EUR/€
                # -------------------------------------------------------------------
                validated = False
                validation_attempts = 0
                max_validation_attempts = 5

                while not validated and running and validation_attempts < max_validation_attempts:
                    validation_attempts += 1

                    if driver is None:  # first time or after failure
                        driver = configure_driver()

                    log.info(f"🔍 Checking EUR currency for {log_identifier} (attempt {validation_attempts})…")
                    try:
                        if _ensure_eur_for_search_input(driver, search_input):
                            log.info(f"✅ {log_identifier} confirmed EUR – scraping full {MAX_PAGES} page(s)")
                            validated = True  # leave the while-retry loop
                        else:
                            log.error(f"❌ Currency mismatch for {log_identifier} – rotating proxy and retrying")
                            _safe_quit(driver)
                            driver = None  # trigger new proxy
                            time.sleep(2)  # Small delay before retry
                            continue  # retry same search input
                    except Exception as e:
                        log.error(f"💥 Critical error during currency validation: {str(e)}")
                        log.error(traceback.format_exc())
                        _safe_quit(driver)
                        driver = None
                        time.sleep(5)
                        continue

                # If validation failed after max attempts, skip this search input
                if not validated:
                    log.error(f"❌ Skipping {log_identifier} after {max_validation_attempts} validation attempts")
                    continue

                # Check again before continuing with scraping
                if not running:
                    log.info("🛑 Stop requested - exiting before scraping")
                    break

                last_iso = state.get(state_key)
                log.info(f"🔍 Checking {log_identifier} (last seen: {last_iso or 'never'})")
                first_run = last_iso is None
                last_dt   = datetime.fromisoformat(last_iso) if last_iso else datetime(1970, 1, 1)

                # ---- scrape --------------------------------------------------------
                try:
                    listings = scrape_search_input(driver, search_input, MAX_PAGES)
                    log.info(f"✅ Found {len(listings)} listings for {log_identifier}")
                except WebDriverException as exc:
                    log.error(f"🔥 WebDriver crashed during scraping: {exc}")
                    log.error(traceback.format_exc())
                    log.info("🔄 Restarting webdriver...")
                    _safe_quit(driver)
                    driver = configure_driver()
                    continue
                except Exception as exc:
                    log.error(f"💥 Unexpected error during scraping: {exc}")
                    log.error(traceback.format_exc())
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
                    state[state_key] = newest_seen.isoformat()
                    save_state(state)
                    log.info(f"📝 Updated last_seen for {log_identifier} to {newest_seen.isoformat()}")

                # ---- send messages (if any) ----------------------------------------
                if fresh and running:  # Only send if still running
                    log.info(f"📧 Found {len(fresh)} new listings for {log_identifier} - sending to Telegram...")

                    for _dt, lst in sorted(fresh, key=lambda t: t[0]):
                        if not running:  # Check before each message
                            log.info("🛑 Stop requested - stopping message sending")
                            break
                        try:
                            log.info(f"📤 Sending new listing: {lst.get('title', 'No title')[:60]}")
                            send_telegram_message(fmt_listing_for_telegram(lst))
                            time.sleep(1)  # be polite with Telegram API
                        except Exception as e:
                            log.error(f"❌ Failed to send Telegram message: {str(e)}")

            # Check if we should exit before waiting
            if not running:
                log.info("🛑 Stop requested - exiting main loop")
                break

            # ----- wait before next poll -------------------------------------------
            log.info(f"✅ Completed cycle #{cycle_count}. Sleeping for {POLL_INTERVAL} seconds...")
            # Make sleep interruptible by checking running flag every second
            for i in range(POLL_INTERVAL):
                if not running:
                    log.info("🛑 Stop requested during sleep - exiting")
                    break
                time.sleep(1)

    except Exception as e:
        log.error(f"💥 Critical error in main loop: {str(e)}")
        log.error(traceback.format_exc())
    finally:
        if 'driver' in locals() and driver:
            _safe_quit(driver)
        _kill_chrome_processes()
        cleanup_on_exit()
        log.info("🛑 eBay scraper stopped and cleaned up")


if __name__ == "__main__":
    main()
