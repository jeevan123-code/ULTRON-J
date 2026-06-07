"""Topic Detector — LLM filter that decides which utterances are worth researching.

Given a list of recent utterances, returns a list of zero or more
{"name": str, "priority": int 1..5, "reason": str} topics.
"""
import json
from typing import Any, Dict, List


def _llm_ask(prompt: str, **kwargs) -> str:
    from llm_engine import ask
    return ask(prompt, **kwargs)


_PROMPT = """TOPIC_DETECTOR: {joined}

You are JARVIS — a personal AI deciding whether to autonomously research
topics that came up in your principal's conversation. Pull at most 3 topics
that are SPECIFIC enough to research and would benefit your principal to
know more about (people, events, technical concepts, organisations, places).
Skip generic chit-chat, well-known nouns, and ambiguous references.

Respond ONLY with JSON: {{"topics": [{{"name": "<topic>", "priority": <1-5>, "reason": "<short>"}}, ...]}}

Priority guide:
 5 = directly actionable (upcoming meeting / appointment / event)
 4 = mentioned by name with intent to learn
 3 = casually mentioned proper noun worth knowing about
 2 = generic concept; nice to have
 1 = mostly skip
"""


def detect_topics(utterances: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return up to 3 research-worthy topics extracted from the utterances."""
    if not utterances:
        return []
    joined = " ".join(u.get("text", "") for u in utterances if u.get("text"))
    if not joined.strip():
        return []
    try:
        resp = _llm_ask(_PROMPT.format(joined=joined))
        data = json.loads(resp)
        out: List[Dict[str, Any]] = []
        for t in data.get("topics", [])[:3]:
            name = (t.get("name") or "").strip()
            if not name:
                continue
            prio = t.get("priority", 1)
            try:
                prio = max(1, min(5, int(prio)))
            except Exception:
                prio = 1
            out.append({"name": name, "priority": prio, "reason": t.get("reason", "")})
        return out
    except Exception:
        return []
