"""Tests for the Phase 13 wiring: voice_engine Phase 10 hook now uses strict_validation."""
from unittest.mock import MagicMock

import pytest

import voice_engine
import chain_executor


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    for flag in ("ULTRON_PHASE1_ENABLED", "ULTRON_PHASE2A_ENABLED",
                 "ULTRON_PHASE2B_ENABLED", "ULTRON_PHASE3B_ENABLED",
                 "ULTRON_PHASE4_ENABLED", "ULTRON_PHASE6_ENABLED"):
        monkeypatch.delenv(flag, raising=False)
    yield


def test_voice_hook_calls_execute_chain_with_strict_validation(monkeypatch):
    monkeypatch.setenv("ULTRON_PHASE10_ENABLED", "1")
    fake_exec = MagicMock(return_value=[{"ok": True}])
    monkeypatch.setattr(chain_executor, "execute_chain", fake_exec)
    voice_engine.parse_voice_command("research GraphQL adoption")
    fake_exec.assert_called_once()
    # The hook MUST pass strict_validation=True
    _, kwargs = fake_exec.call_args
    assert kwargs.get("strict_validation") is True


def test_voice_hook_short_circuits_when_validation_fails(monkeypatch):
    """An invalid plan returned by plan_builder is blocked by strict mode.

    plan_builder won't normally produce invalid plans, but the test
    forces the failure mode by monkeypatching the validator output.
    """
    monkeypatch.setenv("ULTRON_PHASE10_ENABLED", "1")
    # Real execute_chain runs but strict_validation will block on a bad plan
    import plan_builder

    def _bad_plan(_utterance):
        from intent_types import ExecutionPlan
        # research without topic -> missing required arg
        return ExecutionPlan(
            steps=[{"action": "research", "args": {}}],
            pre_checks=[], rationale="test",
        )
    monkeypatch.setattr(plan_builder, "build_from_utterance", _bad_plan)

    fake_research = MagicMock()
    monkeypatch.setattr(chain_executor, "_dispatch_research", fake_research)
    voice_engine.parse_voice_command("research")
    fake_research.assert_not_called()
