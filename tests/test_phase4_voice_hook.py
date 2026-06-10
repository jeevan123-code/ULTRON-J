"""Tests for Phase 4 voice_engine hook — scenario trigger short-circuits parse."""
from unittest.mock import MagicMock

import pytest

import voice_engine
import multi_device_coordinator as mdc
import scenarios_builtin as sb


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    mdc._reset_for_test()
    # Disable Phase 1/2a/2b/3b to keep parse_voice_command focused on the new hook.
    for flag in ("ULTRON_PHASE1_ENABLED", "ULTRON_PHASE2A_ENABLED",
                 "ULTRON_PHASE2B_ENABLED", "ULTRON_PHASE3B_ENABLED"):
        monkeypatch.delenv(flag, raising=False)
    yield
    mdc._reset_for_test()


def test_flag_off_no_scenario_run(monkeypatch):
    monkeypatch.delenv("ULTRON_PHASE4_ENABLED", raising=False)
    sb.register_builtins()
    fake_run = MagicMock()
    monkeypatch.setattr(mdc, "run", fake_run)
    voice_engine.parse_voice_command("house party")
    fake_run.assert_not_called()


def test_flag_on_matched_trigger_runs_scenario(monkeypatch):
    monkeypatch.setenv("ULTRON_PHASE4_ENABLED", "1")
    sb.register_builtins()
    fake_run = MagicMock(return_value={0: {"ok": True}})
    monkeypatch.setattr(mdc, "run", fake_run)
    result = voice_engine.parse_voice_command("Jarvis, activate house party now")
    fake_run.assert_called_once()
    sc_arg = fake_run.call_args[0][0]
    assert sc_arg.name == "house_party"
    assert result is None  # short-circuit


def test_flag_on_no_match_passes_through(monkeypatch):
    monkeypatch.setenv("ULTRON_PHASE4_ENABLED", "1")
    sb.register_builtins()
    fake_run = MagicMock()
    monkeypatch.setattr(mdc, "run", fake_run)
    # "what is the time" does not match any scenario but DOES match the
    # fast-path TIME regex — confirms the hook didn't intercept.
    result = voice_engine.parse_voice_command("what is the time")
    fake_run.assert_not_called()
    assert result == "TIME"


def test_flag_on_run_exception_does_not_crash(monkeypatch):
    monkeypatch.setenv("ULTRON_PHASE4_ENABLED", "1")
    sb.register_builtins()
    monkeypatch.setattr(mdc, "run", MagicMock(side_effect=RuntimeError("boom")))
    # Should not raise — exceptions in coordinator are swallowed
    voice_engine.parse_voice_command("house party")
