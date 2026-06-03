"""
perception.py — Ultron-J's Perception Engine. NEW MODULE.

What this adds:
- FileSystemWatcher: monitors multiple directories for changes in background
- ClipboardMonitor: polls clipboard and extracts intent from copied content
- ProjectDetector: identifies when a new project directory appears
- ContextExtractor: infers meaning from file names, types, and content snippets
- EnvironmentSnapshot: richer than the old observe_environment()
- Perception log: keeps a timestamped history of everything Ultron perceives
- Smart context building: turns raw perceptions into actionable suggestions

This module gives Ultron-J eyes. It sees what Jeevan is working on even
before Jeevan says anything.
"""

import datetime
import json
import os
import threading
import time
from typing import Optional

from config import (
    PERCEPTION_LOG_FILE, CLIPBOARD_FILE,
    WATCH_DIRS, PERCEPTION_INTERVAL, CLIPBOARD_INTERVAL,
    CLIPBOARD_MIN_LENGTH, INTERESTING_EXTENSIONS,
    PROJECT_MARKERS, PERCEPTION_HISTORY, JEEVAN_NAME,
)
from memory import atomic_json_write

# ── Thread safety ─────────────────────────────────────────────────────────────
_perception_lock  = threading.Lock()
_clipboard_lock   = threading.Lock()
_running          = False
_threads          = []

# ── Clipboard availability (Windows/Linux/Mac) ────────────────────────────────
try:
    import pyperclip
    CLIPBOARD_AVAILABLE = True
except ImportError:
    CLIPBOARD_AVAILABLE = False

# =============================================================================
# PERCEPTION LOG
# =============================================================================

def _load_perception_log() -> list:
    if os.path.exists(PERCEPTION_LOG_FILE):
        try:
            with open(PERCEPTION_LOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_perception_log(log: list):
    with _perception_lock:
        # Keep bounded
        if len(log) > PERCEPTION_HISTORY:
            log = log[-PERCEPTION_HISTORY:]
        atomic_json_write(PERCEPTION_LOG_FILE, log)


def log_perception(kind: str, content: str, source: str = "", metadata: dict = None):
    """Record a perception event."""
    log = _load_perception_log()
    log.append({
        "kind":     kind,       # "file_change", "new_project", "clipboard", "process"
        "content":  content[:500],
        "source":   source,
        "metadata": metadata or {},
        "at":       datetime.datetime.now().isoformat(),
    })
    _save_perception_log(log)


def get_recent_perceptions(n: int = 10) -> list:
    """Return the N most recent perception events."""
    log = _load_perception_log()
    return log[-n:]


def get_perception_state() -> dict:
    """Return a summary of what Ultron currently perceives."""
    log   = _load_perception_log()
    recent = log[-20:] if log else []
    kinds  = {}
    for e in recent:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    return {
        "total_events":     len(log),
        "recent_events":    recent[-5:],
        "event_counts":     kinds,
        "clipboard_active": CLIPBOARD_AVAILABLE,
        "watch_dirs":       [d for d in WATCH_DIRS if os.path.exists(d)],
        "last_event_at":    log[-1]["at"] if log else None,
    }

# =============================================================================
# CONTEXT EXTRACTOR — infer meaning from file names and types
# =============================================================================

FILE_CATEGORY_MAP = {
    ".py":      "Python code",
    ".js":      "JavaScript code",
    ".ts":      "TypeScript code",
    ".html":    "Web page",
    ".css":     "Stylesheet",
    ".json":    "Data/config",
    ".md":      "Documentation",
    ".txt":     "Text document",
    ".csv":     "Data file",
    ".sql":     "Database query",
    ".yaml":    "Configuration",
    ".yml":     "Configuration",
    ".ipynb":   "Jupyter notebook",
    ".pdf":     "PDF document",
    ".docx":    "Word document",
    ".xlsx":    "Spreadsheet",
    ".mp4":     "Video",
    ".mp3":     "Audio",
    ".jpg":     "Image",
    ".png":     "Image",
}

PROJECT_TYPE_MAP = {
    "requirements.txt": "Python project",
    "package.json":     "Node.js project",
    "Dockerfile":       "Docker project",
    "setup.py":         "Python package",
    "pyproject.toml":   "Python project",
    "Makefile":         "Build project",
    ".git":             "Git repository",
    "index.html":       "Web project",
    "main.py":          "Python project",
    "app.py":           "Flask/Python project",
    "README.md":        "Documented project",
}


def extract_file_context(path: str) -> dict:
    """Extract rich context from a file path."""
    name      = os.path.basename(path)
    ext       = os.path.splitext(name)[1].lower()
    category  = FILE_CATEGORY_MAP.get(ext, "file")
    size      = 0
    try:
        size = os.path.getsize(path)
    except Exception:
        pass
    return {
        "name":         name,
        "ext":          ext,
        "category":     category,
        "size_kb":      round(size / 1024, 1),
        "is_code":      ext in {".py", ".js", ".ts", ".html", ".css", ".sql"},
        "is_data":      ext in {".json", ".csv", ".xlsx", ".yaml", ".yml"},
        "is_doc":       ext in {".md", ".txt", ".pdf", ".docx"},
        "is_media":     ext in {".mp4", ".mp3", ".jpg", ".png", ".gif"},
    }


def detect_project_in_dir(dirpath: str) -> Optional[str]:
    """Check if a directory looks like a project. Return project type or None."""
    if not os.path.isdir(dirpath):
        return None
    try:
        contents = set(os.listdir(dirpath))
        for marker, ptype in PROJECT_TYPE_MAP.items():
            if marker in contents:
                return ptype
    except Exception:
        pass
    return None


def extract_clipboard_intent(text: str) -> dict:
    """
    Infer what Jeevan was doing from clipboard content.
    Returns intent category and a brief description.
    """
    text_lower = text.lower().strip()
    lines      = text.strip().splitlines()
    n_lines    = len(lines)

    # Code detection
    code_signals = ["def ", "class ", "import ", "function ", "const ", "var ",
                    "return ", "if (", "for (", "SELECT ", "INSERT ", "UPDATE "]
    if any(sig in text for sig in code_signals):
        lang = "Python" if "def " in text or "import " in text else "JavaScript/other"
        return {
            "intent": "code",
            "description": f"Copied {lang} code snippet ({n_lines} lines)",
            "suggest_action": "Shall I review, explain, or improve this code?",
        }

    # URL detection
    if text.startswith("http://") or text.startswith("https://"):
        domain = text.split("/")[2] if "/" in text[8:] else text
        return {
            "intent": "url",
            "description": f"Copied URL: {domain[:60]}",
            "suggest_action": "Want me to fetch and summarize this page?",
        }

    # Error message detection
    error_signals = ["error:", "exception:", "traceback", "syntaxerror",
                     "typeerror", "valueerror", "nameerror", "404", "500"]
    if any(sig in text_lower for sig in error_signals):
        return {
            "intent": "error",
            "description": "Copied error/exception message",
            "suggest_action": "Want me to diagnose this error?",
        }

    # Long text — likely for summarization/analysis
    if len(text) > 500:
        word_count = len(text.split())
        return {
            "intent": "long_text",
            "description": f"Copied long text ({word_count} words, {n_lines} lines)",
            "suggest_action": "Want a summary, or should I analyze this?",
        }

    # Default
    return {
        "intent": "text",
        "description": f"Copied text ({len(text)} chars)",
        "suggest_action": None,
    }

# =============================================================================
# CLIPBOARD MONITOR
# =============================================================================

_last_clipboard = ""
_clipboard_suggestions = []


def _clipboard_monitor_loop():
    """Background thread: polls clipboard for changes."""
    global _last_clipboard
    while _running:
        try:
            if CLIPBOARD_AVAILABLE:
                current = pyperclip.paste()
                if (
                    current
                    and current != _last_clipboard
                    and len(current) >= CLIPBOARD_MIN_LENGTH
                ):
                    _last_clipboard = current
                    intent = extract_clipboard_intent(current)
                    log_perception(
                        kind="clipboard",
                        content=intent["description"],
                        source="clipboard",
                        metadata={
                            "intent":   intent["intent"],
                            "suggest":  intent.get("suggest_action"),
                            "preview":  current[:200],
                        },
                    )
                    # Queue suggestion if there's an action to suggest
                    if intent.get("suggest_action"):
                        with _clipboard_lock:
                            _clipboard_suggestions.append({
                                "time":     datetime.datetime.now().strftime("%H:%M:%S"),
                                "msg":      f"📋 Clipboard: {intent['description']}. {intent['suggest_action']}",
                                "raw":      current[:500],
                                "intent":   intent["intent"],
                            })
                            if len(_clipboard_suggestions) > 10:
                                _clipboard_suggestions.pop(0)
        except Exception:
            pass
        time.sleep(CLIPBOARD_INTERVAL)


def pop_clipboard_suggestions() -> list:
    """Drain and return all pending clipboard suggestions."""
    with _clipboard_lock:
        out = list(_clipboard_suggestions)
        _clipboard_suggestions.clear()
    return out


def get_clipboard_content() -> str:
    """Get current clipboard text (safe)."""
    if not CLIPBOARD_AVAILABLE:
        return ""
    try:
        return pyperclip.paste() or ""
    except Exception:
        return ""

# =============================================================================
# FILE SYSTEM WATCHER
# =============================================================================

_dir_snapshots: dict = {}    # dir_path → set of filenames
_fs_suggestions = []
_fs_lock = threading.Lock()


def _take_dir_snapshot(dirpath: str) -> set:
    """Return the set of filenames currently in a directory."""
    try:
        return set(os.listdir(dirpath))
    except Exception:
        return set()


def _fs_watcher_loop():
    """Background thread: monitors WATCH_DIRS for changes."""
    global _dir_snapshots
    # Initial snapshots
    for d in WATCH_DIRS:
        if os.path.exists(d):
            _dir_snapshots[d] = _take_dir_snapshot(d)

    while _running:
        for dirpath in WATCH_DIRS:
            if not os.path.exists(dirpath):
                continue
            try:
                current_files = _take_dir_snapshot(dirpath)
                old_files     = _dir_snapshots.get(dirpath, set())

                added   = current_files - old_files
                removed = old_files - current_files

                for fname in added:
                    full_path = os.path.join(dirpath, fname)
                    ctx       = extract_file_context(full_path)
                    log_perception(
                        kind="file_added",
                        content=f"New {ctx['category']}: {fname}",
                        source=dirpath,
                        metadata=ctx,
                    )
                    # Check if it's a new project
                    proj_type = detect_project_in_dir(full_path)
                    if proj_type:
                        log_perception(
                            kind="new_project",
                            content=f"New {proj_type} detected: {fname}",
                            source=dirpath,
                            metadata={"project_type": proj_type, "path": full_path},
                        )
                        _push_fs_suggestion(
                            f"🆕 New {proj_type} detected: '{fname}'. "
                            f"Want me to set up tracking for this project?"
                        )

                for fname in removed:
                    log_perception(
                        kind="file_removed",
                        content=f"Removed: {fname}",
                        source=dirpath,
                        metadata={"name": fname},
                    )

                _dir_snapshots[dirpath] = current_files

            except Exception:
                pass
        time.sleep(PERCEPTION_INTERVAL)


def _push_fs_suggestion(msg: str):
    with _fs_lock:
        _fs_suggestions.append({
            "time": datetime.datetime.now().strftime("%H:%M:%S"),
            "msg":  msg,
        })
        if len(_fs_suggestions) > 20:
            _fs_suggestions.pop(0)


def pop_fs_suggestions() -> list:
    with _fs_lock:
        out = list(_fs_suggestions)
        _fs_suggestions.clear()
    return out

# =============================================================================
# ENVIRONMENT SNAPSHOT — richer version of old observe_environment()
# =============================================================================

def take_environment_snapshot() -> dict:
    """
    Build a comprehensive snapshot of the current environment.
    Includes filesystem, processes, clipboard, patterns, time context.
    """
    now = datetime.datetime.now()
    snap = {
        "timestamp":    now.isoformat(),
        "time_of_day":  now.strftime("%H:%M"),
        "day":          now.strftime("%A"),
        "hour":         now.hour,
        "date":         now.strftime("%Y-%m-%d"),
    }

    # Filesystem state
    all_watched = []
    for d in WATCH_DIRS:
        if os.path.exists(d):
            try:
                files = os.listdir(d)
                all_watched.append({
                    "dir":   d,
                    "count": len(files),
                    "sample": files[:5],
                })
            except Exception:
                pass
    snap["watched_dirs"] = all_watched

    # Clipboard state
    clip_text = get_clipboard_content()
    snap["clipboard_has_content"] = bool(clip_text and len(clip_text) >= CLIPBOARD_MIN_LENGTH)
    if snap["clipboard_has_content"]:
        snap["clipboard_intent"] = extract_clipboard_intent(clip_text)

    # Recent perceptions
    recent = get_recent_perceptions(5)
    snap["recent_perceptions"] = recent

    return snap


def build_perception_context() -> str:
    """
    Build a natural-language perception context string for injection into LLM prompts.
    Shows Ultron what it currently sees.
    """
    snap    = take_environment_snapshot()
    lines   = []
    now_str = datetime.datetime.now().strftime("%A, %B %d %Y at %I:%M %p")
    lines.append(f"Current time: {now_str}")

    if snap.get("clipboard_has_content"):
        intent = snap.get("clipboard_intent", {})
        lines.append(f"Clipboard: {intent.get('description', 'content present')}")

    recent = snap.get("recent_perceptions", [])
    if recent:
        lines.append("Recent observations:")
        for p in recent[-3:]:
            lines.append(f"  • [{p['kind']}] {p['content']}")

    return "\n".join(lines) if lines else ""


def build_screen_context() -> str:
    """Build a short context string about current screen for LLM."""
    try:
        from screen_engine import get_screen_status, get_latest_screen_text
        s = get_screen_status()
        parts = []
        if s.get("active_window"):
            parts.append(f"Active window: {s['active_window']}")
        text = get_latest_screen_text() or ""
        if text:
            parts.append(f"Screen text snippet: {text[:600]}")
        return "\n".join(parts)
    except Exception:
        return ""

# =============================================================================
# LIFECYCLE MANAGEMENT
# =============================================================================

def start_perception():
    """Start all background perception threads."""
    global _running, _threads
    # Phase 4.1 — gate through loop_supervisor / config.LOOPS
    from loop_supervisor import loop_enabled
    if not loop_enabled("perception"):
        print("[Perception] loop disabled by config.LOOPS — not starting")
        return
    if _running:
        return
    _running = True

    t1 = threading.Thread(target=_fs_watcher_loop,        daemon=True, name="UltronFSWatcher")
    t2 = threading.Thread(target=_clipboard_monitor_loop, daemon=True, name="UltronClipboard")

    _threads = [t1, t2]
    for t in _threads:
        t.start()

    print(f"[Perception] File watcher and clipboard monitor started.")
    if not CLIPBOARD_AVAILABLE:
        print("[Perception] pyperclip not installed — clipboard monitoring disabled.")
        print("[Perception] Install: pip install pyperclip")


def stop_perception():
    """Stop all perception threads."""
    global _running
    _running = False
