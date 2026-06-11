"""Phase 6 world-event poller — orchestrates source adapters.

Holds a registry of named sources. Each `_tick_for_test(name)` fetches
that source, scores its events through `interest_matcher`, and writes
matched events into `worldfeed_store`. A background thread is provided
for production use, but no test depends on it — every code path is
reachable via the `_tick_for_test` / `_tick_all_for_test` seams.
"""
import threading
import time
from typing import Any, Dict, List

import interest_matcher
import worldfeed_store
from world_event_types import WorldEvent


_lock = threading.RLock()
_sources: Dict[str, Any] = {}
_intervals: Dict[str, float] = {}
_last_tick: Dict[str, float] = {}
_running = False
_thread: threading.Thread = None  # type: ignore


def _now() -> float:
    return time.time()


def _safe_log(msg: str) -> None:
    try:
        with open("ultron_log.txt", "a") as f:
            f.write(f"[phase6][poller] {msg}\n")
    except Exception:
        pass


def _reset_for_test() -> None:
    global _running
    with _lock:
        _sources.clear()
        _intervals.clear()
        _last_tick.clear()
        _running = False


def register(name: str, source: Any, interval_seconds: float = 900.0) -> None:
    """Register or replace a source. Tests pass a MagicMock with .fetch()."""
    with _lock:
        _sources[name] = source
        _intervals[name] = float(interval_seconds)


def _dispatch_one(name: str) -> None:
    src = _sources.get(name)
    if src is None:
        return
    try:
        events: List[WorldEvent] = src.fetch() or []
    except Exception as e:
        _safe_log(f"{name} fetch failed: {e!r}")
        return
    if not events:
        return
    try:
        interests = interest_matcher.load_interests()
        matched = interest_matcher.match(events, interests)
    except Exception as e:
        _safe_log(f"{name} match failed: {e!r}")
        return
    for ev in matched:
        try:
            worldfeed_store.record(ev)
        except Exception as e:
            _safe_log(f"{name} record failed: {e!r}")


def _tick_for_test(name: str) -> None:
    """Force one source tick — used by tests."""
    _dispatch_one(name)


def _tick_all_for_test() -> None:
    """Force every registered source to tick — used by tests."""
    for name in list(_sources.keys()):
        _dispatch_one(name)


def _background_loop() -> None:
    while _running:
        now = _now()
        for name in list(_sources.keys()):
            interval = _intervals.get(name, 900.0)
            last = _last_tick.get(name, 0.0)
            if now - last >= interval:
                _dispatch_one(name)
                _last_tick[name] = now
        time.sleep(5.0)


def start() -> None:
    """Start the background poller thread (no-op if already running)."""
    global _running, _thread
    with _lock:
        if _running:
            return
        _running = True
        _thread = threading.Thread(target=_background_loop, daemon=True)
        _thread.start()


def stop() -> None:
    global _running
    with _lock:
        _running = False
