"""Phase 6 briefing scheduler — cron-based dispatch.

Holds a JSON-backed list of `BriefingSchedule`s. `tick(now, window_seconds)`
finds schedules whose cron expression fires inside `(now - window, now]`
and dispatches each through `_compose_briefing` + `_deliver_briefing`.

`croniter` is a soft dependency: if it isn't installed, `IS_AVAILABLE`
is False and tick / due become no-ops (logged once).
"""
import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

from briefing_types import BriefingSchedule


try:
    from croniter import croniter as _croniter
    IS_AVAILABLE = True
except Exception:
    _croniter = None  # type: ignore
    IS_AVAILABLE = False


_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(_BASE_DIR, "scheduled_briefings.json")

_lock = threading.RLock()
_cache: List[BriefingSchedule] = []
_loaded = False


def _now() -> float:
    return time.time()


def _safe_log(msg: str) -> None:
    try:
        with open("ultron_log.txt", "a") as f:
            f.write(f"[phase6][scheduler] {msg}\n")
    except Exception:
        pass


def _persist() -> None:
    try:
        os.makedirs(os.path.dirname(_PATH), exist_ok=True)
        with open(_PATH, "w") as f:
            json.dump([s.to_dict() for s in _cache], f, indent=2)
    except Exception:
        pass


def _load_from_disk() -> None:
    global _cache, _loaded
    with _lock:
        if not os.path.exists(_PATH):
            _cache = []
            _loaded = True
            return
        try:
            with open(_PATH) as f:
                data = json.load(f)
            _cache = [BriefingSchedule.from_dict(d) for d in data]
            _loaded = True
        except Exception:
            _cache = []
            _loaded = True


def _ensure_loaded() -> None:
    with _lock:
        if not _loaded:
            _load_from_disk()


def _reset_for_test() -> None:
    global _cache, _loaded
    with _lock:
        _cache = []
        _loaded = True
        try:
            if os.path.exists(_PATH):
                os.remove(_PATH)
        except Exception:
            pass


def _reset_in_memory_for_test() -> None:
    global _cache, _loaded
    with _lock:
        _cache = []
        _loaded = False


def _valid_cron(expr: str) -> bool:
    if not IS_AVAILABLE:
        # Without croniter we can't validate; allow non-empty strings through.
        return bool(expr and expr.strip())
    try:
        _croniter(expr, _now())
        return True
    except Exception:
        return False


def add(id: str, cron_expr: str,
        channels: Optional[List[str]] = None,
        include_worldfeed: bool = True) -> BriefingSchedule:
    """Add or replace a scheduled briefing."""
    if not id or not id.strip():
        raise ValueError("id must be non-empty")
    if not _valid_cron(cron_expr):
        raise ValueError(f"invalid cron expression: {cron_expr!r}")

    schedule = BriefingSchedule(
        id=id, cron_expr=cron_expr,
        channels=list(channels or ["telegram"]),
        include_worldfeed=include_worldfeed,
        created_at=_now(),
    )
    with _lock:
        _ensure_loaded()
        for i, existing in enumerate(_cache):
            if existing.id == id:
                _cache.pop(i)
                break
        _cache.append(schedule)
        _persist()
    return schedule


def remove(id: str) -> bool:
    with _lock:
        _ensure_loaded()
        for i, s in enumerate(_cache):
            if s.id == id:
                _cache.pop(i)
                _persist()
                return True
    return False


def list_all() -> List[BriefingSchedule]:
    with _lock:
        _ensure_loaded()
        return list(_cache)


def due(now: Optional[float] = None, window_seconds: float = 60.0) -> List[BriefingSchedule]:
    """Return schedules whose cron fires inside `(now - window, now]`."""
    if not IS_AVAILABLE:
        return []
    n = _now() if now is None else float(now)
    out: List[BriefingSchedule] = []
    with _lock:
        _ensure_loaded()
        for s in list(_cache):
            try:
                # croniter gives the previous fire instant; if it falls in our
                # window, the briefing is due.
                cron = _croniter(s.cron_expr, n)
                last_fire = cron.get_prev(float)
                if n - last_fire <= window_seconds and last_fire <= n:
                    out.append(s)
            except Exception as e:
                _safe_log(f"cron eval failed for {s.id}: {e!r}")
    return out


# ---- delivery indirections (tests stub these) ----

def _compose_briefing(schedule: BriefingSchedule, now: float) -> str:
    try:
        import briefing_builder
        return briefing_builder.compose(
            now=now, include_worldfeed=schedule.include_worldfeed,
        )
    except Exception as e:
        _safe_log(f"compose failed for {schedule.id}: {e!r}")
        return ""


def _deliver_briefing(text: str, channels: List[str]) -> Dict[str, Any]:
    try:
        import briefing_delivery
        return briefing_delivery.deliver(text, channels)
    except Exception as e:
        _safe_log(f"deliver failed: {e!r}")
        return {}


def tick(now: Optional[float] = None, window_seconds: float = 60.0) -> Dict[str, Any]:
    """Dispatch every due briefing. Returns {schedule_id: deliver_result}."""
    n = _now() if now is None else float(now)
    results: Dict[str, Any] = {}
    for schedule in due(now=n, window_seconds=window_seconds):
        text = _compose_briefing(schedule, n)
        if not text:
            results[schedule.id] = {"ok": False, "reason": "empty_compose"}
            continue
        results[schedule.id] = _deliver_briefing(text, schedule.channels)
    return results
