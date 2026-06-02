"""
confirm_gate.py — second layer of protection for irreversible endpoints.

Auth.py proves you're allowed to call ANY endpoint. This module proves
you MEAN to call THIS endpoint. The distinction matters for self-modify
/ self-upgrade / shutdown / delete-style operations where an auth'd-but-
careless caller (a wrong-curl, an LLM-generated request, an automation
script that lost its mind) could trash the codebase or the machine.

Phase 1 contract: caller must include
    {"confirm": "I CONFIRM <action_name>"}
in the JSON body. The string is literal — no signing, no challenge — but
typing the action name out is sufficient evidence that the call wasn't a
typo or stray LLM output.

Phase 7.3 will consolidate this with task_orchestrator._is_destructive_shell
and intent_router's destructive guard into a single gate that also returns
a dry-run preview and uses a real signed challenge. The plan calls this
out (Phase 1.4 -> "Reuse the single gate built in 7.3").
"""

from typing import Optional

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
