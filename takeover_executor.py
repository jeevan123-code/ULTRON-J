"""Phase 3c takeover executor.

Thin wrapper around `computer_control`: turns an ExecutionPlan whose first
step is `action="takeover"` into one or more direct UI calls (typing,
hotkeys). Mirrors `phase2_executor.execute` in shape — return a small dict
describing what happened.

Supported step args (one per step):
  * ``{"type_text": "<string>"}``         → ``computer_control.type_text``
  * ``{"keys": ["ctrl", "shift", "p"]}`` → ``computer_control.hotkey``
  * ``{"press_key": "enter"}``           → ``computer_control.press_key``

Anything else is treated as malformed (no execution, no side effects).
Errors raised by ``computer_control`` are caught and logged; this layer
never lets a failed UI call crash the consent dispatch.
"""
from typing import Any, Dict

from intent_types import ExecutionPlan


def _type_text(text: str) -> Dict[str, Any]:
    from computer_control import type_text as cc_type_text
    return cc_type_text(text)


def _hotkey(*keys: str) -> Dict[str, Any]:
    from computer_control import hotkey as cc_hotkey
    return cc_hotkey(*keys)


def _press_key(key: str) -> Dict[str, Any]:
    from computer_control import press_key as cc_press_key
    return cc_press_key(key)


def _log_error(message: str) -> None:
    try:
        with open("ultron_log.txt", "a") as f:
            f.write(f"[phase3c][takeover_error] {message}\n")
    except Exception:
        pass


def execute(plan: ExecutionPlan) -> Dict[str, Any]:
    """Run the first takeover step of `plan` against the user's machine."""
    if not plan.steps:
        return {"executed": False, "action": None, "reason": "empty_plan"}

    step = plan.steps[0]
    action = step.get("action")
    if action != "takeover":
        return {"executed": False, "action": action, "reason": "not_takeover"}

    args = step.get("args") or {}

    try:
        if "type_text" in args:
            result = _type_text(args["type_text"])
            return {"executed": True, "action": action, "mode": "type_text", "result": result}
        if "keys" in args:
            keys = list(args["keys"])
            result = _hotkey(*keys)
            return {"executed": True, "action": action, "mode": "keys", "result": result}
        if "press_key" in args:
            result = _press_key(args["press_key"])
            return {"executed": True, "action": action, "mode": "press_key", "result": result}
    except Exception as e:
        _log_error(f"dispatch failed: {e!r} args={args!r}")
        return {"executed": False, "action": action, "reason": "exception", "error": repr(e)}

    return {"executed": False, "action": action, "reason": "malformed_plan"}
