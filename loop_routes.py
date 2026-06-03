"""
loop_routes.py - Flask blueprint for the Claude.ai loop / visual verify /
self-modify / app-control / full-loop routes.

Extracted from app.py during the Task 2 blueprint split. Behavior is byte-for-byte
identical to the original handlers; only the decorator changed from @app.route
to @loop_bp.route.

Routes (23 total):
  /claude_loop/status            GET   - session status
  /claude_loop/login             POST  - manual Claude.ai login
  /claude_loop/ask               POST  - ask + get reply
  /claude_loop/get_code          POST  - ask + return first code block
  /claude_loop/clear_session     POST  - drop saved session
  /claude_loop/log               GET   - recent loop activity log
  /verify/screenshot             POST  - labeled screenshot
  /verify/diff                   POST  - pixel/LLM diff
  /verify/check_url              POST  - before/after URL screenshots
  /verify/log                    GET   - visual verify log
  /self_modify/status            GET   - status + backup list
  /self_modify/improve           POST  - full self-improvement pipeline
  /self_modify/patch             POST  - direct patch
  /self_modify/rollback          POST  - rollback last patch
  /self_modify/backups           GET   - list backups
  /self_modify/log               GET   - patch log
  /app_control/status            GET   - app control engine status
  /app_control/windows           GET   - list open windows
  /app_control/focus             POST  - focus a window
  /app_control/action            POST  - run any app control action
  /app_control/chrome            POST  - chrome shortcut
  /app_control/vscode            POST  - vscode shortcut
  /full_loop                     POST  - 5-step autonomous loop
"""

import os
from flask import Blueprint, request, jsonify

# ── Claude.ai loop (optional) ──────────────────────────────────────────────────
try:
    from claude_loop import (
        ask_claude_ai, ask_and_get_code, get_session_status,
        clear_session, do_manual_login, has_saved_session,
        extract_code_blocks, get_loop_log,
    )
    CLAUDE_LOOP_AVAILABLE = True
except ImportError:
    CLAUDE_LOOP_AVAILABLE = False
    def ask_claude_ai(prompt, **kw): return {"success": False, "error": "claude_loop not available"}
    def ask_and_get_code(prompt): return {"success": False, "error": "claude_loop not available"}
    def get_session_status(): return {"has_session": False}
    def clear_session(): return {"success": False}
    def do_manual_login(): return {"success": False, "error": "claude_loop not available"}
    def has_saved_session(): return False
    def get_loop_log(limit=30): return []

# ── Visual verify (optional) ───────────────────────────────────────────────────
try:
    from visual_verify import (
        verify_ui_change, verify_code_patch, take_labeled_screenshot,
        quick_screenshot_diff, pixel_diff, llm_diff_analysis,
        capture_url_screenshot, get_verify_log,
    )
    VISUAL_VERIFY_AVAILABLE = True
except ImportError:
    VISUAL_VERIFY_AVAILABLE = False
    def take_labeled_screenshot(label="screen"): return {"success": False, "error": "visual_verify not available"}
    def verify_code_patch(url, desc=""): return {"success": False, "error": "visual_verify not available"}
    def pixel_diff(before, after): return {"changed": False}
    def llm_diff_analysis(before, after, desc): return None
    def get_verify_log(limit=30): return []

# ── Self-modify (optional) ─────────────────────────────────────────────────────
try:
    from self_modify import (
        self_improve, patch_file_direct, rollback,
        get_self_modify_status, list_backups, get_patch_log,
    )
    SELF_MODIFY_AVAILABLE = True
except ImportError:
    SELF_MODIFY_AVAILABLE = False
    def self_improve(req, **kw): return {"success": False, "error": "self_modify not available"}
    def patch_file_direct(fname, code): return {"success": False, "error": "self_modify not available"}
    def rollback(fname): return {"success": False, "error": "self_modify not available"}
    def get_self_modify_status(): return {}
    def list_backups(): return []
    def get_patch_log(limit=30): return []

# ── App control (optional) ─────────────────────────────────────────────────────
try:
    from app_control import (
        control_app, get_app_control_status, list_windows,
        focus_window,
    )
    APP_CONTROL_AVAILABLE = True
except ImportError:
    APP_CONTROL_AVAILABLE = False
    def control_app(action, params=None): return {"success": False, "error": "app_control not available"}
    def get_app_control_status(): return {}
    def list_windows(): return []
    def focus_window(title): return {"success": False, "error": "app_control not available"}


loop_bp = Blueprint("loop", __name__)


# =============================================================================
# CLAUDE.AI LOOP ROUTES — /claude_loop/*
# Full autonomous Claude.ai interaction: login -> prompt -> read reply -> extract code
# =============================================================================

@loop_bp.route("/claude_loop/status", methods=["GET"])
def claude_loop_status():
    """Check Claude.ai loop session status."""
    status = get_session_status()
    status["module_available"] = CLAUDE_LOOP_AVAILABLE
    return jsonify(status)


@loop_bp.route("/claude_loop/login", methods=["POST"])
def claude_loop_login():
    """
    Open a visible browser window for manual Claude.ai login.
    Call this once - session is saved and reused automatically after.
    """
    if not CLAUDE_LOOP_AVAILABLE:
        return jsonify({"success": False, "error": "claude_loop module not available"})
    result = do_manual_login()
    return jsonify(result)


@loop_bp.route("/claude_loop/ask", methods=["POST"])
def claude_loop_ask():
    """
    Send a prompt to Claude.ai and get the full reply + extracted code.
    Body: {"prompt": "...", "headless": true}
    """
    if not CLAUDE_LOOP_AVAILABLE:
        return jsonify({"success": False, "error": "claude_loop module not available"})

    data   = request.json or {}
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"success": False, "error": "prompt is required"})

    headless = bool(data.get("headless", True))
    result = ask_claude_ai(prompt, headless=headless)
    return jsonify(result)


@loop_bp.route("/claude_loop/get_code", methods=["POST"])
def claude_loop_get_code():
    """
    Ask Claude.ai and return only the first extracted code block.
    Body: {"prompt": "..."}
    """
    if not CLAUDE_LOOP_AVAILABLE:
        return jsonify({"success": False, "error": "claude_loop module not available"})

    data   = request.json or {}
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"success": False, "error": "prompt is required"})

    result = ask_and_get_code(prompt)
    return jsonify(result)


@loop_bp.route("/claude_loop/clear_session", methods=["POST"])
def claude_loop_clear_session():
    """Clear saved Claude.ai session (force re-login next time)."""
    return jsonify(clear_session())


@loop_bp.route("/claude_loop/log", methods=["GET"])
def claude_loop_log():
    """Get recent Claude.ai loop activity log."""
    limit = int(request.args.get("limit", 30))
    return jsonify({"log": get_loop_log(limit)})


# =============================================================================
# VISUAL VERIFICATION ROUTES — /verify/*
# Before/after screenshots + vision LLM diff analysis
# =============================================================================

@loop_bp.route("/verify/screenshot", methods=["POST"])
def verify_screenshot():
    """
    Take a labeled screenshot and return path + base64.
    Body: {"label": "before_patch"}

    Phase 5 hardening: take_labeled_screenshot can raise (gnome-screenshot
    binary not installed, headless display, X server refused, etc.).
    Catch and surface as 503 instead of letting an uncaught exception
    bubble up as a 500 stack-trace.
    """
    if not VISUAL_VERIFY_AVAILABLE:
        return jsonify({"success": False, "error": "visual_verify module not available"}), 503
    label = (request.json or {}).get("label", "manual")
    try:
        result = take_labeled_screenshot(label)
    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"screenshot capture failed: {e}",
            "hint":  "missing gnome-screenshot binary, no X display, or wrong Pillow version",
        }), 503
    return jsonify(result)


@loop_bp.route("/verify/diff", methods=["POST"])
def verify_diff():
    """
    Compare two screenshot files (pixel diff + optional LLM analysis).
    Body: {"before": "/path/to/before.png", "after": "/path/to/after.png", "use_llm": true}
    """
    if not VISUAL_VERIFY_AVAILABLE:
        return jsonify({"success": False, "error": "visual_verify module not available"})

    data   = request.json or {}
    before = data.get("before", "")
    after  = data.get("after", "")
    if not before or not after:
        return jsonify({"success": False, "error": "before and after paths required"})

    diff = pixel_diff(before, after)
    llm_result = None
    if data.get("use_llm", False) and diff.get("changed"):
        desc = data.get("description", "UI change")
        llm_result = llm_diff_analysis(before, after, desc)

    return jsonify({
        "diff": diff,
        "llm": llm_result,
    })


@loop_bp.route("/verify/check_url", methods=["POST"])
def verify_check_url():
    """
    Take before + after screenshots of a URL and compare.
    Body: {"url": "http://localhost:5000", "wait": 3, "description": "patch applied"}
    """
    if not VISUAL_VERIFY_AVAILABLE:
        return jsonify({"success": False, "error": "visual_verify module not available"})

    data  = request.json or {}
    url   = data.get("url", "http://localhost:5000")
    wait  = float(data.get("wait", 3.0))
    desc  = data.get("description", "UI change")

    result = verify_code_patch(url, desc)
    return jsonify(result)


@loop_bp.route("/verify/log", methods=["GET"])
def verify_log():
    """Get recent visual verification log."""
    limit = int(request.args.get("limit", 30))
    return jsonify({"log": get_verify_log(limit)})


# =============================================================================
# SELF-MODIFICATION ROUTES — /self_modify/*
# Ultron patches its own code, reloads, verifies the change
# =============================================================================

@loop_bp.route("/self_modify/status", methods=["GET"])
def self_modify_status():
    """Status of self-modification engine + backup list."""
    status = get_self_modify_status()
    status["module_available"] = SELF_MODIFY_AVAILABLE
    return jsonify(status)


@loop_bp.route("/self_modify/improve", methods=["POST"])
def self_modify_improve():
    """
    Full self-improvement pipeline: request -> LLM -> patch -> verify.
    Body: {
        "request": "Make the chat bubble wider with dark green theme",
        "target": "index.html",   // optional, auto-detected if omitted
        "use_claude": true,        // use Claude.ai loop (needs session)
        "verify": true,            // take before/after screenshots
        "confirm": "I CONFIRM self_modify_improve"   // Phase 1.4 — required
    }
    """
    from confirm_gate import require_confirm
    denial = require_confirm("self_modify_improve")
    if denial:
        return denial

    if not SELF_MODIFY_AVAILABLE:
        return jsonify({"success": False, "error": "self_modify module not available"})

    data    = request.json or {}
    req_txt = data.get("request", "").strip()
    if not req_txt:
        return jsonify({"success": False, "error": "request is required"})

    target      = data.get("target")
    use_claude  = bool(data.get("use_claude", True))
    result = self_improve(req_txt, target=target, use_claude=use_claude)
    return jsonify(result)


@loop_bp.route("/self_modify/patch", methods=["POST"])
def self_modify_patch():
    """
    Directly patch a file with provided code (no LLM call).
    Body: {
        "filename": "index.html",
        "code": "<!DOCTYPE html>...",
        "confirm": "I CONFIRM self_modify_patch"     // Phase 1.4 — required
    }
    """
    from confirm_gate import require_confirm
    denial = require_confirm("self_modify_patch")
    if denial:
        return denial

    if not SELF_MODIFY_AVAILABLE:
        return jsonify({"success": False, "error": "self_modify module not available"})

    data     = request.json or {}
    filename = data.get("filename", "").strip()
    code     = data.get("code", "").strip()
    if not filename or not code:
        return jsonify({"success": False, "error": "filename and code are required"})

    result = patch_file_direct(filename, code)
    return jsonify(result)


@loop_bp.route("/self_modify/rollback", methods=["POST"])
def self_modify_rollback():
    """
    Roll back the last patch to a file.
    Body: {
        "filename": "index.html",
        "confirm": "I CONFIRM self_modify_rollback"  // Phase 1.4 — required
    }
    """
    from confirm_gate import require_confirm
    denial = require_confirm("self_modify_rollback")
    if denial:
        return denial

    if not SELF_MODIFY_AVAILABLE:
        return jsonify({"success": False, "error": "self_modify module not available"})

    filename = (request.json or {}).get("filename", "").strip()
    if not filename:
        return jsonify({"success": False, "error": "filename is required"})

    return jsonify(rollback(filename))


@loop_bp.route("/self_modify/backups", methods=["GET"])
def self_modify_backups():
    """List all available backups."""
    if not SELF_MODIFY_AVAILABLE:
        return jsonify({"backups": []})
    return jsonify({"backups": list_backups()})


@loop_bp.route("/self_modify/log", methods=["GET"])
def self_modify_log():
    """Get recent self-modification log."""
    limit = int(request.args.get("limit", 30))
    return jsonify({"log": get_patch_log(limit)})


# =============================================================================
# FULL APP CONTROL ROUTES — /app_control/*
# Control VS Code, Chrome, any window on the laptop
# =============================================================================

@loop_bp.route("/app_control/status", methods=["GET"])
def app_control_status():
    """Status + capabilities of the app control engine."""
    status = get_app_control_status()
    status["module_available"] = APP_CONTROL_AVAILABLE
    return jsonify(status)


@loop_bp.route("/app_control/windows", methods=["GET"])
def app_control_windows():
    """List all open windows on the laptop."""
    if not APP_CONTROL_AVAILABLE:
        return jsonify({"success": False, "error": "app_control module not available"})
    windows = list_windows()
    return jsonify({"success": True, "windows": windows, "count": len(windows)})


@loop_bp.route("/app_control/focus", methods=["POST"])
def app_control_focus():
    """
    Bring a window to foreground by partial title match.
    Body: {"title": "Visual Studio Code"}
    """
    if not APP_CONTROL_AVAILABLE:
        return jsonify({"success": False, "error": "app_control module not available"})
    title = (request.json or {}).get("title", "").strip()
    if not title:
        return jsonify({"success": False, "error": "title is required"})
    return jsonify(focus_window(title))


@loop_bp.route("/app_control/action", methods=["POST"])
def app_control_action():
    """
    Execute any app control action.
    Body: {
        "action": "chrome_new_tab",
        "params": {"url": "https://claude.ai"}
    }

    Available actions:
      Window: list_windows, focus, minimize, maximize, launch, type_in_window
      Chrome: chrome_new_tab, chrome_navigate, chrome_close_tab, chrome_next_tab,
              chrome_prev_tab, chrome_tab_number, chrome_reload, chrome_get_url
      VSCode: vscode_open_file, vscode_command, vscode_save, vscode_format,
              vscode_terminal, vscode_run_in_terminal, vscode_type_code, vscode_search
    """
    if not APP_CONTROL_AVAILABLE:
        return jsonify({"success": False, "error": "app_control module not available"})

    data   = request.json or {}
    action = data.get("action", "").strip()
    params = data.get("params", {})

    if not action:
        return jsonify({"success": False, "error": "action is required"})

    return jsonify(control_app(action, params))


@loop_bp.route("/app_control/chrome", methods=["POST"])
def app_control_chrome():
    """
    Chrome-specific shortcut route.
    Body: {"action": "new_tab", "url": "https://claude.ai"}
    """
    if not APP_CONTROL_AVAILABLE:
        return jsonify({"success": False, "error": "app_control module not available"})

    data   = request.json or {}
    action = data.get("action", "").strip()
    url    = data.get("url", "")

    action_map = {
        "new_tab":   lambda: control_app("chrome_new_tab",   {"url": url or "https://google.com"}),
        "navigate":  lambda: control_app("chrome_navigate",  {"url": url}),
        "close_tab": lambda: control_app("chrome_close_tab", {}),
        "next_tab":  lambda: control_app("chrome_next_tab",  {}),
        "prev_tab":  lambda: control_app("chrome_prev_tab",  {}),
        "reload":    lambda: control_app("chrome_reload",    {}),
        "get_url":   lambda: control_app("chrome_get_url",   {}),
    }

    if action not in action_map:
        return jsonify({"success": False, "error": f"Unknown chrome action: {action}. Use: {list(action_map.keys())}"})

    return jsonify(action_map[action]())


@loop_bp.route("/app_control/vscode", methods=["POST"])
def app_control_vscode():
    """
    VS Code-specific shortcut route.
    Body: {"action": "open_file", "file": "/path/to/file.py"}
    """
    if not APP_CONTROL_AVAILABLE:
        return jsonify({"success": False, "error": "app_control module not available"})

    data    = request.json or {}
    action  = data.get("action", "").strip()
    params  = {k: v for k, v in data.items() if k != "action"}

    return jsonify(control_app(f"vscode_{action}", params))


# =============================================================================
# FULL LOOP — "Ultron, go to Claude and get a better UI"
# This single endpoint does ALL 5 steps from the diagram automatically:
#   Step 1: Open claude.ai (chrome_new_tab / playwright)
#   Step 2: Type the prompt (ask_claude_ai)
#   Step 3: Wait + read reply
#   Step 4: Copy code back (extract_code_blocks)
#   Step 5: Patch + verify (self_modify + visual_verify)
# =============================================================================

@loop_bp.route("/full_loop", methods=["POST"])
def full_loop():
    """
    FULL AUTONOMOUS LOOP - All 5 steps in one call.

    Body: {
        "request": "Give me a better dark-theme navbar for my AI assistant",
        "target_file": "index.html",    // optional
        "verify_url": "http://localhost:5000",   // optional
        "use_claude_ai": true           // false = use local Groq/Gemini instead
    }

    Returns step-by-step result of the entire pipeline.
    """
    data        = request.json or {}
    user_req    = data.get("request", "").strip()
    target_file = data.get("target_file")
    verify_url  = data.get("verify_url", "http://localhost:5000")
    use_claude  = bool(data.get("use_claude_ai", True))

    if not user_req:
        return jsonify({"success": False, "error": "request is required"})

    steps = []

    # ── Step 1 & 2: Ask Claude.ai (or fallback LLM) ──────────────────────
    code = None
    code_source = "none"

    if use_claude and CLAUDE_LOOP_AVAILABLE and has_saved_session():
        steps.append({"step": 1, "name": "Open Claude.ai + type prompt", "status": "running"})
        loop_result = ask_and_get_code(user_req)
        if loop_result.get("success"):
            code = loop_result.get("code") or loop_result.get("reply")
            code_source = "claude.ai"
            steps[-1]["status"] = "done"
            steps[-1]["reply_length"] = len(loop_result.get("reply", ""))
            steps[-1]["code_found"] = loop_result.get("has_code", False)
        else:
            steps[-1]["status"] = "failed"
            steps[-1]["error"] = loop_result.get("error")
    else:
        steps.append({
            "step": 1,
            "name": "Prompt LLM (Claude.ai session unavailable, using fallback)",
            "status": "skipped_to_fallback",
        })

    # Fallback to Groq/Gemini if Claude.ai not available
    if not code:
        steps.append({"step": "1b", "name": "Fallback LLM (Groq/Gemini)", "status": "running"})
        try:
            from llm_engine import call_llm_batch, determine_best_provider
            import re

            # Read current file for context
            target = target_file or "index.html"
            from self_modify import ALLOWED_FILES
            current = ""
            fp = ALLOWED_FILES.get(target, "")
            if fp and os.path.exists(fp):
                with open(fp) as f:
                    current = f.read()[:3000]

            prompt = f"""You are a senior web/Python developer. Improve the following file.

REQUEST: {user_req}

CURRENT FILE ({target}) - first 3000 chars:
{current}

Return ONLY the complete improved file. No markdown, no explanation."""

            provider = determine_best_provider(prompt)
            raw = call_llm_batch(prompt, provider=provider)
            if raw:
                raw = re.sub(r"^```\w*\n?", "", raw.strip())
                raw = re.sub(r"\n?```$", "", raw)
                code = raw
                code_source = provider
            steps[-1]["status"] = "done" if code else "failed"
        except Exception as e:
            steps[-1]["status"] = "failed"
            steps[-1]["error"] = str(e)

    if not code:
        return jsonify({
            "success": False,
            "error": "Could not get code from any LLM. Check API keys.",
            "steps": steps,
        })

    # ── Step 3: Read reply (already done above) ─────────────────────────────
    steps.append({
        "step": 3,
        "name": "Read reply",
        "status": "done",
        "code_length": len(code),
        "source": code_source,
    })

    # ── Step 4: Copy code + patch file ──────────────────────────────────────
    steps.append({"step": 4, "name": "Patch file", "status": "running"})
    if SELF_MODIFY_AVAILABLE:
        patch_result = patch_file_direct(
            target_file or "index.html",
            code,
        )
        steps[-1]["status"] = "done" if patch_result.get("success") else "failed"
        steps[-1]["patch"] = patch_result
    else:
        steps[-1]["status"] = "skipped"
        steps[-1]["note"] = "self_modify module not available"

    # ── Step 5: Verify ──────────────────────────────────────────────────────
    steps.append({"step": 5, "name": "Visual verification", "status": "running"})
    if VISUAL_VERIFY_AVAILABLE:
        try:
            import time as _time
            _time.sleep(2)
            verify_result = verify_code_patch(verify_url, user_req)
            steps[-1]["status"] = "done"
            steps[-1]["rating"] = verify_result.get("rating", "?")
            steps[-1]["diff_percent"] = verify_result.get("diff_percent", 0)
        except Exception as e:
            steps[-1]["status"] = "skipped"
            steps[-1]["error"] = str(e)
    else:
        steps[-1]["status"] = "skipped"
        steps[-1]["note"] = "visual_verify module not available"

    return jsonify({
        "success": True,
        "request": user_req,
        "code_source": code_source,
        "code_length": len(code),
        "steps": steps,
        "message": f"Full loop complete. Code from {code_source}. Patched {target_file or 'index.html'}.",
    })


# =============================================================================
# SMART BROWSER (browser-use AI agent)
# =============================================================================

try:
    from smart_browser import browse as _smart_browse, search_and_read as _smart_search, \
        BROWSER_USE_AVAILABLE as _BROWSER_USE_AVAILABLE
except ImportError:
    _BROWSER_USE_AVAILABLE = False


@loop_bp.route("/browser/task", methods=["POST"])
def browser_task():
    """Run an AI browser task using browser-use. POST {task: str}."""
    if not _BROWSER_USE_AVAILABLE:
        return jsonify({"error": "smart_browser not available — pip install browser-use"}), 503
    data = request.json or {}
    task = data.get("task", "").strip()
    if not task:
        return jsonify({"error": "task field required"}), 400
    return jsonify(_smart_browse(task))


@loop_bp.route("/browser/search", methods=["POST"])
def browser_search():
    """Web search and summarise using AI browser. POST {query: str}."""
    if not _BROWSER_USE_AVAILABLE:
        return jsonify({"error": "smart_browser not available"}), 503
    data = request.json or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "query field required"}), 400
    return jsonify(_smart_search(query))
