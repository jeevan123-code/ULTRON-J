"""
model_selector.py — Per-sub-task provider routing.

Existing llm_engine.determine_best_provider() picks one provider for a
whole request. That's fine for chat, but a multi-step plan often has
sub-tasks with very different profiles:

  "decompose this request into 5 steps"      → needs reasoning → Gemini / Llama-70B
  "extract urls from this HTML"              → trivial         → Groq / local Phi3
  "analyze what's sensitive in this doc"     → privacy         → Ollama
  "write a friendly 2-line summary"          → fast + cheap    → Groq
  "why did this test fail"                   → reasoning       → Gemini flash

This module routes per-sub-task. Each task carries a "kind" (from
task_graph) and optional hints; we pick a provider based on:
  - task kind (planner, extractor, summariser, reasoner, coder, private)
  - current provider health (from llm_engine)
  - whether Ollama is running locally
  - explicit override (user forced provider)

Public API:
    pick(kind, prompt="", private=False, hint=None) -> str
    call(kind, messages, **kwargs) -> str    # convenience: picks + calls

The returned provider string matches the ones llm_engine understands:
    "groq" | "gemini" | "openrouter" | "ollama"
"""

import threading
from typing import List, Optional, Dict

try:
    from llm_engine import (
        _is_provider_healthy, _best_ollama_model, call_llm_batch,
        set_forced_provider, get_current_provider,
    )
    _LLM_ENGINE_AVAILABLE = True
except ImportError:
    _LLM_ENGINE_AVAILABLE = False
    def _is_provider_healthy(p): return True
    def _best_ollama_model(): return None
    def call_llm_batch(prompt, system="", provider=None): return ""
    def set_forced_provider(p): pass
    def get_current_provider(): return "groq"


# =============================================================================
# ROUTING POLICY
# =============================================================================
# For each task kind, list providers in preferred order. We walk the list
# and return the first one that's healthy (or available for Ollama).

_ROUTING: Dict[str, List[str]] = {
    # Planning / decomposition → wants strong reasoning. Gemini Pro or Llama-70B.
    "planner":    ["gemini", "groq", "openrouter", "ollama"],
    "decompose":  ["gemini", "groq", "openrouter", "ollama"],
    "reasoner":   ["gemini", "groq", "openrouter", "ollama"],

    # Synthesis of research findings → needs context handling. Gemini good at long ctx.
    "synthesise": ["gemini", "groq", "openrouter", "ollama"],
    "summarise":  ["groq", "gemini", "openrouter", "ollama"],

    # Simple extraction / classification → fast and cheap is fine.
    "extractor":  ["groq", "gemini", "openrouter", "ollama"],
    "classifier": ["groq", "gemini", "openrouter", "ollama"],
    "parser":     ["groq", "gemini", "openrouter", "ollama"],

    # Code generation / patching → Llama-70B is strong; Gemini fallback.
    "coder":      ["groq", "gemini", "openrouter", "ollama"],

    # Conversational short replies → Groq is fastest.
    "chat":       ["groq", "gemini", "openrouter", "ollama"],
    "quick":      ["groq", "gemini", "openrouter", "ollama"],

    # Privacy-sensitive → always local if possible.
    "private":    ["ollama", "groq", "gemini"],

    # Catch-all default.
    "default":    ["groq", "gemini", "openrouter", "ollama"],
}

# Override state (set by user from the UI / voice command)
_override_lock = threading.Lock()
_global_override: Optional[str] = None
_kind_overrides: Dict[str, str] = {}


def set_global_override(provider: Optional[str]):
    """Force ALL picks to use this provider (or clear with None)."""
    global _global_override
    with _override_lock:
        _global_override = provider


def set_kind_override(kind: str, provider: Optional[str]):
    """Override routing for one specific kind (e.g. always use local for 'coder')."""
    with _override_lock:
        if provider:
            _kind_overrides[kind] = provider
        else:
            _kind_overrides.pop(kind, None)


def get_overrides() -> Dict:
    with _override_lock:
        return {"global": _global_override, "by_kind": dict(_kind_overrides)}


# =============================================================================
# PICK
# =============================================================================

def pick(
    kind: str = "default",
    prompt: str = "",
    private: bool = False,
    hint: Optional[str] = None,
) -> str:
    """Pick the best provider for a sub-task.

    Args:
        kind: task kind (see _ROUTING keys). Unknown kinds use "default".
        prompt: optional — lets us upgrade complexity ("explain in detail" → reasoner).
        private: if True, prefer Ollama hard.
        hint: explicit preferred provider; honoured if healthy.
    """
    with _override_lock:
        if _global_override:
            return _global_override
        if kind in _kind_overrides:
            return _kind_overrides[kind]

    if hint and _provider_available(hint):
        return hint

    if private:
        kind = "private"

    # Upgrade complexity from prompt content
    if prompt:
        pl = prompt.lower()
        if any(k in pl for k in (
            "explain why", "analyse", "analyze", "compare", "trade-off", "reason",
            "prove", "derive", "decompose", "plan", "step by step",
        )):
            if kind in ("chat", "quick", "default"):
                kind = "reasoner"

    order = _ROUTING.get(kind, _ROUTING["default"])
    for p in order:
        if _provider_available(p):
            return p

    # Last resort: just return whatever the engine currently thinks is best
    return get_current_provider()


def _provider_available(p: str) -> bool:
    if p == "ollama":
        return _best_ollama_model() is not None
    return _is_provider_healthy(p)


# =============================================================================
# CALL — convenience: pick provider then dispatch
# =============================================================================

def call(
    kind: str,
    prompt: str,
    system: str = "",
    private: bool = False,
    hint: Optional[str] = None,
) -> str:
    """Pick the right provider for `kind` and call it.

    Returns the raw text response (empty string on failure).
    """
    provider = pick(kind, prompt=prompt, private=private, hint=hint)
    try:
        return call_llm_batch(prompt, system=system, provider=provider) or ""
    except Exception as e:
        # One-level fallback: try the NEXT provider in the routing list
        order = _ROUTING.get(kind, _ROUTING["default"])
        for fb in order:
            if fb == provider:
                continue
            if not _provider_available(fb):
                continue
            try:
                return call_llm_batch(prompt, system=system, provider=fb) or ""
            except Exception:
                continue
        print(f"[model_selector] all providers failed for kind={kind}: {e}")
        return ""


def call_json(kind: str, prompt: str, system: str = "", private: bool = False) -> Optional[Dict]:
    """Call and parse JSON out of the response — used heavily by the planner.

    Handles markdown fences, trailing text, etc.
    Returns None on parse failure so caller can retry.
    """
    import json
    import re
    raw = call(kind, prompt, system=system, private=private)
    if not raw:
        return None
    # Strip fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw.strip())
    # Try direct parse
    try:
        return json.loads(raw)
    except Exception:
        pass
    # Try extracting first JSON object/array
    for pattern in (r"(\{.*\})", r"(\[.*\])"):
        m = re.search(pattern, raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                continue
    return None


# =============================================================================
# STATUS
# =============================================================================
def status() -> Dict:
    """Snapshot of routing state — used by /status endpoint."""
    return {
        "overrides":  get_overrides(),
        "available":  {p: _provider_available(p) for p in ("groq", "gemini", "openrouter", "ollama")},
        "routing":    _ROUTING,
    }


if __name__ == "__main__":
    print("== model_selector smoke test ==")
    for k in ("planner", "extractor", "chat", "private", "coder"):
        print(f"  pick({k!r}) → {pick(k)}")
    print(f"\nstatus: {status()}")
