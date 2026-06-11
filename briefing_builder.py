"""Phase 6 briefing builder — compose briefing text from multiple sources.

Pure assembly. Pulls top worldfeed items + research_queue jobs + recent
goals into a compact markdown-ish string. Each data accessor is a small
indirection so tests can stub without importing the real modules.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List


def _worldfeed_recent(**kw) -> List[Any]:
    try:
        import worldfeed_store
        return worldfeed_store.recent(**kw)
    except Exception:
        return []


def _research_queue_snapshot() -> List[Dict[str, Any]]:
    try:
        import research_queue
        return research_queue.snapshot()
    except Exception:
        return []


def _recent_goals() -> List[str]:
    try:
        import autonomous_goal as ag  # type: ignore
        if hasattr(ag, "recent_goals"):
            return [str(g) for g in ag.recent_goals()]
    except Exception:
        pass
    return []


def _format_world_section(events: List[Any]) -> str:
    if not events:
        return ""
    lines = ["**World pulse:**"]
    for ev in events:
        title = getattr(ev, "title", "")
        score = getattr(ev, "score", 0.0)
        if not title:
            continue
        lines.append(f"- {title} _(score {score:.2f})_")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def _format_research_section(jobs: List[Dict[str, Any]]) -> str:
    if not jobs:
        return ""
    top = sorted(jobs, key=lambda j: j.get("priority", 0), reverse=True)[:3]
    lines = ["**On the research queue:**"]
    for j in top:
        topic = j.get("topic", "")
        priority = j.get("priority", 0)
        if not topic:
            continue
        lines.append(f"- {topic} _(priority {priority})_")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def _format_goals_section(goals: List[str]) -> str:
    if not goals:
        return ""
    lines = ["**Recent goals:**"]
    for g in goals[:3]:
        lines.append(f"- {g}")
    return "\n".join(lines)


def _greeting(now: float) -> str:
    dt = datetime.fromtimestamp(now, tz=timezone.utc)
    hour = dt.hour
    if hour < 12:
        tod = "morning"
    elif hour < 17:
        tod = "afternoon"
    else:
        tod = "evening"
    return f"Good {tod}. Here's your briefing for {dt.strftime('%A, %B %d')}:"


def compose(now: float,
            include_worldfeed: bool = True,
            max_chars: int = 2000) -> str:
    """Assemble briefing text. Returns at most `max_chars` characters."""
    sections: List[str] = [_greeting(now)]

    if include_worldfeed:
        events = _worldfeed_recent(now=now, within_seconds=24 * 3600, top_n=5)
        world = _format_world_section(events)
        if world:
            sections.append(world)

    jobs = _research_queue_snapshot()
    research = _format_research_section(jobs)
    if research:
        sections.append(research)

    goals = _recent_goals()
    goals_text = _format_goals_section(goals)
    if goals_text:
        sections.append(goals_text)

    out = "\n\n".join(sections)
    if len(out) > max_chars:
        out = out[:max_chars - 14].rstrip() + "\n_(truncated)_"
    return out
