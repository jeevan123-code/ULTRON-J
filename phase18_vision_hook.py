"""Phase 18 wiring hook — starts the continuous vision loop and routes its
events to the user.

vision_stream shipped with start()/stop()/set_event_handler() and no production
caller, so the loop never ran and its events had nowhere to go. app.py calls
start() here at boot, mirroring how phase5g_implicit_hook wires Phase 5g.

Gated by ULTRON_PHASE18_ENABLED (default OFF). The camera backend is a real
hardware dependency — cv2 may not be installed — so every failure path degrades
to "did not start" and is logged. Vision must never be able to stop the app
from booting.
"""
import os
from typing import Any, Dict

DEFAULT_INTERVAL = 5.0
_INTERVAL_ENV = "ULTRON_PHASE18_INTERVAL"
_FLAG = "ULTRON_PHASE18_ENABLED"


def _safe_log(msg: str) -> None:
    try:
        print(f"[phase18] {msg}")
    except Exception:
        pass


def _enabled() -> bool:
    return os.environ.get(_FLAG, "0") == "1"


def _interval() -> float:
    """Loop interval in seconds. Configurable, never hardcoded at the call site."""
    raw = os.environ.get(_INTERVAL_ENV, "")
    try:
        value = float(raw)
        return value if value > 0 else DEFAULT_INTERVAL
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL


def _notify(msg: str) -> None:
    """Surface a vision event to the user through the normal suggestion path."""
    try:
        from autonomous_loop import push_agent_suggestion
        push_agent_suggestion(msg, priority="normal")
    except Exception as e:
        _safe_log(f"notify unavailable: {e!r}")


def _describe(event: Dict[str, Any]) -> str:
    kind = event.get("kind", "event")
    detail = event.get("detail") or {}
    if isinstance(detail, dict) and detail:
        bits = ", ".join(f"{k}={v}" for k, v in list(detail.items())[:4])
        return f"👁 vision: {kind} ({bits})"
    return f"👁 vision: {kind}"


def _on_event(event: Dict[str, Any]) -> None:
    # vision_stream._emit already guards handler exceptions, but a notify
    # failure must not look like a vision failure either.
    try:
        _notify(_describe(event))
    except Exception as e:
        _safe_log(f"event handler failed: {e!r}")


def start() -> bool:
    """Start the vision loop if enabled. Returns True only if it actually started."""
    if not _enabled():
        return False
    try:
        import vision_stream
        vision_stream.set_event_handler(_on_event)
        started = bool(vision_stream.start(_interval()))
        _safe_log(f"vision loop {'started' if started else 'already running'} "
                  f"@ {_interval()}s")
        return started
    except Exception as e:
        # Missing cv2 / no camera / driver error — degrade, never crash boot.
        _safe_log(f"vision loop unavailable: {e!r}")
        return False


def stop() -> None:
    try:
        import vision_stream
        vision_stream.stop()
        vision_stream.set_event_handler(None)
    except Exception as e:
        _safe_log(f"stop failed: {e!r}")
