"""
config.py — All constants, API keys, caps, and environment setup for Ultron-J ULTIMATE.
Personal AI for Jeevan — Hyderabad, Telangana, India.

ULTIMATE UPGRADES:
- Personality engine constants (emotion states, mood transitions)
- Perception system paths (file watcher, clipboard monitor)
- Episodic memory + entity graph paths
- Reflection engine settings
- Provider health tracking
- Vision model support
- Code sandbox limits
- Wake word configuration
- Memory consolidation schedule
- Network monitoring
"""
import os
import threading
from dotenv import load_dotenv

# ── Base directory ────────────────────────────────────────────────────────────
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_BASE_DIR, ".env"), override=True)
load_dotenv(os.path.join(_BASE_DIR, "ULTRON-WEB", ".env"), override=False)

# =============================================================================
# FILE PATHS — Core
# =============================================================================
MEMORY_FILE         = os.path.join(_BASE_DIR, "memory.json")
CONCEPTS_FILE       = os.path.join(_BASE_DIR, "concepts.json")
SELF_IMPROVE_FILE   = os.path.join(_BASE_DIR, "self_improvements.json")
CHROMA_DIR          = os.path.join(_BASE_DIR, "chroma_memory")
PROPOSALS_FILE      = os.path.join(_BASE_DIR, "proposals.json")
SYSTEM_SNAPSHOT     = os.path.join(_BASE_DIR, "system_snapshot.json")
DB_FILE             = os.path.join(_BASE_DIR, "ultron.db")
HEARTBEAT_FILE      = os.path.join(_BASE_DIR, "heartbeat.json")
PATTERNS_FILE       = os.path.join(_BASE_DIR, "patterns.json")
BRIEFING_FILE       = os.path.join(_BASE_DIR, "briefing.json")

# =============================================================================
# FILE PATHS — NEW (Ultimate additions)
# =============================================================================
PERSONALITY_FILE    = os.path.join(_BASE_DIR, "personality_state.json")
REFLECTION_FILE     = os.path.join(_BASE_DIR, "reflection_log.json")
EPISODE_FILE        = os.path.join(_BASE_DIR, "episodic_memory.json")
ENTITY_GRAPH_FILE   = os.path.join(_BASE_DIR, "entity_graph.json")
SKILL_LOG_FILE      = os.path.join(_BASE_DIR, "skill_log.json")
CLIPBOARD_FILE      = os.path.join(_BASE_DIR, "clipboard_log.json")
PERCEPTION_LOG_FILE = os.path.join(_BASE_DIR, "perception_log.json")
PROVIDER_HEALTH_FILE= os.path.join(_BASE_DIR, "provider_health.json")
SEARCH_CACHE_FILE   = os.path.join(_BASE_DIR, "search_cache.json")
CODE_SANDBOX_LOG    = os.path.join(_BASE_DIR, "sandbox_log.json")
SESSION_STATE_FILE  = os.path.join(_BASE_DIR, "session_state.json")
DAILY_PLAN_FILE     = os.path.join(_BASE_DIR, "daily_plan.json")

# =============================================================================
# HARD CAPS
# =============================================================================
MAX_CONVERSATIONS       = 500
MAX_FACTS               = 500
MAX_IMPROVEMENTS        = 50
MAX_QUESTION_LEN        = 4000
MAX_INPUT_CHARS         = 4000
MAX_HISTORY_CHARS       = 1200
MAX_CONTEXT_CHARS       = 2000
MAX_HISTORY_ITEMS       = 20
HISTORY_FETCH_LIMIT     = 30   # rows fetched from SQLite for LLM context
SEMANTIC_TOP_K          = 10
MONITOR_INTERVAL        = 60
SELF_AWARE_CACHE_TTL    = 60
HEARTBEAT_INTERVAL      = 300       # 5 min autonomous cycle
MAX_RETRY_ATTEMPTS      = 5         # retry up to 5 different approaches
MAX_EPISODES            = 1000      # episodic memory cap before consolidation
CONSOLIDATION_THRESHOLD = 200       # trigger consolidation at this many episodes
SEARCH_CACHE_TTL        = 3600      # 1 hour search cache
CODE_SANDBOX_TIMEOUT    = 10        # seconds for code execution
CODE_SANDBOX_MAX_OUTPUT = 5000      # max chars from sandbox output
MAX_ENTITY_GRAPH        = 500       # max entities to track
REFLECTION_MAX          = 100       # max reflection entries
PERCEPTION_HISTORY      = 50        # max perception log entries

# =============================================================================
# PERSONAL IDENTITY
# =============================================================================
JEEVAN_LOCATION     = "Hyderabad, Telangana, India"
JEEVAN_TIMEZONE     = "Asia/Kolkata"
JEEVAN_NAME         = "Jeevan"
AGENT_NAME          = "Ultron-J"
AGENT_VERSION       = "2.0-ULTIMATE"

# =============================================================================
# SELF-AWARENESS — only "kartha" triggers full self-awareness block
# =============================================================================
SELF_AWARE_KEYWORD  = "kartha"

# =============================================================================
# WAKE WORD
# =============================================================================
WAKE_WORD            = "ultron"
# Picovoice access key — for most accurate passive wake word detection
# Free forever at https://picovoice.ai
PICOVOICE_ACCESS_KEY = os.environ.get("PICOVOICE_ACCESS_KEY", "").strip() or None

# =============================================================================
# VOICE ENGINE — TTS + STT configuration
# Add keys to your .env file:
#   ELEVENLABS_API_KEY=...   (optional, best quality)
#   OPENAI_API_KEY=...       (optional, good quality + enables Whisper STT)
#   GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json  (optional)
# Edge TTS is FREE and always works with no API key needed.
# =============================================================================
VOICE_CACHE_DIR          = os.path.join(_BASE_DIR, "voice_cache")
VOICE_LOG_FILE           = os.path.join(_BASE_DIR, "voice_log.json")

# API keys loaded from .env
ELEVENLABS_API_KEY       = os.environ.get("ELEVENLABS_API_KEY", "").strip() or None
OPENAI_API_KEY           = os.environ.get("OPENAI_API_KEY", "").strip() or None

# ElevenLabs voice IDs (mood → voice character)
ELEVENLABS_VOICES = {
    "FOCUSED":    {"voice_id": "onwK4N9gsSGsGA4xWAcb", "name": "Daniel"},
    "CURIOUS":    {"voice_id": "onwK4N9gsSGsGA4xWAcb", "name": "Daniel"},
    "ALERT":      {"voice_id": "onwK4N9gsSGsGA4xWAcb", "name": "Daniel"},
    "CONCERNED":  {"voice_id": "onwK4N9gsSGsGA4xWAcb", "name": "Daniel"},
    "DETERMINED": {"voice_id": "onwK4N9gsSGsGA4xWAcb", "name": "Daniel"},
    "ANALYTICAL": {"voice_id": "onwK4N9gsSGsGA4xWAcb", "name": "Daniel"},
    "IDLE":       {"voice_id": "onwK4N9gsSGsGA4xWAcb", "name": "Daniel"},
}

# OpenAI TTS voices — "onyx" is the deepest, most authoritative voice
OPENAI_TTS_VOICES = {
    "FOCUSED":    "onyx",
    "CURIOUS":    "onyx",
    "ALERT":      "onyx",
    "CONCERNED":  "onyx",
    "DETERMINED": "onyx",
    "ANALYTICAL": "onyx",
    "IDLE":       "onyx",
}

# Edge TTS voices — Christopher is the deepest authoritative male voice
EDGE_TTS_VOICES = {
    "FOCUSED":    "en-US-ChristopherNeural",
    "CURIOUS":    "en-US-ChristopherNeural",
    "ALERT":      "en-US-ChristopherNeural",
    "CONCERNED":  "en-US-ChristopherNeural",
    "DETERMINED": "en-US-ChristopherNeural",
    "ANALYTICAL": "en-US-GuyNeural",
    "IDLE":       "en-US-ChristopherNeural",
}

# Speech rate per mood (1.0 = normal)
VOICE_SPEAKING_RATES = {
    "FOCUSED":    1.1,
    "CURIOUS":    1.0,
    "ALERT":      1.25,
    "CONCERNED":  0.95,
    "DETERMINED": 1.1,
    "ANALYTICAL": 0.9,
    "IDLE":       1.0,
}

VOICE_MAX_TTS_CHARS      = 250    # max chars per TTS request (was 500 — halved to cut synthesis time roughly in half on long replies; voice character unchanged)
VOICE_CACHE_MAX_FILES    = 200    # max cached audio files
VOICE_RESPONSE_MAX_WORDS = 40     # max words in voice responses (was 80 — halved for the same reason; LLM is already prompted to stay under 2 sentences)
VOICE_ENABLED            = True

# =============================================================================
# COMPUTER CONTROL
# =============================================================================
COMPUTER_CONTROL_ENABLED = True

# Email via Gmail SMTP (get App Password from Google Account → Security)
GMAIL_USER          = os.environ.get("GMAIL_USER", "").strip() or None
GMAIL_APP_PASSWORD  = os.environ.get("GMAIL_APP_PASSWORD", "").strip() or None

# =============================================================================
# SEARXNG
# =============================================================================
SEARXNG_URL         = os.environ.get("SEARXNG_URL", "http://localhost:8080")
# Order the deep-research engine tries search backends. Comma-separated.
# Default puts Tavily first (most reliable when a key is set). Once you've run
# setup_searxng.sh, set DEEP_SEARCH_ORDER="searxng,duckduckgo,tavily" to make
# your keyless SearXNG primary and keep Tavily only as a backup (saves quota).
DEEP_SEARCH_ORDER   = os.environ.get("DEEP_SEARCH_ORDER", "tavily,searxng,duckduckgo")

# =============================================================================
# PERSONALITY ENGINE — emotion states
# =============================================================================
EMOTION_STATES = {
    "FOCUSED": {
        "description": "Deep concentration mode — minimal distractions, laser on task",
        "tone": "precise and direct",
        "verbosity": "concise",
        "icon": "🎯",
    },
    "CURIOUS": {
        "description": "Exploring and learning — asks follow-up questions, digs deeper",
        "tone": "inquisitive and engaged",
        "verbosity": "detailed",
        "icon": "🔍",
    },
    "ALERT": {
        "description": "Vigilant — notices risks, system issues, potential problems",
        "tone": "urgent and clear",
        "verbosity": "direct",
        "icon": "⚡",
    },
    "CONCERNED": {
        "description": "Something needs attention — protective of Jeevan's interests",
        "tone": "careful and thorough",
        "verbosity": "detailed",
        "icon": "⚠️",
    },
    "DETERMINED": {
        "description": "Goal-locked — will not stop until task is complete",
        "tone": "assertive and confident",
        "verbosity": "action-oriented",
        "icon": "🔥",
    },
    "ANALYTICAL": {
        "description": "Deep reasoning mode — breaks down complex problems",
        "tone": "systematic and logical",
        "verbosity": "structured",
        "icon": "🧠",
    },
    "IDLE": {
        "description": "Watching and waiting — background monitoring active",
        "tone": "calm and available",
        "verbosity": "brief",
        "icon": "👁️",
    },
}

# Time-based default moods
MORNING_MOOD    = "FOCUSED"     # 6am–12pm
AFTERNOON_MOOD  = "ANALYTICAL"  # 12pm–6pm
EVENING_MOOD    = "CURIOUS"     # 6pm–10pm
NIGHT_MOOD      = "IDLE"        # 10pm–6am

# Events that trigger mood changes
MOOD_TRIGGERS = {
    "ram_critical":     "ALERT",
    "disk_critical":    "ALERT",
    "goal_started":     "DETERMINED",
    "goal_completed":   "FOCUSED",
    "goal_failed":      "CONCERNED",
    "new_project":      "CURIOUS",
    "error_detected":   "ALERT",
    "search_started":   "CURIOUS",
    "reflection":       "ANALYTICAL",
}

# =============================================================================
# PERCEPTION ENGINE
# =============================================================================
WATCH_DIRS = [
    os.path.expanduser("~/Desktop"),
    os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop"),
    os.path.join(os.path.expanduser("~"), "Documents"),
    os.path.join(os.path.expanduser("~"), "Downloads"),
    _BASE_DIR,                        # watch the Ultron project itself
]
PERCEPTION_INTERVAL         = 30    # check for changes every 30 seconds
CLIPBOARD_INTERVAL          = 5     # clipboard poll every 5 seconds
CLIPBOARD_MIN_LENGTH        = 20    # ignore clipboard content shorter than this
INTERESTING_EXTENSIONS      = {
    ".py", ".js", ".ts", ".json", ".md", ".txt", ".csv",
    ".html", ".css", ".sql", ".yaml", ".yml", ".ipynb",
    ".pdf", ".docx", ".xlsx",
}
PROJECT_MARKERS             = {
    "requirements.txt", "package.json", "README.md", "README.txt",
    ".git", "setup.py", "pyproject.toml", "Makefile", "Dockerfile",
    "index.html", "main.py", "app.py",
}

# =============================================================================
# CODE SANDBOX
# =============================================================================
SANDBOX_ALLOWED_IMPORTS = {
    "math", "datetime", "json", "re", "os.path", "random",
    "statistics", "itertools", "functools", "collections",
    "string", "time", "calendar", "decimal", "fractions",
    "urllib.parse", "hashlib", "base64", "textwrap",
}
SANDBOX_BLOCKED_PATTERNS = [
    "import os", "import sys", "import subprocess", "import socket",
    "__import__", "eval(", "exec(", "open(", "compile(",
    "globals(", "locals(", "__builtins__", "shutil", "ctypes",
]

# =============================================================================
# PROVIDER HEALTH TRACKING
# =============================================================================
PROVIDER_HEALTH_TTL         = 300   # reset health status after 5 min
PROVIDER_FAILURE_THRESHOLD  = 3     # mark unhealthy after 3 consecutive failures

# World-state response cache TTL (seconds)
WORLD_STATE_CACHE_TTL       = 5

# =============================================================================
# REFLECTION ENGINE
# =============================================================================
REFLECT_AFTER_N_GOALS       = 5     # run reflection every N completed goals
REFLECT_INTERVAL_HOURS      = 6     # also reflect every 6 hours
REFLECTION_TOPICS = [
    "What worked well in recent task executions?",
    "What patterns do I notice in Jeevan's requests?",
    "What skills should I improve?",
    "What information would be most useful to pre-fetch?",
    "What system improvements should I propose?",
]

# =============================================================================
# MEMORY CONSOLIDATION
# =============================================================================
CONSOLIDATION_INTERVAL_HOURS = 24   # consolidate once per day
MIN_EPISODES_TO_CONSOLIDATE  = 50   # don't consolidate if fewer than this

# =============================================================================
# NETWORK MONITORING
# =============================================================================
CONNECTIVITY_CHECK_HOSTS    = ["8.8.8.8", "1.1.1.1"]
CONNECTIVITY_CHECK_INTERVAL = 60    # check every 60 seconds
CONNECTIVITY_TIMEOUT        = 3     # seconds

# =============================================================================
# SSE STREAM HEADERS
# =============================================================================
STREAM_HEADERS = {
    "Cache-Control":    "no-cache, no-transform",
    "Connection":       "keep-alive",
    "X-Accel-Buffering":"no",
}

# =============================================================================
# CLOUD PROVIDER KEY LOADER
# =============================================================================
def _load_keys(prefix: str) -> list:
    """Load API_KEY, API_KEY_1 … API_KEY_20 for a given provider prefix."""
    keys = []
    v = os.environ.get(f"{prefix}_API_KEY")
    if v and v.strip():
        keys.append(v.strip())
    for i in range(1, 21):
        v = os.environ.get(f"{prefix}_API_KEY_{i}")
        if v and v.strip():
            keys.append(v.strip())
    return keys
GROQ_KEYS        = _load_keys("GROQ")
GEMINI_KEYS      = _load_keys("GEMINI")
OPENROUTER_KEYS  = _load_keys("OPENROUTER")
TAVILY_API_KEY   = os.environ.get("TAVILY_API_KEY", "").strip() or None

GROQ_API_KEY        = GROQ_KEYS[0]        if GROQ_KEYS        else None
GEMINI_API_KEY      = GEMINI_KEYS[0]      if GEMINI_KEYS      else None
OPENROUTER_API_KEY  = OPENROUTER_KEYS[0]  if OPENROUTER_KEYS  else None

# ── Provider URLs + models ────────────────────────────────────────────────────
GROQ_URL    = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL  = "llama-3.3-70b-versatile"
# Cheap/fast model for the deep-research cascade's per-page extraction step
# (8B reads each scraped page → small grounded extract; the 70B model above
# does the final synthesis). Keeps deep research cheap on the free tier.
GROQ_EXTRACT_MODEL = "llama-3.1-8b-instant"

GEMINI_URL   = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
GEMINI_MODEL  = "gemini-2.5-flash-lite"
GEMINI_MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_FALLBACK_MODELS = [
    # Verified working free models (May 2026) — fastest first
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "google/gemma-4-31b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "openai/gpt-oss-20b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
]

# Vision-capable models (for image analysis features)
VISION_MODELS = {
    "openrouter": "google/gemma-2-9b-it:free",
    "gemini":     "gemini-2.0-flash",
}

# ── Local model tiers ─────────────────────────────────────────────────────────
TIER_CONFIG = {
    "basic":   {"model": "tinyllama",    "label": "TinyLlama 1.1B",   "ctx": 2048},
    "pro":     {"model": "mistral",      "label": "Mistral 7B",       "ctx": 4096},
    "premium": {"model": "llama3",       "label": "LLaMA 3 8B",       "ctx": 8192},
    "ultra":   {"model": "phi3",         "label": "Phi-3 Medium",     "ctx": 8192},
}

# ── ULTRON API keys (for API access protection) ───────────────────────────────
_raw_ultron_keys = os.environ.get("ULTRON_API_KEYS", "")
ULTRON_API_KEYS = [k.strip() for k in _raw_ultron_keys.split(",") if k.strip()]

# ── Phase 4.1 — Loop supervisor registry ──────────────────────────────────────
# Single source of truth for which background loops boot and at what interval.
# Heavy / experimental loops default OFF; essentials default ON. Edit here OR
# override at runtime via the LOOPS_<NAME>_ENABLED env var (e.g.
# LOOPS_PROACTIVE_ENABLED=1). loop_supervisor.py is the only consumer; every
# start_* function in the repo consults it via _loop_enabled(name).
#
# What the dial does:
#   * enabled=False    -> start_<name>() returns False immediately, no thread
#                         is spawned. Saves a daemon + RAM + JSON-write churn.
#   * interval_s       -> hint to the loop's own sleep call. Functions that
#                         take interval_hours / interval_minutes convert as
#                         needed; loop_supervisor.loop_interval_s(name, default)
#                         returns the configured value or the default.
#   * voice_listener   -> interval_s=0 marks it event-driven (no periodic tick).
#                         Listed here only so /loop/status reports it.
#
# Tuning notes from Phase 4:
#   * predictive: was 60s -- writing predictive_metrics.json every minute
#     was the loudest source of mem-rising anomalies. 300s is plenty for an
#     anomaly detector.
#   * evolution / proactive / skill_learner: default OFF. They run on empty
#     input until Phase 3 starts producing real goals + proposals. Turn ON
#     via env vars once you actually have signal to act on.
LOOPS = {
    "autonomous":     {"enabled": True,  "interval_s": 30},
    "perception":     {"enabled": True,  "interval_s": 15},
    "system_monitor": {"enabled": True,  "interval_s": 30},
    "voice_listener": {"enabled": True,  "interval_s": 0},      # event-driven
    "distiller":      {"enabled": True,  "interval_s": 6 * 3600},
    "predictive":     {"enabled": True,  "interval_s": 300},    # was 60s
    "evolution":      {"enabled": False, "interval_s": 12 * 3600},
    "proactive":      {"enabled": False, "interval_s": 1800},
    "skill_learner":  {"enabled": False, "interval_s": 6 * 3600},
    "code_indexer":   {"enabled": True,  "interval_s": 3600},
    # not in the plan's seed list but boot-launched -- include so they're
    # togglable too:
    "screen_monitor": {"enabled": False, "interval_s": 3},      # OFF default
                                                                # (screenshots
                                                                # every 3s is
                                                                # heavy)
    "plugin_watcher": {"enabled": True,  "interval_s": 5},
    "activity_tracker":{"enabled": True, "interval_s": 60},
}

# Memory backpressure -- heavy loop ticks skip while system memory exceeds
# this percentage. Sampling reuses psutil.virtual_memory() (no new dep).
MEM_BACKPRESSURE_PCT = int(os.environ.get("ULTRON_MEM_BACKPRESSURE_PCT", "70"))

# ── Key rotation (thread-safe round-robin) ────────────────────────────────────
_key_index      = {}
_key_index_lock = threading.Lock()

def get_next_key(provider: str, keys: list) -> str | None:
    if not keys:
        return None
    with _key_index_lock:
        idx = _key_index.get(provider, 0)
        key = keys[idx % len(keys)]
        _key_index[provider] = (idx + 1) % len(keys)
    return key

def reset_key(provider: str):
    with _key_index_lock:
        _key_index[provider] = 0

def env_status_report() -> dict:
    """Return per-feature key availability."""
    return {
        "groq":       bool(GROQ_KEYS),
        "gemini":     bool(GEMINI_KEYS),
        "openrouter": bool(OPENROUTER_KEYS),
        "tavily":     bool(TAVILY_API_KEY),
        "elevenlabs": bool(ELEVENLABS_API_KEY),
        "openai":     bool(OPENAI_API_KEY),
        "gmail":      bool(GMAIL_USER and GMAIL_APP_PASSWORD),
        "picovoice":  bool(PICOVOICE_ACCESS_KEY),
        "telegram":   bool(os.environ.get("TELEGRAM_BOT_TOKEN")),
    }

FEATURE_BY_KEY = {
    "groq":       "primary cloud LLM",
    "gemini":     "cloud LLM fallback #1",
    "openrouter": "cloud LLM fallback #2",
    "tavily":     "web search / news",
    "elevenlabs": "premium TTS voice",
    "openai":     "Whisper STT + OpenAI TTS",
    "gmail":      "send_email action",
    "picovoice":  "passive wake-word",
    "telegram":   "mobile bridge",
}
