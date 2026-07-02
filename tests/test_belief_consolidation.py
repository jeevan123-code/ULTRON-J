"""Tests for belief_consolidation bridge + mind_tick stage wiring."""
import pytest

import belief_store as bs
import belief_consolidation as bc


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, "_STORE_PATH", str(tmp_path / "beliefs.json"))
    monkeypatch.setattr(bc, "_STATE_PATH", str(tmp_path / "wm.json"))
    bs._reset_for_test()
    bc._reset_for_test()
    yield
    bs._reset_for_test()
    bc._reset_for_test()


def _fake_facts(monkeypatch, facts):
    import personal_facts
    monkeypatch.setattr(personal_facts, "get_all_facts", lambda: facts)


def test_run_consolidates_new_facts(monkeypatch):
    _fake_facts(monkeypatch, [
        {"raw": "prefers dark roast coffee", "category": "preference",
         "ts": "2026-07-01T10:00:00"},
    ])
    s = bc.run()
    assert s["processed_facts"] == 1
    assert s["added"] == 1
    assert any("dark roast" in b.statement for b in bs.all_beliefs())


def test_watermark_prevents_reprocessing(monkeypatch):
    facts = [{"raw": "likes jazz", "category": "preference",
              "ts": "2026-07-01T10:00:00"}]
    _fake_facts(monkeypatch, facts)
    bc.run()
    s2 = bc.run()                      # same facts, nothing newer than watermark
    assert s2["processed_facts"] == 0
    assert s2["reinforced"] == 0       # confidence NOT inflated by re-runs
    assert len(bs.all_beliefs()) == 1


def test_newer_fact_after_watermark_is_processed(monkeypatch):
    _fake_facts(monkeypatch, [{"raw": "uses vim", "category": "tool",
                               "ts": "2026-07-01T10:00:00"}])
    bc.run()
    _fake_facts(monkeypatch, [
        {"raw": "uses vim", "category": "tool", "ts": "2026-07-01T10:00:00"},
        {"raw": "learning rust", "category": "activity", "ts": "2026-07-02T09:00:00"},
    ])
    s = bc.run()
    assert s["processed_facts"] == 1   # only the newer fact
    assert any("rust" in b.statement for b in bs.all_beliefs())


def test_mind_tick_stage_flag_gated(monkeypatch):
    import mind_tick
    monkeypatch.setenv("ULTRON_PHASE16_ENABLED", "0")
    summary = {}
    mind_tick._stage_beliefs(0.0, summary)
    assert summary["beliefs_consolidated"] == 0


def test_mind_tick_stage_runs_when_enabled(monkeypatch):
    import mind_tick
    import belief_consolidation
    monkeypatch.setenv("ULTRON_PHASE16_ENABLED", "1")
    monkeypatch.setattr(belief_consolidation, "run",
                        lambda now=None: {"added": 2, "reinforced": 1})
    summary = {}
    mind_tick._stage_beliefs(0.0, summary)
    assert summary["beliefs_consolidated"] == 3
