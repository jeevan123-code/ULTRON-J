"""
autonomous_browser.py — Ultron-J can now browse the web like a human.

Capabilities:
- Navigate to any URL
- Read page content / extract text
- Click buttons, fill forms (Playwright)
- Screenshot any page
- Autonomous multi-step research tasks
- Session persistence (cookies saved between runs)
- JS rendering support for dynamic pages
- Falls back to requests+BS4 if Playwright not installed

BEYOND JARVIS: Ultron can autonomously research, buy, fill forms, log in,
monitor price pages, read news — without you doing anything.
"""

import json
import os
import re
import threading
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests

_BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
BROWSER_LOG_FILE  = os.path.join(_BASE_DIR, "browser_log.json")
BROWSER_CACHE_DIR = os.path.join(_BASE_DIR, "browser_cache")
SESSION_FILE      = os.path.join(_BASE_DIR, "browser_session.json")

os.makedirs(BROWSER_CACHE_DIR, exist_ok=True)

# ── Optional: Playwright for JS rendering ─────────────────────────────────────
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# ── Optional: BeautifulSoup ───────────────────────────────────────────────────
try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

_log_lock = threading.Lock()
_HEADERS  = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

# =============================================================================
# REQUESTS-BASED BROWSER (no JS, fast)
# =============================================================================

class LightBrowser:
    """Fast requests+BS4 browser for static pages."""

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)
        self._load_cookies()

    def _load_cookies(self):
        if os.path.exists(SESSION_FILE):
            try:
                with open(SESSION_FILE) as f:
                    data = json.load(f)
                for cookie in data.get("cookies", []):
                    self._session.cookies.set(cookie["name"], cookie["value"],
                                              domain=cookie.get("domain", ""))
            except Exception:
                pass

    def _save_cookies(self):
        try:
            cookies = [{"name": c.name, "value": c.value, "domain": c.domain}
                       for c in self._session.cookies]
            try:
                from memory import atomic_json_write
                atomic_json_write(SESSION_FILE, {"cookies": cookies, "saved_at": datetime.now().isoformat()})
            except Exception:
                with open(SESSION_FILE, "w") as f:
                    json.dump({"cookies": cookies, "saved_at": datetime.now().isoformat()}, f)
        except Exception:
            pass

    def fetch(self, url: str, timeout: int = 15) -> Dict:
        try:
            r = self._session.get(url, timeout=timeout, allow_redirects=True)
            self._save_cookies()
            content_type = r.headers.get("content-type", "")
            if "html" in content_type and BS4_AVAILABLE:
                soup   = BeautifulSoup(r.text, "html.parser")
                # Remove scripts, styles, nav, footer for cleaner text
                for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                    tag.decompose()
                text  = soup.get_text(separator="\n", strip=True)
                title = soup.title.string if soup.title else url
                links = [urljoin(url, a["href"]) for a in soup.find_all("a", href=True)][:50]
            else:
                text  = r.text[:5000]
                title = url
                links = []

            return {
                "success":    True,
                "url":        r.url,
                "title":      title,
                "text":       text[:8000],
                "links":      links,
                "status":     r.status_code,
                "js_rendered": False,
            }
        except Exception as e:
            return {"success": False, "url": url, "error": str(e)}

    def post(self, url: str, data: dict = None, json_data: dict = None, timeout: int = 15) -> Dict:
        try:
            if json_data:
                r = self._session.post(url, json=json_data, timeout=timeout)
            else:
                r = self._session.post(url, data=data or {}, timeout=timeout)
            self._save_cookies()
            return {"success": True, "status": r.status_code, "text": r.text[:5000]}
        except Exception as e:
            return {"success": False, "error": str(e)}


# =============================================================================
# PLAYWRIGHT BROWSER (full JS, screenshots, clicks)
# =============================================================================

class FullBrowser:
    """Playwright browser — full JS rendering, clicks, forms, screenshots."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._pw      = None
        self._browser = None
        self._context = None
        self._page    = None
        self._started = False

    def start(self):
        if self._started:
            return
        self._pw      = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(
            user_agent=_HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 800},
        )
        # Load saved cookies
        if os.path.exists(SESSION_FILE):
            try:
                with open(SESSION_FILE) as f:
                    data = json.load(f)
                self._context.add_cookies(data.get("cookies", []))
            except Exception:
                pass
        self._page    = self._context.new_page()
        self._started = True

    def stop(self):
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._started = False

    def _save_cookies(self):
        try:
            cookies = self._context.cookies()
            try:
                from memory import atomic_json_write
                atomic_json_write(SESSION_FILE, {"cookies": cookies, "saved_at": datetime.now().isoformat()})
            except Exception:
                with open(SESSION_FILE, "w") as f:
                    json.dump({"cookies": cookies, "saved_at": datetime.now().isoformat()}, f)
        except Exception:
            pass

    def navigate(self, url: str, wait_for: str = "networkidle", timeout: int = 20000) -> Dict:
        try:
            self._page.goto(url, wait_until=wait_for, timeout=timeout)
            self._save_cookies()
            title = self._page.title()
            text  = self._page.inner_text("body")[:8000]
            links = self._page.eval_on_selector_all(
                "a[href]", "els => els.map(e => e.href).slice(0, 50)"
            )
            return {
                "success":    True,
                "url":        self._page.url,
                "title":      title,
                "text":       text,
                "links":      links,
                "js_rendered": True,
            }
        except Exception as e:
            return {"success": False, "url": url, "error": str(e)}

    def click(self, selector: str, timeout: int = 5000) -> Dict:
        try:
            self._page.click(selector, timeout=timeout)
            time.sleep(1)
            return {"success": True, "action": f"clicked '{selector}'"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def fill(self, selector: str, value: str) -> Dict:
        try:
            self._page.fill(selector, value)
            return {"success": True, "action": f"filled '{selector}' with value"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def screenshot(self, save_path: str = None) -> Dict:
        try:
            if not save_path:
                save_path = os.path.join(BROWSER_CACHE_DIR,
                                         f"screenshot_{int(time.time())}.png")
            self._page.screenshot(path=save_path, full_page=False)
            return {"success": True, "path": save_path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_text(self) -> str:
        try:
            return self._page.inner_text("body")[:8000]
        except Exception:
            return ""


# =============================================================================
# AUTONOMOUS RESEARCH AGENT
# =============================================================================

class ResearchAgent:
    """
    Autonomous multi-step web researcher.
    Given a query, it searches → reads top results → synthesizes an answer.
    """

    SEARCH_ENGINES = [
        "https://search.brave.com/search?q={q}&source=web",
        "https://html.duckduckgo.com/html/?q={q}",
    ]

    def __init__(self):
        self._light = LightBrowser()
        self._full  = FullBrowser() if PLAYWRIGHT_AVAILABLE else None

    def search_and_read(self, query: str, max_pages: int = 3,
                        use_js: bool = False) -> Dict:
        """Search query, read top N results, return combined text."""
        results = []
        links_to_read = []

        # Try DuckDuckGo first
        try:
            ddg_url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}"
            page = self._light.fetch(ddg_url)
            if page["success"] and BS4_AVAILABLE:
                soup  = BeautifulSoup(page["text"], "html.parser")
                for a in soup.find_all("a", class_="result__a")[:max_pages]:
                    href = a.get("href", "")
                    if href.startswith("http"):
                        links_to_read.append(href)
        except Exception:
            pass

        # Read each result page
        for url in links_to_read[:max_pages]:
            try:
                if use_js and self._full:
                    if not self._full._started:
                        self._full.start()
                    res = self._full.navigate(url)
                else:
                    res = self._light.fetch(url)

                if res["success"]:
                    results.append({
                        "url":   res["url"],
                        "title": res.get("title", url),
                        "text":  res["text"][:3000],
                    })
            except Exception as e:
                results.append({"url": url, "error": str(e)})

        _log({"action": "research", "query": query, "pages_read": len(results)})
        return {
            "success": True,
            "query":   query,
            "results": results,
            "summary": _combine_results(results),
        }

    def monitor_page(self, url: str, check_for: str, interval: int = 300,
                     callback=None) -> threading.Thread:
        """
        Background thread: check a page every N seconds.
        If check_for text appears → call callback(url, text).
        Useful for price alerts, stock changes, job listings.
        """
        def _loop():
            last_text = ""
            while True:
                try:
                    res = self._light.fetch(url)
                    if res["success"]:
                        text = res["text"]
                        if check_for.lower() in text.lower() and text != last_text:
                            last_text = text
                            _log({"action": "page_alert", "url": url, "trigger": check_for})
                            if callback:
                                callback(url, text)
                except Exception:
                    pass
                time.sleep(interval)

        t = threading.Thread(target=_loop, daemon=True)
        t.start()
        return t

    def fill_and_submit(self, url: str, fields: Dict[str, str],
                        submit_selector: str = "button[type=submit]") -> Dict:
        """Fill a form and submit it (Playwright required)."""
        if not PLAYWRIGHT_AVAILABLE:
            return {"success": False, "error": "Playwright not installed. pip install playwright"}
        if not self._full._started:
            self._full.start()
        res = self._full.navigate(url)
        if not res["success"]:
            return res
        for selector, value in fields.items():
            fill_res = self._full.fill(selector, value)
            if not fill_res["success"]:
                return fill_res
        return self._full.click(submit_selector)


def _combine_results(results: list) -> str:
    """Combine page texts into a single summary block."""
    parts = []
    for i, r in enumerate(results, 1):
        if "text" in r:
            parts.append(f"[Source {i}: {r.get('title', r['url'])}]\n{r['text'][:1500]}")
    return "\n\n---\n\n".join(parts)[:6000]


# =============================================================================
# CONVENIENCE FUNCTIONS (called from app.py / agent_routes.py)
# =============================================================================

_light_browser  = LightBrowser()
_research_agent = ResearchAgent()


def browse(url: str, js: bool = False) -> Dict:
    """Simple fetch a URL."""
    _log({"action": "browse", "url": url, "js": js})
    if js and PLAYWRIGHT_AVAILABLE:
        fb = FullBrowser()
        fb.start()
        res = fb.navigate(url)
        fb.stop()
        return res
    return _light_browser.fetch(url)


def research(query: str, max_pages: int = 3) -> Dict:
    """Search + read + summarize."""
    return _research_agent.search_and_read(query, max_pages=max_pages)


def screenshot_url(url: str) -> Dict:
    """Screenshot a URL (Playwright required)."""
    if not PLAYWRIGHT_AVAILABLE:
        return {"success": False, "error": "Install playwright: pip install playwright && playwright install chromium"}
    fb = FullBrowser()
    fb.start()
    fb.navigate(url)
    res = fb.screenshot()
    fb.stop()
    return res


def watch_page(url: str, keyword: str, interval: int = 300, callback=None) -> Dict:
    """Start monitoring a page for a keyword."""
    t = _research_agent.monitor_page(url, keyword, interval, callback)
    return {"success": True, "monitoring": url, "keyword": keyword, "interval_s": interval}


def get_browser_log(limit: int = 50) -> list:
    try:
        if os.path.exists(BROWSER_LOG_FILE):
            with open(BROWSER_LOG_FILE) as f:
                log = json.load(f)
            return log[-limit:]
    except Exception:
        pass
    return []


def _log(data: dict):
    with _log_lock:
        try:
            log = []
            if os.path.exists(BROWSER_LOG_FILE):
                with open(BROWSER_LOG_FILE) as f:
                    log = json.load(f)
            log.append({"ts": datetime.now().isoformat(), **data})
            if len(log) > 300:
                log = log[-300:]
            with open(BROWSER_LOG_FILE, "w") as f:
                json.dump(log, f, indent=2)
        except Exception:
            pass
