"""
claude_loop.py — Full Autonomous Claude.ai Loop for Ultron-J

WHAT THIS DOES:
  Step 1: Open claude.ai in a real browser (Playwright)
  Step 2: Type your prompt into the chat box
  Step 3: Wait for Claude to finish responding
  Step 4: Read the full reply text
  Step 5: Extract any code blocks from the response
  Step 6: Return everything back to Ultron

REQUIREMENTS:
  pip install playwright
  playwright install chromium

SESSION COOKIES:
  - First run: opens browser visibly so you can log in manually
  - After that: saves session cookies to claude_session.json
  - Future runs: fully headless, no login needed

WHY NOT HEADLESS FROM START:
  Claude.ai detects bots. Session cookies from a real login bypass this.

USAGE:
  from claude_loop import ask_claude_ai, get_claude_code
  result = ask_claude_ai("Give me a better navbar in dark theme")
  code = get_claude_code(result["reply"])
"""

import json
import os
import re
import time
import threading
from datetime import datetime
from typing import Dict, List, Optional

_BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
SESSION_FILE   = os.path.join(_BASE_DIR, "claude_session.json")
LOOP_LOG_FILE  = os.path.join(_BASE_DIR, "claude_loop_log.json")
_log_lock      = threading.Lock()

CLAUDE_URL      = "https://claude.ai"
CLAUDE_NEW_CHAT = "https://claude.ai/new"

# Selectors for Claude.ai (update if Claude changes their DOM)
SELECTORS = {
    "prompt_box":      '[contenteditable="true"]',
    "send_button":     'button[aria-label="Send message"]',
    "response_block":  '[data-testid="assistant-message"]',
    "stop_button":     'button[aria-label="Stop generating"]',
    "login_check":     '[data-testid="sidebar"]',
}

WAIT_POLL_INTERVAL = 0.8   # seconds between response checks
MAX_WAIT_SECONDS   = 120   # max wait for Claude to finish

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


# =============================================================================
# LOGGING
# =============================================================================

def _log(data: dict):
    with _log_lock:
        try:
            log = []
            if os.path.exists(LOOP_LOG_FILE):
                with open(LOOP_LOG_FILE) as f:
                    log = json.load(f)
            log.append({"ts": datetime.now().isoformat(), **data})
            log = log[-200:]
            with open(LOOP_LOG_FILE, "w") as f:
                json.dump(log, f, indent=2)
        except Exception:
            pass


def get_loop_log(limit: int = 30) -> list:
    try:
        with open(LOOP_LOG_FILE) as f:
            return json.load(f)[-limit:]
    except Exception:
        return []


# =============================================================================
# SESSION MANAGEMENT
# =============================================================================

def save_session(context) -> bool:
    """Save browser cookies/session to file."""
    try:
        cookies = context.cookies()
        storage = context.storage_state()
        data = {
            "cookies": cookies,
            "storage": storage,
            "saved_at": datetime.now().isoformat(),
        }
        with open(SESSION_FILE, "w") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        _log({"action": "save_session", "error": str(e)})
        return False


def load_session(context) -> bool:
    """Load previously saved session into browser context."""
    if not os.path.exists(SESSION_FILE):
        return False
    try:
        with open(SESSION_FILE) as f:
            data = json.load(f)
        cookies = data.get("cookies", [])
        if cookies:
            context.add_cookies(cookies)
        return True
    except Exception:
        return False


def has_saved_session() -> bool:
    return os.path.exists(SESSION_FILE)


# =============================================================================
# LOGIN — First-time setup (shows real browser window)
# =============================================================================

def do_manual_login() -> Dict:
    """
    Open a visible browser window so Jeevan can log in manually to Claude.ai.
    Once logged in, session cookies are saved for future headless runs.

    Phase 9 hardening: this function calls `input()` to pause until the
    human finishes the login. Over HTTP (POST /claude_loop/login) there
    is no terminal, so `input()` would block on a non-existent stdin
    and hang the request. We detect non-interactive stdin and refuse
    with a 400-style payload that points the caller at the CLI form.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return {"success": False, "error": "playwright not installed. Run: pip install playwright && playwright install chromium"}

    # Bail out cleanly if we have no terminal -- the input() call below
    # would hang the request forever.
    import sys as _sys
    if not _sys.stdin.isatty():
        return {
            "success": False,
            "error": (
                "manual login requires an interactive terminal -- the "
                "input() prompt has no stdin over HTTP. Run from the "
                "Ultron CLI: `venv/bin/python -c "
                "'from claude_loop import do_manual_login; "
                "print(do_manual_login())'`"
            ),
        }

    result = {"success": False}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, slow_mo=200)
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            page.goto(CLAUDE_URL, wait_until="networkidle", timeout=30000)

            print("\n[Claude Loop] 🌐 Browser opened. Please log in to Claude.ai manually.")
            print("[Claude Loop] After login, press ENTER here to save your session.\n")
            input("Press ENTER after you are logged in to Claude.ai...")

            # Save session
            saved = save_session(context)
            browser.close()

            if saved:
                result = {"success": True, "message": "Session saved! Future runs will be headless."}
                _log({"action": "manual_login", "success": True})
            else:
                result = {"success": False, "error": "Failed to save session."}

    except Exception as e:
        result = {"success": False, "error": str(e)}
        _log({"action": "manual_login", "error": str(e)})

    return result


# =============================================================================
# CORE — Ask Claude.ai (with saved session)
# =============================================================================

def ask_claude_ai(
    prompt: str,
    headless: bool = True,
    timeout_seconds: int = MAX_WAIT_SECONDS,
) -> Dict:
    """
    Send a prompt to Claude.ai and get the full response back.

    Returns:
        {
            "success": True,
            "reply": "Full reply text...",
            "code_blocks": ["code snippet 1", ...],
            "screenshot_path": "/path/to/after.png",   # optional
            "elapsed": 12.3,
        }
    """
    if not PLAYWRIGHT_AVAILABLE:
        return {
            "success": False,
            "error": "playwright not installed. Run: pip install playwright && playwright install chromium",
        }

    if not has_saved_session():
        return {
            "success": False,
            "error": "No Claude.ai session found. Call /claude_loop/login first to log in manually.",
        }

    start = time.time()
    result = {"success": False}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
            )

            # Load saved session
            load_session(context)
            page = context.new_page()

            # Navigate to new chat
            page.goto(CLAUDE_NEW_CHAT, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)

            # Check we are actually logged in (sidebar should exist)
            try:
                page.wait_for_selector(SELECTORS["login_check"], timeout=8000)
            except Exception:
                browser.close()
                return {
                    "success": False,
                    "error": "Session expired or not logged in. Call /claude_loop/login to re-authenticate.",
                }

            # Find prompt box and type
            try:
                prompt_el = page.wait_for_selector(SELECTORS["prompt_box"], timeout=10000)
                prompt_el.click()
                time.sleep(0.3)
                prompt_el.fill(prompt)
                time.sleep(0.5)
            except Exception as e:
                browser.close()
                return {"success": False, "error": f"Could not find prompt box: {e}"}

            # Click Send
            try:
                send_btn = page.wait_for_selector(SELECTORS["send_button"], timeout=5000)
                send_btn.click()
            except Exception:
                # Fallback: press Enter
                prompt_el.press("Enter")

            _log({"action": "prompt_sent", "prompt_preview": prompt[:80]})

            # Wait for response to complete (stop button disappears = done)
            elapsed = 0
            while elapsed < timeout_seconds:
                time.sleep(WAIT_POLL_INTERVAL)
                elapsed = time.time() - start

                # Check if stop button is gone (means generation finished)
                stop_btn = page.query_selector(SELECTORS["stop_button"])
                if stop_btn is None:
                    # Additional wait for final render
                    time.sleep(1.5)
                    break

            # Extract the last assistant response
            reply_text = ""
            try:
                responses = page.query_selector_all(SELECTORS["response_block"])
                if responses:
                    last = responses[-1]
                    reply_text = last.inner_text()
                else:
                    # Fallback: get all text from main content
                    reply_text = page.inner_text("main")[:8000]
            except Exception as e:
                reply_text = f"[Could not extract reply: {e}]"

            # Screenshot
            screenshot_path = None
            try:
                from config import _BASE_DIR as BASE
                ss_dir = os.path.join(BASE, "browser_cache")
                os.makedirs(ss_dir, exist_ok=True)
                screenshot_path = os.path.join(ss_dir, f"claude_reply_{int(time.time())}.png")
                page.screenshot(path=screenshot_path, full_page=False)
            except Exception:
                pass

            # Save updated session
            save_session(context)
            browser.close()

            code_blocks = extract_code_blocks(reply_text)
            elapsed_total = time.time() - start

            result = {
                "success": True,
                "reply": reply_text,
                "code_blocks": code_blocks,
                "screenshot_path": screenshot_path,
                "elapsed": round(elapsed_total, 1),
            }

            _log({
                "action": "ask_complete",
                "prompt_preview": prompt[:80],
                "reply_length": len(reply_text),
                "code_blocks_found": len(code_blocks),
                "elapsed": elapsed_total,
            })

    except Exception as e:
        result = {"success": False, "error": str(e)}
        _log({"action": "ask_error", "error": str(e)})

    return result


# =============================================================================
# CODE EXTRACTION
# =============================================================================

def extract_code_blocks(text: str) -> List[str]:
    """
    Extract all code blocks from a markdown-formatted response.
    Handles ```python, ```js, ```html, ``` (generic), etc.
    """
    # Match fenced code blocks
    pattern = r"```(?:\w+)?\n?(.*?)```"
    blocks = re.findall(pattern, text, re.DOTALL)
    blocks = [b.strip() for b in blocks if b.strip()]

    if not blocks:
        # Fallback: look for indented code-like blocks
        lines = text.split("\n")
        current_block = []
        in_block = False
        for line in lines:
            if line.startswith("    ") or line.startswith("\t"):
                current_block.append(line)
                in_block = True
            elif in_block and not line.strip():
                current_block.append("")
            else:
                if current_block and len(current_block) > 3:
                    blocks.append("\n".join(current_block).strip())
                current_block = []
                in_block = False

    return blocks


def get_claude_code(reply_text: str) -> Optional[str]:
    """Get the first (or largest) code block from a Claude reply."""
    blocks = extract_code_blocks(reply_text)
    if not blocks:
        return None
    # Return the largest block (usually the main code)
    return max(blocks, key=len)


# =============================================================================
# CONVENIENCE WRAPPERS
# =============================================================================

def ask_and_get_code(prompt: str) -> Dict:
    """
    Full loop: ask Claude.ai → wait → extract first code block → return.
    Used by self_modify.py for UI/code improvements.
    """
    result = ask_claude_ai(prompt)
    if not result["success"]:
        return result
    code = get_claude_code(result["reply"])
    return {
        **result,
        "code": code,
        "has_code": code is not None,
    }


def ask_claude_headful(prompt: str) -> Dict:
    """
    Run with visible browser (useful for debugging or when headless fails).
    """
    return ask_claude_ai(prompt, headless=False)


def get_session_status() -> Dict:
    """Check if a saved Claude.ai session exists and is recent."""
    if not has_saved_session():
        return {"has_session": False, "message": "No session. Call /claude_loop/login first."}
    try:
        with open(SESSION_FILE) as f:
            data = json.load(f)
        saved_at = data.get("saved_at", "unknown")
        cookie_count = len(data.get("cookies", []))
        return {
            "has_session": True,
            "saved_at": saved_at,
            "cookie_count": cookie_count,
            "playwright_available": PLAYWRIGHT_AVAILABLE,
        }
    except Exception as e:
        return {"has_session": False, "error": str(e)}


def clear_session() -> Dict:
    """Delete the saved Claude.ai session (force re-login)."""
    try:
        if os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)
        return {"success": True, "message": "Session cleared. Next use will require login."}
    except Exception as e:
        return {"success": False, "error": str(e)}
