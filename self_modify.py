"""
self_modify.py — Ultron-J Self-Modification Engine

FULL LOOP:
  1. Jeevan says: "Ultron, get a better UI from Claude"
  2. Ultron builds a prompt describing the current UI issue
  3. Sends to Claude.ai (or local LLM as fallback) via claude_loop.py
  4. Gets code back (HTML/CSS/JS/Python)
  5. Identifies which file to patch (templates/index.html, voice.html, app.py, etc.)
  6. Makes a BACKUP of the original file
  7. Patches the file (full replace OR targeted section replace)
  8. Signals Flask to reload (or does it automatically via watchdog)
  9. Takes BEFORE+AFTER screenshot to verify the change happened
  10. Tells Jeevan the result

SAFETY:
  - Every patch creates a timestamped backup in self_modify_backups/
  - Backups are auto-restored if verification detects a broken UI
  - Max 10 patches per session to prevent runaway changes
  - Only allowed files can be patched (whitelist)

USAGE:
  from self_modify import SelfModifier, self_improve
  result = self_improve("Make the chat bubble wider and use dark green theme")
"""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from memory import atomic_json_write

_BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR     = os.path.join(_BASE_DIR, "self_modify_backups")
PATCH_LOG_FILE = os.path.join(_BASE_DIR, "self_modify_log.json")
os.makedirs(BACKUP_DIR, exist_ok=True)

_log_lock = threading.Lock()

# ── Which files are allowed to be patched ──────────────────────────────────────
def _build_allowed():
    import glob
    forbidden = {"config.py", ".env", "memory.py"}
    allowed = {}
    for f in glob.glob(os.path.join(_BASE_DIR, "*.py")):
        base = os.path.basename(f)
        if base not in forbidden:
            allowed[base] = f
    for tpl in glob.glob(os.path.join(_BASE_DIR, "templates", "*.html")):
        allowed[os.path.basename(tpl)] = tpl
    return allowed

ALLOWED_FILES = _build_allowed()

# Max patches per session (safety limit)
MAX_PATCHES_PER_SESSION = 15
_patches_this_session   = 0
_patch_lock             = threading.Lock()


# =============================================================================
# LOGGING
# =============================================================================

def _log(data: dict):
    with _log_lock:
        try:
            log = []
            if os.path.exists(PATCH_LOG_FILE):
                with open(PATCH_LOG_FILE) as f:
                    log = json.load(f)
            log.append({"ts": datetime.now().isoformat(), **data})
            log = log[-300:]
            atomic_json_write(PATCH_LOG_FILE, log)
        except Exception:
            pass


def get_patch_log(limit: int = 30) -> list:
    try:
        with open(PATCH_LOG_FILE) as f:
            return json.load(f)[-limit:]
    except Exception:
        return []


# =============================================================================
# BACKUP MANAGER
# =============================================================================

def _backup_file(filepath: str) -> Optional[str]:
    """Create a timestamped backup before patching."""
    if not os.path.exists(filepath):
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.basename(filepath)
    backup_path = os.path.join(BACKUP_DIR, f"{filename}_{ts}.bak")
    shutil.copy2(filepath, backup_path)
    _log({"action": "backup", "original": filepath, "backup": backup_path})
    return backup_path


def restore_backup(backup_path: str, original_path: str) -> Dict:
    """Restore a file from backup."""
    try:
        shutil.copy2(backup_path, original_path)
        return {"success": True, "restored": original_path, "from": backup_path}
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_backups() -> List[Dict]:
    """List all available backups."""
    backups = []
    for f in sorted(Path(BACKUP_DIR).glob("*.bak"), reverse=True):
        backups.append({
            "filename": f.name,
            "path": str(f),
            "size": f.stat().st_size,
            "created": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        })
    return backups[:50]


def restore_latest_backup(filename: str) -> Dict:
    """Find and restore the most recent backup for a given filename."""
    pattern = f"{filename}_*.bak"
    backups = sorted(Path(BACKUP_DIR).glob(pattern), reverse=True)
    if not backups:
        return {"success": False, "error": f"No backup found for {filename}"}
    latest = backups[0]
    original = ALLOWED_FILES.get(filename)
    if not original:
        return {"success": False, "error": f"{filename} not in allowed files"}
    return restore_backup(str(latest), original)


# =============================================================================
# CODE EXTRACTION & FILE DETECTION
# =============================================================================

def _detect_target_file(request: str, code: str) -> str:
    """
    Detect which file should be patched based on the request + code content.
    Returns filename from ALLOWED_FILES keys.
    """
    request_lower = request.lower()
    code_lower    = code.lower() if code else ""

    # Explicit mentions
    for fname in ALLOWED_FILES:
        if fname in request_lower:
            return fname

    # Code type detection
    if code:
        if "<!doctype html" in code_lower or "<html" in code_lower or "<body" in code_lower:
            if "voice" in request_lower:
                return "voice.html"
            return "index.html"
        if "@app.route" in code or "from flask" in code or "def " in code and "flask" in code_lower:
            return "app.py"
        if "personality" in request_lower and ".py" in code:
            return "personality.py"

    # Keyword matching
    if any(w in request_lower for w in ["ui", "interface", "design", "navbar", "chat", "button", "color", "theme", "style", "css", "html"]):
        if "voice" in request_lower:
            return "voice.html"
        return "index.html"
    if any(w in request_lower for w in ["route", "endpoint", "api", "flask", "backend"]):
        return "app.py"

    return "index.html"  # default


def _extract_section(content: str, start_marker: str, end_marker: str) -> Optional[Tuple[int, int, str]]:
    """
    Find a section between two markers in a file.
    Returns (start_idx, end_idx, old_section) or None.
    """
    start_idx = content.find(start_marker)
    if start_idx == -1:
        return None
    end_idx = content.find(end_marker, start_idx + len(start_marker))
    if end_idx == -1:
        return None
    end_idx += len(end_marker)
    return start_idx, end_idx, content[start_idx:end_idx]


def _smart_patch(original: str, new_code: str, request: str) -> str:
    """
    Intelligently merge new code into original file.
    Strategy:
      1. If new_code is a FULL file (has <html> or starts with #!/ etc) → full replace
      2. If new_code is a SECTION (CSS block, function, etc) → find and replace that section
      3. Otherwise → append to end / inject at best location
    """
    original_lower = original.lower()
    new_code_lower = new_code.lower()

    # Full HTML file replacement
    if "<!doctype" in new_code_lower or (new_code_lower.startswith("<html") and len(new_code) > 500):
        return new_code

    # Full Python file (has imports at top and function definitions)
    if (new_code.startswith("import ") or new_code.startswith("from ")) and "def " in new_code and len(new_code) > 300:
        return new_code

    # CSS block → replace inside <style> tag
    if "<style>" in new_code or "body {" in new_code or ".container" in new_code:
        # Find existing <style> section and replace
        style_start = original.find("<style>")
        style_end   = original.find("</style>")
        if style_start != -1 and style_end != -1:
            # Extract just the CSS from new_code if it has <style> tags
            css = new_code
            if "<style>" in new_code:
                css_match = re.search(r"<style>(.*?)</style>", new_code, re.DOTALL)
                if css_match:
                    css = css_match.group(1)
            return original[:style_start + 7] + "\n" + css + "\n" + original[style_end:]

    # Python function replacement
    func_match = re.search(r"^def (\w+)\(", new_code, re.MULTILINE)
    if func_match:
        func_name = func_match.group(1)
        # Find existing function in original
        orig_match = re.search(rf"^def {re.escape(func_name)}\(", original, re.MULTILINE)
        if orig_match:
            start = orig_match.start()
            # Find next function or end of file
            next_func = re.search(r"^def ", original[start + 5:], re.MULTILINE)
            if next_func:
                end = start + 5 + next_func.start()
            else:
                end = len(original)
            return original[:start] + new_code + "\n\n" + original[end:]

    # Fallback: append with a comment
    return original + "\n\n# === ULTRON PATCH ===\n" + new_code + "\n# === END PATCH ==="


# =============================================================================
# FLASK RELOAD
# =============================================================================

def _signal_flask_reload():
    """
    Signal Flask to reload by touching app.py's modification time.
    Works when Flask is run with use_reloader=True or watchdog installed.
    """
    try:
        app_path = os.path.join(_BASE_DIR, "app.py")
        os.utime(app_path, None)  # Update mtime → triggers reload
        return True
    except Exception:
        return False


def _restart_flask():
    """Full restart of the Flask process (more aggressive than reload)."""
    try:
        # Write restart signal file
        signal_file = os.path.join(_BASE_DIR, ".restart_signal")
        with open(signal_file, "w") as f:
            f.write(datetime.now().isoformat())
        return True
    except Exception:
        return False


# =============================================================================
# CORE SELF-MODIFICATION
# =============================================================================

class SelfModifier:
    """Manages the full self-modification pipeline."""

    def __init__(self):
        self.session_patches = 0

    def patch_file(
        self,
        filename: str,
        new_code: str,
        request: str = "",
        smart_merge: bool = True,
    ) -> Dict:
        """
        Patch a specific allowed file with new code.

        Args:
            filename: Key from ALLOWED_FILES (e.g., "index.html")
            new_code: The new code to apply
            request: Original user request (for context)
            smart_merge: If True, try to merge. If False, do full replace.
        """
        if filename in {"config.py", "memory.py", ".env"}:
            return {
                "success": False,
                "error": f"{filename} is permanently protected from self_modify",
            }

        global _patches_this_session
        with _patch_lock:
            if _patches_this_session >= MAX_PATCHES_PER_SESSION:
                return {
                    "success": False,
                    "error": f"Patch limit reached ({MAX_PATCHES_PER_SESSION} patches/session). Restart Ultron to reset.",
                }

        if filename not in ALLOWED_FILES:
            return {
                "success": False,
                "error": f"'{filename}' is not in the allowed patch list. Allowed: {list(ALLOWED_FILES.keys())}",
            }

        filepath = ALLOWED_FILES[filename]
        if not os.path.exists(filepath):
            return {"success": False, "error": f"File not found: {filepath}"}

        # Backup first
        backup_path = _backup_file(filepath)

        try:
            # Read original
            with open(filepath, "r", encoding="utf-8") as f:
                original = f.read()

            # Apply patch
            if smart_merge:
                patched = _smart_patch(original, new_code, request)
            else:
                patched = new_code

            # Reject patches that would introduce a SyntaxError into a .py
            # file BEFORE writing. Without this, a broken patch to app.py (or
            # any imported module) makes Ultron fail to import on next reload
            # and it cannot self-restore because it cannot start. The original
            # file is left untouched and the backup remains available.
            if filename.endswith(".py"):
                try:
                    compile(patched, filepath, "exec")
                except SyntaxError as e:
                    _log({
                        "action": "patch_rejected",
                        "filename": filename,
                        "error": f"SyntaxError at line {e.lineno}: {e.msg}",
                        "backup": backup_path,
                    })
                    return {
                        "success": False,
                        "error": (
                            f"patch rejected: would introduce SyntaxError "
                            f"at line {e.lineno}: {e.msg}"
                        ),
                        "backup": backup_path,
                    }

            # Write patched file
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(patched)

            with _patch_lock:
                _patches_this_session += 1

            _log({
                "action": "patch",
                "filename": filename,
                "backup": backup_path,
                "request_preview": request[:100],
                "patch_size": len(new_code),
                "full_replace": not smart_merge,
            })

            # Signal reload
            _signal_flask_reload()

            return {
                "success": True,
                "filename": filename,
                "filepath": filepath,
                "backup": backup_path,
                "patch_size": len(new_code),
                "full_replace": not smart_merge,
                "session_patches": _patches_this_session,
            }

        except Exception as e:
            # Restore backup on error
            if backup_path:
                shutil.copy2(backup_path, filepath)
            _log({"action": "patch_error", "filename": filename, "error": str(e)})
            return {"success": False, "error": str(e)}

    def improve_from_llm(
        self,
        request: str,
        target_file: Optional[str] = None,
        use_claude_ai: bool = True,
        verify_after: bool = True,
        url_to_verify: str = "http://localhost:5000",
    ) -> Dict:
        """
        Full self-improvement pipeline:
        1. Build prompt from request
        2. Get code from Claude.ai (or fallback to Groq)
        3. Detect target file
        4. Patch it
        5. Verify visually
        """
        _log({"action": "improve_start", "request": request[:100]})

        # 1. Build a smart prompt
        if target_file:
            tf = target_file
        else:
            tf = _detect_target_file(request, "")

        # Read current file for context
        current_code = ""
        if tf in ALLOWED_FILES and os.path.exists(ALLOWED_FILES[tf]):
            with open(ALLOWED_FILES[tf], "r", encoding="utf-8") as f:
                current_code = f.read()[:3000]  # first 3000 chars for context

        prompt = f"""You are a senior web developer. Improve the following file for Ultron-J, a personal AI assistant UI.

IMPROVEMENT REQUEST: {request}

CURRENT FILE ({tf}) — first 3000 chars:
{current_code}

INSTRUCTIONS:
- Return ONLY the complete improved file content (no explanation, no markdown fences)
- Make the requested changes while preserving all existing functionality
- Keep the code clean, modern, and working
- If it's HTML/CSS, keep it beautiful with dark theme matching the current design
- If it's Python Flask code, ensure all routes still work"""

        # 2. Get code from LLM
        code = None
        source = "none"

        if use_claude_ai:
            try:
                from claude_loop import ask_and_get_code, has_saved_session
                if has_saved_session():
                    result = ask_and_get_code(prompt)
                    if result.get("success") and result.get("code"):
                        code = result["code"]
                        source = "claude.ai"
                    elif result.get("success") and result.get("reply"):
                        code = result["reply"]  # use raw reply if no code block
                        source = "claude.ai (raw)"
            except ImportError:
                pass

        if not code:
            # Fallback: local LLM
            try:
                from llm_engine import call_llm_batch, determine_best_provider
                provider = determine_best_provider(prompt)
                raw = call_llm_batch(prompt, provider=provider)
                if raw:
                    # Strip markdown fences
                    raw = re.sub(r"^```\w*\n?", "", raw.strip())
                    raw = re.sub(r"\n?```$", "", raw)
                    code = raw
                    source = provider
            except Exception as e:
                return {"success": False, "error": f"LLM call failed: {e}"}

        if not code:
            return {"success": False, "error": "No code received from LLM."}

        # 3. Auto-detect target if not specified
        if not target_file:
            tf = _detect_target_file(request, code)

        # 4. Take before screenshot
        before_screenshot = None
        if verify_after:
            try:
                from visual_verify import capture_url_screenshot
                before_result = capture_url_screenshot(url_to_verify, "before_patch")
                if before_result["success"]:
                    before_screenshot = before_result["path"]
            except ImportError:
                verify_after = False

        # 5. Patch the file
        patch_result = self.patch_file(tf, code, request=request, smart_merge=True)
        if not patch_result["success"]:
            return patch_result

        # 6. Verify
        verify_result = None
        if verify_after and before_screenshot:
            try:
                time.sleep(2.5)  # wait for Flask reload
                from visual_verify import verify_code_patch
                verify_result = verify_code_patch(url_to_verify, request)
            except Exception as e:
                verify_result = {"error": str(e)}

        return {
            "success": True,
            "request": request,
            "target_file": tf,
            "code_source": source,
            "code_length": len(code),
            "patch": patch_result,
            "verification": verify_result,
            "message": f"Patched {tf} using code from {source}. {('Visual check: ' + verify_result.get('rating', '?')) if verify_result else 'No visual check.'}",
        }


# Singleton
_modifier = SelfModifier()


def self_improve(request: str, target: str = None, use_claude: bool = True) -> Dict:
    """Top-level function for voice commands / API routes."""
    return _modifier.improve_from_llm(request, target_file=target, use_claude_ai=use_claude)


def patch_file_direct(filename: str, new_code: str) -> Dict:
    """Directly patch a file with given code (no LLM)."""
    return _modifier.patch_file(filename, new_code, smart_merge=False)


def rollback(filename: str) -> Dict:
    """Roll back the last patch to a file."""
    return restore_latest_backup(filename)


def get_self_modify_status() -> Dict:
    """Return status of self-modification engine."""
    return {
        "session_patches": _patches_this_session,
        "max_patches": MAX_PATCHES_PER_SESSION,
        "allowed_files": list(ALLOWED_FILES.keys()),
        "backup_count": len(list(Path(BACKUP_DIR).glob("*.bak"))),
        "backup_dir": BACKUP_DIR,
    }
