"""Tests for the GET /api/integrations/health route."""
from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def client():
    import app as app_module
    import auth
    auth.ULTRON_API_KEYS = []
    return app_module.app.test_client()


def test_flag_off_returns_404(monkeypatch, client):
    monkeypatch.delenv("ULTRON_PHASE6_ENABLED", raising=False)
    r = client.get("/api/integrations/health")
    assert r.status_code == 404


def test_flag_on_returns_health_payload(monkeypatch, client):
    monkeypatch.setenv("ULTRON_PHASE6_ENABLED", "1")
    import integration_health as ih
    fake_all = MagicMock(return_value={
        "telegram": {"configured": True, "ok": True, "error": None, "last_checked_ts": 1.0},
        "smart_home": {"configured": False, "ok": False, "error": None, "last_checked_ts": 1.0},
        "newsapi": {"configured": False, "ok": False, "error": None, "last_checked_ts": 1.0},
        "alphavantage": {"configured": False, "ok": False, "error": None, "last_checked_ts": 1.0},
    })
    monkeypatch.setattr(ih, "all", fake_all)
    r = client.get("/api/integrations/health")
    assert r.status_code == 200
    body = r.get_json()
    assert "telegram" in body
    assert body["telegram"]["ok"] is True


def test_route_respects_auth_gate(monkeypatch, client):
    """When ULTRON_API_KEYS is set, the route requires an X-API-Key header."""
    monkeypatch.setenv("ULTRON_PHASE6_ENABLED", "1")
    import auth
    auth.ULTRON_API_KEYS = ["secret"]
    r = client.get("/api/integrations/health",
                   environ_overrides={"REMOTE_ADDR": "192.168.1.99"})
    assert r.status_code in (401, 403)
    auth.ULTRON_API_KEYS = []
