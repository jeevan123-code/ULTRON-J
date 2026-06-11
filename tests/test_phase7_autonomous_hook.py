"""Tests for the Phase 7 hook inside autonomous_loop's cycle.

We don't run the full loop (it's a long-running thread). Instead we test
the small helper `_phase7_unified_tick(obs)` that the cycle delegates to.
"""
from unittest.mock import MagicMock

import pytest

import autonomous_loop


def test_helper_runs_mind_tick_when_flag_on(monkeypatch):
    monkeypatch.setenv("ULTRON_PHASE7_ENABLED", "1")
    fake_tick = MagicMock(return_value={
        "briefings_dispatched": 0, "world_alerts": 0, "improvement_offers": 0,
    })
    monkeypatch.setattr("mind_tick.tick", fake_tick)
    obs = {"hour": 8}
    autonomous_loop._phase7_unified_tick(obs)
    fake_tick.assert_called_once()
    assert obs.get("phase7_summary") is not None


def test_helper_noop_when_flag_off(monkeypatch):
    monkeypatch.delenv("ULTRON_PHASE7_ENABLED", raising=False)
    fake_tick = MagicMock()
    monkeypatch.setattr("mind_tick.tick", fake_tick)
    obs = {"hour": 8}
    autonomous_loop._phase7_unified_tick(obs)
    fake_tick.assert_not_called()
    assert "phase7_summary" not in obs


def test_helper_swallows_exception(monkeypatch):
    monkeypatch.setenv("ULTRON_PHASE7_ENABLED", "1")
    monkeypatch.setattr("mind_tick.tick",
                        MagicMock(side_effect=RuntimeError("boom")))
    obs = {"hour": 8}
    # Must not raise — autonomous_loop's cycle would crash otherwise
    autonomous_loop._phase7_unified_tick(obs)
    assert obs.get("phase7_error") is not None
