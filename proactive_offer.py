"""Proactive Offer — the polite voice prompt + consent dispatch.

Lifecycle:
  1. screen_watcher reports a StuckEvent.
  2. handle_stuck_event:
       - rate-limit check (at most 1 offer per _RATE_LIMIT_SECONDS)
       - speak "Sir, mind if I help?"
       - store pending offer with the error text + ts
  3. voice_engine pipes the user's response into consent_manager.
  4. confirm_offer(mode):
       - HANDS_ON / VOICE_ONLY -> build ExecutionPlan{action=research, topic=error}
                                   and pass to phase2_executor.execute
       - DECLINE -> clear pending
       - NONE -> keep pending (user hasn't decided yet)

Phase 3c extension (flag-gated by ULTRON_PHASE3C_ENABLED):
  * offer_takeover_suggestion(suggestion, plan) stores a different kind of
    pending offer that carries an ExecutionPlan whose first step is
    action="takeover".
  * confirm_offer(HANDS_ON) on such an offer is routed through
    takeover_executor (computer_control side effect) instead of research.
  * If the flag is OFF, the pending offer is dropped silently — safe default.
"""
import os
import threading
import time
from typing import Any, Dict, Optional

from consent_types import ConsentMode
from intent_types import ExecutionPlan
from struggle_types import StuckEvent
from improvement_types import Suggestion


_RATE_LIMIT_SECONDS = 300   # at most one polite offer per 5 minutes

_lock = threading.RLock()
_pending_offer: Optional[Dict[str, Any]] = None
_last_offer_at: float = 0.0


def _reset_for_test() -> None:
    global _pending_offer, _last_offer_at
    with _lock:
        _pending_offer = None
        _last_offer_at = 0.0


def _speak(text: str) -> None:
    from voice_engine import tts
    tts(text, mood="FOCUSED")


def _execute_plan(plan: ExecutionPlan) -> Dict[str, Any]:
    from phase2_executor import execute
    return execute(plan)


def _execute_takeover_plan(plan: ExecutionPlan) -> Dict[str, Any]:
    """Indirection so tests can patch the takeover executor."""
    from takeover_executor import execute as takeover_execute
    return takeover_execute(plan)


def _phase3c_enabled() -> bool:
    return os.environ.get("ULTRON_PHASE3C_ENABLED", "0") == "1"


def _now() -> float:
    return time.time()


def offer_takeover_suggestion(suggestion: Suggestion, plan: ExecutionPlan) -> None:
    """Store a Phase 3c improvement-suggestion offer for later HANDS_ON dispatch.

    The actual voice prompt is the caller's responsibility (e.g., the
    suggester surface). This just parks the plan + summary so confirm_offer
    can later route it through takeover_executor.
    """
    global _pending_offer, _last_offer_at
    with _lock:
        _pending_offer = {
            "kind": "improvement",
            "suggestion_kind": suggestion.kind,
            "summary": suggestion.summary,
            "takeover_plan": plan,
            "offered_at": _now(),
        }
        _last_offer_at = _now()


def handle_stuck_event(event: StuckEvent) -> bool:
    """Called by screen_watcher when a StuckEvent fires.

    Returns True if a polite voice offer was spoken; False if rate-limited.
    """
    global _pending_offer, _last_offer_at
    with _lock:
        if _now() - _last_offer_at < _RATE_LIMIT_SECONDS:
            return False
        _last_offer_at = _now()
        _pending_offer = {
            "error_text": event.snapshot.error_text,
            "active_window": event.snapshot.active_window,
            "first_seen_ts": event.first_seen_ts,
            "offered_at": _last_offer_at,
        }
    try:
        _speak("Sir, mind if I help?")
    except Exception:
        try:
            with open("ultron_log.txt", "a") as f:
                f.write("[phase3b][voice_error] polite offer failed\n")
        except Exception:
            pass
    return True


def peek_pending_offer() -> Optional[Dict[str, Any]]:
    with _lock:
        return dict(_pending_offer) if _pending_offer else None


def confirm_offer(mode: ConsentMode) -> Dict[str, Any]:
    """Apply the user's consent to the current pending offer.

    Returns a result dict: {confirmed: bool, mode: str, reason?: str}.
    """
    global _pending_offer
    with _lock:
        pending = _pending_offer

    if pending is None:
        return {"confirmed": False, "reason": "no_pending_offer"}

    if mode == ConsentMode.NONE:
        return {"confirmed": False, "reason": "no_consent_extracted"}

    if mode == ConsentMode.DECLINE:
        with _lock:
            _pending_offer = None
        return {"confirmed": False, "mode": ConsentMode.DECLINE.value, "reason": "declined"}

    # Phase 3c: takeover-style offer (flag-gated).
    if pending.get("kind") == "improvement":
        with _lock:
            _pending_offer = None
        if not _phase3c_enabled():
            return {"confirmed": False, "reason": "phase3c_disabled"}
        plan = pending.get("takeover_plan")
        try:
            takeover_result = _execute_takeover_plan(plan)
        except Exception as e:
            try:
                with open("ultron_log.txt", "a") as f:
                    f.write(f"[phase3c][exec_error] {e!r}\n")
            except Exception:
                pass
            return {
                "confirmed": True, "mode": mode.value,
                "executed": False, "error": repr(e),
            }
        return {
            "confirmed": True, "mode": mode.value,
            "executed": bool(takeover_result.get("executed")),
            "takeover_result": takeover_result,
        }

    topic = pending["error_text"]
    plan = ExecutionPlan(
        steps=[{"action": "research", "args": {"topic": topic}}],
        pre_checks=[],
        rationale=f"co-pilot consent mode={mode.value} on error {topic!r}",
    )
    with _lock:
        _pending_offer = None
    try:
        exec_result = _execute_plan(plan)
    except Exception as e:
        try:
            with open("ultron_log.txt", "a") as f:
                f.write(f"[phase3b][exec_error] {e!r}\n")
        except Exception:
            pass
        return {"confirmed": True, "mode": mode.value, "executed": False, "error": repr(e)}

    return {
        "confirmed": True,
        "mode": mode.value,
        "executed": bool(exec_result.get("executed")),
        "exec_result": exec_result,
    }
