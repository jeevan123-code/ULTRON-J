"""Phase 19 wiring hook — per-session homes for the duplex state machine.

duplex_voice.DuplexController is a pure decision engine: it returns ACTIONS, a
driver performs them. It shipped with no caller, so no controller was ever
constructed and the logic was unreachable outside its own tests.

This hook keeps one controller per voice session and voice_routes exposes it,
which is the surface the browser client drives. The audio DRIVER — real
barge-in on live PCM — remains the hardware seam, unchanged and still honest.

Deliberately additive: nothing here touches the existing half-duplex path, so
adopting it is a client-side decision rather than a server behaviour change.
"""
import threading
from collections import OrderedDict
from typing import Any, Dict

from duplex_voice import DuplexController

# Voice sessions are unbounded and long-lived; cap the table so a long-running
# server cannot accumulate controllers forever.
MAX_SESSIONS = 128

_lock = threading.RLock()
_controllers: "OrderedDict[str, DuplexController]" = OrderedDict()

# event name -> controller method. Anything else is rejected rather than
# silently ignored, so a client typo surfaces instead of hanging the machine.
_EVENTS = {
    "wake": "on_wake",
    "speech_final": "on_speech_final",
    "response_ready": "on_response_ready",
    "tts_finished": "on_tts_finished",
    "user_interrupt": "on_user_interrupt",
    "silence": "on_silence",
}


def _reset_for_test() -> None:
    with _lock:
        _controllers.clear()


def controller_for(session_id: str) -> DuplexController:
    """Get (or create) the controller for a session, LRU-capped."""
    key = session_id or "voice_default"
    with _lock:
        ctrl = _controllers.get(key)
        if ctrl is None:
            ctrl = DuplexController()
            _controllers[key] = ctrl
        else:
            _controllers.move_to_end(key)
        while len(_controllers) > MAX_SESSIONS:
            _controllers.popitem(last=False)
        return ctrl


def reset(session_id: str) -> None:
    with _lock:
        _controllers.pop(session_id or "voice_default", None)


def snapshot(session_id: str) -> Dict[str, Any]:
    ctrl = controller_for(session_id)
    return {"ok": True, **ctrl.snapshot()}


def handle(session_id: str, event: str, text: str = "") -> Dict[str, Any]:
    """Feed one event to the session's machine and return the actions to run."""
    method = _EVENTS.get((event or "").strip())
    if method is None:
        return {"ok": False,
                "error": f"unknown event '{event}'",
                "valid_events": sorted(_EVENTS)}
    ctrl = controller_for(session_id)
    try:
        fn = getattr(ctrl, method)
        actions = fn(text) if method == "on_speech_final" else fn()
    except Exception as e:
        return {"ok": False, "error": repr(e)}
    return {"ok": True, "actions": list(actions), **ctrl.snapshot()}
