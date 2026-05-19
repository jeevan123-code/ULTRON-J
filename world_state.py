"""
world_state.py — World State Builder for Ultron-J Intelligence Core.
THE CORE PROBLEM THIS SOLVES:
─────────────────────────────────────────────────────────────────
Before this file, the LLM received only:
  [personality prompt] + [last 10 messages] + [basic perception context]
That's 5% of what Ultron actually knows about Jeevan's situation.
After this file, the LLM receives a rich 2000-token snapshot of:
  • What time/day it is
  • System health (RAM, disk)
  • Ultron's current mood + energy
  • Active goals and their status
  • Memories relevant to THIS specific question
  • Upcoming calendar events
  • Life tracking data (sleep, productivity)
  • Predictive engine predictions
  • What's on screen right now
  • Recent behavioral patterns
This is what makes Ultron aware instead of amnesiac.
─────────────────────────────────────────────────────────────────
Author: Jeevan's Ultron-J Intelligence Core
"""
import datetime
import os

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# =============================================================================
# SECTION BUILDERS — each collects one source, fails gracefully
# =============================================================================
def _section_datetime() -> str:
    """Current time, day, date — always inject this."""
    now = datetime.datetime.now()
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    day = days[now.weekday()]
    hour = now.hour

    # Time of day context — Ultron knows if it's morning/night
    if 5 <= hour < 12:
        period = "morning"
    elif 12 <= hour < 17:
        period = "afternoon"
    elif 17 <= hour < 21:
        period = "evening"
    else:
        period = "night"

    return (
        f"🕐 TIME: {day} {now.strftime('%d %B %Y')} — {now.strftime('%H:%M')} IST ({period})\n"
        f"📍 Hyderabad, Telangana, India"
    )


def _section_system() -> str:
    """PC health — RAM, disk, system score."""
    try:
        from system_monitor import get_memory_usage, get_disk_usage, get_system_health_score
        parts = []

        mem = get_memory_usage()
        if mem:
            used = mem.get("used_gb") or mem.get("used", "?")
            total = mem.get("total_gb") or mem.get("total", "?")
            pct = mem.get("percent", "?")
            parts.append(f"RAM {pct}% ({used}/{total}GB)")

        disk = get_disk_usage()
        if disk:
            parts.append(f"Disk {disk.get('percent', '?')}%")

        try:
            health = get_system_health_score()
            if health is not None:
                parts.append(f"Health {health}/100")
        except Exception:
            pass

        return "🖥️ SYSTEM: " + " | ".join(parts) if parts else ""
    except Exception:
        return ""


def _section_mood() -> str:
    """Ultron's current mood and energy level."""
    try:
        from personality import get_personality_status, get_mood_phrase
        status = get_personality_status()
        mood = status.get("mood", "FOCUSED")
        energy = status.get("energy", 1.0)
        energy_pct = int(float(energy) * 100)
        phrase = get_mood_phrase(mood)
        return f"🤖 ULTRON: mood={mood} energy={energy_pct}% — {phrase}"
    except Exception:
        return ""


def _section_goals() -> str:
    """What Ultron is currently working on autonomously."""
    try:
        from decision_engine import get_active_goals
        goals = get_active_goals()
        if not goals:
            return ""
        lines = ["🎯 ACTIVE GOALS:"]
        for g in goals[:4]:
            status = g.get("status", "")
            title = g.get("title", "")
            priority = g.get("priority", "medium").upper()
            lines.append(f"  [{priority}] {title} → {status}")
        return "\n".join(lines)
    except Exception:
        return ""


def _section_memory(question: str = "") -> str:
    """
    Most important section — recall memories relevant to THIS question.
    This is what makes Ultron say 'I remember you mentioned X last week.'
    """
    try:
        from memory import recall_relevant, sqlite_get_facts
        lines = []

        # Semantic recall against the current question
        if question:
            try:
                relevant = recall_relevant(question, top_k=4)
                if relevant:
                    lines.append("🧠 RELEVANT MEMORIES:")
                    for r in relevant[:4]:
                        text = (
                            r.get("text") or
                            r.get("content") or
                            r.get("document") or
                            str(r)
                        )
                        if text and len(text.strip()) > 10:
                            lines.append(f"  • {str(text).strip()[:130]}")
            except Exception:
                pass

        # Recent key facts from SQLite
        try:
            facts = sqlite_get_facts(limit=6)
            if facts:
                lines.append("📌 KEY FACTS:")
                for f in facts[:4]:
                    fact_text = str(f).strip()
                    if len(fact_text) > 10:
                        lines.append(f"  – {fact_text[:110]}")
        except Exception:
            pass

        return "\n".join(lines) if lines else ""
    except Exception:
        return ""


def _section_patterns() -> str:
    """Jeevan's behavioral patterns — work rhythms, habits."""
    try:
        from memory import get_pattern_context
        ctx = get_pattern_context()
        if ctx and len(ctx.strip()) > 20:
            # Trim to avoid token bloat
            return f"📊 PATTERNS:\n{ctx.strip()[:300]}"
        return ""
    except Exception:
        return ""


def _section_calendar() -> str:
    """What's on Jeevan's calendar today and upcoming."""
    try:
        from calendar_integration import get_calendar
        cal = get_calendar()
        if not cal.is_connected:
            return ""

        # Events in next 24 hours
        events = cal.get_events(days_ahead=1)
        if not events:
            return ""

        lines = ["📅 CALENDAR (next 24h):"]
        for e in events[:4]:
            title = e.get("title") or e.get("summary", "?")
            start = e.get("start", "")[:16].replace("T", " ")
            mins_until = e.get("minutes_until")
            suffix = f" (in {mins_until}min!)" if mins_until and mins_until <= 60 else ""
            lines.append(f"  • {start}: {title}{suffix}")
        return "\n".join(lines)
    except Exception:
        return ""


def _section_life() -> str:
    """Sleep + productivity data from life_tracker."""
    try:
        from life_tracker import get_dashboard
        dashboard = get_dashboard()
        briefing = dashboard.get_daily_briefing()
        if briefing and briefing != "Not enough data yet for life insights.":
            return f"❤️ LIFE: {briefing[:250]}"
        return ""
    except Exception:
        return ""


def _section_predictions() -> str:
    """What the predictive engine thinks Jeevan needs right now."""
    try:
        from predictive_engine import get_status
        status = get_status()
        parts = []

        peak_hours = status.get("peak_hours", [])
        if peak_hours:
            hours_str = ", ".join(str(h) for h in peak_hours[:3])
            parts.append(f"Peak productivity hours: {hours_str}:00")

        session = status.get("current_session")
        if session:
            dur = session.get("duration_minutes", 0)
            app = session.get("app", "")
            if dur > 0:
                parts.append(f"Current session: {int(dur)} min on {app}")

        streaks = status.get("habit_streaks", {})
        if streaks:
            top = sorted(streaks.items(), key=lambda x: x[1], reverse=True)[:2]
            for habit, days in top:
                if days >= 2:
                    parts.append(f"{habit}: {days}-day streak")

        if parts:
            return "🔮 PREDICTIONS: " + " | ".join(parts)
        return ""
    except Exception:
        return ""


_SCREEN_SECTION_CACHE = {"text": "", "ts": 0.0}
_SCREEN_SECTION_TTL   = 5.0   # seconds — matches typical screen refresh cadence


def _section_screen() -> str:
    """What's currently on Jeevan's screen — gives massive context.

    Cached for _SCREEN_SECTION_TTL seconds because OCR text doesn't change
    rapidly between requests and the format/preview work was running on every
    /ask. Reduces per-request world_state cost by ~50-100ms.
    """
    import time as _time
    now = _time.time()
    if (now - _SCREEN_SECTION_CACHE["ts"]) < _SCREEN_SECTION_TTL:
        return _SCREEN_SECTION_CACHE["text"]
    try:
        from screen_engine import get_latest_screen_text
        text = get_latest_screen_text()
        if not text or len(text.strip()) < 30:
            result = ""
        else:
            preview = text.strip()[:200].replace("\n", " ").replace("  ", " ")
            result = f"🖥️ ON SCREEN: {preview}"
    except Exception:
        result = ""
    _SCREEN_SECTION_CACHE["text"] = result
    _SCREEN_SECTION_CACHE["ts"]   = now
    return result


def _section_code_context(question: str) -> str:
    """Inject relevant code chunks when the question is about Ultron's codebase."""
    try:
        from code_index import get_code_context
        ctx = get_code_context(question, max_chars=1200)
        return ctx if ctx else ""
    except Exception:
        return ""


# =============================================================================
# MAIN BUILDER
# =============================================================================
def build_world_state(question: str = "", max_chars: int = 2200) -> str:
    """
    Build the complete world state string for LLM context injection.
    Called before EVERY LLM response. Collects from all available
    data sources and compresses into a rich context block.

    Args:
        question: Current question (used for semantic memory recall)
        max_chars: Token budget — stays under this limit

    Returns:
        Multi-line context string ready to inject into system prompt.
        Returns empty string if all modules fail (safe fallback).
    """
    # Run all sections — each fails independently
    sections = [
        _section_datetime(),
        _section_system(),
        _section_mood(),
        _section_goals(),
        _section_memory(question),
        _section_calendar(),
        _section_life(),
        _section_predictions(),
        _section_screen(),
        _section_patterns(),
        _section_code_context(question),
    ]

    # Filter empty
    filled = [s.strip() for s in sections if s and s.strip()]
    if not filled:
        return ""

    state = "\n\n".join(filled)

    # Hard cap — never waste too many tokens on context
    if len(state) > max_chars:
        state = state[:max_chars] + "\n[...context capped]"

    return state


def build_world_state_header(question: str = "") -> str:
    """
    Returns the world state wrapped in clear delimiters for system prompt injection.
    """
    state = build_world_state(question)
    if not state:
        return ""
    return (
        "\n\n"
        "━━━━━━━━━━━━━━━ ULTRON WORLD STATE ━━━━━━━━━━━━━━━\n"
        f"{state}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
