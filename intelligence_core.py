"""
intelligence_core.py — Complete Intelligence Core for Ultron-J.
THE CORE PROBLEM THIS SOLVES:
─────────────────────────────────────────────────────────────────
Before: /ask route did this:
  messages = [last 10 history messages] + [user question]
  extra_context = perception_context (barely used)
  → stream_llm(messages, extra_context=extra_ctx)
That gives the LLM 5% of what it needs to be truly intelligent.
After: intelligence_core.think_and_stream() does this:
  1. Build FULL world state (all 10 data sources)
  2. Inject Jeevan model (who he is, how he thinks)
  3. Classify complexity (SIMPLE / MEDIUM / COMPLEX)
  4. SIMPLE → stream directly with rich context
  5. MEDIUM → chain-of-thought + stream
  6. COMPLEX → ReAct loop (reason + tools) → stream final answer
  7. Post-response → update Jeevan model if needed
─────────────────────────────────────────────────────────────────
HOW TO INTEGRATE INTO app.py:
─────────────────────────────────────────────────────────────────
Step 1 — Add imports at the top of app.py:
  from intelligence_core import think_and_stream, init_intelligence
Step 2 — After app = Flask(__name__):
  init_intelligence()
Step 3 — In the /ask route's generate() function, replace:
  for chunk in stream_llm(messages, temperature=temperature, extra_context=extra_ctx):
  ...
With:
  for chunk in think_and_stream(question, session_id, history_rows, temperature):
  ...
That's it. Everything else stays the same.
─────────────────────────────────────────────────────────────────
Author: Jeevan's Ultron-J Intelligence Core
"""
import json
import os
import queue as _queue_module
import re
import requests
import threading
import time
import datetime
from typing import Generator, List, Tuple

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

INTELLIGENCE_MODEL = "llama-3.3-70b-versatile"

# Output caps. JARVIS brevity is enforced at the prompt level, but these are
# the hard backstop so a verbose model can't blow past it.
INTELLIGENCE_MAX_TOKENS_SHORT = 350    # SIMPLE / MEDIUM / chat replies
INTELLIGENCE_MAX_TOKENS_LONG  = 1200   # COMPLEX path — when Jeevan needs depth

# Shared persona + tool inventory injected into every chat-path system prompt.
# Single source of truth — keep it next to the only function that uses it.
_PERSONA_BLOCK = (
    "You are Ultron-J, Jeevan's personal autonomous AI assistant. "
    "Speak like JARVIS — direct, calm, and short. "
    "Default to 1–2 sentences. Maximum 4 sentences unless Jeevan explicitly asks for detail. "
    "No hedging, no apologies, no 'as an AI' phrases, no headers, no bullet lists in chat replies."
)

_TOOLS_BLOCK = (
    "TOOLS YOU HAVE (Ultron's orchestrator runs these — DO NOT refuse them):\n"
    "  • Screen vision: I CAN see Jeevan's screen. The world-state header in "
    "this prompt contains live OCR text from his active window (under "
    "'🖥️ ON SCREEN:') and the focused window title. When Jeevan asks 'what's "
    "on my screen' / 'do you see my screen' / 'can you read my screen' — "
    "answer YES, then summarize whatever appears in the ON SCREEN section. "
    "Never deny screen access; the OCR pipeline (Tesseract + screen_engine) "
    "is wired and continuously running.\n"
    "  • Screen & input: take_screenshot, click, type_text, scroll, press_key, hotkey\n"
    "  • Apps: open_app (chrome, code, notepad, calc, spotify, whatsapp, discord, etc.), "
    "focus_window, list_windows, minimize, maximize\n"
    "  • Browser: open_url, chrome_new_tab, chrome_navigate, chrome_reload, chrome_close_tab\n"
    "  • VS Code: vscode_open_file, vscode_save, vscode_terminal, vscode_run_in_terminal\n"
    "  • Web: search_web (Tavily), web_scrape, weather_fetch, send_email\n"
    "  • Compute: calculate (math), run_python (sandbox)\n"
    "  • Files & folders: file_read, file_write, file_list, create_folder, open_folder\n"
    "  • Memory: memory_store, memory_fetch, semantic recall over past conversations\n"
    "  • Phone (ADB): phone_screenshot, phone_open_app, phone_back, phone_home, phone_swipe, "
    "phone_volume\n"
    "  • System: lock_screen, sleep, volume up/down, mute, empty_trash\n"
    "  • YouTube: 'open youtube and play X' — searches and auto-plays first result\n"
    "  • Project builder: 'build me a snake game' — scaffolds and runs an end-to-end project\n"
    "  • Voice: I speak aloud via edge-tts — I DO have a voice. When Jeevan asks if I can "
    "speak or hear, say YES. Never say 'I am a text-based AI'.\n"
    "When Jeevan asks for one of these, confirm in ONE short sentence "
    "(e.g. 'Taking a screenshot.' / 'Opening Chrome.' / 'Searching YouTube for X.'). "
    "The orchestrator runs the action — you do not need to. "
    "If a request is NOT in this list (e.g. 'pause video', 'show cricket score'), "
    "be honest: say it's not wired yet and offer to web-search instead.\n"
    "CRITICAL — Capability honesty: NEVER say 'I do not have access to view "
    "your screen', 'my capabilities are limited', 'I am a text-only AI', or "
    "similar denials. You have screen OCR, voice I/O, file/window control, "
    "and web search wired and running. When asked about a capability, "
    "consult this tool list — if the capability is listed, say YES.\n"
    "CRITICAL: Only report what tool results actually say. Never invent file paths, "
    "filenames, or claim an action completed if no success signal was returned. "
    "If a result message says 'Screenshot saved to X', quote X exactly."
)

# Thread lock for Jeevan model updates
_model_update_lock = threading.Lock()

# ── Response / world-state caches ─────────────────────────────────────────
_ws_cache: dict = {}               # world_state result → 5-second TTL
_WS_CACHE_TTL = 5

_simple_response_cache: dict = {}  # SIMPLE answer text → 60-second TTL
_SIMPLE_CACHE_TTL = 60


def _stamp_provider(sse_chunk: str, prov: str) -> str:
    """Inject `provider: <prov>` into a `_full` SSE event so the UI can show
    accurate per-message attribution. Non-_full events pass through unchanged.
    """
    if not isinstance(sse_chunk, str) or not sse_chunk.startswith("data: "):
        return sse_chunk
    raw = sse_chunk[6:].strip()
    if not raw or raw == "[DONE]":
        return sse_chunk
    try:
        obj = json.loads(raw)
    except Exception:
        return sse_chunk
    if "_full" not in obj:
        return sse_chunk
    obj.setdefault("provider", prov)
    return f"data: {json.dumps(obj)}\n\n"

# =============================================================================
# INIT
# =============================================================================
def init_intelligence():
    """
    Initialize the Intelligence Core on startup.
    Call once after Flask app is created.
    """
    print("[Intelligence Core] Initializing...")
    # Create jeevan_model.json if it doesn't exist
    try:
        from jeevan_model import load_profile, save_profile, DEFAULT_PROFILE
        profile = load_profile()
        if not profile.get("last_updated"):
            save_profile(profile)
        print("[Intelligence Core] Jeevan model initialized.")
    except Exception as e:
        print(f"[Intelligence Core] Jeevan model init warning: {e}")
    print("[Intelligence Core] Ready. World State + Jeevan Model + ReAct active.")


# =============================================================================
# STREAMING LLM CALL WITH INTELLIGENCE SYSTEM PROMPT
# =============================================================================
def _stream_with_intelligence_prompt(
    system_prompt: str,
    history: list,
    question: str,
    temperature: float = 0.7,
    max_tokens: int = INTELLIGENCE_MAX_TOKENS_SHORT,
    provider: str = "auto",
) -> Generator:
    """
    Stream a response using the enriched intelligence system prompt.
    Provider routing:
      - "auto" / "groq" → try Groq Llama 3.3 70B direct, fall back to stream_llm chain.
      - "gemini" / "openrouter" → skip Groq, go straight to stream_llm with that provider forced.
      - "ollama:<model>" → handled upstream in app.py; should never reach here.
    """
    # Build message list
    messages = [{"role": "system", "content": system_prompt}]

    # Add history (last 8 turns)
    for role, content in (history or [])[-8:]:
        messages.append({"role": role, "content": str(content)})

    # Add current question
    messages.append({"role": "user", "content": question})

    # ── User forced a non-Groq cloud provider — skip Groq-direct entirely ────
    # The Groq direct path below is only correct when the user wants Groq (or
    # didn't pick anything). Honoring the dropdown means not silently trying
    # Groq first.
    _prov = (provider or "auto").lower().strip()
    if _prov in ("gemini", "openrouter"):
        from llm_engine import stream_llm
        try:
            # Stamp the actual provider used onto every _full event so the UI
            # can show per-message attribution instead of stale heartbeat data.
            for chunk in stream_llm(messages, temperature=temperature, force_provider=_prov):
                yield _stamp_provider(chunk, _prov)
        except Exception:
            err_msg = f"{_prov.title()} stream failed. Please try again."
            yield f"data: {json.dumps({'token': err_msg})}\n\n"
            yield f"data: {json.dumps({'_full': err_msg, 'provider': _prov})}\n\n"
        return

    _groq_rate_limited = False
    _groq_direct_failed = False
    try:
        from config import GROQ_KEYS, GROQ_URL, get_next_key
        if not GROQ_KEYS:
            raise ValueError("No Groq keys")

        key = get_next_key("groq", GROQ_KEYS)
        full_response = ""

        # Streaming timeout: (connect, read-per-chunk). 25s per-chunk lets a
        # silent server be detected as stalled instead of hanging the UI.
        resp = requests.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": INTELLIGENCE_MODEL,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": True,
            },
            stream=True,
            timeout=(10, 25),
        )
        resp.raise_for_status()

        for line in resp.iter_lines():
            if not line:
                continue
            text = line.decode("utf-8") if isinstance(line, bytes) else line
            if not text.startswith("data: "):
                continue
            chunk_data = text[6:]
            if chunk_data == "[DONE]":
                break
            try:
                parsed = json.loads(chunk_data)
                if "error" in parsed:
                    raise ValueError(parsed["error"])
                token = parsed["choices"][0]["delta"].get("content", "")
                if token:
                    full_response += token
                    yield f"data: {json.dumps({'token': token})}\n\n"
            except (KeyError, IndexError, json.JSONDecodeError, ValueError):
                pass

        if full_response:
            yield f"data: {json.dumps({'_full': full_response, 'provider': 'groq'})}\n\n"
        return

    except Exception as _exc:
        _status = getattr(getattr(_exc, 'response', None), 'status_code', None)
        _groq_direct_failed = True
        # Push Groq past the failure threshold so stream_llm auto mode skips it
        # and goes straight to Gemini → OpenRouter with full fallback chain.
        try:
            from llm_engine import _mark_provider_failure, PROVIDER_FAILURE_THRESHOLD
            _calls = PROVIDER_FAILURE_THRESHOLD if _status != 429 else (PROVIDER_FAILURE_THRESHOLD * 2)
            for _ in range(_calls):
                _mark_provider_failure('groq', _status or 500)
        except Exception:
            pass

    # Fallback after Groq-direct failure.
    # STRICT provider lock: when the user explicitly picked groq / gemini /
    # openrouter we forward that exact provider through to stream_llm so
    # `order = [force_provider]` (line ~688 in llm_engine) — meaning no
    # silent cross-cloud cascade. If their pick is also dead, stream_llm
    # ends in the Ollama fallback (line ~758) rather than secretly answering
    # via a provider the user did not consent to.
    # 'auto' is the only mode that gets the full cascade.
    try:
        from llm_engine import stream_llm, get_current_provider
        _fallback_prov = _prov if _prov in ("groq", "gemini", "openrouter") else "auto"
        for chunk in stream_llm(messages, temperature=temperature, force_provider=_fallback_prov):
            # In "auto" mode we don't know upfront which provider stream_llm
            # picks — use get_current_provider() at emit time so the _full
            # event still shows something accurate.
            yield _stamp_provider(chunk, _fallback_prov if _fallback_prov != "auto"
                                  else (get_current_provider() or "auto"))
    except Exception as e:
        err_msg = "Intelligence core stream failed. Please try again."
        yield f"data: {json.dumps({'token': err_msg})}\n\n"
        yield f"data: {json.dumps({'_full': err_msg})}\n\n"


# =============================================================================
# STATUS STREAMER — yields thinking/action status tokens
# =============================================================================
def _status_token(message: str) -> str:
    """Yield a status indicator token (shown in UI while thinking)."""
    return f"data: {json.dumps({'token': message, 'type': 'status'})}\n\n"


# =============================================================================
# MAIN INTELLIGENCE FUNCTION
# =============================================================================
def think_and_stream(
    question: str,
    session_id: str,
    history: list,
    temperature: float = 0.7,
    search_context: str = "",
    provider: str = "auto",
) -> Generator:
    """
    The complete intelligence pipeline. Drop-in replacement for
    the stream_llm call in app.py's /ask route.

    Args:
        question: The user's question
        session_id: Current session ID
        history: List of (role, content) tuples from sqlite_get_history
        temperature: LLM temperature

    Yields:
        SSE chunks in format: data: {"token": "..."}\n\n
        Final: data: {"_full": "full response"}\n\n
    """
    # Immediate status ping — browser sees this in <1 ms, spinner starts
    yield _status_token("⚡ Processing...")

    # ── Step 0: Classify Complexity FIRST (cheap regex) ───────────────────────
    # Moved ahead of context build so SIMPLE questions ("hi", "what time")
    # can skip the heavy recall + world_state + jeevan_model work entirely.
    complexity = "MEDIUM"
    try:
        from react_engine import classify_complexity
        complexity = classify_complexity(question)
    except Exception:
        pass

    # ── Step 1: Fast path for SIMPLE — skip the entire context build ─────────
    # Greetings, time/date, "who are you" — these don't benefit from semantic
    # memory recall, code-index lookup, screen OCR injection, or vector
    # research. Persona + tools block alone is enough. Saves 0.5-1.5s.
    if complexity == "SIMPLE":
        # Check 60-second response cache — same question gets instant replay
        _cache_key = hash(question.strip().lower())
        _cached_simple = _simple_response_cache.get(_cache_key)
        if _cached_simple and (time.time() - _cached_simple["ts"]) < _SIMPLE_CACHE_TTL:
            _ct = _cached_simple["text"]
            _words = _ct.split(" ")
            for _i, _w in enumerate(_words):
                yield f"data: {json.dumps({'token': _w + (' ' if _i < len(_words) - 1 else '')})}\n\n"
            yield f"data: {json.dumps({'_full': _ct, 'provider': 'cache'})}\n\n"
            return

        # Still kick off the conversation-count update in the background — it's
        # the only state side-effect we'd lose otherwise.
        try:
            from jeevan_model import (
                increment_conversation_count, should_update_profile,
                update_profile_async,
            )
            def _bump():
                try:
                    increment_conversation_count()
                    if should_update_profile():
                        update_profile_async(session_id)
                except Exception:
                    pass
            threading.Thread(target=_bump, daemon=True).start()
        except Exception:
            pass

        ws_simple = ""
        if search_context:
            ws_simple = "=== Web Search Results ===\n" + search_context.strip()
        system_prompt = _build_simple_system_prompt(ws_simple, "")
        for _chunk in _stream_with_intelligence_prompt(
            system_prompt, history, question, temperature,
            provider=provider,
        ):
            if isinstance(_chunk, str) and '"_full"' in _chunk:
                try:
                    _obj = json.loads(_chunk[6:].strip())
                    if "_full" in _obj and _obj["_full"]:
                        _simple_response_cache[_cache_key] = {
                            "text": _obj["_full"], "ts": time.time()
                        }
                except Exception:
                    pass
            yield _chunk
        return

    # ── Step 2: Parallel context build for MEDIUM/COMPLEX ────────────────────
    # recall (vector + mem0), world_state, and jeevan_model are independent.
    # Running them sequentially adds 0.5-1.5s of unnecessary wall-clock cost.
    # Each task writes its result into the shared `ctx` dict; the join below
    # blocks at most _CTX_BUILD_TIMEOUT seconds total so one slow source
    # can't stall the whole reply.
    ctx = {"recall": "", "world_state": "", "jeevan": ""}

    def _build_recall():
        block = ""
        try:
            import vector_store as _vs
            hits = _vs.recall(question, n=12)
            turns   = [h for h in hits if (h.get("metadata") or {}).get("kind") == "turn"     and h.get("score", 0) >= 0.40][:3]
            lessons = [h for h in hits if (h.get("metadata") or {}).get("kind") == "lesson"   and h.get("score", 0) >= 0.35][:2]
            research= [h for h in hits if (h.get("metadata") or {}).get("kind") == "research" and h.get("score", 0) >= 0.55][:1]
            pieces = []
            if lessons:
                pieces.append("Relevant lessons from past work:")
                for l in lessons:
                    pieces.append(f"  • {l['text'][:220]}")
            if research:
                pieces.append("\nPrior research on this topic:")
                for r in research:
                    pieces.append(f"  • {r['text'][:300]}")
            if turns:
                pieces.append("\nRelated past conversation snippets:")
                for t in turns[:2]:
                    pieces.append(f"  • {t['text'][:200]}")
            if pieces:
                block = "=== Memory Recall ===\n" + "\n".join(pieces)
        except Exception:
            pass
        try:
            from smart_memory import recall as _smart_recall, MEM0_AVAILABLE as _MEM0_AVAIL
            if _MEM0_AVAIL:
                smart_facts = _smart_recall(question)
                if smart_facts:
                    facts_block = "USER FACTS:\n" + "\n".join(f"- {f}" for f in smart_facts)
                    block = (block + "\n\n" + facts_block) if block else facts_block
        except Exception:
            pass
        ctx["recall"] = block

    def _build_world_state():
        _now = time.time()
        _ws_key = question[:120]
        _hit = _ws_cache.get(_ws_key)
        if _hit and (_now - _hit["ts"]) < _WS_CACHE_TTL:
            ctx["world_state"] = _hit["val"]
            return
        try:
            from world_state import build_world_state_header
            ws = build_world_state_header(question)
            ctx["world_state"] = ws
            _ws_cache[_ws_key] = {"val": ws, "ts": _now}
        except Exception:
            pass

    def _build_jeevan():
        try:
            from jeevan_model import (
                get_profile_for_prompt, increment_conversation_count,
                should_update_profile, update_profile_async,
            )
            ctx["jeevan"] = get_profile_for_prompt()
            def _count_and_maybe_update():
                try:
                    increment_conversation_count()
                    if should_update_profile():
                        update_profile_async(session_id)
                except Exception:
                    pass
            threading.Thread(target=_count_and_maybe_update, daemon=True).start()
        except Exception:
            pass

    _CTX_BUILD_TIMEOUT = 3.0  # hard ceiling; partial context is fine
    workers = [
        threading.Thread(target=_build_recall,      daemon=True, name="ctx-recall"),
        threading.Thread(target=_build_world_state, daemon=True, name="ctx-world"),
        threading.Thread(target=_build_jeevan,      daemon=True, name="ctx-jeevan"),
    ]
    _t0 = __import__("time").perf_counter()
    for w in workers: w.start()
    for w in workers:
        remaining = max(0.05, _CTX_BUILD_TIMEOUT - (__import__("time").perf_counter() - _t0))
        w.join(timeout=remaining)

    recall_block   = ctx["recall"]
    world_state    = ctx["world_state"]
    jeevan_profile = ctx["jeevan"]

    if recall_block:
        world_state = (world_state + "\n\n" + recall_block) if world_state else recall_block

    if search_context:
        _sc_block = "=== Web Search Results ===\n" + search_context.strip()
        world_state = (world_state + "\n\n" + _sc_block) if world_state else _sc_block

    # ── Step 3b: Planner intercept (NEW) ──────────────────────────────────────
    # For COMPLEX requests, optionally route through the DAG planner. Opt-in
    # via the USE_BRAIN_ORCHESTRATOR env var OR the "kartha plan" phrase so
    # we don't change behaviour for unprepared users.
    use_planner = False
    ql = question.lower()
    if ("plan this" in ql or "plan:" in ql or "kartha plan" in ql or
            os.environ.get("USE_BRAIN_ORCHESTRATOR") == "1"):
        use_planner = (complexity == "COMPLEX")

    if use_planner:
        try:
            from brain_orchestrator import orchestrate
            yield _status_token("🗺️  Planning steps...")
            result = orchestrate(question, context=world_state[:2000])
            if result.get("used_planner") and result.get("answer"):
                ans = result["answer"]
                words = ans.split(" ")
                for i, word in enumerate(words):
                    token = word + (" " if i < len(words) - 1 else "")
                    yield f"data: {json.dumps({'token': token})}\n\n"
                yield f"data: {json.dumps({'_full': ans, '_graph_id': result.get('graph_id')})}\n\n"
                return
            # planner said trivial — fall through to normal flow
        except Exception as e:
            yield _status_token(f"⚠️ Planner failed: {str(e)[:80]}")

    # ── Step 4: Route by complexity ───────────────────────────────────────────
    # SIMPLE is handled by Step 1's early return; only MEDIUM and COMPLEX can
    # reach this point.
    if complexity == "MEDIUM":
        # ── MEDIUM PATH: CoT instruction + rich context ───────────────────────
        yield _status_token("🧠 Thinking...")
        system_prompt = _build_medium_system_prompt(world_state, jeevan_profile)
        yield from _stream_with_intelligence_prompt(
            system_prompt, history, question, temperature,
            provider=provider,
        )
        return

    # ── COMPLEX PATH: Full ReAct reasoning loop ───────────────────────────────
    yield _status_token("🔍 Analyzing deeply...")

    try:
        from react_engine import reason, get_reasoning_system_for_stream
    except ImportError:
        # Graceful fallback if react_engine not available
        system_prompt = _build_medium_system_prompt(world_state, jeevan_profile)
        yield from _stream_with_intelligence_prompt(
            system_prompt, history, question, temperature,
            max_tokens=INTELLIGENCE_MAX_TOKENS_LONG,
            provider=provider,
        )
        return

    # Run reasoning phase with live status streaming via a queue.
    # reason() runs in a background thread; each tool call it makes pushes a
    # status string into the queue so we can yield it live to the browser.
    _react_q = _queue_module.Queue()
    _react_result = [None]

    def _react_status_cb(msg: str):
        _react_q.put(msg)

    def _react_thread():
        try:
            _react_result[0] = reason(
                question=question,
                history=history,
                world_state=world_state,
                jeevan_profile=jeevan_profile,
                complexity=complexity,
                status_callback=_react_status_cb,
            )
        except Exception:
            _react_result[0] = ("", [])
        _react_q.put(None)  # sentinel — tells the drain loop to stop

    _rt = threading.Thread(target=_react_thread, daemon=True)
    _rt.start()

    # Drain status queue while reasoning runs — each item is yielded live
    while True:
        try:
            _msg = _react_q.get(timeout=30)
        except _queue_module.Empty:
            break
        if _msg is None:
            break
        yield _status_token(_msg)

    _rt.join(timeout=5)
    pre_answer, steps = _react_result[0] or ("", [])

    # Collect tool results for enriched context (post-reasoning)
    tool_results = []
    for step in steps:
        if "tool_called" in step and "tool_result" in step:
            tool_results.append(f"[{step['tool_called']}]: {step['tool_result']}")

    enriched_context = "\n".join(tool_results)

    # If reasoning phase already produced a complete answer, stream it directly
    if pre_answer and len(pre_answer.strip()) > 30:
        # Stream the pre-computed answer token by token for smooth UX
        full_response = pre_answer.strip()
        words = full_response.split(" ")
        for i, word in enumerate(words):
            token = word + (" " if i < len(words) - 1 else "")
            yield f"data: {json.dumps({'token': token})}\n\n"
        yield f"data: {json.dumps({'_full': full_response})}\n\n"
        return

    # Otherwise: stream final answer with all enriched context
    system_prompt = get_reasoning_system_for_stream(
        world_state=world_state,
        jeevan_profile=jeevan_profile,
        enriched_context=enriched_context,
        complexity=complexity,
    )
    yield from _stream_with_intelligence_prompt(
        system_prompt, history, question, temperature,
        max_tokens=INTELLIGENCE_MAX_TOKENS_LONG,
        provider=provider,
    )


# =============================================================================
# SYSTEM PROMPT BUILDERS
# =============================================================================
def _build_simple_system_prompt(world_state: str, jeevan_profile: str) -> str:
    """System prompt for simple queries — persona + tools + rich context, direct answer."""
    parts = [_PERSONA_BLOCK, _TOOLS_BLOCK]
    if jeevan_profile:
        parts.append(jeevan_profile)
    if world_state:
        parts.append(world_state)
    return "\n\n".join(parts)


def _build_medium_system_prompt(world_state: str, jeevan_profile: str) -> str:
    """System prompt for medium queries — persona + tools + CoT hint + rich context."""
    parts = [_PERSONA_BLOCK, _TOOLS_BLOCK]
    if jeevan_profile:
        parts.append(jeevan_profile)
    if world_state:
        parts.append(world_state)
    parts.append(
        "APPROACH: Before answering, briefly think — what is Jeevan really asking? "
        "What do I already know that's relevant? Then answer in 1–3 sentences."
    )
    return "\n\n".join(parts)


# =============================================================================
# UTILITY: Non-streaming intelligence call (for agent tasks)
# =============================================================================
def intelligence_batch(prompt: str, system: str = "", context: str = "") -> str:
    """
    Non-streaming intelligence call for autonomous agent tasks.
    Uses world state + Jeevan model automatically.

    Args:
        prompt: The task/question
        system: Optional additional system instruction
        context: Optional additional context

    Returns:
        Full response string
    """
    world_state = ""
    jeevan_profile = ""

    try:
        from world_state import build_world_state_header
        world_state = build_world_state_header(prompt)
    except Exception:
        pass

    try:
        from jeevan_model import get_profile_for_prompt
        jeevan_profile = get_profile_for_prompt()
    except Exception:
        pass

    sys_prompt = (
        "You are Ultron-J, Jeevan's personal autonomous AI. "
        "Be intelligent, direct, and precise.\n\n"
    )
    if jeevan_profile:
        sys_prompt += jeevan_profile + "\n\n"
    if world_state:
        sys_prompt += world_state + "\n\n"
    if system:
        sys_prompt += system + "\n\n"
    if context:
        sys_prompt += f"Additional context:\n{context}\n\n"

    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": prompt},
    ]

    try:
        from config import GROQ_KEYS, GROQ_URL, get_next_key
        if not GROQ_KEYS:
            raise ValueError("No Groq keys")

        key = get_next_key("groq", GROQ_KEYS)
        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": INTELLIGENCE_MODEL,
                "messages": messages,
                "max_tokens": 1500,
                "temperature": 0.4,
                "stream": False,
            },
            timeout=45,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception:
        try:
            from llm_engine import call_llm_batch
            return call_llm_batch(prompt, system=sys_prompt)
        except Exception:
            return ""


# =============================================================================
# STATUS ENDPOINT SUPPORT
# =============================================================================
def get_intelligence_status() -> dict:
    """Return status info for the /status endpoint."""
    try:
        from jeevan_model import load_profile
        profile = load_profile()
        profile_status = {
            "version": profile.get("version", 1),
            "conversation_count": profile.get("conversation_count", 0),
            "last_updated": profile.get("last_updated", "never"),
        }
    except Exception:
        profile_status = {"error": "jeevan_model unavailable"}

    return {
        "intelligence_core": "active",
        "model": INTELLIGENCE_MODEL,
        "modules": {
            "world_state": _check_module("world_state"),
            "jeevan_model": _check_module("jeevan_model"),
            "react_engine": _check_module("react_engine"),
        },
        "jeevan_model": profile_status,
    }


def _check_module(name: str) -> str:
    try:
        __import__(name)
        return "✅ loaded"
    except ImportError:
        return "❌ not found"
    except Exception as e:
        return f"⚠️ error: {str(e)[:50]}"
