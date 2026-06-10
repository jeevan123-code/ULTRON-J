"""End-to-end Phase 4: voice transcript -> scenario -> all-device dispatch."""
from unittest.mock import MagicMock

import pytest

import voice_engine
import multi_device_coordinator as mdc
import scenarios_builtin as sb


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    mdc._reset_for_test()
    for flag in ("ULTRON_PHASE1_ENABLED", "ULTRON_PHASE2A_ENABLED",
                 "ULTRON_PHASE2B_ENABLED", "ULTRON_PHASE3B_ENABLED"):
        monkeypatch.delenv(flag, raising=False)
    yield
    mdc._reset_for_test()


def test_house_party_end_to_end(monkeypatch):
    """house party trigger fans out to all dispatchers."""
    monkeypatch.setenv("ULTRON_PHASE4_ENABLED", "1")
    sb.register_builtins()

    laptop_calls = []
    phone_calls = []
    smart_calls = []
    tv_calls = []

    monkeypatch.setattr(mdc, "_laptop_action",
                        lambda action, args: laptop_calls.append((action, args)) or {"ok": True})
    monkeypatch.setattr(mdc, "_phone_action",
                        lambda action, args: phone_calls.append((action, args)) or {"ok": True})
    monkeypatch.setattr(mdc, "_smart_home_action",
                        lambda action, args: smart_calls.append((action, args)) or {"ok": True})
    monkeypatch.setattr(mdc, "_tv_action",
                        lambda action, args: tv_calls.append((action, args)) or {"ok": True})

    result = voice_engine.parse_voice_command("Jarvis, activate house party protocol now")
    assert result is None  # short-circuited

    assert any(a == "lock" for a, _ in laptop_calls)
    assert any(a == "do_not_disturb" for a, _ in phone_calls)
    assert any(a == "lights" for a, _ in smart_calls)
    assert any(a == "lock_doors" for a, _ in smart_calls)
    assert any(a == "security_view" for a, _ in tv_calls)


def test_bedtime_end_to_end_with_failing_phone(monkeypatch):
    """Bedtime trigger continues even if phone dispatch raises."""
    monkeypatch.setenv("ULTRON_PHASE4_ENABLED", "1")
    sb.register_builtins()

    laptop_calls = []
    smart_calls = []

    def fake_phone(action, args):
        raise RuntimeError("telegram token missing")

    monkeypatch.setattr(mdc, "_laptop_action",
                        lambda action, args: laptop_calls.append((action, args)) or {"ok": True})
    monkeypatch.setattr(mdc, "_phone_action", fake_phone)
    monkeypatch.setattr(mdc, "_smart_home_action",
                        lambda action, args: smart_calls.append((action, args)) or {"ok": True})

    voice_engine.parse_voice_command("bedtime")

    # Laptop and smart-home steps still completed despite phone failure
    assert any(a == "lock" for a, _ in laptop_calls)
    assert any(a == "lights_off" for a, _ in smart_calls)


def test_unknown_trigger_does_not_dispatch(monkeypatch):
    monkeypatch.setenv("ULTRON_PHASE4_ENABLED", "1")
    sb.register_builtins()
    fake_run = MagicMock()
    monkeypatch.setattr(mdc, "run", fake_run)
    voice_engine.parse_voice_command("what is the time")
    fake_run.assert_not_called()
