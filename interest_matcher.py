"""Phase 6 interest matcher — pure logic, no I/O beyond reading interests.json.

`load_interests()` reads the explicit `interests.json` file if present.
If the file is missing (or unreadable), falls back to keywords mined from
`conversation_listener.snapshot()` — recent utterances become the interest
set so the poller still has something to match against.

`match(events, interests)` scores each event by how many interest
keywords appear in its title + summary, returns sorted desc, drops
zero-score events.
"""
import json
import os
import re
from typing import Any, Dict, List

from world_event_types import WorldEvent


_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(_BASE_DIR, "interests.json")

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_]{2,}")
_STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "you", "yours", "your",
    "from", "have", "has", "are", "was", "were", "but", "not", "all",
    "ultron", "claude", "jarvis", "thinking", "about", "want", "need",
}


def _listener_snapshot() -> List[Dict[str, Any]]:
    """Indirection so tests can stub without importing the real listener."""
    try:
        import conversation_listener as _cl
        return _cl.snapshot()
    except Exception:
        return []


def _extract_keywords_from_text(text: str) -> List[str]:
    if not text:
        return []
    tokens = _TOKEN_RE.findall(text.lower())
    out: List[str] = []
    for t in tokens:
        if t in _STOPWORDS:
            continue
        if t not in out:
            out.append(t)
    return out


def load_interests() -> List[str]:
    """Read interests.json if present; otherwise mine from conversation_listener."""
    if os.path.exists(_PATH):
        try:
            with open(_PATH) as f:
                data = json.load(f)
            if isinstance(data, list):
                return [str(x) for x in data if str(x).strip()]
        except Exception:
            pass

    # Fall-back: mine recent utterances
    snap = _listener_snapshot() or []
    merged: List[str] = []
    for u in snap:
        for kw in _extract_keywords_from_text(u.get("text", "")):
            if kw not in merged:
                merged.append(kw)
    return merged


def _score_event(event: WorldEvent, interests_lower: List[str]) -> float:
    haystack = f"{event.title} {event.summary}".lower()
    hits = 0
    for kw in interests_lower:
        if not kw:
            continue
        hits += haystack.count(kw)
    if hits == 0:
        return 0.0
    # Map raw count to (0,1] with a soft cap so very high counts saturate.
    return min(1.0, 0.2 + 0.1 * hits)


def match(events: List[WorldEvent], interests: List[str]) -> List[WorldEvent]:
    """Score events; return those with score > 0, sorted desc."""
    if not interests:
        return []
    interests_lower = [str(k).strip().lower() for k in interests if str(k).strip()]
    if not interests_lower:
        return []
    scored: List[WorldEvent] = []
    for ev in events:
        s = _score_event(ev, interests_lower)
        if s > 0.0:
            ev.score = s
            scored.append(ev)
    scored.sort(key=lambda e: e.score, reverse=True)
    return scored
