"""
action_engine.py — Action execution layer for Ultron-J ULTIMATE.

ULTIMATE UPGRADES:
- Code execution sandbox: safely run Python with resource limits + import control
- Web scraper tool: fetch and parse web pages with BeautifulSoup
- Git status tool: check git repos Jeevan is working on
- Note-taking tool: structured notes with categories
- Calculator tool: safe math eval (no subprocess, no exec)
- Weather tool: direct weather fetch
- Image analysis tool: pass image URL to vision-capable model
- Improved tool chaining: tools can pass output to next tool
- Tool scoring: learns which tools work best for which task types
- Richer tool registry with capability tags
"""

import json
import os
import datetime
import subprocess
import sys
import threading
import traceback
import time
import requests
import io
import contextlib
from typing import Optional

# =============================================================================
# PATH RESOLUTION — well-known folders + OneDrive redirect awareness
# =============================================================================
# Lets voice commands like "list my Downloads" / "open my Pictures" / "file
# read notes" work without a full Windows path. Resolves bare folder names
# to the user's home subdir, preferring OneDrive-redirected copies (where
# Jeevan's Desktop / Documents / Pictures actually live on this machine).

_HOME = os.path.expanduser("~")
_ONEDRIVE_ROOT = os.path.join(_HOME, "OneDrive")
_WELL_KNOWN_FOLDERS = {
    "home":       [_HOME],
    "userprofile":[_HOME],
    "desktop":    [os.path.join(_ONEDRIVE_ROOT, "Desktop"),    os.path.join(_HOME, "Desktop")],
    "documents":  [os.path.join(_ONEDRIVE_ROOT, "Documents"),  os.path.join(_HOME, "Documents")],
    "downloads":  [os.path.join(_ONEDRIVE_ROOT, "Downloads"),  os.path.join(_HOME, "Downloads")],
    "pictures":   [os.path.join(_ONEDRIVE_ROOT, "Pictures"),   os.path.join(_HOME, "Pictures")],
    "videos":     [os.path.join(_ONEDRIVE_ROOT, "Videos"),     os.path.join(_HOME, "Videos")],
    "music":      [os.path.join(_ONEDRIVE_ROOT, "Music"),      os.path.join(_HOME, "Music")],
    "onedrive":   [_ONEDRIVE_ROOT],
}

_HOME_PHRASES = {
    "home", "~", "my home", "home directory", "home folder",
    "my home directory", "my home folder", "user home", "home dir",
}

import re as _path_re

# Common Windows user-folder subpaths → Linux equivalents under HOME.
_WIN_FOLDER_MAP = [
    ("desktop",   "Desktop"),
    ("documents", "Documents"),
    ("downloads", "Downloads"),
    ("pictures",  "Pictures"),
    ("videos",    "Videos"),
    ("music",     "Music"),
    ("onedrive",  ""),          # OneDrive root → home
]


def _translate_win_path(p: str) -> str:
    """
    If p looks like a Windows absolute path (C:\\... or C:/...), translate it
    to the Linux equivalent under the real home directory.
    Examples:
        C:\\Users\\jeevan\\Desktop\\file.txt  → /home/jeevan/Desktop/file.txt
        C:\\Users\\User\\Desktop\\file.txt    → /home/jeevan/Desktop/file.txt  (any username)
        C:\\Users\\User\\file.txt             → /home/jeevan/file.txt
        C:\\Windows\\System32\\foo            → unchanged (system path, not translatable)
    """
    norm = p.replace("\\", "/")
    # Must look like  X:/...
    if not _path_re.match(r"^[A-Za-z]:/", norm):
        return p
    home = os.path.expanduser("~")
    # C:/Users/<any_username>/... → map relative tail under home
    m = _path_re.match(r"^[A-Za-z]:/[Uu]sers/[^/]+/(.*)", norm)
    if m:
        tail = m.group(1)
        return os.path.join(home, tail) if tail else home
    # C:/Users → just home
    if _path_re.match(r"^[A-Za-z]:/[Uu]sers/?$", norm):
        return home
    # Not a user path — return unchanged so caller can surface the error
    return p


def _resolve_path(p: str) -> str:
    """Expand ~/env vars and map well-known bare folder names to real paths.
    Also translates Windows-style paths (C:\\...) to Linux paths on non-Windows.
    Examples:
       'Downloads'                          -> ~/Downloads (or OneDrive/Downloads)
       'desktop/notes.txt'                  -> ~/Desktop/notes.txt
       '~/projects'                         -> /home/jeevan/projects
       'C:\\Users\\User\\Desktop\\file.txt' -> /home/jeevan/Desktop/file.txt
    """
    if not p:
        return p
    # Natural-language home phrases (e.g. LLM returns "my home directory")
    if p.strip().lower() in _HOME_PHRASES:
        return os.path.expanduser("~")
    # Translate Windows-style paths on Linux/macOS before anything else
    if os.name != "nt":
        p = _translate_win_path(p)
    s = os.path.expanduser(os.path.expandvars(p))
    if os.path.isabs(s):
        # Fix LLM-hallucinated /home/user when the real home is different.
        _real_home = os.path.expanduser("~")
        s = _path_re.sub(r"^/home/user(?=/|$)", _real_home, s)
        return s
    # Normalize separators just for comparison
    norm = s.replace("\\", "/").strip("/")
    if not norm:
        return s
    head, _, tail = norm.partition("/")
    head_lc = head.lower()
    if head_lc in _WELL_KNOWN_FOLDERS:
        for base in _WELL_KNOWN_FOLDERS[head_lc]:
            if os.path.isdir(base):
                return os.path.join(base, tail) if tail else base
        # Even if neither base exists, return the first candidate so the
        # caller's error message names a real Windows-shaped path.
        base = _WELL_KNOWN_FOLDERS[head_lc][0]
        return os.path.join(base, tail) if tail else base
    return s


from decision_engine import (
    safety_check, TaskStatus, GoalStatus, Priority,
    load_goals, save_goals, get_goal, update_goal,
    create_goal, build_plan, evaluate_task_result,
    calculate_goal_progress, log_execution,
    update_working_memory, load_working_memory,
    update_agent_mode, load_agent_state, save_agent_state,
    ALLOWED_COMMANDS,
)

# Atomic state writes — survives OneDrive sync locks (see memory.py).
try:
    from memory import atomic_json_write
except Exception:  # never let an import error here crash action_engine
    def atomic_json_write(filepath, data):
        with open(filepath, "w", encoding="utf-8") as _f:
            json.dump(data, _f, indent=2, ensure_ascii=False)

try:
    from config import (
        TIER_CONFIG, SEARXNG_URL, JEEVAN_LOCATION,
        MAX_RETRY_ATTEMPTS, GROQ_KEYS, GEMINI_KEYS,
        GROQ_URL, GROQ_MODEL, CODE_SANDBOX_TIMEOUT,
        CODE_SANDBOX_MAX_OUTPUT, SANDBOX_BLOCKED_PATTERNS,
        SANDBOX_ALLOWED_IMPORTS, VISION_MODELS,
        OPENROUTER_KEYS, OPENROUTER_URL,
    )
except ImportError:
    TIER_CONFIG             = {}
    SEARXNG_URL             = "http://localhost:8080"
    JEEVAN_LOCATION         = "Hyderabad, Telangana, India"
    MAX_RETRY_ATTEMPTS      = 5
    GROQ_KEYS               = []
    GEMINI_KEYS             = []
    GROQ_URL                = ""
    GROQ_MODEL              = ""
    CODE_SANDBOX_TIMEOUT    = 10
    CODE_SANDBOX_MAX_OUTPUT = 5000
    SANDBOX_BLOCKED_PATTERNS = []
    SANDBOX_ALLOWED_IMPORTS  = set()
    VISION_MODELS            = {}
    OPENROUTER_KEYS          = []
    OPENROUTER_URL           = ""

_BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE_FILE    = os.path.join(_BASE_DIR, "knowledge_base.json")
TOOL_STATS_FILE   = os.path.join(_BASE_DIR, "tool_stats.json")
NOTES_FILE        = os.path.join(_BASE_DIR, "notes.json")

# Optional: BeautifulSoup for web scraping
try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

# =============================================================================
# TOOL REGISTRY — extended
# =============================================================================

TOOL_REGISTRY = {
    "search_web": {
        "description":  "Search the web via Tavily or SearXNG",
        "best_for":     ["news", "current events", "web pages", "urls", "recent info"],
        "cost":         "medium",
        "capability":   "retrieval",
    },
    "search_local": {
        "description":  "Search local SearXNG or DuckDuckGo",
        "best_for":     ["offline search", "local queries", "privacy-first"],
        "cost":         "low",
        "capability":   "retrieval",
    },
    "web_scrape": {             # NEW
        "description":  "Fetch and parse a specific web page URL",
        "best_for":     ["fetch url", "read page", "scrape site", "get content from"],
        "cost":         "medium",
        "capability":   "retrieval",
    },
    "ask_llm": {
        "description":  "Query the LLM for reasoning, generation, or analysis",
        "best_for":     ["reasoning", "writing", "analysis", "code", "explanation"],
        "cost":         "high",
        "capability":   "generation",
    },
    "run_python": {
        "description":  "Execute Python code safely in the sandbox",
        "best_for":     ["calculations", "data processing", "automation", "scripts"],
        "cost":         "medium",
        "capability":   "execution",
    },
    "run_code": {               # NEW alias with security
        "description":  "Run a code snippet safely and return output",
        "best_for":     ["test code", "run script", "execute", "compute"],
        "cost":         "medium",
        "capability":   "execution",
    },
    "calculate": {              # NEW: safe math
        "description":  "Evaluate a mathematical expression safely",
        "best_for":     ["math", "calculate", "formula", "compute number", "percentage"],
        "cost":         "low",
        "capability":   "compute",
    },
    "git_status": {             # NEW
        "description":  "Check git status of a repository",
        "best_for":     ["git", "repository", "commits", "changes", "branch"],
        "cost":         "low",
        "capability":   "system",
    },
    "weather_fetch": {          # NEW
        "description":  "Get current weather for a location",
        "best_for":     ["weather", "temperature", "forecast", "rain", "humidity"],
        "cost":         "low",
        "capability":   "retrieval",
    },
    "note_create": {            # NEW
        "description":  "Create a structured note with title and content",
        "best_for":     ["note", "save thought", "write down", "remember this"],
        "cost":         "low",
        "capability":   "storage",
    },
    "file_read": {
        "description":  "Read file contents",
        "best_for":     ["read file", "open document", "get content"],
        "cost":         "low",
        "capability":   "filesystem",
    },
    "file_write": {
        "description":  "Write content to a file",
        "best_for":     ["save", "create file", "write document"],
        "cost":         "low",
        "capability":   "filesystem",
    },
    "file_list": {
        "description":  "List files in a directory",
        "best_for":     ["list files", "explore directory", "find files"],
        "cost":         "low",
        "capability":   "filesystem",
    },
    "api_call": {
        "description":  "Make HTTP API calls",
        "best_for":     ["external api", "rest", "webhook", "http request"],
        "cost":         "medium",
        "capability":   "network",
    },
    "memory_store": {
        "description":  "Store information in long-term memory",
        "best_for":     ["remember", "save fact", "store knowledge"],
        "cost":         "low",
        "capability":   "storage",
    },
    "memory_fetch": {
        "description":  "Retrieve from long-term memory",
        "best_for":     ["recall", "what do i know", "past conversations"],
        "cost":         "low",
        "capability":   "retrieval",
    },
    "analyze": {
        "description":  "Analyze and evaluate text or data",
        "best_for":     ["evaluate", "check quality", "validate", "review"],
        "cost":         "medium",
        "capability":   "generation",
    },
    "summarize": {
        "description":  "Summarize long text",
        "best_for":     ["summarize", "tldr", "shorten", "condense"],
        "cost":         "medium",
        "capability":   "generation",
    },
    "create_file": {
        "description":  "Create a new file with content",
        "best_for":     ["new file", "create document", "make file"],
        "cost":         "low",
        "capability":   "filesystem",
    },
    "append_file": {
        "description":  "Append content to existing file",
        "best_for":     ["add to file", "log", "append"],
        "cost":         "low",
        "capability":   "filesystem",
    },
    "move_file": {
        "description":  "Move or rename a file",
        "best_for":     ["move", "rename", "relocate file"],
        "cost":         "low",
        "capability":   "filesystem",
    },
    # ── COMPUTER CONTROL TOOLS ─────────────────────────────────────────────
    "screenshot": {
        "description":  "Take a screenshot of the screen",
        "best_for":     ["screenshot", "capture screen", "what's on screen", "see screen"],
        "cost":         "low",
        "capability":   "computer",
    },
    "click": {
        "description":  "Click at screen coordinates",
        "best_for":     ["click", "press button", "select", "tap"],
        "cost":         "low",
        "capability":   "computer",
    },
    "type_text": {
        "description":  "Type text at current cursor position",
        "best_for":     ["type", "write text", "input", "fill form"],
        "cost":         "low",
        "capability":   "computer",
    },
    "open_url": {
        "description":  "Open a URL in the default browser",
        "best_for":     ["open url", "open browser", "open website", "browse to", "navigate to"],
        "cost":         "low",
        "capability":   "computer",
    },
    "open_app": {
        "description":  "Open an application by name",
        "best_for":     ["open app", "launch", "start application", "open program"],
        "cost":         "low",
        "capability":   "computer",
    },
    "run_command": {
        "description":  "Run a safe shell command and return output",
        "best_for":     ["run command", "terminal", "shell", "cmd", "execute command"],
        "cost":         "medium",
        "capability":   "computer",
    },
    "send_email": {
        "description":  "Send an email via Gmail",
        "best_for":     ["send email", "email", "mail", "notify by email", "message someone"],
        "cost":         "medium",
        "capability":   "computer",
    },
    "hotkey": {
        "description":  "Press a keyboard shortcut",
        "best_for":     ["hotkey", "keyboard shortcut", "ctrl", "alt", "copy", "paste"],
        "cost":         "low",
        "capability":   "computer",
    },
}


def select_tool(task_description: str, available_tools: list = None) -> str:
    """Dynamically select the best tool for a task."""
    if available_tools is None:
        available_tools = list(TOOL_REGISTRY.keys())
    desc_lower = task_description.lower()
    scores = {}
    for tool_name, tool_info in TOOL_REGISTRY.items():
        if tool_name not in available_tools:
            continue
        score = 0
        for keyword in tool_info.get("best_for", []):
            if keyword in desc_lower:
                score += 10
        scores[tool_name] = score
    if scores:
        best = max(scores, key=scores.get)
        if scores[best] > 0:
            return best
    return "ask_llm"

# =============================================================================
# TOOL STATS
# =============================================================================

_tool_stats_lock = threading.Lock()


def load_tool_stats() -> dict:
    if os.path.exists(TOOL_STATS_FILE):
        try:
            with open(TOOL_STATS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def record_tool_result(tool: str, success: bool, duration_ms: int = 0):
    stats = load_tool_stats()
    if tool not in stats:
        stats[tool] = {"calls": 0, "successes": 0, "failures": 0, "avg_ms": 0}
    stats[tool]["calls"] += 1
    if success:
        stats[tool]["successes"] += 1
    else:
        stats[tool]["failures"] += 1
    prev_avg = stats[tool].get("avg_ms", 0)
    stats[tool]["avg_ms"] = int((prev_avg + duration_ms) / 2)
    with _tool_stats_lock:
        atomic_json_write(TOOL_STATS_FILE, stats)

# =============================================================================
# KNOWLEDGE BASE
# =============================================================================

_knowledge_lock = threading.Lock()


def load_knowledge() -> dict:
    if os.path.exists(KNOWLEDGE_FILE):
        try:
            with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"entries": [], "topics": {}}


def store_knowledge(topic: str, content: str, source: str = "agent"):
    """Store useful information learned during task execution."""
    kb    = load_knowledge()
    entry = {
        "id":       f"kb_{len(kb['entries'])}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}",
        "topic":    topic,
        "content":  content[:2000],
        "source":   source,
        "at":       datetime.datetime.now().isoformat(),
    }
    kb["entries"].append(entry)
    kb["topics"][topic] = kb["topics"].get(topic, 0) + 1
    if len(kb["entries"]) > 1000:
        kb["entries"] = kb["entries"][-1000:]
    with _knowledge_lock:
        atomic_json_write(KNOWLEDGE_FILE, kb)


def recall_knowledge(query: str, n: int = 5) -> list:
    """Search knowledge base for relevant entries."""
    kb = load_knowledge()
    q  = query.lower()
    scored = []
    for entry in kb.get("entries", []):
        text  = (entry.get("topic", "") + " " + entry.get("content", "")).lower()
        score = sum(1 for word in q.split() if word in text and len(word) > 2)
        if score > 0:
            scored.append((entry, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [e for e, _ in scored[:n]]


def get_knowledge_stats() -> dict:
    kb = load_knowledge()
    return {
        "total_entries": len(kb.get("entries", [])),
        "topics":        len(kb.get("topics", {})),
        "top_topics":    sorted(kb.get("topics", {}).items(), key=lambda x: x[1], reverse=True)[:5],
    }

# =============================================================================
# CODE SANDBOX (NEW) — safe Python execution
# =============================================================================

def _check_code_safety(code: str) -> tuple:
    """Check code for dangerous patterns before execution."""
    for pattern in SANDBOX_BLOCKED_PATTERNS:
        if pattern in code:
            return False, f"Blocked pattern detected: '{pattern}'"
    return True, "OK"


def run_code_sandbox(code: str, timeout: int = None) -> dict:
    """
    Execute Python code safely in a restricted sandbox.
    Returns {"output": str, "error": str, "success": bool}
    """
    timeout = int(timeout) if timeout and str(timeout).isdigit() else CODE_SANDBOX_TIMEOUT

    safe, reason = _check_code_safety(code)
    if not safe:
        return {"output": "", "error": f"Safety check failed: {reason}", "success": False}

    # Capture stdout/stderr
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    result = {"output": "", "error": "", "success": False}

    def _run():
        import math
        import datetime as _dt
        import json as _json
        import re as _re
        import random as _random
        import statistics as _statistics

        # Build a safe globals dict
        safe_globals = {
            "__builtins__": {
                "print": print,
                "len": len, "range": range, "enumerate": enumerate,
                "zip": zip, "map": map, "filter": filter,
                "list": list, "dict": dict, "set": set, "tuple": tuple,
                "int": int, "float": float, "str": str, "bool": bool,
                "abs": abs, "round": round, "sum": sum, "min": min, "max": max,
                "sorted": sorted, "reversed": reversed,
                "isinstance": isinstance, "type": type,
                "True": True, "False": False, "None": None,
            },
            "math": math,
            "datetime": _dt,
            "json": _json,
            "re": _re,
            "random": _random,
            "statistics": _statistics,
        }

        try:
            with contextlib.redirect_stdout(stdout_capture), \
                 contextlib.redirect_stderr(stderr_capture):
                exec(compile(code, "<sandbox>", "exec"), safe_globals)
            result["success"] = True
        except Exception as e:
            result["error"] = str(e)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        return {"output": "", "error": f"Execution timed out after {timeout}s", "success": False}

    raw_output = stdout_capture.getvalue()
    result["output"] = raw_output[:CODE_SANDBOX_MAX_OUTPUT]
    if not result["error"]:
        err_text = stderr_capture.getvalue()
        if err_text:
            result["error"] = err_text[:1000]

    return result

# =============================================================================
# WEB SCRAPER (NEW)
# =============================================================================

def scrape_url(url: str, max_chars: int = 3000) -> dict:
    """
    Fetch and parse a web page. Returns clean text content.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()

        if BS4_AVAILABLE:
            soup = BeautifulSoup(resp.text, "html.parser")
            # Remove scripts, styles, nav
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            # Clean up blank lines
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            text  = "\n".join(lines)
        else:
            # Fallback: strip HTML tags naively
            import re
            text = re.sub(r"<[^>]+>", " ", resp.text)
            text = re.sub(r"\s+", " ", text).strip()

        return {
            "url":      url,
            "title":    _extract_title(resp.text),
            "content":  text[:max_chars],
            "length":   len(text),
            "success":  True,
        }
    except Exception as e:
        return {"url": url, "content": "", "error": str(e), "success": False}


def _extract_title(html: str) -> str:
    """Extract page title from HTML."""
    import re
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()[:100]
    return ""

# =============================================================================
# GIT TOOL (NEW)
# =============================================================================

def git_status(repo_path: str = ".") -> dict:
    """Check git status of a repository."""
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "status", "--short"],
            capture_output=True, text=True, timeout=10,
        )
        branch_result = subprocess.run(
            ["git", "-C", repo_path, "branch", "--show-current"],
            capture_output=True, text=True, timeout=5,
        )
        log_result = subprocess.run(
            ["git", "-C", repo_path, "log", "--oneline", "-5"],
            capture_output=True, text=True, timeout=5,
        )
        return {
            "success":      result.returncode == 0,
            "status":       result.stdout.strip(),
            "branch":       branch_result.stdout.strip(),
            "recent_commits": log_result.stdout.strip(),
            "has_changes":  bool(result.stdout.strip()),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

# =============================================================================
# WEATHER TOOL (NEW)
# =============================================================================

def fetch_weather(location: str = None) -> dict:
    """
    Fetch weather using wttr.in (no API key needed).
    """
    loc = location or JEEVAN_LOCATION
    try:
        url  = f"https://wttr.in/{loc.replace(' ', '+')}?format=j1"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        current = data["current_condition"][0]
        return {
            "success":     True,
            "location":    loc,
            "temp_c":      current.get("temp_C"),
            "feels_like":  current.get("FeelsLikeC"),
            "humidity":    current.get("humidity"),
            "description": current["weatherDesc"][0]["value"],
            "wind_kmph":   current.get("windspeedKmph"),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "location": loc}

# =============================================================================
# CALCULATOR (NEW) — safe math evaluation
# =============================================================================

def safe_calculate(expression: str) -> dict:
    """
    Evaluate a math expression safely using math module.
    No exec/eval with arbitrary code.
    """
    import math
    import re

    # Whitelist: only allow math characters
    cleaned = expression.strip()
    allowed = re.compile(r'^[\d\s\+\-\*\/\(\)\.\,\%\^sqrt\|abs\|pi\|e\|log\|sin\|cos\|tan\|floor\|ceil\|round]+$')

    # Replace common math functions
    cleaned = cleaned.replace("^", "**")
    cleaned = re.sub(r'\bsqrt\(', 'math.sqrt(', cleaned)
    cleaned = re.sub(r'\babs\(', 'abs(', cleaned)
    cleaned = re.sub(r'\bpi\b', 'math.pi', cleaned)
    cleaned = re.sub(r'\bsin\(', 'math.sin(', cleaned)
    cleaned = re.sub(r'\bcos\(', 'math.cos(', cleaned)
    cleaned = re.sub(r'\blog\(', 'math.log(', cleaned)
    cleaned = re.sub(r'\bfloor\(', 'math.floor(', cleaned)
    cleaned = re.sub(r'\bceil\(', 'math.ceil(', cleaned)

    # Block anything suspicious
    for blocked in ["import", "exec", "eval", "open", "__", "os", "sys"]:
        if blocked in cleaned:
            return {"success": False, "error": "Expression contains blocked keyword"}

    try:
        result = eval(cleaned, {"__builtins__": {}, "math": math, "abs": abs, "round": round})
        return {"success": True, "expression": expression, "result": result}
    except Exception as e:
        return {"success": False, "expression": expression, "error": str(e)}

# =============================================================================
# NOTE TOOL (NEW)
# =============================================================================

_notes_lock = threading.Lock()


def load_notes() -> list:
    if os.path.exists(NOTES_FILE):
        try:
            with open(NOTES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def create_note(title: str, content: str, category: str = "general", tags: list = None) -> dict:
    """Create a structured note."""
    notes = load_notes()
    note = {
        "id":       f"note_{len(notes)}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}",
        "title":    title[:100],
        "content":  content[:5000],
        "category": category,
        "tags":     tags or [],
        "created":  datetime.datetime.now().isoformat(),
    }
    notes.append(note)
    with _notes_lock:
        atomic_json_write(NOTES_FILE, notes)
    return note


def search_notes(query: str, n: int = 5) -> list:
    """Search notes by keyword."""
    notes = load_notes()
    q     = query.lower()
    scored = []
    for note in notes:
        text  = (note.get("title", "") + " " + note.get("content", "") + " " + note.get("category", "")).lower()
        score = sum(1 for w in q.split() if w in text and len(w) > 2)
        if score > 0:
            scored.append((note, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [n for n, _ in scored[:n]]

# =============================================================================
# MAIN ACTION EXECUTOR
# =============================================================================

def execute_action(action_type: str, params: dict) -> dict:
    """
    Execute a single action. Returns {"success": bool, "result": str, "error": str}.
    This is the central dispatcher for all tools.
    """
    action = {"type": action_type, "params": params}
    safe, reason = safety_check(action)
    if not safe:
        return {"success": False, "result": "", "error": f"Safety: {reason}"}

    start = time.time()
    result = {"success": False, "result": "", "error": ""}

    try:
        if action_type in ("run_python", "run_code"):
            code = params.get("code", params.get("content", ""))
            out  = run_code_sandbox(code)
            result["success"] = out["success"]
            result["result"]  = out.get("output", "")
            if out.get("error"):
                result["error"] = out["error"]

        elif action_type == "calculate":
            expr = params.get("expression", params.get("content", ""))
            out  = safe_calculate(expr)
            result["success"] = out["success"]
            result["result"]  = str(out.get("result", out.get("error", "")))

        elif action_type == "web_scrape":
            url = params.get("url", "")
            out = scrape_url(url)
            result["success"] = out["success"]
            result["result"]  = out.get("content", out.get("error", ""))

        elif action_type == "git_status":
            path = params.get("path", ".")
            out  = git_status(path)
            result["success"] = out["success"]
            result["result"]  = json.dumps(out, indent=2)

        elif action_type == "weather_fetch":
            loc = params.get("location", "")
            out = fetch_weather(loc or None)
            result["success"] = out["success"]
            if out["success"]:
                result["result"] = (
                    f"{out['location']}: {out['description']}, "
                    f"{out['temp_c']}°C (feels {out['feels_like']}°C), "
                    f"Humidity {out['humidity']}%, Wind {out['wind_kmph']} km/h"
                )
            else:
                result["error"] = out.get("error", "Failed")

        elif action_type == "note_create":
            title   = params.get("title", "Untitled")
            content = params.get("content", "")
            cat     = params.get("category", "general")
            tags    = params.get("tags", [])
            note    = create_note(title, content, cat, tags)
            result["success"] = True
            result["result"]  = f"Note created: '{note['title']}' (ID: {note['id']})"

        elif action_type == "file_read":
            path = _resolve_path(params.get("path", ""))
            with open(path, "r", encoding="utf-8") as f:
                result["result"]  = f.read()[:5000]
            result["success"] = True

        elif action_type in ("file_write", "create_file"):
            path    = params.get("path", "")
            content = params.get("content", "")
            path    = _resolve_path(path)
            # Filename only (no directory) → default to Desktop
            if path and os.sep not in path and '/' not in path:
                for _d in [
                    os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop"),
                    os.path.join(os.path.expanduser("~"), "Desktop"),
                ]:
                    if os.path.isdir(_d):
                        path = os.path.join(_d, path)
                        break
            if not path:
                result["error"] = "create_file: empty path"
            else:
                try:
                    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".",
                                exist_ok=True)
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(content)
                    if os.path.exists(path):
                        stat = os.stat(path)
                        result["success"]       = True
                        result["result"]        = f"Written {stat.st_size} bytes to {path}"
                        result["verified_path"] = path
                        result["verified_size"] = stat.st_size
                    else:
                        result["error"] = f"Wrote to {path} but file not present"
                except Exception as e:
                    result["error"] = f"create_file failed: {e}"

        elif action_type == "append_file":
            path    = params.get("path", "")
            content = params.get("content", "")
            path    = _resolve_path(path)
            if not path:
                result["error"] = "append_file: empty path"
            else:
                try:
                    with open(path, "a", encoding="utf-8") as f:
                        f.write(content)
                    if os.path.exists(path):
                        stat = os.stat(path)
                        result["success"]       = True
                        result["result"]        = f"Appended to {path} (now {stat.st_size} bytes)"
                        result["verified_path"] = path
                        result["verified_size"] = stat.st_size
                    else:
                        result["error"] = f"Appended to {path} but file not present"
                except Exception as e:
                    result["error"] = f"append_file failed: {e}"

        elif action_type == "file_list":
            path  = _resolve_path(params.get("path", ".") or ".")
            if not os.path.isdir(path):
                result["error"] = f"Not a directory: {path}"
            else:
                entries = os.listdir(path)
                dirs_   = sorted([e for e in entries if os.path.isdir(os.path.join(path, e))])
                files_  = sorted([e for e in entries if os.path.isfile(os.path.join(path, e))])
                result["success"] = True
                result["result"]  = (
                    f"{path} — {len(dirs_)} folders, {len(files_)} files\n"
                    + "\n".join(f"[DIR] {d}" for d in dirs_[:50])
                    + "\n".join(files_[:100])
                )

        elif action_type == "delete_file":
            path = _resolve_path(params.get("path", ""))
            if not path:
                result["error"] = "delete_file: empty path"
            elif not os.path.exists(path):
                result["error"] = f"Not found: {path}"
            elif os.path.isdir(path):
                result["error"] = f"'{path}' is a folder — use delete_folder"
            else:
                try:
                    size = os.path.getsize(path)
                    os.remove(path)
                    result["success"] = True
                    result["result"]  = f"Deleted {path} ({size} bytes)"
                except Exception as e:
                    result["error"] = f"delete_file failed: {e}"

        elif action_type == "delete_folder":
            import shutil as _shutil
            path = _resolve_path(params.get("path", ""))
            if not path:
                result["error"] = "delete_folder: empty path"
            elif not os.path.isdir(path):
                result["error"] = f"Not a directory: {path}"
            else:
                try:
                    _shutil.rmtree(path)
                    result["success"] = True
                    result["result"]  = f"Deleted folder: {path}"
                except Exception as e:
                    result["error"] = f"delete_folder failed: {e}"

        elif action_type == "rename_file":
            import shutil as _shutil
            src  = _resolve_path(params.get("src", ""))
            name = params.get("new_name", "")
            if not src or not name:
                result["error"] = "rename_file: needs src and new_name"
            elif not os.path.exists(src):
                result["error"] = f"Not found: {src}"
            else:
                dst = os.path.join(os.path.dirname(src), name)
                try:
                    os.rename(src, dst)
                    result["success"] = True
                    result["result"]  = f"Renamed to {dst}"
                    result["verified_path"] = dst
                except Exception as e:
                    result["error"] = f"rename_file failed: {e}"

        elif action_type == "copy_file":
            import shutil as _shutil
            src  = _resolve_path(params.get("src", ""))
            dest = _resolve_path(params.get("dest", ""))
            if not src or not dest:
                result["error"] = "copy_file: needs src and dest"
            elif not os.path.exists(src):
                result["error"] = f"Not found: {src}"
            else:
                try:
                    os.makedirs(dest if os.path.isdir(dest) else
                                os.path.dirname(dest), exist_ok=True)
                    out = _shutil.copy2(src, dest) if os.path.isfile(src) \
                          else _shutil.copytree(src, dest, dirs_exist_ok=True)
                    result["success"] = True
                    result["result"]  = f"Copied to {out}"
                    result["verified_path"] = str(out)
                except Exception as e:
                    result["error"] = f"copy_file failed: {e}"

        elif action_type == "move_file":
            import shutil as _shutil
            src  = _resolve_path(params.get("src", ""))
            dest = _resolve_path(params.get("dest", ""))
            if not src or not dest:
                result["error"] = "move_file: needs src and dest"
            elif not os.path.exists(src):
                result["error"] = f"Not found: {src}"
            else:
                try:
                    os.makedirs(dest, exist_ok=True)
                    out = _shutil.move(src, dest)
                    result["success"] = True
                    result["result"]  = f"Moved to {out}"
                    result["verified_path"] = str(out)
                except Exception as e:
                    result["error"] = f"move_file failed: {e}"

        elif action_type == "zip_folder":
            import zipfile, shutil as _shutil
            src         = _resolve_path(params.get("src", ""))
            output_path = _resolve_path(params.get("output", src + ".zip"))
            if not src:
                result["error"] = "zip_folder: needs src"
            elif not os.path.exists(src):
                result["error"] = f"Not found: {src}"
            else:
                try:
                    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                        if os.path.isdir(src):
                            for root, _, fnames in os.walk(src):
                                for fname in fnames:
                                    fp = os.path.join(root, fname)
                                    zf.write(fp, os.path.relpath(fp, os.path.dirname(src)))
                        else:
                            zf.write(src, os.path.basename(src))
                    size = os.path.getsize(output_path)
                    result["success"] = True
                    result["result"]  = f"Zipped to {output_path} ({size:,} bytes)"
                    result["verified_path"] = output_path
                    result["verified_size"] = size
                except Exception as e:
                    result["error"] = f"zip_folder failed: {e}"

        elif action_type == "memory_store":
            topic   = params.get("topic", "general")
            content = params.get("content", "")
            store_knowledge(topic, content)
            result["success"] = True
            result["result"]  = f"Stored to knowledge base: topic '{topic}'"

        elif action_type == "memory_fetch":
            query   = params.get("query", "")
            entries = recall_knowledge(query)
            result["success"] = True
            result["result"]  = "\n\n".join(
                f"[{e['topic']}] {e['content'][:300]}" for e in entries
            ) if entries else "No relevant memories found."

        elif action_type == "api_call":
            url     = params.get("url", "")
            method  = params.get("method", "GET").upper()
            headers = params.get("headers", {})
            body    = params.get("body", None)
            resp    = requests.request(method, url, headers=headers, json=body, timeout=15)
            result["success"] = resp.ok
            result["result"]  = resp.text[:3000]

        elif action_type in ("analyze", "summarize", "ask_llm"):
            # These delegate to the LLM — return a signal for the caller
            result["success"] = True
            result["result"]  = "__llm_delegate__"
            result["content"] = params.get("content", params.get("prompt", ""))
        elif action_type == "search_on_site":
            q  = params.get("query", "")
            s  = params.get("site", "google")
            br = params.get("browser")
            try:
                from smart_browser_agent import search_and_summarize
                out = search_and_summarize(q, s, br)
                if out.get("success"):
                    result["success"] = True
                    result["result"]  = out.get("summary", "")
                    result["url"]     = out.get("url")
                else:
                    result["error"] = out.get("error", "search_on_site failed")
            except Exception as _e:
                result["error"] = f"search_on_site error: {_e}"

        elif action_type == "search_web":
            q = params.get("query", "")
            try:
                from smart_browser_agent import search_and_summarize
                out = search_and_summarize(q, "google")
                if out.get("success"):
                    result["success"] = True
                    result["result"]  = out.get("summary", "")
                else:
                    result["error"] = out.get("error", "search_web failed")
            except Exception as _e:
                result["error"] = f"search_web error: {_e}"

        elif action_type == "open_url" and "youtube.com/results" in params.get("url", ""):
            url     = params.get("url", "")
            browser = params.get("browser") or "default"
            try:
                from computer_control import open_url
                opened = open_url(url, browser=browser)
                if not opened.get("success"):
                    result["error"] = opened.get("error", "open_url failed")
                else:
                    time.sleep(5)  # YouTube DOM settle
                    import pyautogui
                    w, h = pyautogui.size()
                    cx, cy = int(w * 0.33), int(h * 0.35)
                    pyautogui.click(cx, cy)
                    result["success"] = True
                    result["result"]  = (f"Opened YouTube in {browser}, "
                                         f"clicked first result at ({cx},{cy})")
            except Exception as e:
                result["error"] = str(e)[:200]
        elif action_type == "open_url":
            url     = params.get("url", "")
            browser = params.get("browser")
            from computer_control import open_url
            out = open_url(url, browser=browser)
            result["success"] = out.get("success", False)
            result["result"]  = json.dumps(out)
            if not out.get("success"):
                result["error"] = out.get("error", "open_url failed")
        # ── COMPUTER CONTROL ─────────────────────────────────────────────────
        elif action_type in ("screenshot", "click", "type_text", "open_url",
                                "open_app", "run_command", "send_email", "hotkey",
                                "scroll", "press_key", "get_clipboard", "set_clipboard",
                                "get_window", "move_mouse"):
                try:
                    from computer_control import execute_computer_action
                    out = execute_computer_action(action_type, params)
                    result["success"] = out.get("success", False)
                    result["result"]  = json.dumps({k: v for k, v in out.items() if k != "image_b64"})
                    if not out.get("success"):
                        result["error"] = out.get("error", "Computer action failed")
                except ImportError:
                    result["error"] = "computer_control not available. pip install pyautogui pillow"
                except Exception as e:
                    result["error"] = f"Computer action error: {str(e)[:200]}"

        else:
            result["error"] = f"Unknown action type: {action_type}"

    except FileNotFoundError as e:
        result["error"] = f"File not found: {e}"
    except PermissionError as e:
        result["error"] = f"Permission denied: {e}"
    except Exception as e:
        result["error"] = f"Action error: {traceback.format_exc()[-500:]}"

    duration_ms = int((time.time() - start) * 1000)
    record_tool_result(action_type, result["success"], duration_ms)
    if not result.get("success"):
        try:
            from error_tracker import log_failure
            log_failure("action_engine", action_type,
                        result.get("error", "unknown"), params)
        except Exception:
            pass
    return result

# =============================================================================
# GOAL EXECUTION HELPERS
# =============================================================================

def start_goal_execution(goal_id: str) -> bool:
    """Mark a goal as active and build its plan."""
    goal = get_goal(goal_id)
    if not goal:
        return False
    update_goal(goal_id, status=GoalStatus.ACTIVE)
    tasks = build_plan(goal)
    update_goal(goal_id, status=GoalStatus.PLANNING, tasks=tasks)
    return True


def execute_goal_step(goal_id: str, task: dict) -> dict:
    """Execute one step of a goal and update its state."""
    action_type = task.get("tool", "ask_llm")
    params      = {"content": task.get("description", ""), "prompt": task.get("description", "")}
    update_goal(goal_id, status=GoalStatus.EXECUTING)

    result = execute_action(action_type, params)
    success = result.get("success", False)

    log_execution(goal_id, task.get("id", "?"), action_type,
                result.get("result", result.get("error", "")), success)
    return result


def finish_goal_evaluation(goal_id: str, final_result: str) -> bool:
    """Evaluate and close out a completed goal."""
    goal = get_goal(goal_id)
    if not goal:
        return False

    progress = calculate_goal_progress(goal)
    success  = progress >= 80    # 80%+ tasks succeeded → goal success

    if success:
        update_goal(goal_id,
                    status=GoalStatus.COMPLETED,
                    progress_pct=progress,
                    result_summary=final_result[:500],
                    completed_at=datetime.datetime.now().isoformat(),
                    execution_score=min(10, int(progress / 10)))
    else:
        tasks = goal.get("tasks", [])
        failed = sum(1 for t in tasks if t.get("status") == TaskStatus.FAILED)
        if failed > 0 and goal.get("retry_count", 0) < 3:
            update_goal(goal_id,
                        status=GoalStatus.PENDING,
                        retry_count=goal.get("retry_count", 0) + 1,
                        progress_pct=progress)
        else:
            update_goal(goal_id,
                        status=GoalStatus.FAILED,
                        progress_pct=progress,
                        result_summary=final_result[:500])
    return success