"""Tests for the Phase 10 voice_engine hook — plan_builder + chain_executor."""
from unittest.mock import MagicMock

import pytest

import voice_engine
import chain_executor
import plan_builder


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    # Disable every other phase so the Phase 10 hook is the only one exercised
    for flag in ("ULTRON_PHASE1_ENABLED", "ULTRON_PHASE2A_ENABLED",
                 "ULTRON_PHASE2B_ENABLED", "ULTRON_PHASE3B_ENABLED",
                 "ULTRON_PHASE4_ENABLED", "ULTRON_PHASE6_ENABLED"):
        monkeypatch.delenv(flag, raising=False)
    yield


def test_flag_off_does_not_invoke_plan_builder(monkeypatch):
    monkeypatch.delenv("ULTRON_PHASE10_ENABLED", raising=False)
    fake_build = MagicMock()
    monkeypatch.setattr(plan_builder, "build_from_utterance", fake_build)
    voice_engine.parse_voice_command("research GraphQL adoption")
    fake_build.assert_not_called()


def test_flag_on_matching_utterance_runs_chain(monkeypatch):
    monkeypatch.setenv("ULTRON_PHASE10_ENABLED", "1")
    fake_exec = MagicMock(return_value=[{"ok": True, "action": "research"}])
    monkeypatch.setattr(chain_executor, "execute_chain", fake_exec)
    result = voice_engine.parse_voice_command("research GraphQL adoption")
    fake_exec.assert_called_once()
    plan_arg = fake_exec.call_args[0][0]
    assert plan_arg.steps[0]["action"] == "research"
    assert result is None  # short-circuited


def test_flag_on_no_match_falls_through_to_fast_path(monkeypatch):
    monkeypatch.setenv("ULTRON_PHASE10_ENABLED", "1")
    fake_exec = MagicMock()
    monkeypatch.setattr(chain_executor, "execute_chain", fake_exec)
    # "what is the time" -> empty plan from plan_builder; falls through to TIME fast-path
    result = voice_engine.parse_voice_command("what is the time")
    fake_exec.assert_not_called()
    assert result == "TIME"


def test_flag_on_empty_utterance_does_not_crash(monkeypatch):
    monkeypatch.setenv("ULTRON_PHASE10_ENABLED", "1")
    fake_exec = MagicMock()
    monkeypatch.setattr(chain_executor, "execute_chain", fake_exec)
    voice_engine.parse_voice_command("")
    fake_exec.assert_not_called()


def test_exception_in_chain_executor_does_not_propagate(monkeypatch):
    monkeypatch.setenv("ULTRON_PHASE10_ENABLED", "1")
    monkeypatch.setattr(chain_executor, "execute_chain",
                        MagicMock(side_effect=RuntimeError("kaboom")))
    # Must NOT raise — voice pipeline must keep running on transient failures
    voice_engine.parse_voice_command("research X and tell me")
