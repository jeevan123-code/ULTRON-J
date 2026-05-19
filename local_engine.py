"""
local_engine.py — Local inference engine for Ultron-J ULTIMATE.

ULTIMATE UPGRADES:
- Smarter query reframer with more category coverage
- Wikipedia summary mode (cleaner extraction)
- SearXNG result scoring: ranks results by relevance before passing to LLM
- Streaming word generator with configurable speed
- Bad response detection expanded with more patterns
- Offline mode: works fully without internet (Ollama + local knowledge base)
- Prompt caching: avoids repeating identical prompts to Ollama in quick succession
- Personality-injected local prompts: Ultron's character shows even in local mode
"""

import json
import time
import datetime
import hashlib
import threading
import os
import requests
from config import (
    MAX_HISTORY_CHARS, MAX_CONTEXT_CHARS, MAX_INPUT_CHARS,
    TIER_CONFIG, SEARXNG_URL, JEEVAN_LOCATION, MAX_RETRY_ATTEMPTS,
    JEEVAN_NAME, AGENT_NAME,
)

# ── Optional local search deps ────────────────────────────────────────────────
try:
    from duckduckgo_search import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    try:
        from ddgs import DDGS
        DDGS_AVAILABLE = True
    except ImportError:
        DDGS_AVAILABLE = False

try:
    import wikipedia
    wikipedia.set_lang("en")
    WIKI_AVAILABLE = True
except ImportError:
    WIKI_AVAILABLE = False

# ── Prompt cache (avoids hammering Ollama with duplicate requests) ─────────────
_prompt_cache       = {}
_prompt_cache_lock  = threading.Lock()
PROMPT_CACHE_TTL    = 60    # seconds

# =============================================================================
# QUERY REFRAMER — smart date/location injection
# =============================================================================

def reframe_query(question: str, now: datetime.datetime = None) -> str:
    """
    Intelligently reframe queries to include date, time, and location context.
    More category coverage than the original.
    """
    if now is None:
        now = datetime.datetime.now()

    date_str = now.strftime("%B %d %Y")
    day_str  = now.strftime("%A")
    time_str = now.strftime("%I:%M %p")
    q        = question.lower().strip()

    # News / current events
    if any(k in q for k in [
        "news", "latest", "today", "current", "happening", "breaking",
        "update", "this week", "yesterday", "recent", "right now",
        "what happened", "headlines", "going on", "new development",
    ]):
        has_location = any(place in q for place in [
            "hyderabad", "india", "delhi", "mumbai", "telangana",
            "world", "global", "international", "us", "usa", "uk",
        ])
        loc_str = f"{JEEVAN_LOCATION} " if not has_location else ""
        return f"latest news {loc_str}{date_str} {question.strip()}"

    # Weather
    if any(k in q for k in [
        "weather", "rain", "temperature", "forecast",
        "humidity", "hot", "cold", "sunny", "cloudy", "wind",
    ]):
        return f"weather {JEEVAN_LOCATION} {date_str}"

    # Price / market / finance
    if any(k in q for k in [
        "price", "rate", "stock", "market", "crypto", "bitcoin",
        "ethereum", "rupee", "dollar", "cost", "nifty", "sensex",
        "fund", "invest", "inflation", "gdp",
    ]):
        return f"{question.strip()} {date_str}"

    # Sports / events
    if any(k in q for k in [
        "match", "game", "tournament", "schedule", "ipl", "cricket",
        "football", "tennis", "score", "result", "series", "copa",
    ]):
        return f"{question.strip()} {date_str} {JEEVAN_LOCATION}"

    # Technology / software releases
    if any(k in q for k in [
        "release", "version", "launch", "update", "new model",
        "gpt", "claude", "llm", "model", "ai news",
    ]):
        return f"{question.strip()} {date_str}"

    # Agriculture / farming (Jeevan's background)
    if any(k in q for k in [
        "crop", "soil", "fertilizer", "farming", "agriculture", "harvest",
        "pest", "irrigation", "mandi", "price agriculture",
    ]):
        return f"{question.strip()} India {date_str}"

    # Default — return as-is
    return question


def reframe_alternatives(question: str, now: datetime.datetime = None) -> list:
    """Generate 5 alternative query reframings for aggressive retry."""
    if now is None:
        now = datetime.datetime.now()
    date_str = now.strftime("%B %d %Y")
    year_str = now.strftime("%Y")
    base     = reframe_query(question, now)
    q        = question.strip()
    return [
        base,
        f"{q} {date_str}",
        f"{q} {year_str} explained in detail",
        f"{q} latest information {JEEVAN_LOCATION}",
        f"comprehensive guide {q} everything you need to know",
    ]

# =============================================================================
# OLLAMA — local LLM inference
# =============================================================================

OLLAMA_ERROR_OFFLINE = "__OLLAMA_OFFLINE__"
OLLAMA_ERROR_NOMODEL = "__OLLAMA_NO_MODEL__"


_status_cache = {"at": 0.0, "result": None, "model": None}
_STATUS_TTL   = 30  # seconds

def check_ollama_status(model: str = None) -> str:
    """Returns 'ok', 'offline', or 'no_model'. Cached for 30 s per model."""
    now = time.time()
    if (now - _status_cache["at"] < _STATUS_TTL
            and _status_cache["model"] == model
            and _status_cache["result"]):
        return _status_cache["result"]
    try:
        res = requests.get("http://localhost:11434/api/tags", timeout=2)
        if res.status_code != 200:
            result = "offline"
        else:
            raw   = res.json().get("models", [])
            full  = [m["name"] for m in raw]
            base  = [m["name"].split(":")[0] for m in raw]
            all_m = full + base
            if model is None:
                result = "ok" if all_m else "no_model"
            else:
                mb     = model.split(":")[0]
                result = "ok" if (mb in all_m or model in all_m) else "no_model"
    except Exception:
        result = "offline"
    _status_cache.update({"at": now, "result": result, "model": model})
    return result


def ask_ollama(prompt: str, model: str) -> str | None:
    """Send prompt to local Ollama and return the complete response."""
    # Check prompt cache
    cache_key = hashlib.md5(f"{model}:{prompt[:200]}".encode()).hexdigest()
    with _prompt_cache_lock:
        cached = _prompt_cache.get(cache_key)
        if cached and (time.time() - cached["at"]) < PROMPT_CACHE_TTL:
            return cached["response"]

    # Quick connectivity check
    status = check_ollama_status(model)
    if status == "offline":
        return OLLAMA_ERROR_OFFLINE
    if status == "no_model":
        return OLLAMA_ERROR_NOMODEL

    try:
        res = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model":  model,
                "prompt": prompt,
                "stream": True,
                "options": {
                    "num_predict": 400,
                    "temperature": 0.3,
                    "num_ctx":     2048,
                    "num_thread":  os.cpu_count() or 4,
                },
            },
            stream=True,
            timeout=120,
        )
        if res.status_code != 200:
            return None
        full = ""
        for line in res.iter_lines():
            if line:
                try:
                    chunk = json.loads(line)
                    full += chunk.get("response", "")
                    if chunk.get("done"):
                        break
                except json.JSONDecodeError:
                    continue
        result = full.strip() if full.strip() else None
        if result:
            with _prompt_cache_lock:
                _prompt_cache[cache_key] = {"response": result, "at": time.time()}
                # Keep cache small
                if len(_prompt_cache) > 20:
                    oldest = min(_prompt_cache, key=lambda k: _prompt_cache[k]["at"])
                    del _prompt_cache[oldest]
        return result
    except requests.exceptions.Timeout:
        return None
    except requests.exceptions.ConnectionError:
        return None
    except Exception:
        return None


def ask_ollama_with_retry(prompt: str, model: str, max_tries: int = 3) -> str | None:
    """Try Ollama multiple times with different prompt lengths on failure."""
    for attempt in range(max_tries):
        result = ask_ollama(prompt, model)
        if result and not is_bad_response(result):
            return result
        if attempt < max_tries - 1:
            # Shorten prompt on retry
            prompt = prompt[:int(len(prompt) * 0.7)]
            time.sleep(1)
    return None


def get_ollama_models() -> list:
    try:
        res = requests.get("http://localhost:11434/api/tags", timeout=5)
        if res.status_code == 200:
            return [m["name"] for m in res.json().get("models", [])]
    except Exception:
        pass
    return []


def stream_ollama(prompt: str, model: str):
    """Yield tokens directly from Ollama as they arrive."""
    status = check_ollama_status(model)
    if status == "offline":
        yield {"error": "Ollama offline"}
        return
    if status == "no_model":
        yield {"error": f"Model {model} not pulled"}
        return
    try:
        res = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model":  model,
                "prompt": prompt,
                "stream": True,
                "options": {
                    "num_predict": 400,
                    "temperature": 0.3,
                    "num_ctx":     2048,
                },
            },
            stream=True, timeout=60,
        )
        if res.status_code != 200:
            yield {"error": f"Ollama HTTP {res.status_code}"}
            return
        for line in res.iter_lines():
            if not line:
                continue
            try:
                chunk = json.loads(line)
                tok   = chunk.get("response", "")
                if tok:
                    yield {"token": tok}
                if chunk.get("done"):
                    return
            except json.JSONDecodeError:
                continue
    except Exception as e:
        yield {"error": str(e)[:200]}


def is_bad_response(text: str) -> bool:
    """Detect low-quality or evasive LLM responses."""
    if not text or len(text.strip()) < 20:
        return True
    lower = text.lower().strip()
    bad_patterns = [
        "i cannot", "i can't", "i'm not able",
        "i don't have access", "i don't have real-time",
        "as an ai", "i am an ai", "i'm an ai language",
        "i don't know", "i have no information",
        "please try again", "unable to assist",
        "my training data", "my knowledge cutoff",
        "i apologize", "unfortunately i cannot",
    ]
    return any(p in lower for p in bad_patterns)

# =============================================================================
# SEARXNG SEARCH
# =============================================================================

def search_searxng(query: str, max_results: int = 5) -> list:
    """Search SearXNG instance. Returns list of result dicts."""
    try:
        resp = requests.get(
            f"{SEARXNG_URL}/search",
            params={"q": query, "format": "json", "categories": "general,news"},
            timeout=8,
        )
        if resp.status_code == 200:
            data    = resp.json()
            results = data.get("results", [])[:max_results]
            return [
                {
                    "title":   r.get("title", ""),
                    "url":     r.get("url", ""),
                    "snippet": r.get("content", "")[:500],
                    "source":  "searxng",
                }
                for r in results if r.get("content") or r.get("title")
            ]
    except Exception:
        pass
    return []


def _score_search_results(results: list, query: str) -> list:
    """Score and sort search results by relevance to query."""
    q_words = set(query.lower().split())
    scored  = []
    for r in results:
        text  = (r.get("title", "") + " " + r.get("snippet", "")).lower()
        score = sum(1 for w in q_words if w in text and len(w) > 2)
        scored.append((r, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [r for r, _ in scored]

# =============================================================================
# DUCKDUCKGO SEARCH (BACKUP)
# =============================================================================

def search_duckduckgo(query: str, max_results: int = 5) -> list:
    """Search DuckDuckGo as backup. Returns list of result dicts."""
    if not DDGS_AVAILABLE:
        return []
    try:
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results))
            return [
                {
                    "title":   r.get("title", ""),
                    "url":     r.get("href", r.get("link", "")),
                    "snippet": r.get("body", r.get("snippet", ""))[:500],
                    "source":  "duckduckgo",
                }
                for r in raw
            ]
    except Exception:
        return []

# =============================================================================
# WIKIPEDIA
# =============================================================================

def search_wikipedia(query: str) -> str:
    """Get a Wikipedia summary for the query."""
    if not WIKI_AVAILABLE:
        return ""
    try:
        search_results = wikipedia.search(query, results=3)
        if not search_results:
            return ""
        page    = wikipedia.page(search_results[0], auto_suggest=False)
        summary = wikipedia.summary(search_results[0], sentences=5, auto_suggest=False)
        return f"[Wikipedia: {page.title}]\n{summary}"
    except wikipedia.exceptions.DisambiguationError as e:
        try:
            summary = wikipedia.summary(e.options[0], sentences=4, auto_suggest=False)
            return f"[Wikipedia: {e.options[0]}]\n{summary}"
        except Exception:
            return ""
    except Exception:
        return ""

# =============================================================================
# SMART SEARCH — SearXNG → DDG → Wikipedia chain
# =============================================================================

def local_smart_search(query: str) -> str:
    """
    Smart search chain: SearXNG → DuckDuckGo → Wikipedia.
    Returns formatted string ready for LLM prompt injection.
    """
    results = []

    # 1. SearXNG (primary)
    searxng_results = search_searxng(query, max_results=5)
    if searxng_results:
        scored = _score_search_results(searxng_results, query)
        results.extend(scored[:3])

    # 2. DuckDuckGo (backup)
    if not results:
        ddg_results = search_duckduckgo(query, max_results=5)
        if ddg_results:
            scored = _score_search_results(ddg_results, query)
            results.extend(scored[:3])

    # 3. Wikipedia (always run alongside)
    wiki_text = search_wikipedia(query)

    # Format output
    parts = []
    if results:
        parts.append("=== Web Search Results ===")
        for i, r in enumerate(results, 1):
            parts.append(f"{i}. {r.get('title', 'Untitled')}")
            if r.get("snippet"):
                parts.append(f"   {r['snippet'][:300]}")
            if r.get("url"):
                parts.append(f"   Source: {r['url'][:80]}")

    if wiki_text:
        parts.append("\n=== Wikipedia ===")
        parts.append(wiki_text[:1000])

    return "\n".join(parts) if parts else ""


def local_smart_search_with_retry(question: str) -> str:
    """
    Try up to MAX_RETRY_ATTEMPTS different query reframings.
    Never gives up without exhausting all angles.
    """
    alternatives = reframe_alternatives(question)

    for attempt, query in enumerate(alternatives[:MAX_RETRY_ATTEMPTS]):
        result = local_smart_search(query)
        if result and len(result.strip()) > 100:
            return result
        time.sleep(0.5)

    return ""

# =============================================================================
# LOCAL PROMPT BUILDER
# =============================================================================

def build_local_prompt(
    question:   str,
    history:    list   = None,
    facts:      list   = None,
    search_ctx: str    = "",
    tier:       str    = "pro",
) -> str:
    """
    Build the full local-mode prompt for Ollama.
    Injects personality, history, facts, and search context.
    """
    tier_info = TIER_CONFIG.get(tier, TIER_CONFIG.get("pro", {}))
    model     = tier_info.get("model", "mistral")

    # Personality intro
    try:
        from personality import get_mood, get_mood_phrase
        mood   = get_mood()
        phrase = get_mood_phrase(mood)
    except Exception:
        mood   = "FOCUSED"
        phrase = "On it."

    system_block = (
        f"You are {AGENT_NAME}, a personal autonomous AI for {JEEVAN_NAME}. "
        f"Current mode: LOCAL (no cloud APIs). "
        f"Mood: {mood}. "
        f"Be direct, concise, and fiercely helpful. "
        f"Never say 'as an AI'. You are Ultron-J — not a generic assistant.\n"
        f"Location context: {JEEVAN_LOCATION}.\n"
        f"Current time: {datetime.datetime.now().strftime('%A, %B %d %Y, %I:%M %p')}.\n"
    )

    # History
    history_block = ""
    if history:
        history_lines = []
        total_chars   = 0
        for role, msg in reversed(history):
            line = f"{'User' if role == 'user' else 'Ultron'}: {msg}"
            if total_chars + len(line) > MAX_HISTORY_CHARS:
                break
            history_lines.insert(0, line)
            total_chars += len(line)
        if history_lines:
            history_block = "Recent conversation:\n" + "\n".join(history_lines) + "\n\n"

    # Facts
    facts_block = ""
    if facts:
        facts_block = "Known facts about Jeevan: " + "; ".join(facts[:5]) + "\n\n"

    # Search context
    search_block = ""
    if search_ctx:
        truncated    = search_ctx[:MAX_CONTEXT_CHARS]
        search_block = f"Search results:\n{truncated}\n\n"

    prompt = (
        f"{system_block}\n"
        f"{facts_block}"
        f"{history_block}"
        f"{search_block}"
        f"User: {question[:MAX_INPUT_CHARS]}\n"
        f"Ultron-J:"
    )
    return prompt

# =============================================================================
# STREAMING WORD GENERATOR
# =============================================================================

def stream_words(text: str, delay: float = 0.03):
    """
    Stream a pre-generated text word by word for SSE output.
    Used when Ollama returns a full response that needs to be streamed.
    """
    words = text.split()
    full  = ""
    for i, word in enumerate(words):
        token = word + (" " if i < len(words) - 1 else "")
        full += token
        yield f"data: {json.dumps({'token': token})}\n\n"
        time.sleep(delay)
    yield f"data: {json.dumps({'_full': full})}\n\n"
