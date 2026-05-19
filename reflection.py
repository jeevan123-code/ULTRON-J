"""
reflection.py — Ultron-J's Self-Reflection Engine. NEW MODULE.

What this adds:
- Periodic self-reflection: Ultron analyzes its own performance
- Performance metrics: which goals succeeded, which failed, and why
- Automatic improvement proposals: concrete suggestions to improve Ultron-J's code
- Pattern recognition: learns what types of tasks Ultron does well vs poorly
- Session summaries: after each conversation, builds a summary for memory
- Daily digest generation: end-of-day performance report
- Skill gap identification: what capabilities Ultron is missing

This is how Ultron-J grows over time. It doesn't just execute — it learns
from every action and proposes real, concrete code improvements.
"""

import datetime
import json
import os
import threading
from typing import Optional

from config import (
    REFLECTION_FILE, REFLECTION_MAX,
    REFLECT_AFTER_N_GOALS, REFLECT_INTERVAL_HOURS,
    REFLECTION_TOPICS, JEEVAN_NAME, AGENT_NAME,
)
from decision_engine import (
    get_execution_log, load_agent_state, save_agent_state,
    load_goals, GoalStatus,
)
from memory import atomic_json_write

# ── Thread safety ─────────────────────────────────────────────────────────────
_reflection_lock = threading.Lock()

# =============================================================================
# REFLECTION STORAGE
# =============================================================================

def load_reflections() -> list:
    if os.path.exists(REFLECTION_FILE):
        try:
            with open(REFLECTION_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_reflections(reflections: list):
    with _reflection_lock:
        atomic_json_write(REFLECTION_FILE, reflections[-REFLECTION_MAX:])


def add_reflection(
    kind:       str,    # "performance", "session", "daily", "skill_gap", "improvement"
    content:    str,
    metrics:    dict = None,
    proposals:  list = None,
):
    """Store a reflection entry."""
    reflections = load_reflections()
    reflections.append({
        "id":        f"ref_{len(reflections)}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}",
        "kind":      kind,
        "content":   content[:2000],
        "metrics":   metrics or {},
        "proposals": proposals or [],
        "at":        datetime.datetime.now().isoformat(),
    })
    save_reflections(reflections)


def get_recent_reflections(n: int = 5, kind: str = "") -> list:
    reflections = load_reflections()
    if kind:
        reflections = [r for r in reflections if r.get("kind") == kind]
    return reflections[-n:]

# =============================================================================
# PERFORMANCE ANALYSIS
# =============================================================================

def analyze_performance() -> dict:
    """
    Analyze recent execution performance.
    Returns structured metrics.
    """
    goals   = load_goals()
    log     = get_execution_log(50)
    now     = datetime.datetime.now()
    today   = now.strftime("%Y-%m-%d")

    # Goal stats
    all_completed = [g for g in goals if g["status"] == GoalStatus.COMPLETED]
    all_failed    = [g for g in goals if g["status"] == GoalStatus.FAILED]
    completed_today = [
        g for g in all_completed
        if g.get("completed_at", "").startswith(today)
    ]

    # Execution log stats
    total_actions  = len(log)
    success_count  = sum(1 for e in log if e.get("success"))
    success_rate   = round(success_count / max(total_actions, 1) * 100, 1)

    # Tool performance
    tool_stats = {}
    for entry in log:
        action = entry.get("action", "unknown")
        tool_stats[action] = tool_stats.get(action, {"success": 0, "fail": 0})
        if entry.get("success"):
            tool_stats[action]["success"] += 1
        else:
            tool_stats[action]["fail"] += 1

    best_tools  = sorted(
        [(t, s["success"] / max(s["success"] + s["fail"], 1)) for t, s in tool_stats.items()],
        key=lambda x: x[1], reverse=True
    )[:3]
    worst_tools = sorted(
        [(t, s["fail"] / max(s["success"] + s["fail"], 1)) for t, s in tool_stats.items()],
        key=lambda x: x[1], reverse=True
    )[:3]

    # Average execution score
    scored_goals = [g for g in all_completed if g.get("execution_score") is not None]
    avg_score    = round(
        sum(g["execution_score"] for g in scored_goals) / max(len(scored_goals), 1), 1
    )

    return {
        "total_goals_ever":     len(goals),
        "completed_ever":       len(all_completed),
        "failed_ever":          len(all_failed),
        "completed_today":      len(completed_today),
        "success_rate_pct":     success_rate,
        "total_actions_logged": total_actions,
        "avg_execution_score":  avg_score,
        "best_tools":           best_tools,
        "worst_tools":          worst_tools,
        "tool_stats":           tool_stats,
        "analyzed_at":          now.isoformat(),
    }


def identify_skill_gaps(metrics: dict) -> list:
    """
    Based on performance metrics, identify what capabilities Ultron lacks.
    Returns a list of skill gap descriptions.
    """
    gaps = []

    # High failure rate
    if metrics.get("success_rate_pct", 100) < 70:
        gaps.append("High action failure rate — consider adding more error handling and retry logic")

    # Worst tools
    for tool, failure_rate in metrics.get("worst_tools", []):
        if failure_rate > 0.5:
            gaps.append(f"Tool '{tool}' failing >50% — investigate and improve implementation")

    # Low execution score
    if metrics.get("avg_execution_score", 10) < 5:
        gaps.append("Low execution scores — goals completing but not achieving full quality")

    # No search tools working
    tool_stats = metrics.get("tool_stats", {})
    if not tool_stats.get("search_web") and not tool_stats.get("search_local"):
        gaps.append("Web search not being used — verify SearXNG and DDG integrations")

    if not gaps:
        gaps.append("No significant skill gaps detected — performance nominal")

    return gaps


def generate_improvement_proposals(metrics: dict, skill_gaps: list) -> list:
    """
    Generate concrete, actionable improvement proposals.
    These can be reviewed by Jeevan and applied to the codebase.
    """
    proposals = []

    # Based on worst tools
    for tool, failure_rate in metrics.get("worst_tools", []):
        if failure_rate > 0.4:
            proposals.append({
                "type":        "tool_fix",
                "priority":    "high",
                "title":       f"Improve '{tool}' tool reliability",
                "description": (
                    f"Tool '{tool}' is failing {round(failure_rate*100)}% of the time. "
                    f"Add better error handling, fallback logic, and input validation."
                ),
                "target_file": "action_engine.py",
            })

    # Generic proposals based on usage
    if not tool_stats_has("web_scrape", metrics):
        proposals.append({
            "type":        "new_capability",
            "priority":    "medium",
            "title":       "Enable web scraping",
            "description": "Install BeautifulSoup4 to enable full web scraping: pip install beautifulsoup4",
            "target_file": "requirements.txt",
        })

    if metrics.get("completed_today", 0) == 0:
        proposals.append({
            "type":        "process",
            "priority":    "low",
            "title":       "No goals completed today",
            "description": "Consider reviewing the goal queue. Goals may be blocked or not set correctly.",
            "target_file": None,
        })

    # Cap at 5 proposals per reflection
    return proposals[:5]


def tool_stats_has(tool: str, metrics: dict) -> bool:
    return tool in metrics.get("tool_stats", {})

# =============================================================================
# SESSION SUMMARY
# =============================================================================

def generate_session_summary(
    session_id:     str,
    conversation:   list,
    goals_created:  list = None,
    mode:           str  = "cloud",
) -> dict:
    """
    Build a summary of what happened in a conversation session.
    Stored in episodic memory.
    """
    now      = datetime.datetime.now()
    n_turns  = len(conversation)
    topics   = _extract_session_topics(conversation)
    goals    = goals_created or []

    summary = {
        "session_id":   session_id,
        "at":           now.isoformat(),
        "duration_hint": f"{n_turns} turns",
        "mode":         mode,
        "topics":       topics[:5],
        "goals_created": len(goals),
        "goal_titles":   [g.get("title", "") for g in goals[:3]],
        "summary":       _build_session_summary_text(n_turns, topics, goals, mode),
    }
    return summary


def _extract_session_topics(conversation: list) -> list:
    """Extract likely topics from a conversation."""
    from collections import Counter
    import re
    text  = " ".join(m.get("content", "") for m in conversation if m.get("role") == "user")
    words = re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())
    stop  = {"that", "this", "with", "from", "have", "what", "when", "where",
              "will", "your", "about", "just", "like", "into", "then", "than",
              "some", "they", "also", "been", "more", "very", "want", "need"}
    filtered = [w for w in words if w not in stop]
    counts   = Counter(filtered)
    return [word for word, _ in counts.most_common(5)]


def _build_session_summary_text(
    n_turns: int, topics: list, goals: list, mode: str
) -> str:
    parts = [f"Session with {n_turns} exchanges in {mode} mode."]
    if topics:
        parts.append(f"Topics covered: {', '.join(topics)}.")
    if goals:
        parts.append(f"Created {len(goals)} goal(s): {', '.join(g.get('title', '')[:30] for g in goals[:3])}.")
    return " ".join(parts)

# =============================================================================
# REFLECTION RUNNER
# =============================================================================

def run_reflection() -> dict:
    """
    Run a complete self-reflection cycle.
    Analyzes performance, identifies gaps, generates proposals.
    Returns the full reflection result.
    """
    metrics  = analyze_performance()
    gaps     = identify_skill_gaps(metrics)
    proposals = generate_improvement_proposals(metrics, gaps)

    # Build reflection content
    content_lines = [
        f"Performance Analysis — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Success rate: {metrics['success_rate_pct']}%",
        f"Goals completed today: {metrics['completed_today']}",
        f"Avg execution score: {metrics['avg_execution_score']}/10",
        "",
        "Skill gaps identified:",
    ]
    for gap in gaps:
        content_lines.append(f"  • {gap}")
    if proposals:
        content_lines.append("")
        content_lines.append("Improvement proposals:")
        for p in proposals:
            content_lines.append(f"  [{p['priority'].upper()}] {p['title']}: {p['description']}")

    content = "\n".join(content_lines)

    add_reflection(
        kind="performance",
        content=content,
        metrics=metrics,
        proposals=proposals,
    )

    # Store proposals to the system monitor proposals file
    try:
        from system_monitor import add_proposal
        for p in proposals:
            add_proposal(
                title=p["title"],
                description=p["description"],
                target_file=p.get("target_file", ""),
            )
    except Exception:
        pass

    # Update personality state with reflection timestamp
    try:
        from personality import load_personality_state, save_personality_state
        state = load_personality_state()
        state["last_reflection"] = datetime.datetime.now().isoformat()
        save_personality_state(state)
    except Exception:
        pass

    return {
        "metrics":   metrics,
        "gaps":      gaps,
        "proposals": proposals,
        "content":   content,
    }


def should_reflect() -> bool:
    """
    Check if it's time to run a reflection cycle.
    Triggers: every N goals completed OR every N hours.
    """
    reflections = load_reflections()
    if not reflections:
        return True

    last = reflections[-1]
    last_at = last.get("at", "")
    if not last_at:
        return True

    try:
        last_dt  = datetime.datetime.fromisoformat(last_at)
        hours_since = (datetime.datetime.now() - last_dt).total_seconds() / 3600
        if hours_since >= REFLECT_INTERVAL_HOURS:
            return True
    except Exception:
        pass

    # Check if enough goals have completed since last reflection
    goals    = load_goals()
    completed = [g for g in goals if g["status"] == GoalStatus.COMPLETED]
    if len(completed) >= REFLECT_AFTER_N_GOALS:
        # Check if reflection already happened after these goals
        recent_reflection = reflections[-1].get("metrics", {})
        prev_completed    = recent_reflection.get("completed_ever", 0)
        if len(completed) - prev_completed >= REFLECT_AFTER_N_GOALS:
            return True

    return False


def get_reflection_summary() -> str:
    """
    Return a brief summary of the latest reflection for the UI.
    """
    reflections = load_reflections()
    if not reflections:
        return "No reflections yet."
    last = reflections[-1]
    metrics = last.get("metrics", {})
    return (
        f"Last reflection: {last['at'][:16]} | "
        f"Success rate: {metrics.get('success_rate_pct', '?')}% | "
        f"Goals completed: {metrics.get('completed_ever', 0)} total"
    )
