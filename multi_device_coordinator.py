"""Phase 4 multi-device coordinator — House Party Protocol.

Holds a registry of `Scenario`s and routes voice triggers into coordinated
multi-device actions. Each `ScenarioStep` is dispatched to the appropriate
existing module (`computer_control`, `mobile_bridge`, `smart_home`) wrapped
in try/except so one failure does not abort the others.

Pattern matches the rest of the codebase: module-level registry behind a
lock, `_reset_for_test` seam, defensive imports so missing optional deps
don't break the coordinator.
"""
import threading
from typing import Any, Dict, List, Optional

from scenario_types import Scenario, ScenarioStep


_lock = threading.RLock()
_registry: List[Scenario] = []


def _reset_for_test() -> None:
    with _lock:
        _registry.clear()


def _snapshot_for_test() -> List[Scenario]:
    with _lock:
        return list(_registry)


def register(scenario: Scenario) -> None:
    """Add a scenario to the registry. Newer registrations win on conflict."""
    with _lock:
        for i, existing in enumerate(_registry):
            if existing.name == scenario.name:
                _registry.pop(i)
                break
        _registry.append(scenario)


def match_trigger(text: str) -> Optional[Scenario]:
    """Return the first registered scenario whose trigger matches `text`."""
    if not text:
        return None
    with _lock:
        for sc in _registry:
            if sc.matches_trigger(text):
                return sc
    return None


# ---- Per-target dispatchers (thin indirections; tests patch these) ----

def _laptop_action(action: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch a laptop step. Wraps computer_control behind a try/except."""
    try:
        import computer_control as cc
    except Exception as e:
        return {"skipped": True, "reason": f"computer_control unavailable: {e!r}"}

    if action == "lock":
        # Best-effort: send the standard Linux/macOS/Windows lock chord.
        try:
            return cc.hotkey("ctrl", "alt", "l")
        except Exception as e:
            return {"success": False, "error": repr(e)}
    if action == "open_app":
        name = (args or {}).get("name", "")
        if not name:
            return {"success": False, "error": "missing app name"}
        return cc.open_app(name)
    if action == "type_text":
        text = (args or {}).get("text", "")
        return cc.type_text(text)
    if action == "hotkey":
        keys = (args or {}).get("keys", [])
        if not keys:
            return {"success": False, "error": "missing keys"}
        return cc.hotkey(*keys)
    return {"skipped": True, "reason": f"unknown laptop action {action!r}"}


def _phone_action(action: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch a phone step via mobile_bridge (Telegram)."""
    try:
        import mobile_bridge as mb
    except Exception as e:
        return {"skipped": True, "reason": f"mobile_bridge unavailable: {e!r}"}

    if action in ("silence", "do_not_disturb"):
        msg = (args or {}).get("message", "Sir, going dark on your phone.")
        try:
            return mb.alert(msg, priority="low") or {"success": True}
        except Exception as e:
            return {"success": False, "error": repr(e)}
    if action == "alert":
        text = (args or {}).get("message", "")
        priority = (args or {}).get("priority", "normal")
        try:
            return mb.alert(text, priority=priority) or {"success": True}
        except Exception as e:
            return {"success": False, "error": repr(e)}
    if action == "message":
        text = (args or {}).get("text", "")
        try:
            return mb.send_message(text)
        except Exception as e:
            return {"success": False, "error": repr(e)}
    return {"skipped": True, "reason": f"unknown phone action {action!r}"}


def _smart_home_action(action: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch a smart-home step via smart_home (Home Assistant bridge)."""
    try:
        import smart_home as sh
    except Exception as e:
        return {"skipped": True, "reason": f"smart_home unavailable: {e!r}"}

    if action == "lights_off":
        try:
            return sh.lights_off() if hasattr(sh, "lights_off") else {"skipped": True}
        except Exception as e:
            return {"success": False, "error": repr(e)}
    if action == "lights":
        color = (args or {}).get("color", "")
        try:
            if hasattr(sh, "set_lights"):
                return sh.set_lights(color=color)
            return {"skipped": True, "reason": "set_lights not available"}
        except Exception as e:
            return {"success": False, "error": repr(e)}
    if action == "lock_doors":
        try:
            return sh.lock_doors() if hasattr(sh, "lock_doors") else {"skipped": True}
        except Exception as e:
            return {"success": False, "error": repr(e)}
    return {"skipped": True, "reason": f"unknown smart_home action {action!r}"}


def _tv_action(action: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """TV dispatcher — currently a stub (no TV module wired)."""
    return {"skipped": True, "reason": "tv target not implemented"}


_DISPATCH_NAMES = {
    "laptop": "_laptop_action",
    "phone": "_phone_action",
    "smart_home": "_smart_home_action",
    "tv": "_tv_action",
}


def _dispatch_step(step: ScenarioStep) -> Dict[str, Any]:
    name = _DISPATCH_NAMES.get(step.target)
    if name is None:
        return {"skipped": True, "reason": f"unknown target {step.target!r}"}
    # Look up at call time so tests can monkeypatch the per-target dispatcher.
    fn = globals()[name]
    return fn(step.action, step.args)


def run(scenario: Scenario) -> Dict[int, Dict[str, Any]]:
    """Execute every step of `scenario`. One failure does not stop others."""
    results: Dict[int, Dict[str, Any]] = {}
    for idx, step in enumerate(scenario.steps):
        try:
            results[idx] = _dispatch_step(step)
        except Exception as e:
            try:
                with open("ultron_log.txt", "a") as f:
                    f.write(f"[phase4][step_error] step={idx} target={step.target} action={step.action} err={e!r}\n")
            except Exception:
                pass
            results[idx] = {"ok": False, "error": repr(e), "target": step.target}
    return results
