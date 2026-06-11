"""Tests for setup_integrations — CLI driven by patched input + dotenv writes."""
from unittest.mock import MagicMock

import pytest

import setup_integrations as si


@pytest.fixture(autouse=True)
def _tmp_env(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    monkeypatch.setattr(si, "_ENV_PATH", str(env_path))
    yield env_path


def test_upsert_writes_new_key(tmp_path, _tmp_env):
    env_path = _tmp_env
    si._upsert_env_var("TELEGRAM_BOT_TOKEN", "abc123")
    content = env_path.read_text()
    assert "TELEGRAM_BOT_TOKEN=abc123" in content


def test_upsert_replaces_existing_key(_tmp_env):
    env_path = _tmp_env
    env_path.write_text("FOO=bar\nTELEGRAM_BOT_TOKEN=oldvalue\nBAZ=qux\n")
    si._upsert_env_var("TELEGRAM_BOT_TOKEN", "newvalue")
    text = env_path.read_text()
    assert "TELEGRAM_BOT_TOKEN=newvalue" in text
    assert "TELEGRAM_BOT_TOKEN=oldvalue" not in text
    assert "FOO=bar" in text
    assert "BAZ=qux" in text


def test_upsert_backs_up_existing_env(_tmp_env, monkeypatch):
    env_path = _tmp_env
    env_path.write_text("FOO=bar\n")
    si._upsert_env_var("TELEGRAM_BOT_TOKEN", "xxx")
    bak = env_path.with_suffix(".env.bak")
    # backup path is .env.bak in the same dir
    bak_path = env_path.parent / ".env.bak"
    assert bak_path.exists()
    assert "FOO=bar" in bak_path.read_text()


def test_run_all_invokes_each_check(monkeypatch, _tmp_env):
    inputs = iter([
        "tg_token", "tg_chat_id",   # telegram
        "hass_url", "hass_token",   # smart_home
        "", "",                       # newsapi (skip)
        "", "",                       # alphavantage (skip)
    ])
    monkeypatch.setattr("builtins.input", lambda *a, **kw: next(inputs))

    fake_check = MagicMock(return_value={
        "telegram": {"configured": True, "ok": True, "error": None, "last_checked_ts": 1.0},
        "smart_home": {"configured": True, "ok": True, "error": None, "last_checked_ts": 1.0},
        "newsapi": {"configured": False, "ok": False, "error": None, "last_checked_ts": 1.0},
        "alphavantage": {"configured": False, "ok": False, "error": None, "last_checked_ts": 1.0},
    })
    import integration_health as ih
    monkeypatch.setattr(ih, "all", fake_check)

    results = si.run_all(interactive=True)
    fake_check.assert_called_once()
    assert "telegram" in results
    assert results["telegram"]["ok"] is True
