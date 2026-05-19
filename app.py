"""
app.py — Flask route layer for Ultron-J ULTIMATE.
Personal autonomous AI for Jeevan — Hyderabad, Telangana, India.

ULTIMATE UPGRADES vs previous version:
- Personality mood shown in every response header
- Perception context injected into LLM prompts automatically
- Episodic memory stores every conversation as an episode
- Entity extraction from user messages — knowledge graph grows automatically
- Image analysis endpoint: /analyze_image
- Note creation endpoint: /note
- Code execution endpoint: /run_code
- Calculate endpoint: /calculate
- Reflection endpoint: /reflect
- Proactive clipboard endpoint: /clipboard
- Provider health endpoint: /provider_health
- Daily plan endpoint: /daily_plan
- All responses include mood + energy metadata
- Tier detection from message: "switch to premium" etc.
- Search query auto-reframing now uses perception context
"""

import os
import subprocess
import datetime
import json
import base64
import re
import sys
import threading
import uuid
from flask import Flask, render_template, request, jsonify, Response
from flask_cors import CORS

# When this file is launched directly (`python app.py`) it lives in sys.modules
# under the name "__main__". Several blueprints (system_routes, voice_routes,
# react_engine) do lazy `from app import ...` inside their handlers — without
# the alias below, that triggers a SECOND full module load (re-running every
# blueprint registration + ultimate-loop start). Aliasing here is the standard
# fix for the script-vs-module duplication footgun.
if __name__ == "__main__":
    sys.modules.setdefault("app", sys.modules[__name__])

# T28 — flag to suppress autonomous loop during active /ask streaming
_conversation_active = threading.Event()

import config as cfg
from config import (
    TAVILY_API_KEY, GROQ_MODEL, GEMINI_MODEL, TIER_CONFIG,
    MAX_QUESTION_LEN, STREAM_HEADERS,
    SELF_AWARE_KEYWORD, JEEVAN_LOCATION, JEEVAN_NAME, AGENT_NAME,
)
from memory import (
    store_conversation, migrate_existing_memory,
    sqlite_save_message, sqlite_get_history, sqlite_get_facts,
    record_activity, store_episode, upsert_entity, SEMANTIC_MEMORY_AVAILABLE,
    set_last_action, get_last_action,
)
from intent_router import detect_intent, execute_intent
from concepts import (
    CONCEPTS, is_concept_question, is_greeting, greeting_reply, intent_agent,
)
from system_monitor import (
    build_self_awareness_block, start_monitor, PSUTIL_AVAILABLE,
)
from llm_engine import stream_llm, call_llm_vision
from local_engine import (
    build_local_prompt, is_bad_response,
    local_smart_search_with_retry,
    reframe_query, stream_words,
    DDGS_AVAILABLE, WIKI_AVAILABLE,
)
from personality import (
    get_mood, get_mood_icon, trigger_mood_change,
    drain_energy, restore_energy,
)
from perception import (
    start_perception, build_perception_context, build_screen_context, get_clipboard_content,
)

# ── Intelligence Core ─────────────────────────────────────────────────────
try:
    from intelligence_core import think_and_stream, init_intelligence
    INTELLIGENCE_AVAILABLE = True
except ImportError as e:
    INTELLIGENCE_AVAILABLE = False
    print(f"[App] Intelligence Core not loaded: {e}")

# Agent system
from autonomous_loop import start_autonomous_loop
from agent_routes import agent_bp
from action_engine import (
    run_code_sandbox, safe_calculate, fetch_weather, create_note,
)

# ── Voice engine — get_voice_status is needed inline (startup print); ────────
#    stream_tts_from_llm is used by /ask voice-mode to wrap the LLM stream in
#    sentence-level TTS so the chat page hears audio as soon as each sentence
#    finishes rather than waiting for the full text + a separate TTS round trip.
try:
    from voice_engine import get_voice_status, stream_tts_from_llm
    VOICE_AVAILABLE = True
except ImportError:
    VOICE_AVAILABLE = False
    def get_voice_status(): return {"ready": False, "error": "edge-tts not installed"}
    def stream_tts_from_llm(gen, mood="FOCUSED"): return iter([])

# ── Task Orchestrator (used by /ask, /clarify/check via blueprints, etc.) ─────
from task_orchestrator import orchestrate
from project_conversation import (
    start_project_conversation,
    answer_project_question,
    save_project_code,
)

# ── Autonomous Builder (used by /build) ───────────────────────────────────────
try:
    from autonomous_builder import build_project_from_voice
    AUTONOMOUS_BUILDER_AVAILABLE = True
except ImportError:
    AUTONOMOUS_BUILDER_AVAILABLE = False
    def build_project_from_voice(cmd): return {"success": False, "error": "autonomous_builder not found"}

# ── Optional modules — only the _AVAILABLE flag is consumed inline (startup print).
#    The actual handlers live in loop_routes.py / system_routes.py / etc.
try:
    import claude_loop  # noqa: F401
    CLAUDE_LOOP_AVAILABLE = True
except ImportError:
    CLAUDE_LOOP_AVAILABLE = False

try:
    import visual_verify  # noqa: F401
    VISUAL_VERIFY_AVAILABLE = True
except ImportError:
    VISUAL_VERIFY_AVAILABLE = False

try:
    import self_modify  # noqa: F401
    SELF_MODIFY_AVAILABLE = True
except ImportError:
    SELF_MODIFY_AVAILABLE = False

try:
    import app_control  # noqa: F401
    APP_CONTROL_AVAILABLE = True
except ImportError:
    APP_CONTROL_AVAILABLE = False

# ── Page Code Extractor (used by /code_extract/*, still inline) ───────────────
try:
    from page_code_extractor import (
        extract_and_save, list_all_code_on_page, get_extract_log,
    )
    PAGE_EXTRACTOR_AVAILABLE = True
except ImportError:
    PAGE_EXTRACTOR_AVAILABLE = False
    def extract_and_save(url, **kw): return {"success": False, "error": "page_code_extractor not available"}
    def list_all_code_on_page(url, **kw): return {"success": False, "error": "page_code_extractor not available"}
    def get_extract_log(limit=30): return []

# ── App ────────────────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)
app.register_blueprint(agent_bp)

# ── ULTIMATE v4: new-blueprint registration (vector store, research, planner,
#    distiller, evolution, proactive, tweak engine) ───────────────────────────
try:
    from ultimate_routes import ultimate_bp, start_ultimate_loops
    app.register_blueprint(ultimate_bp)
    # Kick off the three background loops. Tune intervals here or via the
    # /ultimate/{distiller,evolution,proactive}/start endpoints later.
    _ultimate_started = start_ultimate_loops(
        distiller_hours=6,
        evolution_hours=12,
        proactive_minutes=30,
        enable=True,
    )
    print(f"[app] Ultimate loops started: {_ultimate_started}")
except ImportError as e:
    print(f"[app] Ultimate routes not loaded: {e}")
except Exception as e:
    print(f"[app] Ultimate routes init error: {e}")

# ── BEYOND JARVIS: app_additions integration ──────────────────────────────────
try:
    from app_additions import register_beyond_jarvis_routes, start_beyond_jarvis
    register_beyond_jarvis_routes(app)
    BEYOND_JARVIS_AVAILABLE = True
    print("[app] Beyond JARVIS routes registered (+27 endpoints)")
except ImportError as e:
    BEYOND_JARVIS_AVAILABLE = False
    print(f"[app] app_additions not loaded: {e}")
except Exception as e:
    BEYOND_JARVIS_AVAILABLE = False
    print(f"[app] app_additions init error: {e}")

# ── TASK 2 BLUEPRINTS: extracted route groups ─────────────────────────────────
try:
    from computer_routes import computer_bp
    app.register_blueprint(computer_bp)
    print("[app] computer_routes registered (+5 endpoints)")
except ImportError as e:
    print(f"[app] computer_routes not loaded: {e}")

try:
    from voice_routes import voice_bp
    app.register_blueprint(voice_bp)
    print("[app] voice_routes registered (+8 endpoints)")
except ImportError as e:
    print(f"[app] voice_routes not loaded: {e}")

try:
    from system_routes import system_bp
    app.register_blueprint(system_bp)
    print("[app] system_routes registered (+13 endpoints)")
except ImportError as e:
    print(f"[app] system_routes not loaded: {e}")

try:
    from loop_routes import loop_bp
    app.register_blueprint(loop_bp)
    print("[app] loop_routes registered (+23 endpoints)")
except ImportError as e:
    print(f"[app] loop_routes not loaded: {e}")

# ── Mode state ─────────────────────────────────────────────────────────────────
_MODE      = "cloud"
_mode_lock = threading.Lock()


def get_mode():
    with _mode_lock:
        return _MODE


def set_mode(mode):
    global _MODE
    if mode in ("cloud", "local"):
        with _mode_lock:
            _MODE = mode

# ── Current tier ───────────────────────────────────────────────────────────────
_CURRENT_TIER = "pro"
_tier_lock    = threading.Lock()


def get_current_tier() -> str:
    with _tier_lock:
        return _CURRENT_TIER


def set_current_tier(tier: str):
    global _CURRENT_TIER
    if tier in TIER_CONFIG:
        with _tier_lock:
            _CURRENT_TIER = tier

# =============================================================================
# HELPER UTILITIES
# =============================================================================

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_SEARCH_TRIGGERS = [
    "news", "latest", "today", "current", "what happened", "who is",
    "price", "weather", "trending", "yesterday", "breaking",
    "update", "right now", "this week", "last 24", "recently",
    "score", "cricket", "ipl", "match", "live score", "sports",
    "football", "standings", "who won", "result", "wicket", "goal", "highlights",
]
_SEARCH_RE = re.compile(
    r'\b(' + '|'.join(re.escape(t) for t in _SEARCH_TRIGGERS) + r')\b'
)


def needs_search(q: str) -> bool:
    ql = q.lower()
    return bool(_SEARCH_RE.search(ql)) or bool(_YEAR_RE.search(ql))


def wants_fresh_news(q: str) -> bool:
    ql = (q or "").lower()
    return any(k in ql for k in (
        "latest", "today", "breaking", "right now",
        "this week", "last 24", "news",
    ))


def _detect_tier_switch(q: str) -> str | None:
    ql = q.lower()
    if "switch to premium" in ql or "use premium" in ql:
        return "premium"
    if "switch to ultra"   in ql or "use ultra"   in ql:
        return "ultra"
    if "switch to pro"     in ql or "use pro"     in ql:
        return "pro"
    if "switch to basic"   in ql or "use basic"   in ql:
        return "basic"
    return None


def _detect_mode_switch(q: str) -> str | None:
    ql = q.lower()
    if any(k in ql for k in ["local mode", "go local", "switch to local", "offline mode"]):
        return "local"
    if any(k in ql for k in ["cloud mode", "go cloud", "switch to cloud", "online mode"]):
        return "cloud"
    return None


def _extract_entities_from_message(text: str):
    """Extract entities from user message and store in knowledge graph."""
    try:
        import re
        # Proper nouns (capitalized)
        caps = re.findall(r'\b[A-Z][a-z]{2,}\b', text)
        for name in caps[:5]:
            if name not in {"The", "This", "That", "What", "When", "Where", "How"}:
                upsert_entity(name, kind="concept")
        # File references
        files = re.findall(r'\b[\w]+\.(py|js|json|txt|md|html|csv|sql)\b', text)
        for f_match in files:
            fname = "".join(f_match) if isinstance(f_match, tuple) else f_match
            upsert_entity(fname, kind="file")
    except Exception:
        pass

# =============================================================================
# TAVILY WEB SEARCH
# =============================================================================

def search_web_tavily(query, max_results=5, search_depth="advanced",
                      topic="general", days=None, include_domains=None):
    if not TAVILY_API_KEY:
        return {"summary": "", "sources": []}
    try:
        import requests as _req
        payload = {
            "api_key":      TAVILY_API_KEY,
            "query":        query,
            "search_depth": search_depth,
            "topic":        topic,
            "max_results":  max_results,
        }
        if days is not None and topic == "news":
            payload["days"] = days
        if include_domains:
            # Tavily accepts a list of domain strings — strip protocol and path.
            doms = []
            for d in (include_domains if isinstance(include_domains, (list, tuple)) else [include_domains]):
                d = str(d).strip().lower()
                d = d.replace("https://", "").replace("http://", "").strip("/")
                if d and "." in d:
                    doms.append(d)
            if doms:
                payload["include_domains"] = doms
        resp = _req.post("https://api.tavily.com/search", json=payload, timeout=3)
        resp.raise_for_status()
        data    = resp.json()
        sources = data.get("results", [])
        summary = data.get("answer", "")
        return {"summary": summary, "sources": sources}
    except Exception:
        return {"summary": "", "sources": []}

# =============================================================================
# ROUTES — MAIN UI
# =============================================================================

@app.route("/")
def index():
    return render_template("index.html")


# Lightweight liveness probe. sleep_guard.py's Watchdog pings this every
# check_interval and kill+restart after 3 consecutive misses, so it must
# stay cheap (no I/O, no third-party calls) and never raise. The richer
# system snapshot lives at /agent/health.
@app.route("/health", methods=["GET"])
def health():
    """Comprehensive health check — returns status of every module."""
    status = {}

    # Memory (SQLite)
    try:
        from memory import sqlite_get_history
        sqlite_get_history("_health_check_", limit=1)
        status["memory"] = "ok"
    except Exception as e:
        status["memory"] = f"error: {str(e)[:60]}"

    # ChromaDB / vector store
    try:
        import vector_store as _vs
        if _vs._collection is not None or not _vs.CHROMA_AVAILABLE:
            status["chromadb"] = "ok" if _vs.CHROMA_AVAILABLE else "unavailable"
        else:
            status["chromadb"] = "ok"
    except Exception as e:
        status["chromadb"] = f"error: {str(e)[:60]}"

    # LLM providers — key presence + health-tracker state
    try:
        from llm_engine import get_provider_health
        ph = get_provider_health()
        for prov in ("groq", "gemini", "openrouter"):
            info = ph.get(prov, {})
            if info.get("status") == "no_key":
                status[prov] = "no_key"
            elif info.get("healthy", True):
                status[prov] = "ok"
            else:
                status[prov] = f"cooling_down ({info.get('failures',0)} failures)"
    except Exception as e:
        status["groq"] = status["gemini"] = status["openrouter"] = f"error: {str(e)[:60]}"

    # Tavily web search
    try:
        from config import TAVILY_KEY
        status["tavily"] = "ok" if TAVILY_KEY else "no_key"
    except Exception:
        status["tavily"] = "unavailable"

    # Voice engine
    status["voice_engine"] = "ok" if VOICE_AVAILABLE else "unavailable (pip install edge-tts aiohttp)"

    # Perception engine
    try:
        from perception import PERCEPTION_AVAILABLE
        status["perception"] = "ok" if PERCEPTION_AVAILABLE else "unavailable"
    except Exception:
        status["perception"] = "unavailable"

    all_ok = all(v == "ok" for v in status.values())
    return jsonify({"ok": all_ok, "modules": status}), 200

# =============================================================================
# CHAT ENDPOINT — CLOUD MODE
# =============================================================================

@app.route("/ask", methods=["POST"])
def ask():
    data       = request.json or {}
    question   = (data.get("question") or data.get("message") or "").strip()
    session_id = data.get("session_id") or "default"
    temperature= float(data.get("temperature", 0.7))
    provider   = data.get("provider", "auto") or "auto"
    # Opt-in JARVIS streaming-voice mode. When the client (e.g. templates/index.html
    # chat page) sets voice=true, the LLM stream is wrapped in stream_tts_from_llm
    # so audio for each completed sentence ships inline in the same SSE response.
    # Text-only callers see byte-identical behaviour because voice_mode defaults
    # to False when the flag is absent.
    voice_mode = bool(data.get("voice"))

    # Persist the user's dropdown selection so get_current_provider() (and
    # therefore /heartbeat → the "Provider" pill) reflects what's actually
    # going to run. "auto" clears the forcing so the health-based selector
    # decides per request.
    try:
        from llm_engine import set_forced_provider
        _p = (provider or "auto").lower().strip()
        if _p in ("groq", "gemini", "openrouter"):
            set_forced_provider(_p)
        else:
            set_forced_provider(None)
    except Exception:
        pass

    if not question:
        return jsonify({"response": "I didn't catch that. What would you like?",
                        "mood": get_mood(), "mood_icon": get_mood_icon()})
    if len(question) > MAX_QUESTION_LEN:
        question = question[:MAX_QUESTION_LEN]

    # Detect mode/tier switches
    new_tier = _detect_tier_switch(question)
    if new_tier:
        set_current_tier(new_tier)
        return jsonify({"response": f"Switched to {new_tier.upper()} tier. Ready."})

    new_mode = _detect_mode_switch(question)
    if new_mode:
        set_mode(new_mode)
        return jsonify({"response": f"Switched to {new_mode.upper()} mode."})


    # ── NEW: Orchestrator intercept (computer control, project builder) ───────────
    _orch = orchestrate(question, session_id=session_id)
    if _orch.get("action_taken") and not _orch.get("passthrough"):
        # Prefer detect_intent groups so repeat-last can re-execute correctly
        _orch_intent = detect_intent(question) or {"type": _orch.get("action_taken"), "groups": [question], "raw": question}
        set_last_action(session_id, _orch_intent, _orch)
        _orch_msg = (_orch.get("message")
                     or (f"❌ Failed: {_orch['error']}" if not _orch.get("success") and _orch.get("error") else None)
                     or "Done!")
        return jsonify({
            "response":     _orch_msg,
            "action_taken": _orch.get("action_taken"),
            "data":         _orch,
            "mood":         get_mood(),
            "mood_icon":    get_mood_icon(),
            "needs_input":  _orch.get("needs_input", False),
            "questions":    _orch.get("questions", []),
        })
    # ── End orchestrator intercept ────────────────────────────────────────────────

    # ── Pre-LLM intent intercept (T09) ───────────────────────────────────────
    _intent = detect_intent(question)
    if _intent and _intent["type"] == "repeat_last":
        last = get_last_action(session_id)
        if last and last.get("intent"):
            _r = execute_intent(last["intent"])
            set_last_action(session_id, last["intent"], _r)
            return jsonify({
                "response": f"Repeating: {last['intent']['type']}",
                "action":   last["intent"]["type"],
                "result":   _r,
                "executed": True,
            })
        return jsonify({"response": "No previous action to repeat."})
    elif _intent and _intent["type"] != "help_me_now":
        _r = execute_intent(_intent)
        set_last_action(session_id, _intent, _r)
        sqlite_save_message(session_id, "user", question)
        _resp = (
            f"{_intent['type'].replace('_', ' ').title()}: "
            f"{_r.get('result') or _r.get('app') or 'done'}"
            if _r.get("success")
            else f"Failed: {_r.get('error', 'unknown')}"
        )
        sqlite_save_message(session_id, "assistant", _resp)
        return jsonify({
            "response": _resp,
            "action":   _intent["type"],
            "result":   _r,
            "executed": True,
        })
    # ── End intent intercept ──────────────────────────────────────────────────

    # T22 — "Help me" / "I'm stuck" with screen context
    if _intent and _intent["type"] == "help_me_now":
        try:
            from screen_engine import take_screenshot, ocr_screen, get_screen_status
            ocr    = ocr_screen()
            status = get_screen_status()
            screen_dump = (
                f"Active window: {status.get('active_window', '?')}\n"
                f"Screen OCR text:\n{(ocr.get('text') or '')[:1500]}"
            )
        except Exception as _se:
            screen_dump = f"(screen capture failed: {_se})"

        _help_prompt = (
            "User asked for help and may be stuck. Their current screen:\n"
            f"{screen_dump}\n\n"
            f"User said: \"{_intent['raw']}\"\n\n"
            "Identify what app they're in, what they're trying to do, "
            "and give CONCRETE numbered steps to unblock them. Be brief."
        )
        _help_hist = sqlite_get_history(session_id)
        _help_msgs = [{"role": "system", "content": _help_prompt}]
        _help_msgs.extend([{"role": r, "content": m} for r, m in _help_hist])
        _help_msgs.append({"role": "user", "content": _intent["raw"]})

        def _help_gen():
            _full = []
            for _c in stream_llm(_help_msgs, temperature=0.3):
                if isinstance(_c, dict) and "token" in _c:
                    _full.append(_c["token"])
                    yield f"data: {json.dumps({'token': _c['token']})}\n\n"
                elif isinstance(_c, str):
                    _full.append(_c)
                    yield f"data: {json.dumps({'token': _c})}\n\n"
            _ft = "".join(_full)
            sqlite_save_message(session_id, "user", _intent["raw"])
            sqlite_save_message(session_id, "assistant", _ft)
            yield f"data: {json.dumps({'_full': _ft, 'done': True})}\n\n"

        return Response(_help_gen(), content_type="text/event-stream",
                        headers=STREAM_HEADERS)

    # Intent detection
    intent_result = intent_agent(question)
    intent        = intent_result.get("intent", "chat")

    # Special intents — handle directly
    if intent == "greeting" and len(question.split()) <= 2:
        restore_energy(0.02)
        return jsonify({
            "response": greeting_reply(),
            "mood":     get_mood(),
            "mood_icon": get_mood_icon(),
    })

    if intent == "calculate":
        result = safe_calculate(question)
        if result.get("success"):
            return jsonify({
                "response":  f"= {result['result']}",
                "mood":      get_mood(),
                "mood_icon": get_mood_icon(),
            })

    if intent == "weather":
        # Only handle short, direct weather queries — skip if it's a reasoning/logic question
        _reasoning_words = ("explain", "yes or no", "if ", "because", "therefore",
                            "always", "never", "all ", "when ", "prove", "logical")
        _is_direct_weather = (
            len(question.split()) <= 12 and
            not any(k in question.lower() for k in _reasoning_words)
        )
        if _is_direct_weather:
            weather = fetch_weather()
            if weather.get("success"):
                return jsonify({
                    "response": (
                        f"**{weather['location']}** — {weather['description']}\n"
                        f"🌡️ {weather['temp_c']}°C (feels {weather['feels_like']}°C) | "
                        f"💧 Humidity {weather['humidity']}% | "
                        f"💨 Wind {weather['wind_kmph']} km/h"
                    ),
                    "mood":      get_mood(),
                    "mood_icon": get_mood_icon(),
                })

    if intent == "note":
        note = create_note("Quick note", question, "chat")
        return jsonify({
            "response": f"📝 Saved as note '{note['id']}'. You can find it in /agent/notes.",
            "mood":     get_mood(),
        })

    # Self-awareness — KARTHA keyword
    if SELF_AWARE_KEYWORD.lower() in question.lower():
        block = build_self_awareness_block()
        return jsonify({"response": block, "mood": get_mood(), "mood_icon": get_mood_icon()})

    # Concept lookup
    concept_key = is_concept_question(question)
    if concept_key and not needs_search(question):
        record_activity(topic=concept_key, mode="cloud", session_id=session_id)
        return jsonify({
            "response":  CONCEPTS[concept_key],
            "mood":      get_mood(),
            "mood_icon": get_mood_icon(),
        })

    # Entity extraction
    _extract_entities_from_message(question)

    # Record activity
    record_activity(topic=question[:30], mode="cloud", session_id=session_id)

    # Build history
    history_rows = sqlite_get_history(session_id)
    messages     = [{"role": r, "content": m} for r, m in history_rows]
    messages.append({"role": "user", "content": question})

    # SSE stream response
    def generate():
        nonlocal provider
        full_response = ""
        search_context = ""
        _done_sent = False

        if needs_search(question):
            trigger_mood_change("search_started")
            reframed = reframe_query(question)
            days     = 3 if wants_fresh_news(question) else None
            if not TAVILY_API_KEY:
                tavily = {"sources": [], "skipped": "no_tavily_key"}
            else:
                try:
                    tavily = search_web_tavily(reframed, days=days,
                                               topic="news" if days else "general")
                except Exception as _te:
                    tavily = {"sources": [], "error": str(_te)[:120]}
            if not tavily.get("sources"):
                try:
                    from local_engine import local_smart_search
                    _ddg = local_smart_search(reframed)
                    if _ddg:
                        search_context = _ddg[:2000]
                except Exception:
                    pass
            else:
                snippets = []
                for s in tavily["sources"][:4]:
                    snippets.append(f"• {s.get('title', '')}: {s.get('content', '')[:300]}")
                search_context = "\n".join(snippets)
            # Web search failed — previously this short-circuited the entire
            # reply with "I couldn't reach any web sources". That made every
            # borderline query that *happened* to trigger needs_search (e.g.
            # casual "today" / "now" mentions) wait 3-6s for a search round
            # trip and then refuse to answer. Now we just continue without
            # search context and let the LLM answer from its own knowledge;
            # if the question truly needed fresh data the LLM can say so.

        # ── JARVIS voice-mode: wrap the LLM stream in sentence-level TTS ──────
        # Strictly opt-in (request body voice=true). The else-branch below is
        # byte-identical to the previous text-only behaviour, so non-voice
        # callers are unaffected. We build a single source generator that emits
        # the same SSE shape the existing intelligence_core / stream_llm paths
        # do, then pipe it through stream_tts_from_llm which yields per-sentence
        # audio events as soon as each sentence completes.
        if voice_mode:
            def _llm_source():
                if INTELLIGENCE_AVAILABLE:
                    for chunk in think_and_stream(question, session_id, history_rows,
                                                  temperature,
                                                  search_context=search_context,
                                                  provider=provider):
                        # Drop status tokens before they enter the sentence
                        # chunker — they're UX hints, not speakable content.
                        if chunk.startswith("data: "):
                            try:
                                d = json.loads(chunk[6:])
                                if d.get("type") == "status":
                                    continue
                            except Exception:
                                pass
                        yield chunk
                else:
                    perception_ctx = build_perception_context()
                    screen_ctx     = build_screen_context()
                    extra_ctx = "\n".join(filter(None, [search_context, perception_ctx, screen_ctx]))
                    yield from stream_llm(messages, temperature=temperature,
                                          extra_context=extra_ctx,
                                          force_provider=provider)

            for evt in stream_tts_from_llm(_llm_source(), mood=get_mood()):
                t = evt.get("type")
                if t == "text_token":
                    tok = evt.get("token", "")
                    if tok:
                        full_response += tok
                        yield f"data: {json.dumps({'token': tok})}\n\n"
                elif t in ("sentence", "text_only"):
                    yield f"data: {json.dumps(evt)}\n\n"
                elif t == "done":
                    full_response = (evt.get("full_text") or full_response).strip()
                    yield f"data: {json.dumps({'_full': full_response, 'done': True})}\n\n"
                    _done_sent = True
                elif t == "error":
                    yield f"data: {json.dumps({'error': evt.get('msg', '')})}\n\n"
                # transcript_start is dropped — the chat-page UI doesn't need it.

        elif INTELLIGENCE_AVAILABLE:
            # ── INTELLIGENCE CORE PATH (text-only, unchanged) ─────────────────
            for chunk in think_and_stream(question, session_id, history_rows, temperature,
                                          search_context=search_context,
                                          provider=provider):
                if chunk.startswith("data: "):
                    data_str = chunk[6:]
                    try:
                        d     = json.loads(data_str)
                        # The intelligence core emits "🧠 Thinking…" / "🔍 Analyzing…"
                        # status tokens with type=="status" for UX. The browser UI
                        # already shows its own "Thinking…" hint (templates/index.html:461),
                        # and downstream test clients concatenate every {token: ...}
                        # event verbatim, so leaking these to the client contaminates
                        # the visible response text. Drop them at egress.
                        if d.get("type") == "status":
                            continue
                        token = d.get("token", "")
                        if d.get("_full"):
                            full_response = d["_full"]
                        elif token:
                            full_response += token
                    except Exception:
                        pass
                    yield chunk
        else:
            # ── FALLBACK: existing engine (text-only, unchanged) ──────────────
            perception_ctx = build_perception_context()
            screen_ctx     = build_screen_context()
            extra_ctx = "\n".join(filter(None, [search_context, perception_ctx, screen_ctx]))

            for chunk in stream_llm(messages, temperature=temperature, extra_context=extra_ctx, force_provider=provider):
                if chunk.startswith("data: "):
                    yield chunk
                    data_str = chunk[6:]
                    try:
                        d     = json.loads(data_str)
                        token = d.get("token", "")
                        if d.get("_full"):
                            full_response = d["_full"]
                        elif token:
                            full_response += token
                    except Exception:
                        pass

        # Guarantee every SSE stream ends with done:true so the UI spinner stops
        if not _done_sent:
            yield f"data: {json.dumps({'done': True})}\n\n"

        # Post-response: store in memory
        if full_response:
            sqlite_save_message(session_id, "user", question)
            sqlite_save_message(session_id, "assistant", full_response)
            store_conversation("user", question, session_id)
            store_conversation("assistant", full_response, session_id)
            # Store as episode
            store_episode(
                kind="conversation",
                summary=f"User: {question[:80]}",
                detail=f"Response: {full_response[:300]}",
                valence=0.0,
                importance=0.3,
                session_id=session_id,
            )
            drain_energy(0.03)
            # mem0 async fact extraction — fire and forget
            try:
                from smart_memory import remember as _mem0_remember, MEM0_AVAILABLE as _MEM0_AVAIL
                if _MEM0_AVAIL:
                    import threading as _thr
                    _thr.Thread(
                        target=_mem0_remember,
                        args=(f"User: {question}\nUltron: {full_response[:500]}",),
                        daemon=True
                    ).start()
            except Exception:
                pass

    def _guarded_generate():
        _conversation_active.set()
        try:
            yield from generate()
        finally:
            _conversation_active.clear()

    return Response(_guarded_generate(), content_type="text/event-stream", headers=STREAM_HEADERS)

# =============================================================================
# LOCAL MODE CHAT
# =============================================================================

@app.route("/ask_local", methods=["POST"])
def ask_local():
    """Local mode is retired — Ollama support has been removed. Use cloud /ask."""
    msg = (
        "⚠️ Local mode is no longer available. Ollama support has been removed.\n\n"
        "Please use Cloud mode — it works with Groq, Gemini, and OpenRouter. "
        "Select a provider from the top bar and send your message."
    )
    return Response(stream_words(msg), content_type="text/event-stream", headers=STREAM_HEADERS)

# =============================================================================
# SPECIAL ACTION ENDPOINTS
# =============================================================================

@app.route("/run_code", methods=["POST"])
def run_code_endpoint():
    data    = request.json or {}
    code    = data.get("code", "").strip()
    timeout = int(data.get("timeout", 10))
    if not code:
        return jsonify({"error": "No code provided"}), 400
    result = run_code_sandbox(code, timeout=timeout)
    return jsonify(result)


@app.route("/calculate", methods=["POST"])
def calculate_endpoint():
    data = request.json or {}
    expr = data.get("expression", "").strip()
    if not expr:
        return jsonify({"error": "No expression"}), 400
    return jsonify(safe_calculate(expr))


@app.route("/weather", methods=["GET"])
def weather_endpoint():
    location = request.args.get("location", "")
    return jsonify(fetch_weather(location or None))


@app.route("/analyze_image", methods=["POST"])
def analyze_image():
    data   = request.json or {}
    url    = data.get("image_url", "")
    prompt = data.get("prompt", "Describe this image in detail.")
    if not url:
        return jsonify({"error": "image_url required"}), 400
    result = call_llm_vision(url, prompt)
    return jsonify({"result": result})


@app.route("/note", methods=["POST"])
def create_note_endpoint():
    data    = request.json or {}
    title   = data.get("title", "Quick Note")
    content = data.get("content", "").strip()
    cat     = data.get("category", "general")
    if not content:
        return jsonify({"error": "Content required"}), 400
    note = create_note(title, content, cat)
    return jsonify({"ok": True, "note": note})


@app.route("/clipboard", methods=["GET"])
def clipboard_endpoint():
    content = get_clipboard_content()
    return jsonify({
        "content": content[:500] if content else "",
        "has_content": bool(content),
    })


# NOTE: /reflect, /daily_plan, /heartbeat, /suggestions, /personality, /provider_health,
#       /proposals/*, /status, /clarify/* routes were extracted to system_routes.py (Task 2, Group C).


@app.route("/build", methods=["POST"])
def build_project_endpoint():
    """Autonomous project builder - no copy-paste needed."""
    if not AUTONOMOUS_BUILDER_AVAILABLE:
        return jsonify({"success": False, "error": "autonomous_builder.py not available"}), 500
    data    = request.json or {}
    command = data.get("command", "").strip()
    if not command:
        return jsonify({"success": False, "error": "command required"}), 400
    try:
        result = build_project_from_voice(command)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/v1/models", methods=["GET"])
def v1_models():
    """OpenAI-compatible models list for tool integrations."""
    return jsonify({
        "object": "list",
        "data": [
            {"id": GROQ_MODEL,   "object": "model", "provider": "groq"},
            {"id": GEMINI_MODEL, "object": "model", "provider": "gemini"},
        ],
    })


# NOTE: /computer/* routes were extracted to computer_routes.py (Task 2, Group A).


# =============================================================================
# PROJECT BUILDER ROUTES — /project/*
# =============================================================================

@app.route("/project/start", methods=["POST"])
def project_start():
    """Start an interactive project build session via voice or chat."""
    data        = request.json or {}
    description = data.get("description", "").strip()
    session_id  = data.get("session_id", "default")
    if not description:
        return jsonify({"error": "description required"}), 400
    return jsonify(start_project_conversation(session_id, description))


@app.route("/project/answer", methods=["POST"])
def project_answer_route():
    """Answer a clarifying question for the active project build."""
    data       = request.json or {}
    session_id = data.get("session_id", "default")
    answer     = data.get("answer", "").strip()
    if not answer:
        return jsonify({"error": "answer required"}), 400
    return jsonify(answer_project_question(session_id, answer))


@app.route("/project/save", methods=["POST"])
def project_save():
    """Save code from clipboard and run the project."""
    data       = request.json or {}
    session_id = data.get("session_id", "default")
    return jsonify(save_project_code(session_id))


@app.route("/project/workspace", methods=["GET"])
def project_workspace():
    """List all projects in the workspace folder."""
    from task_orchestrator import _WORK_DIR
    from pathlib import Path
    projects = []
    workspace = Path(_WORK_DIR)
    if workspace.exists():
        for d in workspace.iterdir():
            if d.is_dir():
                files = list(d.glob("*.*"))
                projects.append({
                    "name":  d.name,
                    "files": [f.name for f in files],
                    "count": len(files),
                })
    return jsonify({"projects": projects, "workspace": str(_WORK_DIR)})


# =============================================================================
# PHONE CONTROL ROUTES — /phone/*
# =============================================================================

@app.route("/phone/status", methods=["GET"])
def phone_status_route():
    """Check if Android phone is connected via ADB."""
    from task_orchestrator import PhoneBridge
    phone = PhoneBridge()
    connected = phone.is_connected()
    return jsonify({
        "connected": connected,
        "message": "Phone connected via ADB!" if connected else
                   "Phone not detected. Connect USB cable and enable USB debugging.",
    })


@app.route("/phone/screenshot", methods=["GET"])
def phone_screenshot_route():
    """Take screenshot of connected phone."""
    from task_orchestrator import PhoneBridge
    return jsonify(PhoneBridge.take_screenshot())


@app.route("/phone/action", methods=["POST"])
def phone_action_route():
    """
    Control the phone.
    Body: {"action": "open_app|back|swipe|send_text", "params": {...}}
    """
    from task_orchestrator import PhoneBridge
    phone  = PhoneBridge()
    data   = request.json or {}
    action = data.get("action", "").strip()
    params = data.get("params", {})

    if not phone.is_connected():
        return jsonify({"success": False, "error": "Phone not connected via ADB"})

    if action == "open_app":
        return jsonify(phone.open_app(params.get("app", "")))
    elif action == "back":
        return jsonify(phone.press_back())
    elif action == "swipe":
        return jsonify(phone.swipe(params.get("direction", "up")))
    elif action == "send_text":
        return jsonify(phone.send_text(params.get("text", "")))
    return jsonify({"success": False, "error": f"Unknown phone action: {action}"})


# NOTE: /claude_loop/*, /verify/*, /self_modify/*, /app_control/*, /full_loop
#       routes were extracted to loop_routes.py (Task 2, Group D).


# =============================================================================
# PAGE CODE EXTRACTOR ROUTES — /code_extract/*
# Copy code from any web page and auto-paste to the right file
# =============================================================================

@app.route("/code_extract/list", methods=["POST"])
def code_extract_list():
    """
    List all code blocks on a page WITHOUT saving.
    Body: {"url": "https://...", "use_js": true}
    """
    if not PAGE_EXTRACTOR_AVAILABLE:
        return jsonify({"success": False, "error": "page_code_extractor not available"})
    data   = request.json or {}
    url    = data.get("url", "").strip()
    use_js = bool(data.get("use_js", True))
    if not url:
        return jsonify({"success": False, "error": "url required"})
    return jsonify(list_all_code_on_page(url, use_js=use_js))


@app.route("/code_extract/copy", methods=["POST"])
def code_extract_copy():
    """
    Extract a code block from a URL and save it to the right file.
    Body: {
        "url": "https://...",
        "save_to": "/path/to/file.py",   // optional — auto-detected if omitted
        "index": 0,                        // which block (0=first, -1=largest, "all")
        "use_js": true,
        "voice_confirm": true
    }
    Returns: {"success": true, "filepath": "...", "language": "python", "code_preview": "..."}
    """
    if not PAGE_EXTRACTOR_AVAILABLE:
        return jsonify({"success": False, "error": "page_code_extractor not available"})

    data    = request.json or {}
    url     = data.get("url", "").strip()
    save_to = data.get("save_to")
    index   = data.get("index", 0)
    use_js  = bool(data.get("use_js", True))
    voice   = bool(data.get("voice_confirm", True))

    if not url:
        return jsonify({"success": False, "error": "url required"})

    result = extract_and_save(
        url=url,
        save_to=save_to,
        index=index,
        use_js=use_js,
        voice_confirm=voice,
    )
    return jsonify(result)


@app.route("/code_extract/log", methods=["GET"])
def code_extract_log():
    limit = int(request.args.get("limit", 30))
    return jsonify({"log": get_extract_log(limit)})


# =============================================================================
# WIRELESS PHONE ROUTES — /phone/wireless/*
# Connect to Android phone over WiFi — no USB needed after first setup
# =============================================================================

@app.route("/phone/wireless/enable", methods=["POST"])
def phone_wireless_enable():
    """
    One-time setup: enable wireless ADB on phone.
    USB must be connected for THIS call only. After this you can unplug.

    Steps:
    1. Connect USB cable
    2. Enable USB Debugging on phone
    3. Call this endpoint
    4. Unplug USB — Ultron connects via WiFi from now on
    """
    from task_orchestrator import PhoneBridge
    return jsonify(PhoneBridge.enable_wireless())


@app.route("/phone/wireless/connect", methods=["POST"])
def phone_wireless_connect():
    """
    Reconnect to phone wirelessly using saved IP (no USB needed).
    Call this if connection dropped (e.g. after phone restart).
    """
    from task_orchestrator import PhoneBridge
    return jsonify(PhoneBridge.connect_saved_wireless())


@app.route("/phone/wireless/status", methods=["GET"])
def phone_wireless_status():
    """Check wireless ADB connection status + saved IP."""
    from task_orchestrator import PhoneBridge
    import json as _json
    ip_file = PhoneBridge._phone_ip_file
    saved_ip = PhoneBridge._load_saved_ip()
    connected = PhoneBridge.is_connected()
    return jsonify({
        "connected": connected,
        "saved_ip": saved_ip,
        "port": PhoneBridge._adb_port,
        "message": (
            f"Connected wirelessly to {saved_ip}" if connected and saved_ip
            else "Connected via USB" if connected
            else "Not connected. Connect USB and call /phone/wireless/enable first."
        ),
    })


@app.route("/phone/tap", methods=["POST"])
def phone_tap():
    """Tap a specific coordinate on the phone screen. Body: {"x": 500, "y": 900}"""
    from task_orchestrator import PhoneBridge
    data = request.json or {}
    x, y = data.get("x", 540), data.get("y", 960)
    if not PhoneBridge.is_connected():
        return jsonify({"success": False, "error": "Phone not connected"})
    try:
        import subprocess
        subprocess.run(["adb", "shell", "input", "tap", str(x), str(y)],
                       capture_output=True, timeout=5)
        return jsonify({"success": True, "x": x, "y": y})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/phone/key", methods=["POST"])
def phone_key():
    """Send a keyevent to the phone. Body: {"keycode": 3}  (3=HOME, 4=BACK, 26=POWER)"""
    from task_orchestrator import PhoneBridge
    data    = request.json or {}
    keycode = data.get("keycode", 3)
    if not PhoneBridge.is_connected():
        return jsonify({"success": False, "error": "Phone not connected"})
    try:
        import subprocess
        subprocess.run(["adb", "shell", "input", "keyevent", str(keycode)],
                       capture_output=True, timeout=5)
        return jsonify({"success": True, "keycode": keycode})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/phone/volume", methods=["POST"])
def phone_volume():
    """Adjust phone volume. Body: {"action": "up"/"down"/"mute"}"""
    from task_orchestrator import PhoneBridge
    data   = request.json or {}
    action = data.get("action", "up")
    keycodes = {"up": 24, "down": 25, "mute": 164}
    keycode  = keycodes.get(action, 24)
    if not PhoneBridge.is_connected():
        return jsonify({"success": False, "error": "Phone not connected"})
    try:
        import subprocess
        subprocess.run(["adb", "shell", "input", "keyevent", str(keycode)],
                       capture_output=True, timeout=5)
        return jsonify({"success": True, "action": action})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/self_upgrade/run", methods=["POST"])
def run_self_upgrade():
    """Trigger the self-upgrade pipeline: diagnose → fix → validate → apply."""
    try:
        from self_upgrade import run_upgrade
        return jsonify(run_upgrade())
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    print(f"\n{'='*60}")
    print(f"  {AGENT_NAME} v{cfg.AGENT_VERSION} — Autonomous AI for {JEEVAN_NAME}")
    print(f"  Location: {JEEVAN_LOCATION}")
    print(f"{'='*60}\n")

    # Migrate memory
    migrate_existing_memory()

    # Initialize Intelligence Core
    if INTELLIGENCE_AVAILABLE:
        init_intelligence()

    # Pre-warm SentenceTransformer + ChromaDB so the first /ask doesn't pay
    # the ~0.5-2s lazy-load cost. Runs on a background thread; failures are
    # silent because the recall path already handles a missing embedder.
    def _warm_vector_store():
        try:
            import vector_store as _vs
            _vs._init()
            if _vs._embed_model is not None:
                _vs._embed("warmup")
            print("[+] Vector store pre-warmed")
        except Exception as _e:
            print(f"[!] Vector store warmup skipped: {_e}")
    threading.Thread(target=_warm_vector_store, daemon=True, name="vs-warmup").start()

    # Start background systems
    start_monitor()
    print("[+] System monitor started")

    start_perception()
    print("[+] Perception engine started (file watcher + clipboard)")

    start_autonomous_loop()
    print("[+] Autonomous agent loop started")

    # Keep the OS awake while Ultron is running. Pure in-process — one daemon
    # thread that pokes SetThreadExecutionState (Windows) / caffeinate (macOS) /
    # systemd-inhibit (Linux) every ~30s. The Watchdog half of sleep_guard.py is
    # intentionally NOT wired here — that one launches app.py as a subprocess
    # and would recurse. For crash-restart protection, run
    # `python sleep_guard.py` instead of `python app.py`.
    try:
        from sleep_guard import SleepPreventer
        _sleep_preventer = SleepPreventer()
        _sleep_preventer.start()
        print("[+] Sleep preventer started (OS stays awake while Ultron runs)")
    except Exception as _e:
        print(f"[!] Sleep preventer skipped: {_e}")

    if VOICE_AVAILABLE:
        vs = get_voice_status()
        print(f"[+] Voice engine ready — TTS: {vs['tts']['active']} | STT: {vs['stt']['active']}")
        print(f"    Voice UI at: http://localhost:5000/voice")
        # Background pre-warm so the first /api/voice/speak doesn't pay
        # Kokoro's ~5s one-time model load, and the first slow-path
        # /api/voice/transcribe doesn't pay faster-whisper's ~10s load.
        # Pure pre-warm — voice output and transcription unchanged.
        try:
            from voice_engine import warmup_tts, warmup_stt
            warmup_tts()
            warmup_stt()
        except Exception as _e:
            print(f"[!] Voice warmup skipped: {_e}")
    else:
        print("[!] Voice engine not available — run: pip install edge-tts aiohttp")

    # New modules status
    print(f"[{'+' if CLAUDE_LOOP_AVAILABLE else '!'}] Claude.ai loop  — {'/claude_loop/*'}")
    print(f"[{'+' if VISUAL_VERIFY_AVAILABLE else '!'}] Visual verify   — {'/verify/*'}")
    print(f"[{'+' if SELF_MODIFY_AVAILABLE else '!'}] Self-modify      — {'/self_modify/*'}")
    print(f"[{'+' if APP_CONTROL_AVAILABLE else '!'}] App control      — {'/app_control/*'}")
    print(f"[{'+' if PAGE_EXTRACTOR_AVAILABLE else '!'}] Code extractor  — {'/code_extract/*'}")

    # Startup health table
    print(f"\n{'─'*46}")
    print(f"  Module health check")
    print(f"{'─'*46}")
    def _chk(label, fn):
        try:
            result = fn()
            icon = "✅" if result else "⚠️ "
            print(f"  {icon} {label:<22} {'OK' if result else 'WARN'}")
        except Exception as _exc:
            print(f"  ❌ {label:<22} {str(_exc)[:30]}")
    try:
        from config import GROQ_KEYS, GEMINI_KEYS, OPENROUTER_KEYS, TAVILY_KEY
        _chk("groq",       lambda: bool(GROQ_KEYS))
        _chk("gemini",     lambda: bool(GEMINI_KEYS))
        _chk("openrouter", lambda: bool(OPENROUTER_KEYS))
        _chk("tavily",     lambda: bool(TAVILY_KEY))
    except Exception as _e:
        print(f"  ⚠️  API keys check failed: {_e}")
    _chk("memory (sqlite)", lambda: __import__("memory").sqlite_get_history("_hc_", limit=1) is not None or True)
    _chk("voice_engine",    lambda: VOICE_AVAILABLE)
    print(f"{'─'*46}\n")

    print(f"\n[+] All systems online. {AGENT_NAME} is watching.\n")
    print(f"    Chat UI  at: http://localhost:5000")
    print(f"    Voice UI at: http://localhost:5000/voice\n")

    # Startup voice greeting — Edge TTS (GuyNeural), falls back to Windows SAPI
    def _startup_greeting():
        import time as _t
        import asyncio, tempfile, os as _os
        _t.sleep(1.5)
        try:
            import edge_tts
            _text  = "Hello Jeevan, Ultron J online. Ready to help."
            _voice = "en-US-GuyNeural"
            async def _gen():
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as _f:
                    _tmp = _f.name
                await edge_tts.Communicate(_text, _voice).save(_tmp)
                return _tmp
            _loop = asyncio.new_event_loop()
            _tmp  = _loop.run_until_complete(_gen())
            _loop.close()
            import winsound
            winsound.PlaySound(_tmp, winsound.SND_FILENAME)
            try:
                _os.unlink(_tmp)
            except Exception:
                pass
        except Exception as _e:
            print(f"[!] Edge TTS greeting failed ({_e}), falling back to SAPI")
            try:
                subprocess.Popen(
                    ["powershell", "-WindowStyle", "Hidden", "-c",
                     "Add-Type -AssemblyName System.speech;"
                     "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                     "$s.Volume=100;"
                     "$s.Speak('Hello Jeevan, Ultron J online.')"],
                    creationflags=0x08000000
                )
            except Exception as _e2:
                print(f"[!] Startup greeting failed: {_e2}")
    threading.Thread(target=_startup_greeting, daemon=True).start()

    try:
        from system_index import start_index_refresher
        start_index_refresher()
        print("[+] System index refresher started")
    except Exception as _e:
        print(f"[!] System index not available: {_e}")

    try:
        from activity_tracker import start_tracker
        ok = start_tracker()
        if ok is False:
            print("[!] Activity tracker: pynput not available — pip install pynput")
        else:
            print("[+] Activity tracker (mouse/keyboard) started")
    except Exception as _e:
        print(f"[!] Activity tracker skipped: {_e}")

    try:
        from code_index import start_code_indexer
        start_code_indexer()
        print("[+] Code indexer started (semantic search over project .py files)")
    except Exception as _e:
        print(f"[!] Code indexer skipped: {_e}")

    try:
        from screen_engine import start_screen_monitor, get_screen_status
        start_screen_monitor(interval=3.0)
        _ss = get_screen_status()
        print(f"[+] Screen monitor: OCR={_ss.get('ocr_available', False)} "
              f"PIL={_ss.get('pil_available', False)} "
              f"running={_ss.get('monitor_running', False)}")
    except Exception as _e:
        print(f"[!] Screen monitor failed to start: {_e}")

    if BEYOND_JARVIS_AVAILABLE:
        start_beyond_jarvis(app)
        print("[+] Beyond JARVIS background services started")

    from config import env_status_report, FEATURE_BY_KEY
    print("\n[+] Environment key status:")
    status = env_status_report()
    for k, ok in status.items():
        tick = "OK " if ok else "!! "
        print(f"    [{tick}] {k:12s}  -  {FEATURE_BY_KEY.get(k, '')}")
    missing = [k for k, ok in status.items() if not ok]
    if missing:
        print(f"\n[!] Missing keys: {', '.join(missing)}")
        print("    Affected features will be unavailable until added to .env\n")

    app.run(debug=False, host="0.0.0.0", port=5000, threaded=True, use_reloader=False)