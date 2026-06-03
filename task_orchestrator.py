"""
task_orchestrator.py — Ultron's Master Task Brain
==================================================
This is the CORE UPGRADE. When you speak any complex task,
Ultron decides HOW to get it done:

  1. Simple tasks → handles it directly (screenshot, folder, file ops)
  2. Coding / complex tasks → opens Claude.ai, asks YOU questions,
     collects the code, saves it, runs it automatically
  3. Game/app building → full project scaffolding + execution pipeline
  4. Research → opens browser, searches, summarizes back to you
  5. Phone tasks → bridges to Android/iOS via ADB or Termux HTTP

Usage:
  from task_orchestrator import orchestrate
  result = orchestrate("I want to build a 2D snake game in Python")
"""

import os
import re
import json
import time
import threading
import subprocess
import webbrowser
import platform
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

# ─── Extracted sub-modules ───────────────────────────────────────────────────
from phone_tasks import PhoneBridge
from code_tasks import (
    ProjectBuilder, handle_build_answers, save_and_run_from_clipboard,
    _active_builders,
)
from browser_tasks import (
    _PREFERRED_BROWSER, _WIN_BROWSER_PATHS as _BROWSER_PATHS, _KNOWN_BROWSERS,
    _launch_browser, _detect_browser_hint, _extract_play_query,
    _youtube_play, _press_browser_key,
    handle_set_browser, handle_play_media, handle_pause_resume_media,
    handle_media_next, handle_media_prev,
    handle_open_url, handle_volume_control,
)
from research_tasks import handle_search_web, handle_search_on_site, handle_open_and_search

# ─── Base dir ────────────────────────────────────────────────────────────────
_BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
_WORK_DIR   = os.path.join(_BASE_DIR, "workspace")          # where projects live
_QUEUE_FILE = os.path.join(_BASE_DIR, "task_queue.json")

os.makedirs(_WORK_DIR, exist_ok=True)

# ─── Optional imports ────────────────────────────────────────────────────────
try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE    = 0.1
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False

try:
    import pyperclip
    CLIP_AVAILABLE = True
except ImportError:
    CLIP_AVAILABLE = False

# Browser preference constants and utilities imported from browser_tasks.py


# =============================================================================
# UTTERANCE PARSING HELPERS — structural, not phrase-matching
# =============================================================================

# _KNOWN_BROWSERS imported from browser_tasks
_FILE_EXT_RE = re.compile(r"\.([a-z0-9]{2,5})\b", re.I)

# Trailing locator phrases users append to file/folder names — these are
# location hints, not part of the target name. Stripped before lookup.
_LOCATOR_TAIL_RE = re.compile(
    r"\s+(?:file|folder|document)?\s*"
    r"(?:on|from|in|inside|at|under)\s+"
    r"(?:my\s+|the\s+)?"
    r"(desktop|downloads|documents|pictures|videos|music|onedrive|home|"
    r"d:\\?\S*|c:\\?\S*|[a-z]:\\?\S+)\s*$",
    re.I,
)

# A bare trailing "file" / "folder" / "document" with no location — strip it
# so "README.md file" → "README.md" before lookup.
_BARE_KIND_TAIL_RE = re.compile(r"\s+(?:file|folder|document)\s*$", re.I)


# _detect_browser_hint and _extract_play_query imported from browser_tasks


def _strip_locator_tail(name: str) -> str:
    """Strip trailing location hints like 'on desktop' / 'in documents'.

    'ok.txt file on desktop' → 'ok.txt'
    'project folder in documents' → 'project'
    'README.md file' → 'README.md'   (no location — bare-kind tail stripped)
    """
    if not name:
        return name
    n = _LOCATOR_TAIL_RE.sub("", name)
    n = _BARE_KIND_TAIL_RE.sub("", n)
    return n.strip(' "\'')


def _resolve_file_target(name: str) -> Optional[str]:
    """If `name` describes a file, return its absolute path; otherwise None.

    A target counts as a file only when one of these is true:
      - The literal string (or the locator-stripped version) is an existing
        file on disk, OR
      - After stripping a locator tail it has a recognised file extension
        AND resolves via the system index or a well-known user folder.

    Bare names without an extension are NOT treated as files (so "open
    notepad" / "open chrome" stays on the app-launch path even if the system
    index happens to know a .lnk shortcut with that stem).
    """
    if not name:
        return None
    candidate = name.strip(' "\'')
    if os.path.exists(candidate) and os.path.isfile(candidate):
        return os.path.abspath(candidate)

    stripped = _strip_locator_tail(candidate)
    if not stripped:
        return None

    if os.path.exists(stripped) and os.path.isfile(stripped):
        return os.path.abspath(stripped)

    if not _FILE_EXT_RE.search(stripped):
        # No extension — caller almost certainly meant an app or site, not a
        # file. Bail and let the app/site branches handle it.
        return None

    # Has an extension → try the system index, then well-known folders.
    try:
        from system_index import find_file
        hit = find_file(stripped)
        if hit and os.path.exists(hit):
            return hit
    except Exception:
        pass

    basename = os.path.basename(stripped)
    for folder in (
        os.path.expanduser("~/Desktop"),
        os.path.expanduser("~/OneDrive/Desktop"),
        os.path.expanduser("~/Downloads"),
        os.path.expanduser("~/Documents"),
        os.path.expanduser("~/OneDrive/Documents"),
    ):
        p = os.path.join(folder, basename)
        if os.path.exists(p) and os.path.isfile(p):
            return p
    return None


_FOLDER_HINT_RE = re.compile(
    r"\b(?:folder|directory|dir)\b|"
    r"(?:on|from|in|inside|at|under)\s+"
    r"(?:my\s+|the\s+)?"
    r"(?:desktop|downloads|documents|pictures|videos|music|onedrive|home)",
    re.I,
)


def _resolve_folder_target(name: str) -> Optional[str]:
    """If `name` describes a folder, return its absolute path; otherwise None.

    To avoid hijacking bare app names ("open brave" matching an AppData
    `BraveSoftware` directory), we require ONE of:
      - The literal string (or locator-stripped version) is an existing dir, OR
      - The original input contains an explicit folder hint
        ("folder" / "directory" / "<locator>") before the index lookup runs.
    """
    if not name:
        return None
    candidate = name.strip(' "\'')
    if os.path.exists(candidate) and os.path.isdir(candidate):
        return os.path.abspath(candidate)

    stripped = _strip_locator_tail(candidate)
    if stripped and os.path.exists(stripped) and os.path.isdir(stripped):
        return os.path.abspath(stripped)

    if not _FOLDER_HINT_RE.search(candidate):
        return None

    try:
        from system_index import find_dir
        hit = find_dir(stripped or candidate)
        if hit and os.path.exists(hit):
            return hit
    except Exception:
        pass
    return None


# Shell commands that mutate or destroy state. The LLM picker is allowed to
# stage a yes/cancel confirmation for run_command, but "close X" gets mapped
# to `rm X` more often than not — and a single wrong "yes" deletes the file.
# We refuse these at the staging boundary so they never reach the user as
# something to approve.
#
# Phase 7.3 — the regex now lives in confirm_gate so there's ONE definition,
# not two. _is_destructive_shell here is a thin re-export that keeps existing
# call sites in this file working.

def _is_destructive_shell(cmd: str) -> bool:
    """Delegates to the consolidated gate in confirm_gate (Phase 7.3)."""
    from confirm_gate import is_destructive_shell
    return is_destructive_shell(cmd)


_KNOWN_SITES = {
    "youtube":    "https://www.youtube.com",
    "youtube.com":"https://www.youtube.com",
    "gmail":      "https://mail.google.com",
    "github":     "https://github.com",
    "claude":     "https://claude.ai",
    "claude.ai":  "https://claude.ai",
    "chatgpt":    "https://chat.openai.com",
    "gemini":     "https://gemini.google.com",
    "perplexity": "https://perplexity.ai",
    "drive":      "https://drive.google.com",
    "maps":       "https://www.google.com/maps",
    "twitter":    "https://twitter.com",
    "x":          "https://x.com",
    "reddit":     "https://www.reddit.com",
    "instagram":  "https://www.instagram.com",
    "facebook":   "https://www.facebook.com",
    "whatsapp":   "https://web.whatsapp.com",
    "netflix":    "https://www.netflix.com",
    "spotify":    "https://open.spotify.com",
}


def _xdg_open(path: str) -> None:
    """Cross-platform file/folder opener. Uses xdg-open on Linux, os.startfile on Windows."""
    system = platform.system()
    if system == "Windows":
        os.startfile(path)
    elif system == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def _resolve_site(name: str) -> Optional[str]:
    """Map a bare site name → URL. Stripping trailing 'and ...' clauses first."""
    if not name:
        return None
    n = name.lower().strip(' "\'')
    # Drop trailing " and <rest>" — that clause is for a different action
    n = re.sub(r"\s+and\s+.*$", "", n)
    # Drop trailing browser hint
    n = re.sub(
        r"\b(?:in|on|using|with|via)\s+(?:" + "|".join(_KNOWN_BROWSERS) + r")\b.*$",
        "",
        n,
    ).strip()
    return _KNOWN_SITES.get(n)

# =============================================================================
# TASK CLASSIFIER — understands what you want
# =============================================================================

TASK_PATTERNS = {
    # ── File system ──────────────────────────────────────────────────────────
    "create_folder": [
        r"create (a )?folder (.+)",
        r"make (a )?folder (.+)",
        r"new folder (.+)",
    ],
    "open_folder": [
        r"open (folder|directory) (.+)",
        r"open (.+) folder",
        r"show me (.+) folder",
    ],
    "take_screenshot": [
        r"\btake\s+(a\s+)?screenshot\b",
        r"\bcapture\s+(the\s+)?screen\b",
        r"\b(grab|snap)\s+(a\s+)?screenshot\b",
        r"^\s*screenshot\s*$",
    ],
    "delete_file": [
        r"delete (file|folder) (.+)",
        r"remove (.+)",
    ],

    # ── Web search on a specific site ────────────────────────────────────────
    # Must precede "open_app" so "open claude and search ..." doesn't get
    # eaten as an open_app call with name "claude and search ...".
    "open_and_search": [
        r"^open\s+(\w+)\s+and\s+search\s+(?:for\s+)?(.+)$",   # (site, query)
    ],
    "search_on_site": [
        r"^search\s+(?:for\s+)?(.+?)\s+(?:on|in|using)\s+([\w\-\.]+)\s*$",  # (query, site)
    ],

    # ── Open a specific browser and play on YouTube (must precede open_app) ────
    "open_and_play": [
        r"^open\s+(brave|chrome|firefox|edge|opera|chromium)\s+and\s+(?:play|watch|listen\s+to)\s+(.+)$",
    ],

    # ── Referent open — "open it" / "open the screenshot" (MUST precede open_app) ──
    # Without this, "open (.+)" eats "open the screenshot" → open_app("the screenshot")
    # and tries to launch an app called "the screenshot" → fails.
    "open_recent": [
        r"^open\s+(?:it|that|this)\s*$",
        r"^open\s+(?:the\s+)?(screenshot|file|image|photo|recording|note|video|capture)\s*$",
    ],

    # ── App launching ────────────────────────────────────────────────────────
    "open_app": [
        r"open (.+)",
        r"launch (.+)",
        r"start (.+)",
    ],

    # ── Coding / building ────────────────────────────────────────────────────
    "build_project": [
        r"(build|create|make|develop|code) (a |an )?(game|app|website|tool|script|program|bot|plugin)",
        r"i want to build (.+)",
        r"i want to create (.+)",
        r"i want to make (.+)",
        r"help me (build|create|make) (.+)",
        r"write (a |an )?(.+) (game|app|script|program|tool)",
    ],
    "run_code": [
        r"run (the |my )?code",
        r"execute (the |my )?(file|script|program) (.+)",
        r"run (.+\.py)",
    ],
    "open_editor": [
        r"open (vs ?code|visual studio|code editor|editor)",
        r"edit (file|code) (.+)",
    ],

    # ── Claude AI tasks ──────────────────────────────────────────────────────
    "ask_claude": [
        r"ask claude (.+)",
        r"use claude (for|to) (.+)",
        r"open claude (for|to) (.+)",
        r"explain (to claude|claude) (.+)",
    ],

    # ── Web browsing ─────────────────────────────────────────────────────────
    "search_web": [
        r"search (for |the web for )?(.+)",
        r"google (.+)",
        r"look up (.+)",
        r"find (info|information) (about|on) (.+)",
    ],
    "open_url": [
        r"open (https?://\S+)",
        r"go to (https?://\S+)",
        r"visit (https?://\S+)",
    ],

    # ── Phone control ────────────────────────────────────────────────────────
    "phone_screenshot": [
        r"(phone|mobile) screenshot",
        r"take screenshot (on|from) (phone|mobile)",
    ],
    "phone_open_app": [
        r"(on|open on) (my )?(phone|mobile) (.+)",
        r"open (.+) on (phone|mobile)",
    ],

    # ── Media playback ───────────────────────────────────────────────────────
    "pause_media": [
        r"^pause(\s+(?:the\s+)?(?:video|music|song|playing))?$",
        r"^stop\s+(?:the\s+)?(?:video|music|song|playing)$",
    ],
    "resume_media": [
        r"^(resume|unpause|continue(\s+playing)?|play\s+it(\s+again)?)\b",
        r"^play\s*$",
    ],
    "set_browser": [
        r"\buse\s+(brave|chrome)\b",
        r"\bswitch\s+(?:to\s+)?(brave|chrome)\b",
        r"\bset\s+(?:default\s+)?browser\s+to\s+(brave|chrome)\b",
        r"\bopen\s+(?:everything\s+)?(?:in|with)\s+(brave|chrome)\b",
    ],
    # ── Tab / window close (MUST come before close_app — greedy regex eats it otherwise) ──
    # Hotkeys: Ctrl+W = close tab, Alt+F4 = close window. Works in any focused app.
    "close_tab": [
        # "close the tab" / "close this tab" / "close current tab"
        r"^(?:close|kill|exit)\s+(?:the\s+|this\s+|current\s+)*tab\b\s*$",
        # "close X tab" (X = brave / chrome / firefox / edge OR site name)
        r"^(?:close|kill|exit)\s+(?:the\s+)?(.+?)\s+tab\b\s*$",
        # "inside X close Y" / "in X close Y" — Y is implicit tab content
        r"^(?:inside|in|within)\s+(brave|chrome|firefox|edge|chromium)\s+(?:close|kill)\s+(.+)$",
        # "close X inside/in Y" — X = site, Y = browser
        r"^(?:close|kill)\s+(.+?)\s+(?:inside|in|within|on)\s+(brave|chrome|firefox|edge|chromium)\b",
        # bare known-browser-content names — "close youtube", "close gmail" etc.
        r"^(?:close|kill)\s+(?:the\s+)?(youtube|gmail|github|twitter|reddit|google|stackoverflow|whatsapp|chatgpt|claude|x\.com)\s*$",
    ],
    "close_window": [
        r"^(?:close|kill|quit|exit)\s+(?:the\s+|this\s+|current\s+)*window\b\s*$",
        r"^(?:close|kill|quit)\s+(?:the\s+)?(.+?)\s+window\b\s*$",
    ],
    "focus_window": [
        r"^(?:switch|shift|go|jump|move|flip)\s+to\s+(.+?)(?:\s+window)?\s*$",
        r"^(?:bring\s+up|focus|activate|show)\s+(.+?)(?:\s+window)?\s*$",
    ],
    # ── Clipboard primitives (system hotkeys, work in any focused app) ──────
    "copy_selection": [
        r"^copy(?:\s+(?:it|that|this|selection|selected))?\s*$",
        r"^(?:ctrl|control)\s*[+\-\s]\s*c\s*$",
    ],
    "paste_clipboard": [
        r"^paste(?:\s+(?:it|that|this|here))?\s*$",
        r"^(?:ctrl|control)\s*[+\-\s]\s*v\s*$",
    ],
    "cut_selection": [
        r"^cut(?:\s+(?:it|that|this|selection|selected))?\s*$",
        r"^(?:ctrl|control)\s*[+\-\s]\s*x\s*$",
    ],
    "select_all": [
        r"^select\s+all\s*$",
        r"^(?:ctrl|control)\s*[+\-\s]\s*a\s*$",
    ],

    # ── Close app by name (process-kill — last-resort fallback) ────────────
    "close_app": [
        r"^(?:close|quit|exit|kill|terminate)\s+(.+)$",
    ],
    # ── System controls ───────────────────────────────────────────────────────
    "lock_screen": [
        r"^(?:lock(?:\s+(?:the\s+)?(?:screen|computer|pc|laptop|system|my\s+(?:pc|computer|screen)))?|lock\s+it)$",
    ],
    "sleep_computer": [
        r"^(?:sleep|suspend)(?:\s+(?:the\s+)?(?:computer|pc|laptop|system))?$",
    ],
    "empty_trash": [
        r"^(?:empty|clear)\s+(?:the\s+)?(?:trash|recycle\s*bin|rubbish)$",
    ],
    "system_info": [
        r"^(?:system|pc)\s+(?:info|information|status|stats)$",
    ],
    "brightness_up": [
        r"^(?:brightness\s+up|increase\s+(?:the\s+)?brightness|screen\s+brighter)$",
    ],
    "brightness_down": [
        r"^(?:brightness\s+down|(?:decrease|lower|dim)\s+(?:the\s+)?brightness|screen\s+dimmer)$",
    ],
    # ── Media navigation (must precede play_media) ───────────────────────────
    "media_next": [
        r"^(?:play\s+)?(?:the\s+)?next(?:\s+(?:video|track|song|one))?(?:\s+(?:on|in)\s+youtube)?$",
        r"^skip(?:\s+(?:to\s+)?(?:the\s+|this\s+)?(?:next\s+)?(?:video|track|song))?(?:\s+(?:on|in)\s+youtube)?$",
    ],
    "media_prev": [
        r"^(?:play\s+)?(?:the\s+)?(?:previous|prev)(?:\s+(?:video|track|song|one))?(?:\s+(?:on|in)\s+youtube)?$",
        r"^(?:go\s+(?:back|to\s+(?:the\s+)?previous)|back)(?:\s+(?:video|track|song))?(?:\s+(?:on|in)\s+youtube)?$",
    ],
    "play_media": [
        r"play\s+(.+?)\s+on\s+youtube",
        r"open\s+youtube\s+and\s+play\s+(.+)",
        r"play\s+(.+)",
    ],
    "volume_control": [
        r"\b(increase|raise|turn\s+up|louder|boost|crank)\b.{0,20}\bvolume\b",
        r"\bvolume\b.{0,20}\b(up|max|maximum|louder|increase|raise|higher)\b",
        r"\b(max|maximum)\b.{0,10}\bvolume\b",
        r"\bvolume\b.{0,10}\b(max|maximum)\b",
        r"\b(increase|raise|turn\s+up)\b.{0,20}\b(to\s+)?(max|maximum|full)\b",
        # decrease — now includes "reduce", "drop", "dim", "soften", "down"
        r"\b(decrease|lower|reduce|drop|dim|soften|turn\s+down|quieter)\b.{0,20}\bvolume\b",
        r"\bvolume\b.{0,20}\b(down|lower|decrease|reduce|quiet|softer|less)\b",
        # explicit level: "set/reduce/raise volume to 50", "volume to 30%"
        r"\b(?:set|change|adjust|reduce|raise|lower|drop|increase|turn|put)\s+(?:the\s+)?volume\s+(?:to|at)\s+(\d{1,3})\s*%?",
        r"\bvolume\s+(?:to|at)\s+(\d{1,3})\s*%?",
        r"\b(un)?mute\b",
    ],
}


def classify_task(text: str) -> Dict[str, Any]:
    """
    Classify natural language into a structured task.
    Returns: {type, params, confidence, raw}
    """
    tl = text.lower().strip()

    for task_type, patterns in TASK_PATTERNS.items():
        for pattern in patterns:
            m = re.search(pattern, tl)
            if m:
                return {
                    "type":       task_type,
                    "params":     list(m.groups()),
                    "confidence": 0.9,
                    "raw":        text,
                    "match":      m.group(0),
                }

    # No pattern matched — treat as AI task
    return {
        "type":       "ai_chat",
        "params":     [text],
        "confidence": 0.5,
        "raw":        text,
        "match":      text,
    }


# =============================================================================
# LLM TOOL-SELECTOR FALLBACK — JARVIS-style intent recovery
# =============================================================================
# When the regex misses, ask the LLM to pick one of the actions below.
# Fires only when the text looks command-like (cheap heuristic) so chitchat
# doesn't pay a per-message LLM round trip.
#
# Two tiers:
#   _LLM_SAFE_ACTIONS      — auto-run on a pick.
#   _LLM_HIGH_RISK_ACTIONS — stage a pending confirmation; user's next reply
#                            must include yes/confirm/go-ahead to actually run.
#                            "no/cancel/never mind" aborts.

_LLM_SAFE_ACTIONS = {
    # task_orchestrator-native:
    "take_screenshot", "create_folder", "open_folder", "open_app", "open_url",
    "search_web", "search_on_site", "open_and_search", "open_and_play",
    "play_media", "pause_media", "resume_media",
    "volume_control", "set_browser", "phone_screenshot",
    "media_next", "media_prev", "system_info",
    # window / tab control — autonomous primitives:
    "close_tab", "close_window", "close_app", "focus_window", "open_recent",
    "lock_screen", "brightness_up", "brightness_down",
    # clipboard primitives (Ctrl+C/V/X/A):
    "copy_selection", "paste_clipboard", "cut_selection", "select_all",
    # action_engine read-only / low-impact additions:
    "file_list", "file_read", "get_clipboard", "calculate",
    "weather_fetch", "web_scrape", "note_create", "get_window",
    "memory_fetch", "git_status",
    "screenshot",   # synonym route through action_engine
}

_LLM_HIGH_RISK_ACTIONS = {
    "delete_file", "delete_folder", "run_command", "run_code", "send_email",
    "type_text", "click", "press_key", "hotkey",
    "file_write", "create_file", "append_file",
    "rename_file", "move_file", "copy_file", "zip_folder",
    "set_clipboard",
}

_LLM_ALLOWED_ACTIONS = _LLM_SAFE_ACTIONS | _LLM_HIGH_RISK_ACTIONS

# Synonyms the LLM might emit — normalize them before validating.
_LLM_ACTION_SYNONYMS = {
    "snap_screen":  "take_screenshot",
    "capture":      "take_screenshot",
    "mkdir":        "create_folder",
    "open":         "open_app",
    "launch":       "open_app",
    "open_website": "open_url",
    "browse":       "open_url",
    "google":       "search_web",
    "search":       "search_web",
    "play":         "play_media",
    "pause":        "pause_media",
    "resume":       "resume_media",
    "unpause":      "resume_media",
    "volume":       "volume_control",
    "vol":          "volume_control",
    "ls":           "file_list",
    "dir":          "file_list",
    "list_files":   "file_list",
    "read_file":    "file_read",
    "cat":          "file_read",
    "shell":        "run_command",
    "exec":         "run_command",
    "type":         "type_text",
    "write_file":   "file_write",
    "append":       "append_file",
    "rename":       "rename_file",
    "mv":           "move_file",
    "move":         "move_file",
    "cp":           "copy_file",
    "copy":         "copy_file",
    "zip":          "zip_folder",
    "compress":     "zip_folder",
    "delete":       "delete_file",
    "rm":           "delete_file",
}

# Positional params -> action_engine kwargs. Order matches what the picker
# emits in `params`. Any key the LLM didn't provide is simply omitted.
_ACTION_PARAM_MAPS = {
    "take_screenshot": [],
    "screenshot":      [],
    "file_list":       ["path"],
    "file_read":       ["path"],
    "get_clipboard":   [],
    "set_clipboard":   ["text"],
    "calculate":       ["expression"],
    "weather_fetch":   ["location"],
    "web_scrape":      ["url"],
    "note_create":     ["title", "content", "category", "tags"],
    "memory_fetch":    ["query"],
    "git_status":      ["path"],
    "get_window":      [],
    "open_url":        ["url", "browser"],
    "open_app":        ["name"],
    # High-risk:
    "delete_file":     ["path"],
    "delete_folder":   ["path"],
    "run_command":     ["command"],
    "run_code":        ["code"],
    "send_email":      ["to", "subject", "body"],
    "type_text":       ["text"],
    "click":           ["x", "y"],
    "press_key":       ["key"],
    "hotkey":          ["keys"],
    "file_write":      ["path", "content"],
    "create_file":     ["path", "content"],
    "append_file":     ["path", "content"],
    "rename_file":     ["src", "new_name"],
    "move_file":       ["src", "dest"],
    "copy_file":       ["src", "dest"],
    "zip_folder":      ["src", "output"],
}

# Session-scoped pending action store. Keyed by session_id so different
# chats don't share confirmations. In-process only — cleared on restart.
_PENDING_CONFIRM: Dict[str, Dict[str, Any]] = {}

# Session-scoped tracker for the most-recent file produced by a tool. Lets
# "open the screenshot", "open it", "open that" resolve to a real path
# instead of being interpreted as `open_app("the screenshot")`.
_LAST_ACTION_OUTPUT: Dict[str, Dict[str, Any]] = {}


def _record_last_output(session_id: str, action: str, path: str, kind: str = "file"):
    """Remember the last file an action produced, for referent commands later."""
    if not path:
        return
    _LAST_ACTION_OUTPUT[session_id] = {
        "action": action,
        "path":   path,
        "kind":   kind,
    }


# Session-scoped media play/pause state. YouTube's `k`/Space are TOGGLES — if
# Ultron and reality fall out of sync, the user sees "Paused." when actually
# resuming and vice-versa. Tracking last intent lets us suppress no-op toggles.
_MEDIA_STATE: Dict[str, str] = {}   # session_id -> "playing" | "paused"

_CONFIRM_PHRASES = (
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "confirm", "confirmed",
    "go ahead", "do it", "proceed", "affirmative", "please do", "do that",
    "execute", "run it", "yes please",
)
_CANCEL_PHRASES = (
    "no", "nope", "cancel", "stop", "abort", "never mind", "nevermind",
    "forget it", "don't", "do not", "scratch that", "leave it",
)


def _matches_phrase(text: str, phrases) -> bool:
    s = " " + (text or "").lower().strip() + " "
    return any((" " + p + " ") in s or s.strip() == p for p in phrases)


def _human_summary(action_type: str, params: Dict[str, Any]) -> str:
    if action_type in ("delete_file", "delete_folder"):
        return f"{action_type} on {params.get('path','?')}"
    if action_type == "run_command":
        return f"run_command: {params.get('command','?')!r}"
    if action_type == "run_code":
        return f"run_code ({len(params.get('code',''))} chars)"
    if action_type == "send_email":
        return f"send_email to {params.get('to','?')} — subject {params.get('subject','?')!r}"
    if action_type == "type_text":
        return f"type_text: {params.get('text','?')!r}"
    if action_type in ("file_write", "create_file", "append_file"):
        return f"{action_type} {params.get('path','?')} ({len(params.get('content',''))} chars)"
    if action_type == "rename_file":
        return f"rename {params.get('src','?')} -> {params.get('new_name','?')}"
    if action_type == "move_file":
        return f"move {params.get('src','?')} -> {params.get('dest','?')}"
    if action_type == "copy_file":
        return f"copy {params.get('src','?')} -> {params.get('dest','?')}"
    if action_type == "click":
        return f"click at ({params.get('x','?')},{params.get('y','?')})"
    if action_type == "press_key":
        return f"press_key {params.get('key','?')!r}"
    if action_type == "hotkey":
        return f"hotkey {params.get('keys','?')!r}"
    bits = [f"{k}={v!r}" for k, v in params.items() if v not in (None, "")]
    return f"{action_type}" + (f" with {', '.join(bits)}" if bits else "")


def _llm_params_to_kwargs(action_type: str, params_list) -> Dict[str, Any]:
    keys = _ACTION_PARAM_MAPS.get(action_type, [])
    d: Dict[str, Any] = {}
    for i, key in enumerate(keys):
        if i < len(params_list) and params_list[i] not in (None, ""):
            d[key] = params_list[i]
    return d


def _dispatch_via_action_engine(action_type: str, params_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Run an action through action_engine and re-shape the response so it
       looks like a normal orchestrate() return value."""
    try:
        from action_engine import execute_action
        out = execute_action(action_type, params_dict)
        return {
            "success":      out.get("success", False),
            "action_taken": action_type,
            "message":      out.get("result") or out.get("error") or "Done.",
            "data":         out,
            "passthrough":  False,
        }
    except Exception as e:
        return {
            "success":      False,
            "action_taken": action_type,
            "message":      f"action_engine error: {e}",
            "passthrough":  False,
        }

# First-word imperatives that mean "the user is asking for an action."
# Question-words intentionally excluded so "what time is it?" stays chat,
# but see _ACTION_NOUNS below — a question that names an actionable noun
# ("what's in my clipboard") is still treated as a command.
_COMMAND_VERBS = {
    "open", "close", "start", "stop", "play", "pause", "resume",
    "take", "capture", "screenshot", "snap", "grab", "make", "create",
    "delete", "remove", "search", "find", "look", "google", "browse",
    "go", "visit", "load", "launch", "run", "execute", "build", "write",
    "save", "copy", "move", "rename", "email", "text", "call", "remind",
    "schedule", "mute", "unmute", "lower", "raise", "increase", "decrease",
    "turn", "set", "switch", "change", "send", "show", "fetch", "get",
    "kill", "fire", "minimize", "maximize", "focus", "type", "click",
    "scroll", "press", "say", "speak", "read",
    "crank", "bump", "boost", "drop", "dim", "brighten", "shoot",
    "pull", "push", "spin", "tune", "flip", "toggle", "queue", "stream",
    "list", "calculate", "compute", "scrape", "fetch", "zip", "rename",
    "archive", "compress", "extract", "summarize", "summarise", "translate",
    "convert", "record", "check", "ping", "test", "lookup", "look",
}

# Nouns that signal an actionable target. When the first word is a question
# starter (in _NON_COMMAND_STARTS) but an _ACTION_NOUN appears anywhere
# else in the utterance, treat the message as command-like — "what's in my
# clipboard?" should fetch the clipboard, not chit-chat.
_ACTION_NOUNS = {
    "clipboard", "screenshot", "screen", "window", "windows",
    "weather", "temperature",
    "file", "files", "folder", "folders", "directory",
    "downloads", "documents", "desktop", "music", "song", "video", "media",
    "volume", "sound", "audio", "playback",
    "browser", "tab", "tabs", "url", "link", "website",
    "app", "application", "software",
    "calendar", "email", "mail", "inbox",
    "weather", "news", "stock", "price",
}

# Polite request prefixes — strip these and re-test the rest.
_POLITE_PREFIXES = (
    "can you ", "could you ", "would you ", "will you ",
    "please ", "kindly ", "could you please ", "can you please ",
    "i need you to ", "i want you to ", "i'd like you to ",
    "would you please ", "pls ", "hey ultron ", "ok ultron ", "ultron ",
)

_NON_COMMAND_STARTS = {
    "what", "why", "how", "when", "where", "who", "which", "whose",
    "is", "are", "was", "were", "do", "does", "did",
    "may", "might",
    "tell", "explain", "elaborate", "describe", "define",
    "i", "you", "we", "they", "he", "she", "hi", "hey", "hello",
    "thanks", "thank", "ok", "okay", "yes", "no",
}


# Questions about the *contents* visible on the screen — these must NOT
# be promoted to commands. The /ask LLM path already pulls live screen OCR
# into context, so it can answer them. If we let the picker grab them, it
# picks get_window (which returns only the focused window's title) and the
# real OCR content is never read. Treat these as chitchat so /ask handles.
_SCREEN_CONTENT_VERBS = {"say", "show", "read", "see", "display", "shows", "saying", "showing", "reading", "displaying"}
_SCREEN_CONTENT_NOUNS = {"screen", "monitor", "display"}


def _is_screen_content_question(parts: list) -> bool:
    """True iff the utterance is asking about what is visible/written on
    screen (as opposed to asking which window has focus, which is a real
    get_window intent)."""
    if not parts:
        return False
    # Heuristic: contains one of {say/show/read/...} AND one of {screen/monitor/display}
    # within a short window. Also catches "what's on (my) screen" via the
    # noun-only fallback when the verb is implicit ("on screen").
    has_verb = any(w in _SCREEN_CONTENT_VERBS for w in parts)
    has_noun = any(w in _SCREEN_CONTENT_NOUNS for w in parts)
    if has_verb and has_noun:
        return True
    # "what is on my screen", "what's on screen" — no verb, but the
    # preposition + noun pattern is a strong screen-content tell.
    joined = " ".join(parts)
    if "on screen" in joined or "on my screen" in joined or "on the screen" in joined:
        return True
    return False


_CONTEXTUAL_REFERENCE_WORDS = {
    "it", "that", "this", "those", "these", "them",
    "just", "earlier", "before", "previously", "prior",
    "you", "your", "yours",   # second-person reference inside a question
}


def _likely_command(text: str) -> bool:
    """Cheap heuristic — does this look like a command rather than chitchat/Q&A?"""
    s = (text or "").lower().strip()
    if len(s) < 3:
        return False
    raw_was_question = s.rstrip().endswith("?")
    # Strip a polite-request prefix once so "can you take a screenshot"
    # falls through to the same logic as "take a screenshot".
    for p in _POLITE_PREFIXES:
        if s.startswith(p):
            s = s[len(p):].strip()
            break
    parts = s.split()
    if not parts:
        return False
    # Demote screen-content questions to chitchat (see comment above).
    if _is_screen_content_question(parts):
        return False

    # Demote questions that reference prior conversation context. Examples:
    #   "Can you open the file you just created?"  → has "?" + "you" + "just"
    #   "Did you save that?"                       → has "?" + "you" + "that"
    #   "Do you have access to my screen?"         → has "?" + "you"
    #   "Was that the right one?"                  → has "?" + "that"
    # These are conversational follow-ups, not action requests. Sending them
    # to the LLM picker (which then calls open_app on phrases like "the file
    # you just created") wastes a Groq round-trip AND produces a wrong action.
    if raw_was_question and any(w in _CONTEXTUAL_REFERENCE_WORDS for w in parts):
        return False
    first = parts[0]
    # Strip a trailing apostrophe-s so "what's" can be compared against "what".
    if first.endswith("'s"):
        first = first[:-2]
    if first in _COMMAND_VERBS:
        return True
    if first in _NON_COMMAND_STARTS:
        # Question wording — but if an actionable noun is named, treat it as
        # a command. "what's in my clipboard" / "tell me the weather" should
        # hit get_clipboard / weather_fetch, not free chat.
        return any(w in _ACTION_NOUNS for w in parts[1:])
    # Neither verb nor question-start — fall back to "any actionable word
    # somewhere in a concise utterance".
    return (
        (any(w in _COMMAND_VERBS for w in parts)
         or any(w in _ACTION_NOUNS for w in parts))
        and len(parts) <= 14
    )


# ── Picker LRU cache ─────────────────────────────────────────────────────────
# Repeated phrasings ("take a screenshot", "snap a photo of my desktop") map
# to the same picked action — cache the result so the second-and-later calls
# skip the ~6s Groq round-trip entirely. Pure-Python LRU via dict insertion
# order; eviction = pop the oldest key when we exceed the cap.
_PICKER_CACHE: Dict[str, Optional[Dict[str, Any]]] = {}
_PICKER_CACHE_MAX = 128
_PICKER_CACHE_STATS = {"hits": 0, "misses": 0, "evictions": 0}


def picker_cache_info() -> Dict[str, Any]:
    """Diagnostics for the picker cache. Returned shape is stable for tests."""
    return {
        **_PICKER_CACHE_STATS,
        "size":   len(_PICKER_CACHE),
        "max":    _PICKER_CACHE_MAX,
    }


def picker_cache_clear() -> None:
    """Drop everything. Useful for tests or after a manifest change."""
    _PICKER_CACHE.clear()
    _PICKER_CACHE_STATS.update({"hits": 0, "misses": 0, "evictions": 0})


def _picker_cache_key(text: str) -> str:
    return " ".join((text or "").lower().split())


def _llm_pick_action(text: str) -> Optional[Dict[str, Any]]:
    """
    Ask the LLM to map a free-form command to one of the whitelisted actions.
    Returns a task dict {type, params, ...} if it picks something valid, else None.
    Cached by normalized text. Fail-soft: any error returns None and callers
    fall through to free chat.
    """
    key = _picker_cache_key(text)
    if key and key in _PICKER_CACHE:
        _PICKER_CACHE_STATS["hits"] += 1
        cached = _PICKER_CACHE[key]
        if cached is None:
            return None
        # Shallow-copy + retag so caller mutations don't poison the entry.
        return dict(cached, source="llm_pick_cached", raw=text, match=text)
    _PICKER_CACHE_STATS["misses"] += 1
    picked = _llm_pick_action_uncached(text)
    if key:
        if len(_PICKER_CACHE) >= _PICKER_CACHE_MAX:
            # Pop the oldest insertion (dict insertion order is stable).
            try:
                _PICKER_CACHE.pop(next(iter(_PICKER_CACHE)))
                _PICKER_CACHE_STATS["evictions"] += 1
            except StopIteration:
                pass
        _PICKER_CACHE[key] = picked
    return picked


def _llm_pick_action_uncached(text: str) -> Optional[Dict[str, Any]]:
    """The real worker — does the Groq round-trip. Don't call directly;
    go through _llm_pick_action() so cache stays consistent."""
    try:
        from llm_engine import call_llm_batch
    except Exception:
        return None

    manifest_lines = [
        # ── Safe (auto-run when picked) ───────────────────────────────────────
        "take_screenshot                    # save current screen to disk",
        "create_folder       name           # mkdir at name",
        "open_folder         path           # open File Explorer at a path",
        "open_app            name           # launch installed app (notepad, brave, vscode, etc.)",
        "open_url            url            # open a URL in the default browser",
        "search_web          query          # CLOUD search (Tavily) + summary, NO browser opens",
        "search_on_site      query, site    # CLOUD search scoped to a site, NO browser opens",
        "open_and_search     site, query    # OPENS visible browser at site, then runs the search in-page (only use when user says 'open')",
        "play_media          query          # play a song or video on YouTube",
        "pause_media                        # pause currently playing media",
        "resume_media                       # resume paused media",
        "volume_control      direction      # direction in: up, down, mute, unmute, max",
        "set_browser         which          # which in: chrome, brave",
        "phone_screenshot                   # screenshot on connected phone",
        "file_list           path           # list a directory's contents",
        "file_read           path           # read a text file (first 5KB)",
        "get_clipboard                      # read current clipboard text",
        "get_window                         # info on the focused window",
        "calculate           expression     # math, e.g. '23*45 + sqrt(81)'",
        "weather_fetch       location       # current weather for a city",
        "web_scrape          url            # fetch + summarize a webpage",
        "note_create         title, content # save a note to Ultron's note store",
        "memory_fetch        query          # recall stored knowledge by query",
        "git_status          path           # git status on a repo path",
        # ── High-risk (require user confirmation on next turn) ────────────────
        "delete_file         path           # delete a single file (CONFIRM)",
        "delete_folder       path           # delete a folder recursively (CONFIRM)",
        "run_command         command        # run a shell command (CONFIRM)",
        "run_code            code           # run Python code in a sandbox (CONFIRM)",
        "send_email          to, subject, body              # send email via Gmail (CONFIRM)",
        "type_text           text           # type a string on the active window (CONFIRM)",
        "click               x, y           # mouse click at coords (CONFIRM)",
        "press_key           key            # press a single key (CONFIRM)",
        "hotkey              keys           # press a key combo like 'ctrl+s' (CONFIRM)",
        "file_write          path, content  # overwrite or create a file (CONFIRM)",
        "create_file         path, content  # write a new file (CONFIRM)",
        "append_file         path, content  # append to existing file (CONFIRM)",
        "rename_file         src, new_name  # rename a file (CONFIRM)",
        "move_file           src, dest      # move a file (CONFIRM)",
        "copy_file           src, dest      # copy a file (CONFIRM)",
        "zip_folder          src, output    # zip a folder (CONFIRM)",
        "set_clipboard       text           # write to the clipboard (CONFIRM)",
    ]
    manifest = "\n".join("  - " + L for L in manifest_lines)

    system = (
        "You are Ultron's strict JSON intent router. Your ONLY job is to map a "
        "user's free-form request to one of the listed actions. "
        "Output exactly one JSON object and nothing else — no prose, no code "
        "fence. Use null when no action fits."
    )
    _user_home = os.path.expanduser("~")
    prompt = (
        f"User said: {text!r}\n\n"
        f"Available actions:\n{manifest}\n\n"
        "Respond with this exact JSON shape:\n"
        '  {"action": "<action_name>", "params": ["<arg1>", "<arg2>"]}\n'
        '  or {"action": null} if no action above fits.\n'
        "Rules:\n"
        " - Use exactly the action_name as written above (snake_case).\n"
        " - params must be a JSON array of strings, in the order shown after the # comment.\n"
        " - Never invent an action that isn't in the list.\n"
        " - For questions, small talk, or descriptive requests, return null.\n"
        f" - This system runs Linux. Use Linux paths only (e.g. {_user_home}/Desktop/file.txt).\n"
        f"   NEVER use Windows paths like C:\\\\Users\\\\... — the home directory is {_user_home}.\n"
        f"   'Desktop' = {_user_home}/Desktop, 'Documents' = {_user_home}/Documents, "
        f"'Downloads' = {_user_home}/Downloads."
    )

    try:
        raw = call_llm_batch(prompt, system=system, provider="groq")
    except Exception:
        return None
    if not raw:
        return None

    s = raw.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:].lstrip()
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return None

    action = obj.get("action")
    if not action or not isinstance(action, str):
        return None
    action = _LLM_ACTION_SYNONYMS.get(action.lower(), action.lower())
    if action not in _LLM_ALLOWED_ACTIONS:
        return None

    raw_params = obj.get("params") or []
    if not isinstance(raw_params, list):
        raw_params = [raw_params]
    params = [str(p) for p in raw_params if p is not None]

    return {
        "type":       action,
        "params":     params,
        "confidence": 0.75,
        "raw":        text,
        "match":      text,
        "source":     "llm_pick",
    }


# =============================================================================
# FILE SYSTEM ACTIONS
# =============================================================================

def create_folder(path_or_name: str, parent: str = None) -> Dict:
    """Create a folder. Opens it in Explorer after creation."""
    try:
        # Resolve path
        if os.path.isabs(path_or_name):
            folder_path = path_or_name
        elif parent:
            folder_path = os.path.join(parent, path_or_name)
        else:
            # Default: Desktop
            desktop = Path.home() / "Desktop"
            folder_path = str(desktop / path_or_name)

        os.makedirs(folder_path, exist_ok=True)

        # Open it in Explorer
        if platform.system() == "Windows":
            subprocess.Popen(f'explorer "{folder_path}"')
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", folder_path])
        else:
            subprocess.Popen(["xdg-open", folder_path])

        return {
            "success": True,
            "path":    folder_path,
            "message": f"Folder created and opened: {folder_path}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def open_folder(path: str) -> Dict:
    """Open a folder in File Explorer."""
    try:
        # Try to resolve common shortcuts
        path = path.strip()
        if path.lower() in ("desktop", "the desktop"):
            path = str(Path.home() / "Desktop")
        elif path.lower() in ("downloads", "download"):
            path = str(Path.home() / "Downloads")
        elif path.lower() in ("documents", "docs"):
            path = str(Path.home() / "Documents")
        elif path.lower() == "pictures":
            path = str(Path.home() / "Pictures")
        elif path.lower() == "music":
            path = str(Path.home() / "Music")
        elif path.lower() in ("videos", "video"):
            path = str(Path.home() / "Videos")
        elif not os.path.isabs(path):
            # Search workspace
            workspace_path = os.path.join(_WORK_DIR, path)
            if os.path.exists(workspace_path):
                path = workspace_path
            else:
                desktop_path = str(Path.home() / "Desktop" / path)
                if os.path.exists(desktop_path):
                    path = desktop_path

        if platform.system() == "Windows":
            subprocess.Popen(f'explorer "{path}"')
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

        return {"success": True, "path": path, "message": f"Opened: {path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def create_file_on_disk(filename: str, content: str = "", folder: str = None) -> Dict:
    """Create a file with content and open it."""
    try:
        if folder:
            os.makedirs(folder, exist_ok=True)
            filepath = os.path.join(folder, filename)
        else:
            filepath = os.path.join(_WORK_DIR, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        return {"success": True, "path": filepath, "message": f"File created: {filepath}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ProjectBuilder, PhoneBridge, handle_build_answers, save_and_run_from_clipboard,
# _active_builders — all imported from code_tasks.py and phone_tasks.py above.


# =============================================================================
# MAIN ORCHESTRATOR
# =============================================================================

_phone = PhoneBridge()


def orchestrate(text: str, session_id: str = "default") -> Dict[str, Any]:
    """
    Main entry point. Call this with ANY voice/text command.
    Returns: {
        success, message, action_taken, data, needs_input, questions
    }
    """
    # ── Confirmation handshake (highest priority) ────────────────────────────
    # If the user has a pending high-risk action and replies with yes/cancel,
    # resolve it BEFORE classify_task interprets the reply.
    pending = _PENDING_CONFIRM.get(session_id)
    if pending:
        if _matches_phrase(text, _CONFIRM_PHRASES):
            _PENDING_CONFIRM.pop(session_id, None)
            return _dispatch_via_action_engine(pending["type"], pending["params_dict"])
        if _matches_phrase(text, _CANCEL_PHRASES):
            _PENDING_CONFIRM.pop(session_id, None)
            return {
                "success":      True,
                "action_taken": "cancelled",
                "message":      "Cancelled. Nothing was changed.",
                "passthrough":  False,
            }
        # User said something else — drop the pending and process normally.
        _PENDING_CONFIRM.pop(session_id, None)

    task = classify_task(text)
    t    = task["type"]

    # ── Question-shaped commands are usually NOT commands ─────────────────────
    # classify_task's regex `open (.+)` happily matches "open the file you
    # just created?" — but the trailing "?" plus a contextual reference word
    # ("you" / "that" / "it" / ...) means the user is asking a conversational
    # question, not issuing an action. Demote to passthrough so /ask's LLM
    # path answers it instead of dispatching `open_app("the file you just
    # created?")` which can only ever fail.
    if t != "ai_chat" and text.rstrip().endswith("?"):
        _tl = text.lower()
        _parts = re.split(r"\W+", _tl)
        try:
            if any(p in _CONTEXTUAL_REFERENCE_WORDS for p in _parts):
                return {
                    "success":      True,
                    "action_taken": "ai_chat",
                    "passthrough":  True,
                    "message":      "",
                }
        except NameError:
            # _CONTEXTUAL_REFERENCE_WORDS defined inside _likely_command's
            # module scope; if for any reason it's not in scope here, silently
            # skip the demotion. The picker safety guard above still applies.
            pass

    # ── JARVIS intelligence layer ────────────────────────────────────────────
    # When the regex layer didn't match anything actionable AND the request
    # *looks* like a command (cheap heuristic), let the LLM pick from the
    # whitelisted action manifest. Fail-soft: any error falls through to
    # normal AI chat so we never regress conversational latency.
    if t == "ai_chat" and _likely_command(text):
        picked = _llm_pick_action(text)
        if picked:
            pt = picked["type"]
            pkw = _llm_params_to_kwargs(pt, picked["params"])
            # Safety: never stage a destructive shell command. The picker
            # hallucinated "close X" → `rm X` once already (ok.txt session
            # 2026-05-17); the only correct mapping for "close X" is a
            # window-close, not a file delete. Refuse and let /ask answer
            # conversationally so the user can clarify intent.
            if pt == "run_command" and _is_destructive_shell(pkw.get("command", "")):
                return {
                    "success":      False,
                    "action_taken": "blocked_destructive_command",
                    "message":      (
                        f"Refusing to run a destructive shell command: "
                        f"{pkw.get('command','?')!r}. If you meant to close "
                        f"a window, say 'close window' / 'close tab'. If you "
                        f"really want to delete the file, say 'delete <path>' "
                        f"and I'll stage that with confirmation."
                    ),
                    "passthrough":  False,
                }
            if pt in _LLM_HIGH_RISK_ACTIONS:
                # File-write actions (create_file, file_write, append_file) are
                # auto-executed when the destination is inside the user's home
                # tree (Desktop, Documents, Downloads, home itself).  Destructive
                # or system-path operations still require explicit confirmation.
                _auto_exec = False
                if pt in ("create_file", "file_write", "append_file"):
                    _dest = (pkw.get("path") or (picked["params"][0] if picked["params"] else ""))
                    if _dest:
                        try:
                            from action_engine import _resolve_path as _rp
                            _dest_abs = os.path.realpath(os.path.expanduser(_rp(_dest)))
                            _home_abs = os.path.realpath(os.path.expanduser("~"))
                            _auto_exec = _dest_abs.startswith(_home_abs + os.sep) or _dest_abs == _home_abs
                        except Exception:
                            pass

                if _auto_exec:
                    return _dispatch_via_action_engine(pt, pkw)

                # All other high-risk actions: stage and ask.
                _PENDING_CONFIRM[session_id] = {
                    "type":        pt,
                    "params":      picked["params"],
                    "params_dict": pkw,
                    "raw":         text,
                }
                return {
                    "success":      True,
                    "action_taken": "confirmation_needed",
                    "message":      f"I'd run {_human_summary(pt, pkw)}. Say 'yes' or 'cancel' to decide.",
                    "passthrough":  False,
                    "pending":      pt,
                }
            # Safe — dispatch via action_engine if no regex-branch handles it.
            if pt in _LLM_SAFE_ACTIONS and pt not in TASK_PATTERNS and pt != "take_screenshot":
                return _dispatch_via_action_engine(pt, pkw)
            # Otherwise continue into the existing regex-branch chain.
            task = picked
            t    = pt

    # ── File system ──────────────────────────────────────────────────────────
    if t == "create_folder":
        name = task["params"][-1] if task["params"] else "New Folder"
        return {**create_folder(name), "action_taken": "create_folder"}

    if t == "open_folder":
        name = task["params"][-1] if task["params"] else ""
        return {**open_folder(name), "action_taken": "open_folder"}

    if t == "take_screenshot":
        try:
            from computer_control import take_screenshot
            # Extract an explicit save path from the raw command if the user said
            # "take a screenshot and save it to ~/Documents" or similar.
            _raw_text = task.get("raw", "")
            _save_path = None
            _path_m = re.search(
                r"(?:save|store|put)\s+(?:it\s+)?(?:to|on|in|at|into)\s+(.+?)(?:\s*$|\s+and\b)",
                _raw_text, re.IGNORECASE,
            )
            if _path_m:
                _save_path = _path_m.group(1).strip().strip('"\'')
            result = take_screenshot(prompt_save=False, save_path=_save_path)
            result["action_taken"] = "screenshot"
            if not result.get("message"):
                if result.get("success") and result.get("path"):
                    result["message"] = f"Screenshot saved to {result['path']}"
                elif not result.get("success"):
                    result["message"] = f"Screenshot failed: {result.get('error', 'unknown error')}"
            # Record so "open the screenshot" / "open it" resolves to this file.
            if result.get("success") and result.get("path"):
                _record_last_output(session_id, "screenshot", result["path"], kind="image")
            return result
        except Exception as e:
            return {"success": False, "error": str(e), "action_taken": "screenshot",
                    "message": f"Screenshot failed: {e}"}

    # ── Search on a specific site (must come before open_app) ────────────────
    # CLOUD-ONLY by design — uses Tavily (with site-scoping) so no browser
    # pops up unless the user explicitly says "open <site> and search …",
    # which routes to `open_and_search` below.
    if t == "search_on_site":
        return handle_search_on_site(task)

    if t == "open_and_search":
        return handle_open_and_search(task)

    # ── Open browser and play on YouTube ────────────────────────────────────
    if t == "open_and_play":
        browser = (task["params"][0] if task["params"] else "").strip().lower()
        query   = (task["params"][1] if len(task["params"]) > 1 else "").strip()
        if not query:
            # Fallback: parse from raw text
            raw = task.get("raw", "")
            m = re.search(r"(?:play|watch|listen\s+to)\s+(.+)$", raw, re.IGNORECASE)
            query = m.group(1).strip() if m else raw
        result = _youtube_play(query, browser=browser)
        result["query"] = query
        return result

    # ── App / file / site launching ──────────────────────────────────────────
    # The captured token after "open" can describe any of: a file on disk, a
    # folder, a known website (optionally with a browser hint), a YouTube
    # search-and-play, or an installed application. Resolve in that order so
    # specific targets win over the generic app fallback.
    if t == "open_app":
        app_name  = task["params"][-1] if task["params"] else ""
        # Strip trailing punctuation that snuck in from a casual typing
        # ("open chrome?" / "open notepad!") — these never belong in an app
        # name, app/file/site lookups, or display strings.
        app_name  = app_name.rstrip(" .,!?;:")
        app_lower = app_name.lower()
        # Full utterance carries the browser hint and the play tail, which the
        # captured app_name may have lost depending on which pattern matched.
        full_text = (task.get("raw") or task.get("match") or app_name).strip()

        # ── 1. File on disk ──────────────────────────────────────────────
        file_path = _resolve_file_target(app_name)
        if file_path:
            try:
                _xdg_open(file_path)
                return {
                    "success": True,
                    "action_taken": "open_file",
                    "message": f"Opened {os.path.basename(file_path)}",
                    "path": file_path,
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "action_taken": "open_file",
                    "message": f"Failed to open {os.path.basename(file_path)}: {e}",
                }

        # ── 2. Folder on disk ────────────────────────────────────────────
        folder_path = _resolve_folder_target(app_name)
        if folder_path:
            try:
                _xdg_open(folder_path)
                return {
                    "success": True,
                    "action_taken": "open_folder",
                    "message": f"Opened {os.path.basename(folder_path) or folder_path}",
                    "path": folder_path,
                }
            except Exception as e:
                return {"success": False, "error": str(e),
                        "action_taken": "open_folder"}

        # ── 3. YouTube play (any browser) ────────────────────────────────
        # Triggers when the utterance names YouTube *and* expresses intent to
        # play/watch/listen. Browser preference is parsed from the same
        # utterance; falls back to default.
        has_youtube  = "youtube" in app_lower or "youtube" in full_text.lower()
        wants_play   = bool(re.search(
            r"\b(play(?:ing)?|sing(?:ing)?|listen|put\s+on|watch(?:ing)?|song|video)\b",
            full_text.lower(),
        ))
        if has_youtube and wants_play:
            query = _extract_play_query(full_text)
            if query:
                browser = _detect_browser_hint(full_text)
                result  = _youtube_play(query, browser=browser)
                result["query"] = query
                return result

        # ── 4. Known site (optionally with browser hint) ─────────────────
        site_url = _resolve_site(app_name) or _resolve_site(full_text)
        if site_url:
            browser = _detect_browser_hint(full_text)
            try:
                used = _launch_browser(site_url, browser=browser)
                return {
                    "success": True,
                    "action_taken": "open_url",
                    "message": f"Opened {site_url} in {used}",
                    "url": site_url,
                    "browser": used,
                }
            except Exception as e:
                return {"success": False, "error": str(e),
                        "action_taken": "open_url"}

        # ── 5. Installed application (existing behavior) ────────────────
        try:
            from computer_control import open_app
            result = open_app(app_name)
            result["action_taken"] = "open_app"
            # Ensure failure messages are visible to the UI message fallback.
            if not result.get("success") and not result.get("message"):
                result["message"] = (
                    f"Couldn't open '{app_name}': "
                    f"{result.get('error', 'not found as an app, file, folder, or known site')}"
                )
            return result
        except Exception as e:
            return {"success": False, "error": str(e), "action_taken": "open_app",
                    "message": f"Open failed: {e}"}

    # ── Web search — context-aware routing ───────────────────────────────────
    # If a browser window is currently focused, send the query directly to its
    # address bar (Ctrl+L, type, Enter) so the search happens IN that browser.
    # Otherwise (Ultron focused, no browser, terminal, etc.) fall back to a
    # cloud search via Tavily and return the result text.
    if t == "search_web":
        query = task["params"][-1] if task["params"] else text
        if isinstance(query, tuple):
            query = next((q for q in query if q), text)
        query = (query or "").strip()
        # Browser-hijack path (Ctrl+L → type → Enter into the active browser)
        # only fires when the user EXPLICITLY asked for browser/google/web
        # search. Earlier this hijack ran whenever the focused window was a
        # browser, which meant questions like "who is the CM of Telangana"
        # — typed via voice while Brave happened to be the focused window —
        # silently grabbed the user's tab and ran a Google search instead of
        # answering. Voice info-questions ("who is", "what is", etc.) now
        # fall through to the cloud-summary path.
        text_l = (text or "").lower()
        wants_browser = any(p in text_l for p in (
            "in browser", "in chrome", "in brave", "in firefox", "in edge",
            "open browser and search", "on google", "in google", "google search for",
        ))
        if wants_browser and query:
            try:
                from computer_control import get_active_window, hotkey, type_text, press_key
                win = get_active_window() or {}
                title = (win.get("title") or "").lower()
                wclass = (win.get("class") or "").lower()
                _browser_signals = (
                    "chrome", "brave", "firefox", "edge", "chromium", "opera",
                    "google-chrome", "brave-browser",
                )
                is_browser = any(s in title or s in wclass for s in _browser_signals)
                if is_browser:
                    hotkey("ctrl", "l")
                    import time as _t; _t.sleep(0.12)
                    type_text(query, interval=0.0)
                    _t.sleep(0.05)
                    press_key("enter")
                    return {
                        "success": True, "action_taken": "browser_search",
                        "message": f"Searching {title.split(' - ')[-1] or 'browser'} for '{query}'.",
                    }
            except Exception:
                pass
        # Default: cloud summary via Tavily — no browser hijack.
        return handle_search_web(task, text)

    if t == "open_url":
        return handle_open_url(task, text)

    # ── Ask Claude ───────────────────────────────────────────────────────────
    if t == "ask_claude":
        query = task["params"][-1] if task["params"] else text
        webbrowser.open("https://claude.ai/new")
        if CLIP_AVAILABLE:
            pyperclip.copy(query)
        return {
            "success":      True,
            "action_taken": "ask_claude",
            "message":      "Claude.ai opened! Your query was copied to clipboard.",
        }

    # ── Run code ─────────────────────────────────────────────────────────────
    if t == "run_code":
        file_param = task["params"][-1] if task["params"] else ""
        filepath   = None
        # Look in workspace
        if file_param:
            candidates = [
                file_param,
                os.path.join(_WORK_DIR, file_param),
            ]
            for c in candidates:
                if os.path.exists(c):
                    filepath = c
                    break
        if filepath:
            # Phase 7.4 — quote filepath; LLM-resolved paths can carry
            # spaces / metacharacters even though we validate existence.
            import shlex
            subprocess.Popen(
                f'start cmd /k "python {shlex.quote(filepath)}"',
                shell=True,
                cwd=os.path.dirname(filepath),
            )
            return {
                "success":      True,
                "action_taken": "run_code",
                "message":      f"Running {filepath}!",
            }
        return {"success": False, "error": "Could not find the file to run.", "action_taken": "run_code"}

    # ── Build project ────────────────────────────────────────────────────────
    if t == "build_project":
        # Extract project type from the text
        project_type = "app"
        for ptype in ["game", "app", "website", "bot", "script", "tool", "program"]:
            if ptype in text.lower():
                project_type = ptype
                break

        builder = ProjectBuilder(project_type=project_type, description=text)
        _active_builders[session_id] = builder

        questions = builder.get_questions()

        return {
            "success":      True,
            "action_taken": "build_project_start",
            "message":      (
                f"Great! I'll help you build {text}. "
                f"First, I need to understand what you want. "
                f"Answer these questions and I'll prepare everything for Claude:"
            ),
            "needs_input":  True,
            "questions":    questions,
            "session_id":   session_id,
            "project_name": builder.project_name,
        }

    # ── Phone control ────────────────────────────────────────────────────────
    if t == "phone_screenshot":
        if _phone.is_connected():
            result = _phone.take_screenshot()
        else:
            result = {
                "success": False,
                "error":   "Phone not connected via ADB. Connect with USB and run: adb devices",
            }
        result["action_taken"] = "phone_screenshot"
        return result

    if t == "phone_open_app":
        app_name = task["params"][-1] if task["params"] else ""
        if _phone.is_connected():
            result = _phone.open_app(app_name)
        else:
            result = {"success": False, "error": "Phone not connected via ADB"}
        result["action_taken"] = "phone_open_app"
        return result

    # ── Browser preference ────────────────────────────────────────────────────
    if t == "set_browser":
        return handle_set_browser(task["params"])

    # ── Media playback ───────────────────────────────────────────────────────
    if t == "play_media":
        _MEDIA_STATE[session_id] = "playing"   # explicit play sets known state
        return handle_play_media(text, task["params"])

    if t in ("pause_media", "resume_media"):
        # YouTube `k` is a toggle, not a directional command. We track our
        # intent so re-issuing the same command doesn't invert reality —
        # BUT only when we're confident the tracked state still matches
        # what's on screen. After a skip / prev / new-play the video state
        # is set by autoplay, so older tracking is stale and we trust the
        # user instead of lying with "Already paused".
        want = "paused" if t == "pause_media" else "playing"
        cur  = _MEDIA_STATE.get(session_id)
        stale = _MEDIA_STATE.get(session_id + ":stale", False)
        if cur == want and not stale:
            label = "paused" if want == "paused" else "playing"
            return {"success": True, "action_taken": f"{t}_noop",
                    "message": f"Already {label}.", "passthrough": False}
        r = handle_pause_resume_media(t)
        if r.get("success"):
            _MEDIA_STATE[session_id] = want
            _MEDIA_STATE.pop(session_id + ":stale", None)
        return r

    if t == "media_next":
        # Autoplay starts the next video → known state is "playing".
        # Without this reset, the next "pause" command sees stale state
        # and lies ("Already paused") instead of pausing.
        _MEDIA_STATE[session_id] = "playing"
        _MEDIA_STATE.pop(session_id + ":stale", None)
        return handle_media_next()

    if t == "media_prev":
        _MEDIA_STATE[session_id] = "playing"
        _MEDIA_STATE.pop(session_id + ":stale", None)
        return handle_media_prev()

    if t == "volume_control":
        return handle_volume_control(task, text)

    # ── App/system controls ──────────────────────────────────────────────────
    # ── Clipboard primitives (system hotkeys to whatever has focus) ─────────
    if t in ("copy_selection", "paste_clipboard", "cut_selection", "select_all"):
        from computer_control import hotkey
        _keymap = {
            "copy_selection":  ("c", "Copied."),
            "paste_clipboard": ("v", "Pasted."),
            "cut_selection":   ("x", "Cut."),
            "select_all":      ("a", "Selected all."),
        }
        key, msg = _keymap[t]
        r = hotkey("ctrl", key)
        if r.get("success"):
            return {"success": True, "action_taken": t, "message": msg}
        return {"success": False, "action_taken": t,
                "message": f"Couldn't run Ctrl+{key.upper()}: {r.get('error','unknown error')}"}

    # ── Close a browser/editor tab (Ctrl+W) ──────────────────────────────────
    if t == "close_tab":
        from intent_router import _focus_window
        from computer_control import hotkey
        # Identify browser hint and target from the captured groups (any order).
        _browsers = {"brave", "chrome", "firefox", "edge", "chromium"}
        browser = None
        target  = None
        for p in (task.get("params") or []):
            if not p:
                continue
            pl = p.strip().lower()
            if pl in _browsers:
                browser = pl
            else:
                target = p.strip()
        # If a browser was named, focus it first so Ctrl+W lands in the right window.
        focus_msg = ""
        if browser:
            f = _focus_window(browser)
            if not f.get("success"):
                focus_msg = f" (couldn't focus {browser})"
        r = hotkey("ctrl", "w")
        if r.get("success"):
            label = f"{target} tab" if target else "the tab"
            return {"success": True, "action_taken": "close_tab",
                    "message": f"Closed {label}.{focus_msg}"}
        return {"success": False, "action_taken": "close_tab",
                "message": f"Couldn't close tab: {r.get('error','unknown error')}"}

    # ── Close the active window (Alt+F4 / wmctrl) ────────────────────────────
    if t == "close_window":
        from intent_router import _focus_window
        from computer_control import hotkey
        target = (task.get("params") or [None])[0]
        if target:
            f = _focus_window(target.strip())
            if not f.get("success"):
                return {"success": False, "action_taken": "close_window",
                        "message": f"No '{target}' window to close."}
        r = hotkey("alt", "f4")
        if r.get("success"):
            return {"success": True, "action_taken": "close_window",
                    "message": f"Closed {target} window." if target else "Window closed."}
        return {"success": False, "action_taken": "close_window",
                "message": f"Couldn't close window: {r.get('error','unknown error')}"}

    # ── Switch / focus an open window ────────────────────────────────────────
    if t == "focus_window":
        from intent_router import _focus_window
        name = (task.get("params") or [""])[0].strip()
        if not name:
            return {"success": False, "action_taken": "focus_window",
                    "message": "Switch to which window?"}
        r = _focus_window(name)
        if r.get("success"):
            return {"success": True, "action_taken": "focus_window",
                    "message": f"Switched to {name}."}
        return {"success": False, "action_taken": "focus_window",
                "message": f"No '{name}' window found."}

    # ── Open the most-recent file produced by a previous tool ────────────────
    if t == "open_recent":
        last = _LAST_ACTION_OUTPUT.get(session_id)
        if not last or not last.get("path"):
            return {"success": False, "action_taken": "open_recent",
                    "message": "I don't have a recent file to open — name one and I'll open it."}
        path = last["path"]
        if not os.path.exists(path):
            return {"success": False, "action_taken": "open_recent",
                    "message": f"The last {last.get('kind','file')} ({os.path.basename(path)}) is gone — was it deleted?"}
        try:
            _xdg_open(path)
            return {"success": True, "action_taken": "open_recent",
                    "message": f"Opening {os.path.basename(path)}."}
        except Exception as e:
            return {"success": False, "action_taken": "open_recent",
                    "message": f"Couldn't open {os.path.basename(path)}: {e}"}

    if t == "close_app":
        from intent_router import _close_app
        name = (task["params"][0] if task["params"] else text).strip()
        # Re-route obviously-tab-shaped requests that slipped past the regex
        # (e.g. LLM picker hands us close_app("youtube tab")). Maps to Ctrl+W.
        _ntl = name.lower()
        if (_ntl.endswith(" tab") or _ntl == "tab"
            or _ntl in {"youtube", "gmail", "github", "twitter", "reddit",
                        "google", "stackoverflow", "whatsapp", "chatgpt",
                        "claude", "x.com", "x"}):
            from intent_router import _focus_window
            from computer_control import hotkey
            # If "X tab" form, X might be a browser — try focusing it first.
            stripped = re.sub(r"\s+tab$", "", name, flags=re.IGNORECASE).strip()
            if stripped.lower() in {"brave", "chrome", "firefox", "edge", "chromium"}:
                _focus_window(stripped)
            r = hotkey("ctrl", "w")
            label = stripped if stripped else "the tab"
            if r.get("success"):
                return {"success": True, "action_taken": "close_tab",
                        "message": f"Closed {label} tab."}
            return {"success": False, "action_taken": "close_tab",
                    "message": f"Couldn't close tab: {r.get('error','unknown error')}"}
        return _close_app(name)

    if t == "lock_screen":
        from intent_router import _lock_screen
        return _lock_screen()

    if t == "sleep_computer":
        from intent_router import _sleep_computer
        return _sleep_computer()

    if t == "empty_trash":
        from intent_router import _empty_trash
        return _empty_trash()

    if t == "system_info":
        from intent_router import _system_info
        return _system_info()

    if t == "brightness_up":
        from intent_router import _brightness_ctrl
        return _brightness_ctrl("up")

    if t == "brightness_down":
        from intent_router import _brightness_ctrl
        return _brightness_ctrl("down")

    # ── Default: AI chat ─────────────────────────────────────────────────────
    return {
        "success":      True,
        "action_taken": "ai_chat",
        "message":      None,   # let normal LLM handle it
        "passthrough":  True,
    }


# handle_build_answers and save_and_run_from_clipboard are imported from code_tasks.py
