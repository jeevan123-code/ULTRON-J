"""
confirm_gate.py — the ONE destructive-action gate for Ultron-J.

Phase 1.4 introduced the HTTP-route layer ("I CONFIRM <action>" token
in the JSON body). Phase 7.3 consolidates the rest:

  * is_destructive(action_type, params)   - classify an action_engine
                                            tool call as destructive
                                            or not
  * is_destructive_shell(cmd)             - classify a shell-string
                                            (replaces task_orchestrator
                                            ._is_destructive_shell)
  * dry_run_preview(action_type, params)  - human-readable description
                                            of what WOULD happen
  * require_confirm(action_name)          - HTTP-route confirm token
                                            (Phase 1.4 -- unchanged
                                            signature, still the route
                                            layer's gate)

The principle: ANY code path that can delete files, kill processes,
shut down the machine, rewrite source, or empty the trash funnels
through one of these primitives. New destructive surfaces added later
should consult this module rather than rolling their own check.

The classifier is conservative -- false positives (refusing a safe
op) are recoverable; false negatives (running a destructive op
unflagged) are not.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

from flask import request, jsonify


def _expected_token(action_name: str) -> str:
    return f"I CONFIRM {action_name}"


def require_confirm(action_name: str):
    """
    Call at the very top of a destructive route handler. Returns either:
      * None                              -> caller provided a matching
                                             confirm token; proceed.
      * (Flask response, status_code)     -> caller did not confirm; the
                                             handler must `return` this
                                             tuple directly.

    Usage:
        @app.route("/self_upgrade/run", methods=["POST"])
        def run_self_upgrade():
            denial = require_confirm("self_upgrade_run")
            if denial:
                return denial
            ...
    """
    data = request.get_json(silent=True) or {}
    submitted = (data.get("confirm") or "").strip()
    expected = _expected_token(action_name)
    if submitted != expected:
        return (
            jsonify(
                {
                    "error": "confirm token required",
                    "action": action_name,
                    "required_body_field": "confirm",
                    "required_value": expected,
                    "hint": (
                        "This endpoint can rewrite code or modify the "
                        "system. Resubmit with the exact confirm value "
                        "to acknowledge intent."
                    ),
                }
            ),
            428,  # Precondition Required — semantically the right code here
        )
    return None


# ─── Phase 7.3 — in-process destructive-action classifier ─────────────────────
#
# Used by task_orchestrator + intent_router + action_engine to decide
# whether an action needs the confirm token before executing in-process
# (no Flask request scope). The HTTP-route guard above stays the
# canonical entry point for external callers.

# Action types that mutate or destroy state. Aligned with the
# allow-list in decision_engine.ALLOWED_COMMANDS but classified by
# intent rather than transport.
_DESTRUCTIVE_ACTION_TYPES = frozenset({
    "delete_file", "delete_folder",
    "rename_file", "move_file",          # rename/move can clobber
    "zip_folder",                         # creates a side-effect file
    "run_command", "run_python",          # arbitrary code execution
    "send_email",                         # external + irreversible
    "self_modify", "self_upgrade",
    "shutdown", "sleep", "lock",
    "empty_trash",
})

# Shell-string verbs that mutate or destroy state. Used by the legacy
# task_orchestrator._is_destructive_shell path; kept here so there's
# ONE regex, not two.
_DESTRUCTIVE_SHELL_RE = re.compile(
    r"^\s*(?:rm|del|erase|rmdir|rd|unlink|format|fdisk|mkfs|"
    r"shutdown|reboot|halt|poweroff|"
    r"Remove-Item|ri|Clear-Recycle|Remove-Computer|Stop-Computer|"
    r"Restart-Computer|Format-Volume|Clear-Content|Remove-PSDrive|"
    r"sc(?:\s+delete)?|reg\s+delete|taskkill|wmic|net\s+user)\b",
    re.I,
)


def is_destructive_shell(cmd: str) -> bool:
    """True if `cmd` looks like a shell command that would delete files,
    kill processes, or otherwise change persistent state. Conservative:
    matches the verb at the start of the command line."""
    if not cmd:
        return False
    return bool(_DESTRUCTIVE_SHELL_RE.search(cmd))


def is_destructive(action_type: str, params: Optional[dict] = None) -> Tuple[bool, str]:
    """Classify an action_engine tool call. Returns (is_destructive, reason).

    Reason is a short string describing WHY (used by dry_run_preview).
    Two-pass check:
      1. action_type membership in _DESTRUCTIVE_ACTION_TYPES
      2. for run_command specifically, also check the command string
    """
    params = params or {}
    if action_type in _DESTRUCTIVE_ACTION_TYPES:
        return True, f"action type '{action_type}' mutates state"
    if action_type == "run_command":
        cmd = str(params.get("command", ""))
        if is_destructive_shell(cmd):
            return True, f"shell command starts with destructive verb: {cmd[:60]}"
    return False, ""


def dry_run_preview(action_type: str, params: Optional[dict] = None) -> str:
    """Human-readable description of what an action WOULD do, without
    running it. Used by the UI to show 'about to delete X, Y, Z --
    confirm?' previews."""
    params = params or {}
    destructive, reason = is_destructive(action_type, params)
    prefix = "DESTRUCTIVE: " if destructive else ""

    if action_type in ("delete_file", "delete_folder"):
        return f"{prefix}would delete {params.get('path', '<?>')}"
    if action_type == "rename_file":
        return f"{prefix}would rename {params.get('old', '<?>')} -> {params.get('new', '<?>')}"
    if action_type == "move_file":
        return f"{prefix}would move {params.get('src', '<?>')} -> {params.get('dst', '<?>')}"
    if action_type == "zip_folder":
        return f"{prefix}would zip {params.get('path', '<?>')} into {params.get('output', '<?>')}"
    if action_type in ("run_command", "run_python"):
        body = params.get("command") or params.get("code", "")
        return f"{prefix}would execute: {str(body)[:200]}"
    if action_type == "send_email":
        return f"{prefix}would send email to {params.get('to', '<?>')} subject={params.get('subject', '<?>')!r}"
    if action_type in ("self_modify", "self_upgrade"):
        return f"{prefix}would rewrite source files in this repo"
    if action_type in ("shutdown", "sleep", "lock", "empty_trash"):
        return f"{prefix}would invoke system {action_type}"
    return f"would invoke {action_type} with {sorted(params.keys())[:5]}"
