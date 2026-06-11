"""Phase 12 plan validator — catches malformed ExecutionPlans at build time.

Pure logic. Walks an `ExecutionPlan` and returns a list of
`ValidationIssue` records. Issues are descriptive, never fatal: the
validator never raises. Callers decide whether to surface, log, or
block.

Scope is deliberately conservative — only catches issues that are
*always* wrong regardless of runtime state:

  * empty plan (warning)
  * missing or unknown `action` (error)
  * missing required `args` per known action (error)
  * `if_prev_ok` and `if_prev_failed` on the same step (error — never runs)
  * `if_prev_failed` on step 0 (warning — always skipped)

What it does NOT validate (yet):

  * `{{prev.<key>}}` placeholders against the prior step's result schema —
    each action's result dict varies and some (scenario, briefing) are
    dynamic; better to leave un-interpolated than to false-positive.
  * Plan-level invariants (rationale length, pre_check shape).

Returning `[]` does not mean the plan will succeed at runtime — only
that no statically-detectable issue was found.
"""
from dataclasses import dataclass
from typing import Any, Dict, List

from intent_types import ExecutionPlan


SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"


@dataclass
class ValidationIssue:
    severity: str
    step_index: int      # -1 for plan-level issues
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity,
            "step_index": self.step_index,
            "message": self.message,
        }


# Per-action requirements:
#   required_args: list of arg names that MUST be present (non-empty)
#   alternative_args: list of arg-name sets; at least one set must be present
_KNOWN_ACTIONS: Dict[str, Dict[str, Any]] = {
    "research": {"required": ["topic"]},
    "alert":    {"required": ["message"]},
    "announce": {"required": ["text"]},
    "scenario": {"required": ["name"]},
    "briefing": {"required": []},  # channels default to ["telegram"]
    "look":     {"required": []},  # no args
    "takeover": {"alternatives": [["type_text"], ["keys"], ["press_key"]]},
}


def _check_step(idx: int, step: Dict[str, Any]) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    action = step.get("action")

    if not action:
        issues.append(ValidationIssue(
            severity=SEVERITY_ERROR, step_index=idx,
            message="missing 'action' field on step",
        ))
        return issues  # no point checking args without an action

    if action not in _KNOWN_ACTIONS:
        issues.append(ValidationIssue(
            severity=SEVERITY_ERROR, step_index=idx,
            message=f"unknown action {action!r}",
        ))
        # Still check conditional flags below — they're action-independent.
    else:
        spec = _KNOWN_ACTIONS[action]
        args = step.get("args") or {}
        for required in spec.get("required", []):
            value = args.get(required)
            if value in (None, "") or (isinstance(value, (list, dict)) and len(value) == 0):
                issues.append(ValidationIssue(
                    severity=SEVERITY_ERROR, step_index=idx,
                    message=f"action {action!r} missing required arg {required!r}",
                ))
        for alt_set in spec.get("alternatives", []):
            if any(args.get(name) not in (None, "") for name in alt_set):
                break
        else:
            if spec.get("alternatives"):
                expected = " or ".join("'" + name + "'" for alt in spec["alternatives"] for name in alt)
                issues.append(ValidationIssue(
                    severity=SEVERITY_ERROR, step_index=idx,
                    message=f"action {action!r} requires one of: {expected}",
                ))

    # Conditional flag checks
    if_ok = bool(step.get("if_prev_ok"))
    if_failed = bool(step.get("if_prev_failed"))

    if if_ok and if_failed:
        issues.append(ValidationIssue(
            severity=SEVERITY_ERROR, step_index=idx,
            message="if_prev_ok and if_prev_failed are mutually exclusive on the same step",
        ))

    if idx == 0 and if_failed:
        issues.append(ValidationIssue(
            severity=SEVERITY_WARNING, step_index=idx,
            message="if_prev_failed on step 0 will always skip — no prior step to fail",
        ))

    return issues


def validate(plan: ExecutionPlan) -> List[ValidationIssue]:
    """Return every issue found in `plan`. Empty list = no static issues."""
    issues: List[ValidationIssue] = []

    if not plan.steps:
        issues.append(ValidationIssue(
            severity=SEVERITY_WARNING, step_index=-1,
            message="plan has empty steps list",
        ))
        return issues

    for idx, step in enumerate(plan.steps):
        if not isinstance(step, dict):
            issues.append(ValidationIssue(
                severity=SEVERITY_ERROR, step_index=idx,
                message=f"step is not a dict: {type(step).__name__}",
            ))
            continue
        issues.extend(_check_step(idx, step))

    return issues
