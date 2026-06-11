"""Phase 6 source adapters for the world-event poller.

Each adapter exposes `fetch() -> List[WorldEvent]`. All HTTP / feed
parsing goes through module-level seams (`_http_get`, `_feedparser_parse`)
so tests can stub without touching the network.

Errors from one source never abort the rest; every adapter catches its
own exceptions and returns `[]` on failure.
"""
import time
from typing import Any, Dict, List, Optional

from world_event_types import WorldEvent


def _http_get(url: str, params: Optional[Dict[str, Any]] = None,
              headers: Optional[Dict[str, str]] = None,
              timeout: float = 10.0):
    import requests
    return requests.get(url, params=params, headers=headers, timeout=timeout)


def _feedparser_parse(url: str):
    import feedparser
    return feedparser.parse(url)


def _safe_log(msg: str) -> None:
    try:
        with open("ultron_log.txt", "a") as f:
            f.write(f"[phase6][source] {msg}\n")
    except Exception:
        pass


def _parsed_iso8601(s: str) -> float:
    """Best-effort ISO-8601 parser. Returns time.time() if anything fails."""
    if not s:
        return time.time()
    try:
        from datetime import datetime, timezone
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s).astimezone(timezone.utc).timestamp()
    except Exception:
        return time.time()


def _struct_time_to_ts(st) -> float:
    if not st:
        return time.time()
    try:
        import calendar
        return calendar.timegm(st)
    except Exception:
        return time.time()


class RSSSource:
    """Pluggable RSS feed adapter via `feedparser`."""

    def __init__(self, feed_url: str):
        self.feed_url = feed_url

    def fetch(self) -> List[WorldEvent]:
        try:
            parsed = _feedparser_parse(self.feed_url)
        except Exception as e:
            _safe_log(f"rss {self.feed_url} failed: {e!r}")
            return []

        events: List[WorldEvent] = []
        for entry in getattr(parsed, "entries", []) or []:
            title = (getattr(entry, "title", "") or "").strip()
            link = (getattr(entry, "link", "") or "").strip()
            if not title and not link:
                continue
            summary = (getattr(entry, "summary", "") or "").strip()
            ts = _struct_time_to_ts(getattr(entry, "published_parsed", None))
            events.append(WorldEvent(
                title=title, summary=summary, url=link,
                source=f"rss:{self.feed_url}", ts=ts,
            ))
        return events


class NewsAPISource:
    """NewsAPI.org top-headlines adapter."""

    BASE_URL = "https://newsapi.org/v2/top-headlines"

    def __init__(self, api_key: str, country: str = "us"):
        self.api_key = api_key
        self.country = country

    def fetch(self) -> List[WorldEvent]:
        if not self.api_key:
            return []
        try:
            response = _http_get(
                self.BASE_URL,
                params={"country": self.country, "apiKey": self.api_key, "pageSize": 50},
                timeout=10.0,
            )
        except Exception as e:
            _safe_log(f"newsapi failed: {e!r}")
            return []
        if getattr(response, "status_code", 0) != 200:
            return []
        try:
            data = response.json()
        except Exception:
            return []
        if data.get("status") != "ok":
            return []
        events: List[WorldEvent] = []
        for art in data.get("articles", []) or []:
            title = (art.get("title") or "").strip()
            if not title:
                continue
            events.append(WorldEvent(
                title=title,
                summary=(art.get("description") or "").strip(),
                url=art.get("url") or "",
                source="newsapi",
                ts=_parsed_iso8601(art.get("publishedAt", "")),
            ))
        return events


class AlphaVantageSource:
    """Alpha Vantage Global Quote adapter — one event per ticker per fetch."""

    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(self, api_key: str, tickers: List[str]):
        self.api_key = api_key
        self.tickers = list(tickers or [])

    def fetch(self) -> List[WorldEvent]:
        if not self.api_key or not self.tickers:
            return []
        events: List[WorldEvent] = []
        for ticker in self.tickers:
            try:
                response = _http_get(
                    self.BASE_URL,
                    params={
                        "function": "GLOBAL_QUOTE",
                        "symbol": ticker,
                        "apikey": self.api_key,
                    },
                    timeout=10.0,
                )
            except Exception as e:
                _safe_log(f"alphavantage {ticker} failed: {e!r}")
                continue
            if getattr(response, "status_code", 0) != 200:
                continue
            try:
                data = response.json()
            except Exception:
                continue
            quote = data.get("Global Quote") or {}
            if not quote:
                continue
            symbol = quote.get("01. symbol", ticker)
            price = quote.get("05. price", "")
            change_pct = quote.get("10. change percent", "")
            events.append(WorldEvent(
                title=f"{symbol} at {price} ({change_pct})",
                summary=f"Latest quote: price={price}, change={change_pct}",
                url=f"https://finance.yahoo.com/quote/{symbol}",
                source="alphavantage",
                ts=time.time(),
                tickers=[symbol],
            ))
        return events
