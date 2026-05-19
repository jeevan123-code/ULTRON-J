"""
llm_engine.py — Multi-provider cloud LLM engine for Ultron-J ULTIMATE v3.

PROVIDERS:
  1. Groq      — fastest, free tier, llama-3.3-70b  [WORKING]
  2. Gemini    — Google AI, gemini-2.0-flash  [FIXED — proper auth + model fallback]
  3. OpenRouter — aggregator, free :free models  [FIXED — updated model list]
"""

import json
import time
import threading
import datetime
import requests

from config import (
    GROQ_URL, GROQ_MODEL, GROQ_KEYS,
    GEMINI_URL, GEMINI_MODEL, GEMINI_KEYS,
    OPENROUTER_URL, OPENROUTER_FALLBACK_MODELS, OPENROUTER_KEYS,
    MAX_RETRY_ATTEMPTS, PROVIDER_HEALTH_FILE,
    PROVIDER_FAILURE_THRESHOLD, PROVIDER_HEALTH_TTL,
    get_next_key,
)

# New config additions
try:
    from config import GEMINI_MODELS
except ImportError:
    GEMINI_MODELS = [GEMINI_MODEL, "gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.0-flash"]

try:
    from system_monitor import push_alert
except ImportError:
    def push_alert(msg): print(f"[ALERT] {msg}")

# =============================================================================
# PROVIDER HEALTH TRACKER
# =============================================================================

_health_lock     = threading.Lock()
_provider_health = {}


_FAILURE_LOG = "provider_failures.log"


def _mark_provider_failure(provider: str, status_code: int = 500):
    with _health_lock:
        h = _provider_health.setdefault(provider, {
            "failures": 0, "healthy": True, "last_fail": None, "cooldown": 60
        })
        h["failures"] += 1
        h["last_fail"]  = datetime.datetime.now().isoformat()
        # 429 = rate limit, recovers in ~60s — cap cooldown at 90s
        # 401 = wrong key, short cooldown too (user should fix the key)
        # 5xx = server error, use exponential backoff up to 1h
        if status_code == 429:
            h["cooldown"] = 90
        elif status_code == 401:
            h["cooldown"] = 120
        else:
            h["cooldown"] = min(3600, 60 * (2 ** (h["failures"] - 1)))
        threshold = PROVIDER_FAILURE_THRESHOLD if status_code != 429 else PROVIDER_FAILURE_THRESHOLD * 2
        if h["failures"] >= threshold:
            h["healthy"] = False
            push_alert(f"Provider '{provider}' cooling down {h['cooldown']}s")

    # Log to file so failures are visible post-mortem
    try:
        with open(_FAILURE_LOG, "a") as _f:
            _f.write(
                f"{datetime.datetime.now().isoformat()} | {provider} | "
                f"http={status_code} | failures={h['failures']} | "
                f"healthy={h['healthy']}\n"
            )
    except Exception:
        pass
    print(f"[LLM] FAIL: {provider} (HTTP {status_code}, total failures: {h['failures']})")


def _mark_provider_success(provider: str):
    with _health_lock:
        h = _provider_health.setdefault(provider, {
            "failures": 0, "healthy": True, "last_fail": None, "cooldown": 60
        })
        h["failures"] = 0
        h["healthy"]  = True
        h["cooldown"] = 60


def _is_provider_healthy(provider: str) -> bool:
    with _health_lock:
        h = _provider_health.get(provider, {"healthy": True, "last_fail": None, "cooldown": 60})
        if h.get("healthy", True):
            return True
        last_fail = h.get("last_fail")
        if last_fail:
            try:
                elapsed = (datetime.datetime.now() -
                           datetime.datetime.fromisoformat(last_fail)).total_seconds()
                if elapsed > h.get("cooldown", PROVIDER_HEALTH_TTL):
                    h["healthy"]  = True
                    h["failures"] = max(0, h["failures"] - 1)
                    return True
            except Exception:
                pass
        return False


def get_provider_health() -> dict:
    with _health_lock:
        result = {}
        for k, v in _provider_health.items():
            remaining = 0
            if not v.get("healthy", True) and v.get("last_fail"):
                try:
                    elapsed = (datetime.datetime.now() -
                               datetime.datetime.fromisoformat(v["last_fail"])).total_seconds()
                    remaining = max(0, v.get("cooldown", 0) - elapsed)
                except Exception:
                    pass
            result[k] = {**v, "cooldown_remaining_sec": int(remaining)}
        return result

# =============================================================================
# TASK-BASED ROUTING
# =============================================================================

_COMPLEX_KEYWORDS = {
    "build", "code", "game", "script", "analyze", "debug", "architecture",
    "design", "develop", "program", "create", "write", "implement", "fix",
    "explain in detail", "compare", "research", "summarize", "essay", "plan",
}


def determine_best_provider(prompt: str) -> str:
    pl = prompt.lower()
    is_complex = any(kw in pl for kw in _COMPLEX_KEYWORDS)
    if is_complex:
        for p in ("gemini", "openrouter", "groq"):
            if _is_provider_healthy(p):
                return p
    else:
        for p in ("groq", "gemini", "openrouter"):
            if _is_provider_healthy(p):
                return p
    return "groq"

# =============================================================================
# FORCED PROVIDER STATE
# =============================================================================

_forced_provider      = None
_forced_provider_lock = threading.Lock()


def set_forced_provider(provider):
    global _forced_provider
    with _forced_provider_lock:
        _forced_provider = provider


def get_current_provider() -> str:
    with _forced_provider_lock:
        if _forced_provider:
            return _forced_provider
    for p in ("groq", "gemini", "openrouter"):
        if _is_provider_healthy(p):
            return p
    return "groq"

# =============================================================================
# PERSONALITY PROMPT
# =============================================================================

def _get_personality_system_prompt() -> str:
    try:
        from personality import get_personality_prompt
        return get_personality_prompt()
    except Exception:
        return (
            "You are Ultron-J, a personal autonomous AI assistant for Jeevan in Hyderabad, India. "
            "Be direct, concise, and intelligent. Speak like Jarvis — calm, confident. "
            "For voice responses keep it under 3 sentences unless detail is needed."
        )


def _inject_context(messages: list, extra_context: str = "") -> list:
    if not extra_context:
        try:
            from perception import build_perception_context
            extra_context = build_perception_context()
        except Exception:
            pass

    base_system = _get_personality_system_prompt()
    full_system = base_system + (f"\n\n--- Current Context ---\n{extra_context}" if extra_context else "")

    if messages and messages[0].get("role") == "system":
        existing = messages[0].get("content", "")
        messages = [{"role": "system", "content": f"{full_system}\n\n{existing}"}] + messages[1:]
    else:
        messages = [{"role": "system", "content": full_system}] + messages

    return messages


def _is_limit_error(status_code: int) -> bool:
    return status_code in (429, 402, 503)


def _make_http_error(code: int, msg: str) -> requests.exceptions.HTTPError:
    fake = requests.models.Response()
    try:
        fake.status_code = int(code)
    except Exception:
        fake.status_code = 429
    fake._content = str(msg).encode()
    return requests.exceptions.HTTPError(f"HTTP {code}: {msg}", response=fake)

# =============================================================================
# GROQ (working, no changes needed)
# =============================================================================

def _call_groq_streaming(api_key: str, messages: list, temperature: float):
    headers   = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    safe_temp = round(max(0.0, min(1.0, float(temperature))), 2)
    full_response = ""
    payload = {
        "model":       GROQ_MODEL,
        "messages":    messages,
        "max_tokens":  1500,
        "temperature": safe_temp,
        "stream":      True,
    }
    resp = requests.post(GROQ_URL, headers=headers, json=payload, stream=True, timeout=60)
    if resp.status_code == 400:
        resp.close()
        payload.pop("temperature", None)
        resp = requests.post(GROQ_URL, headers=headers, json=payload, stream=True, timeout=60)
    with resp:
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
                    err  = parsed["error"]
                    code = err.get("code") or err.get("status") or 429
                    raise _make_http_error(code, err.get("message", "Groq error"))
                token = parsed["choices"][0]["delta"].get("content", "")
                if token:
                    full_response += token
                    yield f"data: {json.dumps({'token': token})}\n\n"
            except requests.exceptions.HTTPError:
                raise
            except (KeyError, IndexError, json.JSONDecodeError):
                pass
    yield f"data: {json.dumps({'_full': full_response})}\n\n"

# =============================================================================
# GEMINI — FIXED: API key in BOTH header and query param
# =============================================================================

def _call_gemini_streaming(api_key: str, messages: list, temperature: float):
    safe_temp = round(max(0.0, min(1.0, float(temperature))), 2)
    full_response = ""

    for model in GEMINI_MODELS:
        full_response = ""
        try:
            # Google requires key as query param for some API versions
            url = f"{GEMINI_URL}?key={api_key}"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            resp = requests.post(
                url, headers=headers,
                json={"model": model, "messages": messages,
                      "max_tokens": 1500, "temperature": safe_temp, "stream": True},
                stream=True, timeout=60,
            )
            if resp.status_code in (400, 404, 429):
                resp.close()
                continue  # try next Gemini model
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
                        raise RuntimeError(str(parsed["error"]))
                    token = parsed["choices"][0]["delta"].get("content", "")
                    if token:
                        full_response += token
                        yield f"data: {json.dumps({'token': token})}\n\n"
                except (KeyError, IndexError, json.JSONDecodeError):
                    pass

            if full_response:
                yield f"data: {json.dumps({'_full': full_response})}\n\n"
                return

        except requests.exceptions.HTTPError as e:
            sc = getattr(getattr(e, "response", None), "status_code", 500)
            if sc in (400, 404, 429):
                continue  # try next Gemini model
            raise
        except Exception:
            continue

    if full_response:
        yield f"data: {json.dumps({'_full': full_response})}\n\n"
    else:
        raise RuntimeError("All Gemini models failed")


def _call_gemini_batch(api_key: str, messages: list) -> str:
    for model in GEMINI_MODELS:
        try:
            url = f"{GEMINI_URL}?key={api_key}"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            resp = requests.post(
                url, headers=headers,
                json={"model": model, "messages": messages, "max_tokens": 2000, "stream": False},
                timeout=60,
            )
            if resp.status_code in (400, 404):
                continue
            resp.raise_for_status()
            result = resp.json()["choices"][0]["message"]["content"]
            if result:
                return result
        except Exception:
            continue
    return ""

# =============================================================================
# OPENROUTER — updated to :free models
# =============================================================================

def _call_openrouter_one_model(api_key: str, model: str, messages: list, temperature: float):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
        "HTTP-Referer":  "https://ultron-j.local",
        "X-Title":       "ULTRON-J",
    }
    safe_temp     = round(max(0.0, min(1.0, float(temperature))), 2)
    full_response = ""
    with requests.post(
        OPENROUTER_URL, headers=headers,
        json={"model": model, "messages": messages,
              "max_tokens": 1500, "temperature": safe_temp, "stream": True},
        stream=True, timeout=60,
    ) as resp:
        if resp.status_code in (400, 404, 402):
            raise requests.exceptions.HTTPError(
                f"Model {model} not available", response=resp)
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
                token  = parsed["choices"][0]["delta"].get("content", "")
                if token:
                    full_response += token
                    yield f"data: {json.dumps({'token': token})}\n\n"
            except (KeyError, IndexError, json.JSONDecodeError):
                pass
    yield f"data: {json.dumps({'_full': full_response})}\n\n"

# =============================================================================
# BATCH (non-streaming)
# =============================================================================

def call_llm_batch(prompt: str, system: str = "", provider: str = None) -> str:
    sys_msg  = system or _get_personality_system_prompt()
    messages = [
        {"role": "system", "content": sys_msg},
        {"role": "user",   "content": prompt},
    ]
    provider = provider or determine_best_provider(prompt)

    if GROQ_KEYS and (provider == "groq" or provider not in ("gemini", "openrouter")):
        key = get_next_key("groq", GROQ_KEYS)
        try:
            resp = requests.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": GROQ_MODEL, "messages": messages, "max_tokens": 2000, "stream": False},
                timeout=60,
            )
            resp.raise_for_status()
            result = resp.json()["choices"][0]["message"]["content"]
            if result:
                _mark_provider_success("groq")
                return result
        except Exception as e:
            sc = getattr(getattr(e, "response", None), "status_code", 500)
            _mark_provider_failure("groq", sc)

    if GEMINI_KEYS:
        key    = get_next_key("gemini", GEMINI_KEYS)
        result = _call_gemini_batch(key, messages)
        if result:
            _mark_provider_success("gemini")
            return result
        _mark_provider_failure("gemini")

    # Groq fallback
    if GROQ_KEYS and provider != "groq":
        key = get_next_key("groq", GROQ_KEYS)
        try:
            resp = requests.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": GROQ_MODEL, "messages": messages, "max_tokens": 2000, "stream": False},
                timeout=60,
            )
            resp.raise_for_status()
            result = resp.json()["choices"][0]["message"]["content"]
            if result:
                _mark_provider_success("groq")
                return result
        except Exception:
            pass

    if OPENROUTER_KEYS:
        key     = get_next_key("openrouter", OPENROUTER_KEYS)
        headers = {
            "Authorization": f"Bearer {key}", "Content-Type": "application/json",
            "HTTP-Referer":  "https://ultron-j.local", "X-Title": "ULTRON-J",
        }
        for model in OPENROUTER_FALLBACK_MODELS:
            try:
                resp = requests.post(
                    OPENROUTER_URL, headers=headers,
                    json={"model": model, "messages": messages, "max_tokens": 2000, "stream": False},
                    timeout=60,
                )
                if resp.status_code in (400, 404, 402):
                    continue
                resp.raise_for_status()
                result = resp.json()["choices"][0]["message"]["content"]
                if result:
                    _mark_provider_success("openrouter")
                    return result
            except Exception:
                continue
        _mark_provider_failure("openrouter")

    return ""

# =============================================================================
# VISION
# =============================================================================

def call_llm_vision(prompt: str = "", images: list = None, image_url: str = None) -> str:
    content_parts = []
    if images:
        for img in images:
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{img.get('media_type','image/jpeg')};base64,{img['data']}"},
            })
    elif image_url:
        content_parts.append({"type": "image_url", "image_url": {"url": image_url}})
    content_parts.append({"type": "text", "text": prompt})

    messages = [
        {"role": "system", "content": _get_personality_system_prompt()},
        {"role": "user",   "content": content_parts},
    ]

    if GEMINI_KEYS:
        key    = get_next_key("gemini", GEMINI_KEYS)
        result = _call_gemini_batch(key, messages)
        if result:
            return result

    if OPENROUTER_KEYS:
        from config import VISION_MODELS
        model = VISION_MODELS.get("openrouter", "nvidia/nemotron-3-super-120b-a12b:free")
        key   = get_next_key("openrouter", OPENROUTER_KEYS)
        try:
            resp = requests.post(
                OPENROUTER_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "HTTP-Referer": "https://ultron-j.local"},
                json={"model": model, "messages": messages, "max_tokens": 1000, "stream": False},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception:
            pass

    return "Vision analysis unavailable — add GEMINI_API_KEY to .env"

# =============================================================================
# MAIN STREAMING ENTRY POINT
# =============================================================================

def stream_llm(messages: list, temperature: float = 0.7, extra_context: str = "", force_provider: str = "auto"):
    messages = _inject_context(messages, extra_context)
    attempts = 0

    with _forced_provider_lock:
        forced = _forced_provider

    # UI-selected provider: restrict to exactly that one, no fallback
    if force_provider not in ("auto", "", None) and force_provider in ("groq", "gemini", "openrouter"):
        order = [force_provider]
    elif forced:
        order = [forced] + [p for p in ("groq", "gemini", "openrouter") if p != forced]
    else:
        last_user = next(
            (m["content"] for m in reversed(messages)
             if m.get("role") == "user" and isinstance(m.get("content"), str)), "")
        best  = determine_best_provider(last_user)
        order = [best] + [p for p in ("groq", "gemini", "openrouter") if p != best]

    def _stamp(chunk, prov):
        """Inject `provider: <prov>` into a `_full` SSE event so the UI shows
        the ACTUAL source of the answer, not whichever provider the user
        nominally picked. Non-_full events pass through unchanged."""
        if not isinstance(chunk, str) or not chunk.startswith("data: "):
            return chunk
        raw = chunk[6:].strip()
        if not raw or raw == "[DONE]":
            return chunk
        try:
            obj = json.loads(raw)
        except Exception:
            return chunk
        if "_full" not in obj:
            return chunk
        obj.setdefault("provider", prov)
        return f"data: {json.dumps(obj)}\n\n"

    for current_provider in order:
        if attempts >= MAX_RETRY_ATTEMPTS:
            break

        if current_provider == "groq":
            keys, call_fn = GROQ_KEYS, _call_groq_streaming
        elif current_provider == "gemini":
            keys, call_fn = GEMINI_KEYS, _call_gemini_streaming
        else:
            keys, call_fn = OPENROUTER_KEYS, None

        if not keys:
            continue

        print(f"[LLM] Trying {current_provider}...")
        for key in keys:
            attempts += 1
            try:
                if current_provider == "openrouter":
                    success = False
                    for model in OPENROUTER_FALLBACK_MODELS:
                        try:
                            gen         = _call_openrouter_one_model(key, model, messages, temperature)
                            yielded_any = False
                            for chunk in gen:
                                yield _stamp(chunk, "openrouter")
                                yielded_any = True
                            if yielded_any:
                                _mark_provider_success("openrouter")
                                print(f"[LLM] SUCCESS: openrouter ({model}) responded")
                                success = True
                                break
                        except requests.exceptions.HTTPError as e:
                            sc = getattr(getattr(e, "response", None), "status_code", 500)
                            if sc in (400, 404, 402, 429):
                                continue  # try next model
                            raise
                        except Exception:
                            continue
                    if success:
                        return
                else:
                    gen         = call_fn(key, messages, temperature)
                    yielded_any = False
                    for chunk in gen:
                        yield _stamp(chunk, current_provider)
                        yielded_any = True
                    if yielded_any:
                        _mark_provider_success(current_provider)
                        print(f"[LLM] SUCCESS: {current_provider} responded")
                        return

            except requests.exceptions.HTTPError as e:
                sc = getattr(getattr(e, "response", None), "status_code", 500)
                if _is_limit_error(sc):
                    _mark_provider_failure(current_provider, sc)
                    yield f"data: {json.dumps({'status': f'Switching from {current_provider}...'})}\n\n"
                    break
                _mark_provider_failure(current_provider, sc)
            except Exception:
                continue

    err = "⚠️ All cloud providers (Groq, Gemini, OpenRouter) are currently unavailable. Please check your API keys or try again in a moment."
    yield f"data: {json.dumps({'token': err})}\n\n"
    yield f"data: {json.dumps({'_full': err, 'done': True})}\n\n"
