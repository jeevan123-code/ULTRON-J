"""
personal_facts.py — Persistent personal facts store for Ultron-J.

Extracts and stores structured personal facts from conversations so Ultron
remembers things like "favourite colour is electric blue" even when asked
indirectly ("what colours do I like?") a week later.

Storage: personal_facts.json  (key-value pairs, timestamped, deduplicated)
Extraction: LLM-based (Groq, async background thread — never blocks response)
Retrieval: always injects ALL facts (small set) + semantic similarity scoring
"""

import json
import os
import re
import threading
import time
from datetime import datetime
from typing import List, Dict, Optional

_BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
_FACTS_FILE = os.path.join(_BASE_DIR, "personal_facts.json")
_lock = threading.Lock()

# ── Fact extraction prompt ────────────────────────────────────────────────────
_EXTRACT_PROMPT = """You are a personal fact extractor. Read the user's message below.
Extract ONLY concrete personal facts the user revealed about themselves.

Rules:
- Only extract facts explicitly stated, never infer or guess
- Each fact = one line: CATEGORY: specific fact
- Categories: preference, habit, goal, location, relationship, opinion, work, health, other
- Skip questions, commands, generic statements
- Max 3 facts per message, only the most specific ones
- If no personal facts, reply: NONE

User message: {message}

Facts (or NONE):"""

# ── Storage helpers ───────────────────────────────────────────────────────────

def _load() -> List[Dict]:
    if not os.path.exists(_FACTS_FILE):
        return []
    try:
        with open(_FACTS_FILE, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(facts: List[Dict]):
    with open(_FACTS_FILE, "w", encoding="utf-8") as f:
        json.dump(facts, f, indent=2, ensure_ascii=False)


# ── Core operations ───────────────────────────────────────────────────────────

def store_fact(raw_text: str, category: str = "other") -> bool:
    """
    Store a personal fact. Deduplicates by normalized text.
    Returns True if it was new, False if already known.
    """
    raw_text = raw_text.strip()
    if not raw_text or len(raw_text) < 5:
        return False

    normalized = raw_text.lower().strip(" .,!?")

    with _lock:
        facts = _load()
        # Deduplicate — if a very similar fact already exists, update timestamp
        for existing in facts:
            if _similar(normalized, existing.get("normalized", "")):
                existing["ts"] = datetime.now().isoformat()
                existing["count"] = existing.get("count", 1) + 1
                _save(facts)
                return False
        facts.append({
            "raw":        raw_text,
            "normalized": normalized,
            "category":   category,
            "ts":         datetime.now().isoformat(),
            "count":      1,
        })
        _save(facts)
    return True


def _similar(a: str, b: str) -> bool:
    """True if strings share ≥60% of words."""
    if not a or not b:
        return False
    wa = set(a.split())
    wb = set(b.split())
    if not wa or not wb:
        return False
    overlap = len(wa & wb) / max(len(wa), len(wb))
    return overlap >= 0.6


def get_all_facts() -> List[Dict]:
    """Return all stored facts, newest first."""
    with _lock:
        facts = _load()
    facts.sort(key=lambda x: x.get("ts", ""), reverse=True)
    return facts


def get_facts_block() -> str:
    """
    Return all personal facts as a formatted block for LLM context injection.
    Returns empty string if no facts stored.
    """
    facts = get_all_facts()
    if not facts:
        return ""
    lines = ["Personal facts about Jeevan (always trust these):"]
    for f in facts:
        cat = f.get("category", "other")
        raw = f.get("raw", "")
        lines.append(f"  [{cat}] {raw}")
    return "\n".join(lines)


def get_relevant_facts(query: str, top_n: int = 10) -> List[str]:
    """
    Return facts relevant to the query using word overlap scoring.
    Always returns facts with score > 0, plus all preference/habit facts.
    """
    facts = get_all_facts()
    if not facts:
        return []

    q_words = set(re.findall(r'\w+', query.lower()))
    scored = []
    for f in facts:
        f_words = set(re.findall(r'\w+', f.get("raw", "").lower()))
        # Score = word overlap + bonus for preference/habit categories
        overlap = len(q_words & f_words)
        bonus = 2 if f.get("category") in ("preference", "habit", "goal") else 0
        scored.append((f["raw"], overlap + bonus))

    scored.sort(key=lambda x: x[1], reverse=True)
    # Return all with any score, plus always include high-value categories
    result = [raw for raw, score in scored if score > 0]
    if not result:
        # If nothing matched, return preference/habit facts anyway
        result = [f["raw"] for f in facts
                  if f.get("category") in ("preference", "habit", "goal")][:top_n]
    return result[:top_n]


# ── LLM-based extraction (runs in background thread) ─────────────────────────

def _call_llm_extract(user_message: str) -> List[tuple]:
    """Call Groq to extract facts. Returns list of (category, fact_text)."""
    try:
        import requests, os as _os
        try:
            from config import GROQ_API_KEY, GROQ_URL
            _groq_model = "llama-3.1-8b-instant"  # fast, cheap model for extraction
        except ImportError:
            GROQ_API_KEY = _os.environ.get("GROQ_API_KEY", "")
            GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
            _groq_model = "llama-3.1-8b-instant"

        if not GROQ_API_KEY:
            return []

        prompt = _EXTRACT_PROMPT.format(message=user_message[:500])
        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": _groq_model, "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 120, "temperature": 0.1},
            timeout=8,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()

        if text.upper().startswith("NONE") or not text:
            return []

        results = []
        for line in text.splitlines():
            line = line.strip().lstrip("-• ").strip()
            if ":" in line:
                parts = line.split(":", 1)
                cat = parts[0].strip().lower().lstrip("-• ").strip()
                fact = parts[1].strip()
                if fact and len(fact) > 4 and cat:
                    results.append((cat, fact))
        return results
    except Exception:
        return []


def _rule_based_extract(user_message: str) -> List[tuple]:
    """
    Fast regex extraction for common personal fact patterns.
    Runs before LLM as a cheap first pass.
    """
    msg = user_message.strip()
    facts = []

    patterns = [
        # Preferences
        (r"my favou?rite\s+(\w+(?:\s+\w+)?)\s+is\s+(.+?)(?:\.|$)", "preference",
         lambda m: f"favourite {m.group(1)} is {m.group(2).strip()}"),
        (r"i (?:love|like|enjoy|prefer)\s+(.+?)(?:\.|$)", "preference",
         lambda m: f"likes/loves: {m.group(1).strip()}"),
        (r"i (?:hate|dislike|don't like|cant stand)\s+(.+?)(?:\.|$)", "preference",
         lambda m: f"dislikes: {m.group(1).strip()}"),
        # Location/place
        (r"i (?:live|stay|am) (?:in|at)\s+(.+?)(?:\.|$)", "location",
         lambda m: f"lives in {m.group(1).strip()}"),
        # Work/study
        (r"i (?:work|am working) (?:at|for|in)\s+(.+?)(?:\.|$)", "work",
         lambda m: f"works at {m.group(1).strip()}"),
        (r"i am (?:a|an)\s+(.+?)(?:\.|$)", "work",
         lambda m: f"is a {m.group(1).strip()}"),
        # Goals
        (r"i (?:want to|plan to|am trying to|will)\s+(.+?)(?:\.|$)", "goal",
         lambda m: f"goal: {m.group(1).strip()}"),
        # Family/relationships
        (r"my (wife|husband|mother|father|brother|sister|friend|son|daughter)\s+(.+?)(?:\.|$)", "relationship",
         lambda m: f"{m.group(1)}: {m.group(2).strip()}"),
        # Age
        (r"i am (\d+)\s+years?\s+old", "other",
         lambda m: f"age is {m.group(1)}"),
        # Habits
        (r"i usually\s+(.+?)(?:\.|$)", "habit",
         lambda m: f"usually: {m.group(1).strip()}"),
        (r"every (?:morning|evening|day|night)\s+i\s+(.+?)(?:\.|$)", "habit",
         lambda m: f"daily habit: {m.group(1).strip()}"),
    ]

    for pattern, category, formatter in patterns:
        m = re.search(pattern, msg, re.IGNORECASE)
        if m:
            try:
                fact_text = formatter(m)
                # Cap length
                if len(fact_text) < 120:
                    facts.append((category, fact_text))
            except Exception:
                pass

    return facts


def extract_and_store(user_message: str, use_llm: bool = True):
    """
    Extract personal facts from a user message and store them.
    Combines fast regex + LLM extraction.
    Called from a background thread — never blocks the response.
    """
    if not user_message or len(user_message.strip()) < 8:
        return

    # Skip clearly non-personal messages (commands, questions only)
    msg_lower = user_message.lower().strip()
    skip_prefixes = ("open ", "close ", "play ", "search ", "take ", "create ",
                     "delete ", "show ", "list ", "what is ", "who is ", "how ",
                     "when ", "where ", "why ", "tell me about", "explain ")
    if any(msg_lower.startswith(p) for p in skip_prefixes):
        # Check if it also has personal info ("open X and tell me i love Y")
        if not any(kw in msg_lower for kw in ("my ", "i am", "i like", "i love",
                                                "i hate", "i want", "i work", "i live")):
            return

    stored = 0

    # Pass 1: fast regex
    for category, fact_text in _rule_based_extract(user_message):
        if store_fact(fact_text, category):
            stored += 1

    # Pass 2: LLM extraction (richer, catches indirect statements)
    if use_llm:
        for category, fact_text in _call_llm_extract(user_message):
            if store_fact(fact_text, category):
                stored += 1

    if stored:
        print(f"[PersonalFacts] Extracted {stored} new fact(s) from message")


def extract_and_store_async(user_message: str):
    """Fire-and-forget: extract facts in background thread."""
    t = threading.Thread(
        target=extract_and_store,
        args=(user_message,),
        daemon=True,
        name="fact-extractor",
    )
    t.start()


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_stats() -> Dict:
    facts = get_all_facts()
    by_category = {}
    for f in facts:
        cat = f.get("category", "other")
        by_category[cat] = by_category.get(cat, 0) + 1
    return {
        "total_facts": len(facts),
        "by_category": by_category,
        "oldest": facts[-1].get("ts", "")[:10] if facts else None,
        "newest": facts[0].get("ts", "")[:10] if facts else None,
    }
