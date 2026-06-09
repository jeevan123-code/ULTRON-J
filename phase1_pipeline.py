"""Phase 1 pipeline — public wrapper that composes the three foundation modules.

Single-call entry point used by voice_engine and any other consumer.
"""
from typing import Any, Dict, Optional

from compound_intent_parser import parse
import conversation_intelligence as ci
import reasoning_layer as rl
from intent_types import ExecutionPlan, ParsedUtterance


def process_user_utterance(
    raw: str,
    context: Optional[Dict[str, Any]] = None,
    last_action: Optional[Dict[str, Any]] = None,
) -> ExecutionPlan:
    """Run an utterance through parse -> enrich -> plan and return the ExecutionPlan.

    Args:
        raw: The raw text utterance (post-STT or typed input).
        context: Conversation context for reference resolution (e.g. recent_topics).
        last_action: The most recently proposed action awaiting confirmation, if any.
    """
    context = context or {}

    # Phase 5f: intercept teach utterances + resolve known shortcuts.
    # Flag-gated; failure silently falls back to the original context.
    import os as _os_p5f
    if _os_p5f.environ.get("ULTRON_PHASE5F_ENABLED", "0") == "1":
        try:
            from phase5f_shortcut_hook import apply as _p5f_apply
            context = _p5f_apply(raw, context)
        except Exception:
            pass

    parsed: ParsedUtterance = parse(raw)
    enriched: ParsedUtterance = ci.enrich(parsed, context)
    plan: ExecutionPlan = rl.plan(enriched, last_action=last_action)
    return plan
