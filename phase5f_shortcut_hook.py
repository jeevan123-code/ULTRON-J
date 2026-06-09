"""Phase 5f hook — applies shortcut learning + resolution to a raw utterance.

Pure helper. Single public function `apply(raw, context)` that:
  1. Parses `raw` for a teach utterance and persists it to the registry.
  2. Resolves any known shortcuts present in `raw`.
  3. Returns a NEW context dict (never mutates the input) with the resolved
     shortcuts under the "shortcuts" key.
"""
import time
from typing import Any, Dict, Optional

import shortcut_registry
from shortcut_inferrer import parse_teach_utterance, resolve_in_text
from shortcut_types import Shortcut


def _now() -> float:
    return time.time()


def apply(raw: str, context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Run shortcut learning + resolution. Returns a new context dict."""
    new_context: Dict[str, Any] = dict(context or {})

    # 1) Intercept teach utterances.
    just_taught_term: Optional[str] = None
    parsed = parse_teach_utterance(raw or "")
    if parsed is not None:
        term, canonical = parsed
        try:
            shortcut_registry.teach(Shortcut(
                term=term, canonical=canonical, confidence=1.0,
                created_at=_now(), taught_explicitly=True,
            ))
            just_taught_term = term.strip().lower()
        except Exception:
            pass

    # 2) Enrich context with any resolved shortcuts found in the utterance,
    #    excluding any term we just taught in this same utterance (the teach
    #    sentence is meta-conversation, not a usage of the shortcut).
    resolved = resolve_in_text(raw or "")
    if just_taught_term is not None:
        resolved.pop(just_taught_term, None)
    new_context["shortcuts"] = resolved
    return new_context
