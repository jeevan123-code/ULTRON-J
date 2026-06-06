"""Reasoning Layer — chain-of-thought planning before execution.

Takes an enriched ParsedUtterance + optional last_action context, produces
an ExecutionPlan with:
  - ordered steps (action + args)
  - pre_checks that must succeed before steps run
  - rationale string for transparency / logging

Pure-logic for AFFIRM/DENY/DEFER (no LLM needed). LLM is used for free-form
RESEARCH/COMMAND/CHAT intents to break them into substeps if needed.
"""
from typing import Any, Dict, List, Optional

from intent_types import (
    ExecutionPlan,
    Intent,
    IntentKind,
    Modifier,
    ModifierKind,
    ParsedUtterance,
)


def _apply_excludes(step: Dict[str, Any], excludes: List[str]) -> Dict[str, Any]:
    """Remove excluded items from list-valued args."""
    new_step = {"action": step["action"], "args": dict(step.get("args", {}))}
    for k, v in list(new_step["args"].items()):
        if isinstance(v, list):
            new_step["args"][k] = [x for x in v if not any(ex.lower() in str(x).lower() for ex in excludes)]
    return new_step


def _apply_modifiers(steps: List[Dict[str, Any]], modifiers: List[Modifier]) -> List[Dict[str, Any]]:
    """Apply EXCLUDE/ADD/PRIORITY/MODIFY modifiers to the steps."""
    excludes = [m.value for m in modifiers if m.kind == ModifierKind.EXCLUDE]
    adds = [m.value for m in modifiers if m.kind == ModifierKind.ADD]
    priorities = [m.value for m in modifiers if m.kind == ModifierKind.PRIORITY]

    new_steps = [_apply_excludes(s, excludes) for s in steps]

    for add_val in adds:
        new_steps.append({"action": "add_feature", "args": {"feature": add_val}})

    if priorities:
        for s in new_steps:
            s.setdefault("args", {})["priority"] = priorities[0]

    return new_steps


def _collect_pre_checks(modifiers: List[Modifier]) -> List[str]:
    return [m.value for m in modifiers if m.kind == ModifierKind.PRE_CHECK]


def plan(parsed: ParsedUtterance, last_action: Optional[Dict[str, Any]] = None) -> ExecutionPlan:
    """Produce an ExecutionPlan for the parsed utterance.

    Args:
        parsed: Enriched ParsedUtterance from conversation_intelligence.
        last_action: The action that was last proposed and is awaiting user confirmation.
                     Used when primary intent is AFFIRM/DENY/DEFER.
    """
    kind = parsed.primary.kind
    modifiers = parsed.modifiers

    if kind == IntentKind.AFFIRM:
        if last_action is None:
            return ExecutionPlan(
                steps=[{"action": "clarify", "args": {"reason": "no_pending_action"}}],
                pre_checks=[],
                rationale="User affirmed but no action was pending.",
            )
        steps = _apply_modifiers([last_action], modifiers)
        return ExecutionPlan(
            steps=steps,
            pre_checks=_collect_pre_checks(modifiers),
            rationale="User confirmed previous proposed action.",
        )

    if kind == IntentKind.DENY:
        return ExecutionPlan(
            steps=[{"action": "cancel", "args": {}}],
            pre_checks=[],
            rationale="User declined.",
        )

    if kind == IntentKind.DEFER:
        return ExecutionPlan(
            steps=[{"action": "pause", "args": {}}],
            pre_checks=[],
            rationale="User asked to wait.",
        )

    if kind == IntentKind.RESEARCH:
        topic = parsed.primary.payload.get("topic", parsed.raw)
        steps = [{"action": "research", "args": {"topic": topic}}]
        steps = _apply_modifiers(steps, modifiers)
        return ExecutionPlan(
            steps=steps,
            pre_checks=_collect_pre_checks(modifiers),
            rationale=f"User asked to research: {topic}",
        )

    if kind == IntentKind.COMMAND:
        steps = [{"action": "command", "args": dict(parsed.primary.payload)}]
        steps = _apply_modifiers(steps, modifiers)
        return ExecutionPlan(
            steps=steps,
            pre_checks=_collect_pre_checks(modifiers),
            rationale=f"User issued command: {parsed.raw}",
        )

    if kind == IntentKind.CLARIFY:
        return ExecutionPlan(
            steps=[{"action": "clarify", "args": {"raw": parsed.raw}}],
            pre_checks=[],
            rationale="Ambiguous utterance, asking for clarification.",
        )

    return ExecutionPlan(
        steps=[{"action": "chat_reply", "args": {"raw": parsed.raw}}],
        pre_checks=[],
        rationale="Casual conversation, no action required.",
    )
