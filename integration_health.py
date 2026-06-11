"""Phase 6 integration health checks.

Read-only probes for Telegram, Home Assistant, NewsAPI and Alpha Vantage.
Each returns a uniform dict so a future settings UI / curl user can read
configured/reachable state without touching the integration internals.
"""
import os
import time
from typing import Any, Dict, Optional


_CHECK_RESULT_KEYS = ("configured", "ok", "error", "last_checked_ts")


def _now() -> float:
    return time.time()


def _result(configured: bool, ok: bool, error: Optional[str] = None) -> Dict[str, Any]:
    return {
        "configured": bool(configured),
        "ok": bool(ok),
        "error": error,
        "last_checked_ts": _now(),
    }


# ---- Telegram ----

def _telegram_status() -> Dict[str, Any]:
    try:
        import mobile_bridge
        return mobile_bridge.get_status()
    except Exception:
        return {"enabled": False, "running": False, "chat_id_set": False}


def _telegram_get_me() -> Dict[str, Any]:
    try:
        import mobile_bridge
        return mobile_bridge._tg("getMe", {})
    except Exception as e:
        raise


def check_telegram() -> Dict[str, Any]:
    status = _telegram_status()
    if not status.get("enabled"):
        return _result(configured=False, ok=False)
    try:
        info = _telegram_get_me()
        ok = bool(info and (info.get("ok") or info.get("result")))
        return _result(configured=True, ok=ok)
    except Exception as e:
        return _result(configured=True, ok=False, error=repr(e))


# ---- Home Assistant ----

def _smart_home_status() -> Dict[str, Any]:
    try:
        import smart_home
        sh = smart_home.get_smart_home()
        return sh.get_status()
    except Exception:
        return {"configured": False, "hass_available": False, "hass_url": ""}


def check_smart_home() -> Dict[str, Any]:
    status = _smart_home_status()
    if not status.get("configured"):
        return _result(configured=False, ok=False)
    return _result(
        configured=True,
        ok=bool(status.get("hass_available")),
        error=None if status.get("hass_available") else "hass_unreachable",
    )


# ---- NewsAPI ----

def _newsapi_ping(api_key: str) -> Dict[str, Any]:
    import requests
    response = requests.get(
        "https://newsapi.org/v2/top-headlines",
        params={"country": "us", "apiKey": api_key, "pageSize": 1},
        timeout=10,
    )
    return response.json() if response.status_code == 200 else {"status": "error"}


def check_newsapi(api_key: Optional[str] = None) -> Dict[str, Any]:
    key = api_key if api_key is not None else os.environ.get("NEWSAPI_KEY", "")
    if not key:
        return _result(configured=False, ok=False)
    try:
        info = _newsapi_ping(key)
        return _result(configured=True, ok=(info.get("status") == "ok"))
    except Exception as e:
        return _result(configured=True, ok=False, error=repr(e))


# ---- Alpha Vantage ----

def _alphavantage_ping(api_key: str) -> Dict[str, Any]:
    import requests
    response = requests.get(
        "https://www.alphavantage.co/query",
        params={"function": "GLOBAL_QUOTE", "symbol": "AAPL", "apikey": api_key},
        timeout=10,
    )
    return response.json() if response.status_code == 200 else {"error": "non-200"}


def check_alphavantage(api_key: Optional[str] = None) -> Dict[str, Any]:
    key = api_key if api_key is not None else os.environ.get("ALPHAVANTAGE_KEY", "")
    if not key:
        return _result(configured=False, ok=False)
    try:
        info = _alphavantage_ping(key)
        ok = "Global Quote" in info
        return _result(configured=True, ok=ok)
    except Exception as e:
        return _result(configured=True, ok=False, error=repr(e))


def all() -> Dict[str, Dict[str, Any]]:
    """Run every integration check and return a name → result mapping."""
    return {
        "telegram": check_telegram(),
        "smart_home": check_smart_home(),
        "newsapi": check_newsapi(),
        "alphavantage": check_alphavantage(),
    }
