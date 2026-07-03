"""Phase 18 — continuous vision loop (Tier 2 embodiment).

Phase 9 gave one-shot `look` snapshots. This turns vision into a CONTINUOUS
awareness loop: capture -> perceive -> diff against the last observation ->
emit EVENTS on meaningful transitions (person arrived/left, motion started,
room went dark/lit). Events feed Ultron's mind so it can react proactively.

Event detection is pure; capture/perceive/emit are injectable seams so the
whole thing is testable without a webcam. cv2 is a soft dependency (inherited
from vision_capture) — no camera just means no frames, never a crash.
"""
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from vision_types import VisionObservation

# Thresholds for "meaningful" transitions.
_DARK_THRESHOLD = 0.15
_LIT_THRESHOLD = 0.35
_DEFAULT_INTERVAL = 5.0

_lock = threading.RLock()
_last_obs: Optional[VisionObservation] = None
_running = False
_thread: Optional[threading.Thread] = None
_handler: Optional[Callable[[Dict[str, Any]], None]] = None


def _now() -> float:
    return time.time()


def _safe_log(msg: str) -> None:
    try:
        with open("ultron_log.txt", "a") as f:
            f.write(f"[phase18][vision_stream] {msg}\n")
    except Exception:
        pass


def _reset_for_test() -> None:
    global _last_obs, _running, _handler
    with _lock:
        _last_obs = None
        _running = False
        _handler = None


@dataclass
class VisionEvent:
    ts: float
    kind: str
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"ts": self.ts, "kind": self.kind, "detail": self.detail}


# ── PURE event detection ─────────────────────────────────────────────────────
def detect_events(prev: Optional[VisionObservation],
                  curr: Optional[VisionObservation]) -> List[VisionEvent]:
    """Compare the previous and current observation and emit transition events.
    First observation (prev is None) reports 'person_arrived' if someone's there
    but never spurious 'left' events."""
    if curr is None:
        return []
    events: List[VisionEvent] = []
    ts = curr.ts

    prev_present = bool(prev.person_present) if prev else False
    just_arrived = False
    if curr.person_present and not prev_present:
        events.append(VisionEvent(ts, "person_arrived", {"faces": curr.faces}))
        just_arrived = True
    elif prev is not None and prev_present and not curr.person_present:
        events.append(VisionEvent(ts, "person_left", {}))

    prev_motion = bool(prev.motion) if prev else False
    if curr.motion and not prev_motion:
        events.append(VisionEvent(ts, "motion_started", {}))

    if prev is not None:
        if curr.brightness < _DARK_THRESHOLD <= prev.brightness:
            events.append(VisionEvent(ts, "went_dark", {"brightness": curr.brightness}))
        elif curr.brightness > _LIT_THRESHOLD >= prev.brightness:
            events.append(VisionEvent(ts, "lit_up", {"brightness": curr.brightness}))

    # Don't double-report a face gain that's already covered by an arrival.
    if prev is not None and curr.faces > prev.faces and not just_arrived:
        events.append(VisionEvent(ts, "new_faces",
                                  {"from": prev.faces, "to": curr.faces}))
    return events


# ── seams (mockable) ─────────────────────────────────────────────────────────
def _capture():
    from vision_capture import get_latest_frame
    return get_latest_frame()


def _perceive(frame):
    from vision_perception import observe
    return observe(frame)


def set_event_handler(fn: Optional[Callable[[Dict[str, Any]], None]]) -> None:
    """Register a callback invoked with each event dict. None clears it."""
    global _handler
    with _lock:
        _handler = fn


def _emit(event: VisionEvent) -> None:
    _safe_log(f"event: {event.kind} {event.detail}")
    with _lock:
        handler = _handler
    if handler is not None:
        try:
            handler(event.to_dict())
        except Exception as e:
            _safe_log(f"handler failed: {e!r}")


# ── controller ───────────────────────────────────────────────────────────────
def tick() -> List[VisionEvent]:
    """One capture->perceive->diff->emit cycle. Returns the events emitted."""
    global _last_obs
    frame = _capture()
    obs = _perceive(frame)
    if obs is None:
        return []
    with _lock:
        prev = _last_obs
        _last_obs = obs
    events = detect_events(prev, obs)
    for ev in events:
        _emit(ev)
    return events


def is_running() -> bool:
    return _running


def _loop(interval: float) -> None:
    global _running
    while _running:
        try:
            tick()
        except Exception as e:
            _safe_log(f"loop tick failed: {e!r}")
        time.sleep(interval)


def start(interval: float = _DEFAULT_INTERVAL) -> bool:
    """Start the background vision loop. Returns True if it started."""
    global _running, _thread
    with _lock:
        if _running:
            return False
        _running = True
        _thread = threading.Thread(target=_loop, args=(float(interval),), daemon=True)
        _thread.start()
        return True


def stop() -> None:
    global _running
    with _lock:
        _running = False
