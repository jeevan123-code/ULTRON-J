"""Phase 20 — proactive device orchestration (Tier 2 embodiment).

multi_device_coordinator today is REACTIVE: it matches a voice trigger and runs
a scenario. Phase 20 adds PROACTIVE orchestration — Ultron runs device scenarios
from CONTEXT/EVENTS, not just explicit commands ("nobody's home + it's late ->
lock up + drop the thermostat").

Device actions touch the physical world, so they are AMBER by default (Tier-4
posture): a rule that fires is PARKED for approval unless `approved=True` (or
ULTRON_PHASE20_AUTO=1). Rule evaluation is pure; the device dispatch is a
mockable seam. Per-rule cooldowns are persisted so a standing condition doesn't
re-fire every cycle.
"""
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_STATE_PATH = os.path.join(_BASE_DIR, "proactive_orchestrator_state.json")

_lock = threading.RLock()
_rules: List["ContextRule"] = []


def _now() -> float:
    return time.time()


@dataclass
class ContextRule:
    """A proactive rule: when `predicate(context)` is true, run `actions`."""
    name: str
    predicate: Callable[[Dict[str, Any]], bool]
    actions: List[Dict[str, Any]] = field(default_factory=list)  # [{device, action, args}]
    cooldown_seconds: float = 3600.0


def register_rule(rule: ContextRule) -> None:
    with _lock:
        _rules[:] = [r for r in _rules if r.name != rule.name]
        _rules.append(rule)


def clear_rules() -> None:
    with _lock:
        _rules.clear()


def _reset_for_test() -> None:
    clear_rules()
    with _lock:
        try:
            if os.path.exists(_STATE_PATH):
                os.remove(_STATE_PATH)
        except Exception:
            pass


# ── cooldown state ───────────────────────────────────────────────────────────
def _load_state() -> Dict[str, float]:
    if not os.path.exists(_STATE_PATH):
        return {}
    try:
        with open(_STATE_PATH) as f:
            return (json.load(f) or {}).get("last_fired", {})
    except Exception:
        return {}


def _save_state(last_fired: Dict[str, float]) -> None:
    try:
        tmp = _STATE_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"last_fired": last_fired}, f)
        os.replace(tmp, _STATE_PATH)
    except Exception:
        pass


# ── pure evaluation ──────────────────────────────────────────────────────────
def evaluate(context: Dict[str, Any]) -> List[ContextRule]:
    """Return rules whose predicate matches. Pure (a bad predicate is skipped)."""
    fired: List[ContextRule] = []
    with _lock:
        rules = list(_rules)
    for r in rules:
        try:
            if r.predicate(context or {}):
                fired.append(r)
        except Exception:
            continue
    return fired


# ── device dispatch seam (mockable) ──────────────────────────────────────────
def _dispatch(action: Dict[str, Any]) -> Dict[str, Any]:
    """Perform one device action via smart_home. Mocked in tests."""
    try:
        from smart_home import get_smart_home
        sh = get_smart_home()
        device = action.get("device", "")
        act = action.get("action", "")
        args = action.get("args", {})
        fn = getattr(sh, act, None)
        if callable(fn):
            return {"ok": True, "result": fn(**args) if args else fn()}
        return {"ok": False, "error": f"unknown smart_home action '{act}'",
                "device": device}
    except Exception as e:
        return {"ok": False, "error": repr(e)}


def _notify(msg: str) -> None:
    try:
        from autonomous_loop import push_agent_suggestion
        push_agent_suggestion(msg, priority="normal")
    except Exception:
        pass


def _auto_enabled() -> bool:
    return os.environ.get("ULTRON_PHASE20_AUTO", "0") == "1"


# ── orchestration ────────────────────────────────────────────────────────────
def orchestrate(context: Dict[str, Any], approved: bool = False,
                now: Optional[float] = None) -> Dict[str, Any]:
    """Evaluate rules and either run (auto/approved) or park (default) their
    device actions. Respects per-rule cooldown."""
    n = _now() if now is None else float(now)
    summary = {"fired": 0, "ran": 0, "parked": 0, "cooling_down": 0}
    allow = approved or _auto_enabled()
    with _lock:
        last_fired = _load_state()
        for rule in evaluate(context):
            last = last_fired.get(rule.name)
            if last is not None and (n - float(last)) < rule.cooldown_seconds:
                summary["cooling_down"] += 1
                continue
            summary["fired"] += 1
            last_fired[rule.name] = n
            if allow:
                for action in rule.actions:
                    _dispatch(action)
                summary["ran"] += 1
            else:
                summary["parked"] += 1
                _notify(f"🏠 Ultron suggests running '{rule.name}' "
                        f"({len(rule.actions)} device actions). Approve?")
        _save_state(last_fired)
    return summary
