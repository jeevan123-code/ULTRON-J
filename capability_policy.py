"""Phase 17 — capability / permission policy engine (Tier-4 safety foundation).

Generalises the Phase 14 green/amber/red seed into a single, config-driven
authority model usable anywhere an action is about to run:

    GREEN — read-only / additive. Allowed.
    AMBER — mutates user data / apps / external services. Needs approval.
    RED   — destructive / code-exec / self-modify / third-party send / spend.
            Never allowed autonomously.

`evaluate()` starts from a policy TABLE (overridable at runtime via
capability_policy.json — no hardcoding), then ESCALATES using the existing
`confirm_gate` and `decision_engine.safety_check` signals, and returns the
STRICTEST tier. `enforce()` turns a tier into an allow/deny with an approval
gate for AMBER.
"""
import json
import os
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_POLICY_FILE = os.path.join(_BASE_DIR, "capability_policy.json")

_lock = threading.RLock()


class Tier(str, Enum):
    GREEN = "green"
    AMBER = "amber"
    RED = "red"


_ORDER = {Tier.GREEN: 0, Tier.AMBER: 1, Tier.RED: 2}


def _strictest(a: Tier, b: Tier) -> Tier:
    return a if _ORDER[a] >= _ORDER[b] else b


# Default policy. Unknown actions default to AMBER (safe: ask, don't assume).
_DEFAULT_POLICY: Dict[str, Tier] = {
    # GREEN — read-only / additive
    "file_read": Tier.GREEN, "file_list": Tier.GREEN, "calculate": Tier.GREEN,
    "search_web": Tier.GREEN, "search_on_site": Tier.GREEN, "web_scrape": Tier.GREEN,
    "weather_fetch": Tier.GREEN, "note_create": Tier.GREEN, "git_status": Tier.GREEN,
    "memory_store": Tier.GREEN, "memory_fetch": Tier.GREEN, "analyze": Tier.GREEN,
    "summarize": Tier.GREEN, "ask_llm": Tier.GREEN, "look": Tier.GREEN,
    # AMBER — mutates data / apps / external
    "file_write": Tier.AMBER, "create_file": Tier.AMBER, "append_file": Tier.AMBER,
    "rename_file": Tier.AMBER, "copy_file": Tier.AMBER, "move_file": Tier.AMBER,
    "zip_folder": Tier.AMBER, "open_url": Tier.AMBER, "open_app": Tier.AMBER,
    "click": Tier.AMBER, "type_text": Tier.AMBER, "screenshot": Tier.AMBER,
    "api_call": Tier.AMBER, "send_email": Tier.AMBER, "send_telegram": Tier.AMBER,
    # RED — destructive / code-exec / self-modify
    "delete_file": Tier.RED, "delete_folder": Tier.RED, "run_python": Tier.RED,
    "run_code": Tier.RED, "run_command": Tier.RED, "run_script": Tier.RED,
    "self_modify": Tier.RED, "patch_file": Tier.RED,
}

_policy_override: Optional[Dict[str, Tier]] = None


@dataclass
class PolicyDecision:
    tier: Tier
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {"tier": self.tier.value, "reason": self.reason}


def _load_overrides() -> Dict[str, Tier]:
    """Merge on-disk overrides (capability_policy.json: {action: 'green|amber|red'})."""
    if not os.path.exists(_POLICY_FILE):
        return {}
    try:
        with open(_POLICY_FILE) as f:
            raw = json.load(f) or {}
        out = {}
        for k, v in raw.items():
            try:
                out[k] = Tier(str(v).lower())
            except ValueError:
                continue
        return out
    except Exception:
        return {}


def _effective_policy() -> Dict[str, Tier]:
    with _lock:
        table = dict(_DEFAULT_POLICY)
        table.update(_load_overrides())
        if _policy_override:
            table.update(_policy_override)
        return table


def set_policy_override(overrides: Optional[Dict[str, Tier]]) -> None:
    """In-memory override (tests / runtime tuning)."""
    global _policy_override
    with _lock:
        _policy_override = dict(overrides) if overrides else None


def _reset_for_test() -> None:
    set_policy_override(None)


def evaluate(action_type: str, params: Optional[Dict[str, Any]] = None) -> PolicyDecision:
    """Classify an action. Table tier, escalated by live safety signals.

    Deny-by-default: an action the `safety_check` whitelist does not recognise
    is escalated to RED even though the table's fallback is AMBER — an unknown
    capability is never granted autonomously.
    """
    params = params or {}
    table = _effective_policy()
    tier = table.get(action_type, Tier.AMBER)
    reason = f"policy table: {action_type} -> {tier.value}"

    # Escalate on destructive classification from confirm_gate.
    try:
        from confirm_gate import is_destructive
        destructive, why = is_destructive(action_type, params)
        if destructive:
            tier = _strictest(tier, Tier.AMBER)
            reason = f"destructive: {why}"
    except Exception:
        pass

    # Escalate to RED if the safety layer rejects it outright (dangerous
    # pattern in command/content/code, restricted path, etc.).
    try:
        from decision_engine import safety_check
        ok, why = safety_check({"type": action_type, "params": params})
        if not ok:
            tier = Tier.RED
            reason = f"safety_check blocked: {why}"
    except Exception:
        pass

    return PolicyDecision(tier=tier, reason=reason)


def enforce(action_type: str, params: Optional[Dict[str, Any]] = None,
            approved: bool = False) -> Dict[str, Any]:
    """Decide whether an action may run now.

    Returns {allowed, tier, reason, needs_approval}. GREEN always allowed;
    AMBER allowed only when `approved`; RED never allowed autonomously.
    """
    decision = evaluate(action_type, params)
    if decision.tier == Tier.GREEN:
        return {"allowed": True, "tier": "green", "reason": decision.reason,
                "needs_approval": False}
    if decision.tier == Tier.AMBER:
        return {"allowed": bool(approved), "tier": "amber", "reason": decision.reason,
                "needs_approval": not approved}
    return {"allowed": False, "tier": "red", "reason": decision.reason,
            "needs_approval": False}
