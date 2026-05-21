"""
jeevan_model.py — Living Jeevan Profile for Ultron-J Intelligence Core.
THE CORE PROBLEM THIS SOLVES:
─────────────────────────────────────────────────────────────────
Every conversation, Ultron starts with zero understanding of WHO
Jeevan is as a person — how he thinks, what frustrates him, what
he values, how he communicates.

This file makes Ultron maintain a continuously updated model of
Jeevan that gets injected into EVERY prompt — so Ultron responds
as if it's known Jeevan for years, not just the last 10 messages.

How it works:
─────────────────────────────────────────────────────────────────
1. Starts with a hand-crafted default profile (accurate as of now)
2. Every UPDATE_EVERY conversations, the LLM reads recent messages
   and updates the profile in its own words
3. Profile is saved to jeevan_model.json and persists forever
4. Compressed version injected into every system prompt

What it tracks:
  • Thinking style (how he approaches problems)
  • Work patterns (when/how he works best)
  • Communication preferences (tone, depth, format)
  • Current focus (what he's obsessed with right now)
  • Decision style (how he evaluates options)
  • Frustrations (what bothers him about AI)
  • Values (what he cares about most)
─────────────────────────────────────────────────────────────────
Author: Jeevan's Ultron-J Intelligence Core
"""
import json
import os
import threading
from datetime import datetime
from typing import Optional

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_FILE = os.path.join(_BASE_DIR, "jeevan_model.json")
_lock = threading.Lock()

# Update the profile every N conversations
UPDATE_EVERY = 4

# =============================================================================
# DEFAULT PROFILE
# Accurately represents Jeevan as I know him.
# LLM will enrich this over time with real observations.
# =============================================================================
DEFAULT_PROFILE = {
    "name": "Jeevan",
    "location": "Hyderabad, Telangana, India",
    "background": (
        "BSc Agriculture graduate. Self-taught developer and AI builder. "
        "Former experience at a fruit company. "
        "Building Ultron-J as a personal AI assistant project. "
        "Interests: AI, agri-tech, content creation (YouTube/ResinCraft)."
    ),
    "thinking_style": (
        "Systems-oriented builder. Iterates in layers — gets something working "
        "then goes deeper. Cross-references Claude and ChatGPT outputs critically. "
        "Has caught AI fabricating bugs that don't exist. Validates before trusting."
    ),
    "work_patterns": (
        "Independently self-teaches. Works in intensive focused sessions on one project. "
        "Currently dominant focus is Ultron-J. Works from desktop at home."
    ),
    "communication": (
        "Direct and technical. Wants concrete answers, not theoretical fluff. "
        "Prefers honest analysis over hype. Asks sharp, specific questions. "
        "Doesn't want to be talked down to."
    ),
    "current_focus": (
        "Making Ultron-J the most intelligent personal AI possible. "
        "Specifically: wants it to reason like Jarvis, not just answer like a chatbot. "
        "The intelligence gap between Ultron and Jarvis is his #1 concern right now."
    ),
    "frustrations": (
        "AI that sounds smart but doesn't reason. "
        "Feature count masquerading as intelligence. "
        "Generic answers that don't account for his specific context. "
        "Suggestions that are theoretically correct but wrong for his situation."
    ),
    "values": (
        "Real intelligence over feature count. "
        "Honest assessment over reassurance. "
        "Deep understanding over surface solutions. "
        "Building something that genuinely helps, not just impressively complex."
    ),
    "decision_style": (
        "Evaluates tradeoffs before committing. Wants to understand WHY before implementing. "
        "Prefers to see options with honest pros/cons rather than a single recommendation. "
        "Will push back if something doesn't make sense."
    ),
    "projects": [
        "Ultron-J — personal AI assistant (primary focus)",
        "EyeOS — eye-tracking phone control app (accessibility)",
        "Vanaj AI — 3D Indian plant species library for students",
        "ResinCraft Nest — YouTube resin craft content",
    ],
    "last_updated": None,
    "conversation_count": 0,
    "version": 1,
}


# =============================================================================
# PERSISTENCE
# =============================================================================
def load_profile() -> dict:
    """Load the Jeevan model from disk. Returns default if not found."""
    with _lock:
        if not os.path.exists(MODEL_FILE):
            return dict(DEFAULT_PROFILE)
        try:
            with open(MODEL_FILE, "r", encoding="utf-8") as f:
                stored = json.load(f)
            # Merge with defaults to include any new fields added in updates
            merged = dict(DEFAULT_PROFILE)
            merged.update(stored)
            return merged
        except Exception:
            return dict(DEFAULT_PROFILE)


def save_profile(profile: dict):
    """Persist the Jeevan model to disk."""
    with _lock:
        try:
            from memory import atomic_json_write
            profile["last_updated"] = datetime.now().isoformat()
            atomic_json_write(MODEL_FILE, profile)
        except Exception:
            pass


# =============================================================================
# CONVERSATION COUNTER
# =============================================================================
def increment_conversation_count() -> int:
    """Increment and return the conversation counter."""
    profile = load_profile()
    count = profile.get("conversation_count", 0) + 1
    profile["conversation_count"] = count
    save_profile(profile)
    return count


def should_update_profile() -> bool:
    """Return True if it's time for an LLM-driven profile update."""
    profile = load_profile()
    count = profile.get("conversation_count", 0)
    return count > 0 and count % UPDATE_EVERY == 0


# =============================================================================
# LLM-DRIVEN PROFILE UPDATE
# =============================================================================
def update_profile_async(session_id: str = "default"):
    """
    Trigger an async profile update in the background.
    Called after every UPDATE_EVERY conversations — non-blocking.
    """
    def _update():
        try:
            from memory import sqlite_get_history
            # Get last 30 messages across sessions
            recent = sqlite_get_history(session_id, limit=30)
            if len(recent) < 5:
                return
            _do_update_with_llm(recent)
        except Exception:
            pass

    t = threading.Thread(target=_update, daemon=True, name="jeevan_model_update")
    t.start()


def _do_update_with_llm(recent_messages: list) -> bool:
    """
    Use the LLM to update the Jeevan model based on recent conversations.
    The LLM observes patterns and updates its understanding.

    Args:
        recent_messages: List of (role, content) tuples from SQLite

    Returns:
        True if update was successful
    """
    try:
        from llm_engine import call_llm_batch
        current = load_profile()

        # Get last 20 user messages as conversation sample
        user_msgs = [m[1] for m in recent_messages if m[0] == "user"][-20:]
        sample = "\n".join(f"  • {m[:120]}" for m in user_msgs)

        prompt = f"""Analyze these recent conversation messages from Jeevan and update his behavioral profile.

Current profile:
- Thinking style: {current.get('thinking_style', '')}
- Work patterns: {current.get('work_patterns', '')}
- Communication: {current.get('communication', '')}
- Current focus: {current.get('current_focus', '')}
- Frustrations: {current.get('frustrations', '')}
- Values: {current.get('values', '')}
- Decision style: {current.get('decision_style', '')}

Recent messages from Jeevan:
{sample}

Based on these messages, provide UPDATED values for each field. Only update if you see evidence of change.
Keep each field to 1-2 sentences.

Return ONLY valid JSON with exactly these keys:
thinking_style, work_patterns, communication, current_focus, frustrations, values, decision_style

No markdown. No explanation. Only the JSON object."""

        response = call_llm_batch(
            prompt,
            system=(
                "You analyze conversation patterns and output only valid JSON. "
                "No markdown. No backticks. No explanation. Pure JSON only."
            )
        )

        if not response or len(response) < 20:
            return False

        # Clean and parse
        clean = response.strip()
        if "```" in clean:
            lines = clean.split("\n")
            inner = [l for l in lines if not l.startswith("```")]
            clean = "\n".join(inner)

        # Find JSON object
        start = clean.find("{")
        end = clean.rfind("}") + 1
        if start == -1 or end == 0:
            return False

        updates = json.loads(clean[start:end])

        # Apply non-empty updates
        profile = load_profile()
        updatable = [
            "thinking_style", "work_patterns", "communication",
            "current_focus", "frustrations", "values", "decision_style"
        ]
        changed = False
        for key in updatable:
            val = updates.get(key, "").strip()
            if val and len(val) > 10:
                profile[key] = val
                changed = True

        if changed:
            profile["version"] = profile.get("version", 1) + 1
            save_profile(profile)

        return changed

    except Exception:
        return False


# =============================================================================
# PROMPT INJECTION
# =============================================================================
def get_profile_for_prompt() -> str:
    """
    Returns the Jeevan model as a compressed, injection-ready string.
    Formatted to maximize LLM comprehension with minimum tokens.
    This is what gets injected into EVERY system prompt.
    """
    p = load_profile()
    lines = [
        "━━━━━━━━━━ WHO YOU'RE TALKING TO ━━━━━━━━━━",
        f"Name: {p.get('name', 'Jeevan')} | Location: {p.get('location', 'Hyderabad, India')}",
        f"Background: {p.get('background', '')}",
        f"Thinking: {p.get('thinking_style', '')}",
        f"Work: {p.get('work_patterns', '')}",
        f"Comms: {p.get('communication', '')}",
        f"Focus NOW: {p.get('current_focus', '')}",
        f"Frustrations: {p.get('frustrations', '')}",
        f"Values: {p.get('values', '')}",
        f"Decisions: {p.get('decision_style', '')}",
    ]
    projects = p.get("projects", [])
    if projects:
        lines.append("Projects: " + " | ".join(projects[:3]))
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def get_profile_summary() -> dict:
    """Return the full profile as a dict (for API endpoints)."""
    return load_profile()
