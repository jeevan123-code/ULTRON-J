"""Startup wiring for three features that were built but never connected.

Each of these looked wired from the outside and was silently doing nothing:

- `world_event_poller` is the ONLY writer to `worldfeed_store`, and nothing
  ever started it. Three consumers read that store — `mind_tick`'s world-alert
  stage, `briefing_builder`, and `voice_engine` — so all three have been
  reading a permanently empty table. Not an error anywhere; just no world pulse.
- `scenarios_builtin.register_builtins()` is the only thing that fills the
  Phase 4 scenario registry. With no caller, "house party" and the other
  scenarios had nothing registered to run.
- `auto_research_loop.start()` had no caller at all.

app.py calls `wire_all()` once at boot. Scenario registration is unconditional
(it only fills an in-memory registry). Anything that polls the network stays
behind a flag, default OFF.
"""
import os
from typing import Any, Dict

# Reputable keyless RSS feeds. Override with ULTRON_WORLD_FEEDS rather than
# editing this — the default exists so the feature is not dead on arrival.
DEFAULT_FEEDS = (
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://feeds.npr.org/1001/rss.xml",
    "https://www.theguardian.com/world/rss",
)
POLL_INTERVAL_SECONDS = 900.0


def _safe_log(msg: str) -> None:
    try:
        print(f"[startup_wiring] {msg}")
    except Exception:
        pass


# ── seams (mocked in tests) ──────────────────────────────────────────────────
def _register_source(name: str, feed_url: str) -> None:
    import world_event_poller
    from world_event_sources import RSSSource
    world_event_poller.register(name, RSSSource(feed_url), POLL_INTERVAL_SECONDS)


def _start_poller() -> None:
    import world_event_poller
    world_event_poller.start()


def _start_auto_research() -> bool:
    import auto_research_loop
    return bool(auto_research_loop.start())


# ── scenarios ────────────────────────────────────────────────────────────────
def register_scenarios() -> int:
    """Fill the Phase 4 scenario registry. Returns how many are registered."""
    try:
        import scenarios_builtin
        import multi_device_coordinator as mdc
        scenarios_builtin.register_builtins()
        # _snapshot_for_test is the only read accessor the coordinator exposes.
        return len(mdc._snapshot_for_test())
    except Exception as e:
        _safe_log(f"scenario registration failed: {e!r}")
        return 0


# ── world events ─────────────────────────────────────────────────────────────
def _feeds() -> list:
    raw = os.environ.get("ULTRON_WORLD_FEEDS", "")
    if raw.strip():
        return [u.strip() for u in raw.split(",") if u.strip()]
    return list(DEFAULT_FEEDS)


def start_world_events() -> bool:
    """Start polling world feeds into worldfeed_store. Off unless enabled."""
    if os.environ.get("ULTRON_WORLD_EVENTS_ENABLED", "0") != "1":
        return False
    try:
        for url in _feeds():
            _register_source(f"rss:{url}", url)
        _start_poller()
        _safe_log(f"world event poller started ({len(_feeds())} feeds)")
        return True
    except Exception as e:
        # feedparser missing, network down, bad feed — degrade, never block boot.
        _safe_log(f"world event poller unavailable: {e!r}")
        return False


# ── auto research ────────────────────────────────────────────────────────────
def start_auto_research() -> bool:
    """Start the background auto-research loop. Off unless enabled."""
    if os.environ.get("ULTRON_AUTO_RESEARCH_ENABLED", "0") != "1":
        return False
    try:
        return bool(_start_auto_research())
    except Exception as e:
        _safe_log(f"auto research loop unavailable: {e!r}")
        return False


# ── entry point ──────────────────────────────────────────────────────────────
def wire_all() -> Dict[str, Any]:
    """Wire everything once at boot. Never raises — startup comes first."""
    out: Dict[str, Any] = {"scenarios": 0, "world_events": False,
                           "auto_research": False}
    for key, fn in (("scenarios", register_scenarios),
                    ("world_events", start_world_events),
                    ("auto_research", start_auto_research)):
        try:
            out[key] = fn()
        except Exception as e:
            _safe_log(f"{key} wiring failed: {e!r}")
    return out
