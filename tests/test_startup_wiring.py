"""Three features that look wired but are silently empty.

- world_event_poller is the ONLY writer to worldfeed_store, and nothing ever
  started it. Three consumers read that store — mind_tick._stage_world_alerts,
  briefing_builder, voice_engine — so all three have been reading an empty
  table forever. The world-pulse feature has been a no-op, not a bug anyone
  would see.
- scenarios_builtin.register_builtins() is the only thing that populates the
  Phase 4 scenario registry. Nothing called it, so "house party" and friends
  had zero scenarios to run.
- auto_research_loop.start() exists with no caller.

This hook is where app.py wires them, mirroring phase18_vision_hook.
"""
import pytest

import startup_wiring as sw


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("ULTRON_WORLD_EVENTS_ENABLED", raising=False)
    monkeypatch.delenv("ULTRON_AUTO_RESEARCH_ENABLED", raising=False)
    monkeypatch.delenv("ULTRON_WORLD_FEEDS", raising=False)
    yield


# ── scenarios ────────────────────────────────────────────────────────────────
def test_scenarios_are_registered():
    import multi_device_coordinator as mdc
    mdc._reset_for_test() if hasattr(mdc, "_reset_for_test") else None
    n = sw.register_scenarios()
    assert n > 0, "the Phase 4 registry was left empty"


def test_registering_scenarios_twice_is_safe():
    assert sw.register_scenarios() == sw.register_scenarios()


def test_scenario_registration_failure_does_not_raise(monkeypatch):
    import scenarios_builtin
    monkeypatch.setattr(scenarios_builtin, "register_builtins",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert sw.register_scenarios() == 0


# ── world events ─────────────────────────────────────────────────────────────
def test_world_events_off_by_default(monkeypatch):
    started = []
    monkeypatch.setattr(sw, "_start_poller", lambda: started.append(True))
    assert sw.start_world_events() is False
    assert started == []


def test_world_events_registers_sources_and_starts(monkeypatch):
    monkeypatch.setenv("ULTRON_WORLD_EVENTS_ENABLED", "1")
    registered, started = [], []
    monkeypatch.setattr(sw, "_register_source",
                        lambda name, url: registered.append((name, url)))
    monkeypatch.setattr(sw, "_start_poller", lambda: started.append(True))
    assert sw.start_world_events() is True
    assert registered, "no feeds registered — the store would stay empty"
    assert started == [True]


def test_feed_list_is_configurable_not_hardcoded(monkeypatch):
    monkeypatch.setenv("ULTRON_WORLD_EVENTS_ENABLED", "1")
    monkeypatch.setenv("ULTRON_WORLD_FEEDS", "https://example.com/a.xml,https://example.com/b.xml")
    registered = []
    monkeypatch.setattr(sw, "_register_source", lambda n, u: registered.append(u))
    monkeypatch.setattr(sw, "_start_poller", lambda: None)
    sw.start_world_events()
    assert registered == ["https://example.com/a.xml", "https://example.com/b.xml"]


def test_blank_feed_entries_are_ignored(monkeypatch):
    monkeypatch.setenv("ULTRON_WORLD_EVENTS_ENABLED", "1")
    monkeypatch.setenv("ULTRON_WORLD_FEEDS", "https://a.xml, ,,https://b.xml")
    registered = []
    monkeypatch.setattr(sw, "_register_source", lambda n, u: registered.append(u))
    monkeypatch.setattr(sw, "_start_poller", lambda: None)
    sw.start_world_events()
    assert registered == ["https://a.xml", "https://b.xml"]


def test_world_events_failure_degrades(monkeypatch):
    monkeypatch.setenv("ULTRON_WORLD_EVENTS_ENABLED", "1")
    monkeypatch.setattr(sw, "_start_poller",
                        lambda: (_ for _ in ()).throw(RuntimeError("no feedparser")))
    monkeypatch.setattr(sw, "_register_source", lambda n, u: None)
    assert sw.start_world_events() is False  # degraded, not crashed


# ── auto research ────────────────────────────────────────────────────────────
def test_auto_research_off_by_default(monkeypatch):
    monkeypatch.setattr(sw, "_start_auto_research", lambda: True)
    assert sw.start_auto_research() is False


def test_auto_research_starts_when_enabled(monkeypatch):
    monkeypatch.setenv("ULTRON_AUTO_RESEARCH_ENABLED", "1")
    monkeypatch.setattr(sw, "_start_auto_research", lambda: True)
    assert sw.start_auto_research() is True


# ── the entry point app.py calls ─────────────────────────────────────────────
def test_wire_all_reports_what_it_did(monkeypatch):
    monkeypatch.setattr(sw, "_start_poller", lambda: None)
    monkeypatch.setattr(sw, "_register_source", lambda n, u: None)
    monkeypatch.setattr(sw, "_start_auto_research", lambda: True)
    out = sw.wire_all()
    assert set(out) == {"scenarios", "world_events", "auto_research"}


def test_wire_all_never_raises(monkeypatch):
    for name in ("register_scenarios", "start_world_events", "start_auto_research"):
        monkeypatch.setattr(sw, name,
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    sw.wire_all()  # must not raise — startup can never be blocked by this
