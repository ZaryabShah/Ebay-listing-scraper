# ebay_telegram_watcher_async.py
"""Asynchronous eBay watcher
=================================
* Scrapes the newest *Buy‑it‑Now* listings for a list of **KEYWORDS**.
* Uses **StormProxies back‑connect gateway** ( `5.79.73.131:13010` ) so every
  TCP connection – hence every *page load* – appears from a fresh exit IP.
* Runs each keyword in its **own thread** – they execute in parallel and every
  scan instantiates its *own* headless Chrome instance that lives only for one
  scrape, guaranteeing a fresh proxy connection each cycle.
* Persists the newest `listed_at` timestamp per keyword in `state.json` and is
  *silent on first run* (no Telegram spam for historical items).
* Sends new listings to Telegram via the Bot API (still proxied).

Install & run
-------------
```bash
pip install selenium webdriver-manager requests
export TG_BOT_TOKEN="123456:ABC…"
export TG_CHAT_ID="-987654321"   # user id or group id
python ebay_telegram_watcher_async.py
```

If you want more workers than keywords, tweak `MAX_WORKERS`.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Dict, List
import urllib.parse
import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

###############################################################################
# ----------------------------- USER CONFIG ----------------------------------
###############################################################################
KEYWORDS: List[str] = [
    "Playstation 5",
    "xbox series x",
    "xbox series s",
    "nintendo switch",
    "steam deck",
]

MAX_PAGES = 1               # how deep per keyword
POLL_INTERVAL = 120         # seconds between scans
MAX_WORKERS = len(KEYWORDS) # threads – one per keyword is fine
STATE_FILE = Path("state.json")

# Telegram -----------------------------------------------------------
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "") or "7639063889:AAFBQ1zxgiFQZn7FcdrSkSJQ821CXjrjTFU"
TG_CHAT_ID  = os.getenv("TG_CHAT_ID",  "") or  "7335015078" # "1341792260" client id
if not TG_BOT_TOKEN or not TG_CHAT_ID:
    sys.exit("[FATAL] TG_BOT_TOKEN and TG_CHAT_ID must be set!")

# StormProxies back‑connect gateway – *new exit IP for every request*
PROXY_HOST = "5.79.73.131"
PROXY_PORT = 13010
PROXY_USER = None           # gateway does not need auth; set if you have it
PROXY_PASS = None
###############################################################################

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

###############################################################################
# ---------------------------- CONSTANTS -------------------------------------
###############################################################################
EBAY_SEARCH_TEMPLATE = (
    "https://www.ebay.de/sch/i.html?_from=R40&_nkw={query}&_sacat=139971"
    "&_sop=10&LH_BIN=1&rt=nc&LH_PrefLoc=3"
)
XPATH_BASE = "/html/body/div[5]/div[4]/div[1]/div[3]/ul/li[{}]/div"
PAGE_READY_XPATH = XPATH_BASE.format(1)
PREFIXES_TO_STRIP = ["NEUES ANGEBOT", "SPONSORED", "Sponsored", "Anzeige"]

GERMAN_MONTHS = {
    "Jan": 1, "Feb": 2, "Mär": 3, "Mar": 3, "Apr": 4, "Mai": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Okt": 10, "Nov": 11, "Dez": 12,
}
MONTH_RE = "|".join(GERMAN_MONTHS)
DATE_RE = re.compile(rf"(?P<d>\d{{1,2}})\.\s*(?P<m>{MONTH_RE})\.?(?:\s*(?P<y>\d{{4}}))?\s*(?P<H>\d{{2}}):(?P<M>\d{{2}})")

KNOWN_CONDITIONS = {"Neu", "Brandneu", "Gebraucht", "Defekt", "Nur Ersatzteile"}
EUR_RE = re.compile(r"EUR\s*([\d\.,]+)")
SELLER_RE = re.compile(r"(?P<name>.+?)\s*\((?P<count>[\d\.,]+)\)\s*(?P<pct>[\d\.,]+)%")

API_BASE = f"https://api.telegram.org/bot{TG_BOT_TOKEN}"

state_lock = Lock()  # protect shared state dict across threads

###############################################################################
# ------------------------- LOW‑LEVEL HELPERS --------------------------------
###############################################################################

def ebay_datetime(raw: str) -> datetime:
    m = DATE_RE.search(raw)
    if not m:
        raise ValueError(f"bad date: {raw}")
    day = int(m["d"])
    month = GERMAN_MONTHS[m["m"]]
    year = int(m["y"] or datetime.now().year)
    hour, minute = int(m["H"]), int(m["M"])
    return datetime(year, month, day, hour, minute)


def parse_eur(line: str) -> List[float]:
    return [float(x.replace(".", "").replace(",", ".")) for x in EUR_RE.findall(line)]


def parse_seller(line: str):
    m = SELLER_RE.match(line)
    if m:
        return (
            m["name"].strip(),
            int(m["count"].replace(".", "").replace(",", "")),
            float(m["pct"].replace(",", ".")),
        )

###############################################################################
# ---------------------- CHROME DRIVER / PROXY -------------------------------
###############################################################################

def build_proxy_arg() -> str:
    if PROXY_USER and PROXY_PASS:
        creds = f"{PROXY_USER}:{PROXY_PASS}@"
    else:
        creds = ""
    return f"http://{creds}{PROXY_HOST}:{PROXY_PORT}"


def chrome_driver() -> webdriver.Chrome:
    opts = webdriver.ChromeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1200,800")
    opts.add_argument(f"--proxy-server={build_proxy_arg()}")
    # one scrape → one driver → one proxy connection/IP
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)

###############################################################################
# ---------------------------- PARSER ----------------------------------------
###############################################################################

def parse_card(text: str) -> Dict:
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    if not lines:
        return {}
    first = lines[0]
    for p in PREFIXES_TO_STRIP:
        if first.startswith(p):
            first = first[len(p):].strip()
            break
    out: Dict = {"title": first, "listed_at": None}
    for ln in lines[1:]:
        if any(c in ln for c in KNOWN_CONDITIONS):
            parts = [p.strip() for p in ln.split("|")]
            out["condition"] = parts[0]
            if len(parts) > 1:
                out["seller_type"] = parts[1]
            continue
        if ln.lstrip().startswith("EUR"):
            prices = parse_eur(ln)
            out["price_eur"] = prices[0]
            out["price_raw"] = ln
            continue
        if "Preisvorschlag" in ln:
            out["best_offer"] = True
            continue
        if any(t in ln for t in ("Versand", "Lieferung", "+EUR", "Kostenlos")):
            out["shipping_raw"] = ln
            p = parse_eur(ln)
            out["shipping_eur"] = p[0] if p else 0.0
            continue
        if ln.lower().startswith("aus "):
            out["location"] = ln[4:].strip()
            continue
        if DATE_RE.search(ln):
            out["listed_at"] = ln
            continue
        s = parse_seller(ln)
        if s:
            out["seller"], out["feedback_count"], out["feedback_percent"] = s
    return out

###############################################################################
# ---------------------------- SCRAPER ---------------------------------------
###############################################################################

def scrape_keyword(keyword: str) -> List[Dict]:
    """Return all parsed cards for *keyword* (1–MAX_PAGES)."""
    driver = chrome_driver()
    results: List[Dict] = []
    try:
        url = EBAY_SEARCH_TEMPLATE.format(query=urllib.parse.quote_plus(keyword))
        for page in range(1, MAX_PAGES + 1):
            driver.get(url)
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.XPATH, PAGE_READY_XPATH)))

            idx = 1
            while True:
                try:
                    card = driver.find_element(By.XPATH, XPATH_BASE.format(idx))
                except Exception:
                    break
                parsed = parse_card(card.text)
                parsed["links"] = [a.get_attribute("href") for a in card.find_elements(By.TAG_NAME, "a" ) if a.get_attribute("href")]
                results.append(parsed)
                idx += 1
            try:
                next_btn = driver.find_element(By.CSS_SELECTOR, "a.pagination__next")
                url = next_btn.get_attribute("href")
                if not url:
                    break
            except Exception:
                break
    finally:
        driver.quit()
    return results

###############################################################################
# ----------------------- TELEGRAM HELPERS -----------------------------------
###############################################################################

def tg_fmt(listing: Dict) -> str:
    bo = "🟢" if listing.get("best_offer") else "🔴"
    price = listing.get("price_eur") or listing.get("price_raw") or "-"
    cond  = listing.get("condition") or "-"
    fb    = listing.get("feedback_count") or 0
    ts    = listing.get("listed_at") or "?"
    title = html.escape(listing.get("title") or "(kein Titel)")
    link  = next((l for l in listing.get("links", []) if "/itm/" in l), "")
    link  = html.escape(link)
    return (
        f"<b>Name:</b> {title}\n\n"
        f"<b>Preis:</b> {price}\n"
        f"<b>Preisvorschlag:</b> {bo}\n"
        f"<b>Artikelzustand:</b> {cond}\n"
        f"<b>Bewertungen:</b> {fb}\n"
        f"<b>Veröffentlicht:</b> {ts}\n\n"
        f"<a href=\"{link}\">Öffne Link</a>"
    )


def send_tg(text: str):
    proxies = {"http": build_proxy_arg(), "https": build_proxy_arg()}
    r = requests.post(
        f"{API_BASE}/sendMessage",
        json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": False},
        timeout=30,
        proxies=proxies,
    )
    if not r.ok:
        log.warning("Telegram error %s: %s", r.status_code, r.text[:200])

###############################################################################
# ----------------------------- STATE ----------------------------------------
###############################################################################

def load_state() -> Dict[str, str]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text("utf-8"))
        except Exception:
            pass
    return {}


def save_state(s: Dict[str, str]):
    STATE_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), "utf-8")

state: Dict[str, str] = load_state()  # shared across threads

###############################################################################
# --------------------------- WORKER PER KEYWORD -----------------------------
###############################################################################

def worker(keyword: str):
    global state
    with state_lock:
        last_iso = state.get(keyword)
    first_run = last_iso is None
    last_dt = datetime.fromisoformat(last_iso) if last_iso else datetime(1970, 1, 1)

    try:
        cards = scrape_keyword(keyword)
    except Exception as exc:
        log.error("[%s] scrape failed: %s", keyword, exc)
        return

    newest = last_dt
    fresh: List[tuple[datetime, Dict]] = []
    for c in cards:
        ts_raw = c.get("listed_at")
        if not ts_raw:
            continue
        try:
            dt = ebay_datetime(ts_raw)
        except ValueError:
            continue
        if dt > newest:
            newest = dt
        if not first_run and dt > last_dt:
            fresh.append((dt, c))

    if newest > last_dt:
        with state_lock:
            state[keyword] = newest.isoformat()
            save_state(state)

    for _, listing in sorted(fresh, key=lambda t: t[0]):
        log.info("[%s] new: %s", keyword, listing["title"][:60])
        send_tg(tg_fmt(listing))
        time.sleep(1)

###############################################################################
# -------------------------------- MAIN --------------------------------------
###############################################################################

def main():
    log.info("eBay watcher started with %d keywords", len(KEYWORDS))
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        while True:
            futures = [pool.submit(worker, kw) for kw in KEYWORDS]
            for f in futures:
                f.result()  # propagate exceptions
            log.info("sleeping %ds", POLL_INTERVAL)
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
