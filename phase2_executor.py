"""Phase 2 Executor.

Consumes a Phase 1 ExecutionPlan and executes any `action="research"` step:
  1. Call research_engine.research(topic, depth)
  2. Convert to ResearchReport via research_types.report_from_research_dict
  3. Store high-confidence facts via research_facts.store_verified_facts
  4. Deliver via delivery_manager.deliver

Returns a small dict describing what actually happened.

Non-research steps are passed through unchanged (executed=False) — Phase 2a
only owns the research action.
"""
from typing import Any, Dict, Optional

from intent_types import ExecutionPlan
import research_facts
from research_types import (
    DeliveryEnvelope,
    ResearchReport,
    report_from_research_dict,
)
import delivery_manager


def _research(topic: str, depth: str = "standard") -> Dict[str, Any]:
    """Indirection so tests can patch without importing the real engine."""
    from research_engine import research as engine_research
    return engine_research(topic, depth=depth)


def _depth_for_plan(plan: ExecutionPlan) -> str:
    """Map plan priority/modifiers to research_engine depth strings."""
    for step in plan.steps:
        args = step.get("args", {}) or {}
        prio = args.get("priority")
        if prio == "speed":
            return "quick"
        if prio == "care":
            return "deep"
    return "standard"


def execute(plan: ExecutionPlan) -> Dict[str, Any]:
    """Run a research step from an ExecutionPlan and deliver the result."""
    if not plan.steps:
        return {"executed": False, "action": None, "reason": "empty_plan"}

    primary_step = plan.steps[0]
    action = primary_step.get("action")

    if action != "research":
        return {"executed": False, "action": action, "reason": "not_research"}

    args = primary_step.get("args", {}) or {}
    topic = args.get("topic") or args.get("query") or ""
    if not topic:
        return {"executed": False, "action": action, "reason": "missing_topic"}

    depth = _depth_for_plan(plan)

    try:
        raw = _research(topic, depth=depth)
    except Exception as e:
        try:
            with open("ultron_log.txt", "a") as f:
                f.write(f"[phase2a][research_error] {e!r} topic={topic!r}\n")
        except Exception:
            pass
        return {"executed": False, "action": action, "reason": "engine_error", "error": repr(e)}

    report: ResearchReport = report_from_research_dict(topic, raw)

    try:
        research_facts.store_verified_facts(report, min_confidence=0.6)
    except Exception:
        pass

    envelope = DeliveryEnvelope(report=report, route_voice=True, route_card=True)
    delivery_result = delivery_manager.deliver(envelope)

    return {
        "executed": True,
        "action": action,
        "depth": depth,
        "delivery": delivery_result,
        "facts_stored": sum(1 for f in report.facts if f.confidence >= 0.6),
        "ms": report.ms,
    }
