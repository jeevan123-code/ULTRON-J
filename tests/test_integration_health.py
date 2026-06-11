"""Tests for integration_health — Telegram / HA / NewsAPI / AlphaVantage checks."""
from unittest.mock import MagicMock

import pytest

import integration_health as ih


# ---- Telegram ----

def test_telegram_missing_token_returns_not_configured(monkeypatch):
    monkeypatch.setattr(ih, "_telegram_status", lambda: {
        "enabled": False, "running": False, "chat_id_set": False,
    })
    out = ih.check_telegram()
    assert out["configured"] is False
    assert out["ok"] is False


def test_telegram_configured_and_get_me_ok(monkeypatch):
    monkeypatch.setattr(ih, "_telegram_status", lambda: {
        "enabled": True, "running": True, "chat_id_set": True,
    })
    monkeypatch.setattr(ih, "_telegram_get_me", lambda: {"ok": True})
    out = ih.check_telegram()
    assert out["configured"] is True
    assert out["ok"] is True
    assert out["error"] is None


def test_telegram_configured_but_get_me_fails(monkeypatch):
    monkeypatch.setattr(ih, "_telegram_status", lambda: {
        "enabled": True, "running": True, "chat_id_set": True,
    })
    monkeypatch.setattr(ih, "_telegram_get_me",
                        lambda: (_ for _ in ()).throw(RuntimeError("bad token")))
    out = ih.check_telegram()
    assert out["configured"] is True
    assert out["ok"] is False
    assert "bad token" in out["error"]


# ---- smart_home ----

def test_smart_home_not_configured(monkeypatch):
    monkeypatch.setattr(ih, "_smart_home_status", lambda: {
        "configured": False, "hass_available": False, "hass_url": "",
    })
    out = ih.check_smart_home()
    assert out["configured"] is False
    assert out["ok"] is False


def test_smart_home_configured_and_reachable(monkeypatch):
    monkeypatch.setattr(ih, "_smart_home_status", lambda: {
        "configured": True, "hass_available": True, "hass_url": "http://homeassistant.local",
    })
    out = ih.check_smart_home()
    assert out["configured"] is True
    assert out["ok"] is True


# ---- NewsAPI ----

def test_newsapi_missing_key():
    out = ih.check_newsapi(api_key="")
    assert out["configured"] is False
    assert out["ok"] is False


def test_newsapi_present_key(monkeypatch):
    monkeypatch.setattr(ih, "_newsapi_ping", lambda key: {"status": "ok"})
    out = ih.check_newsapi(api_key="abc")
    assert out["configured"] is True
    assert out["ok"] is True


# ---- all() ----

def test_all_aggregates_every_check(monkeypatch):
    monkeypatch.setattr(ih, "check_telegram",
                        lambda: {"configured": True, "ok": True, "error": None, "last_checked_ts": 1.0})
    monkeypatch.setattr(ih, "check_smart_home",
                        lambda: {"configured": False, "ok": False, "error": "no token", "last_checked_ts": 1.0})
    monkeypatch.setattr(ih, "check_newsapi",
                        lambda api_key=None: {"configured": False, "ok": False, "error": None, "last_checked_ts": 1.0})
    monkeypatch.setattr(ih, "check_alphavantage",
                        lambda api_key=None: {"configured": False, "ok": False, "error": None, "last_checked_ts": 1.0})
    out = ih.all()
    assert {"telegram", "smart_home", "newsapi", "alphavantage"} == set(out.keys())
    assert out["telegram"]["ok"] is True
    assert out["smart_home"]["ok"] is False
