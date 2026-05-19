"""
visual_verify.py — Visual Verification Engine for Ultron-J

WHAT THIS DOES:
  1. Take a "before" screenshot of the current screen / UI
  2. Execute an action (UI change, code patch, etc.)
  3. Take an "after" screenshot
  4. Send both to a vision LLM → get a diff analysis
  5. Return: what changed, did it improve, any errors visible?

USE CASES:
  - Verify that a UI patch actually changed the interface
  - Confirm a button was clicked and the page changed
  - Check that a new feature appeared on screen
  - Detect regressions after code self-modification

USAGE:
  from visual_verify import verify_ui_change, quick_screenshot_diff
  result = verify_ui_change(action_fn=my_function, description="navbar update")
"""

import base64
import io
import json
import os
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

_BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
VERIFY_DIR     = os.path.join(_BASE_DIR, "visual_verify_cache")
VERIFY_LOG     = os.path.join(_BASE_DIR, "visual_verify_log.json")
os.makedirs(VERIFY_DIR, exist_ok=True)

_log_lock = threading.Lock()

try:
    from PIL import Image, ImageChops, ImageFilter, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False


# =============================================================================
# LOGGING
# =============================================================================

def _log(data: dict):
    with _log_lock:
        try:
            log = []
            if os.path.exists(VERIFY_LOG):
                with open(VERIFY_LOG) as f:
                    log = json.load(f)
            log.append({"ts": datetime.now().isoformat(), **data})
            log = log[-200:]
            with open(VERIFY_LOG, "w") as f:
                json.dump(log, f, indent=2)
        except Exception:
            pass


def get_verify_log(limit: int = 30) -> list:
    try:
        with open(VERIFY_LOG) as f:
            return json.load(f)[-limit:]
    except Exception:
        return []


# =============================================================================
# SCREENSHOT HELPERS
# =============================================================================

def _capture_screen(label: str = "screen") -> Dict:
    """
    Capture the full screen and save to verify cache.
    Returns path + base64 + PIL image.
    """
    ts = int(time.time())
    path = os.path.join(VERIFY_DIR, f"{label}_{ts}.png")

    if PYAUTOGUI_AVAILABLE:
        img = pyautogui.screenshot()
    elif PIL_AVAILABLE:
        from PIL import ImageGrab
        img = ImageGrab.grab()
    else:
        return {"success": False, "error": "Install pyautogui or pillow: pip install pyautogui pillow"}

    if PIL_AVAILABLE:
        # Resize to max 1280px wide for LLM APIs
        if img.width > 1280:
            ratio = 1280 / img.width
            img = img.resize((1280, int(img.height * ratio)), Image.LANCZOS)

    img.save(path, "PNG")

    buf = io.BytesIO()
    img.save(buf, "PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    return {
        "success": True,
        "path": path,
        "b64": b64,
        "size": img.size,
        "image": img,  # PIL Image object (not serializable)
        "timestamp": ts,
    }


def _capture_region(x: int, y: int, w: int, h: int, label: str = "region") -> Dict:
    """Capture a specific screen region."""
    ts = int(time.time())
    path = os.path.join(VERIFY_DIR, f"{label}_{ts}.png")

    if PYAUTOGUI_AVAILABLE:
        img = pyautogui.screenshot(region=(x, y, w, h))
    elif PIL_AVAILABLE:
        from PIL import ImageGrab
        img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    else:
        return {"success": False, "error": "Install pyautogui or pillow"}

    img.save(path, "PNG")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    return {"success": True, "path": path, "b64": b64, "size": img.size, "image": img}


def capture_url_screenshot(url: str, label: str = "url") -> Dict:
    """
    Take a screenshot of a specific URL via Playwright (no pyautogui needed).
    Great for verifying web UI changes after a code patch.
    """
    try:
        from playwright.sync_api import sync_playwright
        ts = int(time.time())
        path = os.path.join(VERIFY_DIR, f"{label}_{ts}.png")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(url, wait_until="networkidle", timeout=20000)
            time.sleep(1)  # let animations settle
            page.screenshot(path=path, full_page=False)
            browser.close()

        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()

        return {"success": True, "path": path, "b64": b64}
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# PIXEL DIFF (local, no LLM)
# =============================================================================

def pixel_diff(before_path: str, after_path: str) -> Dict:
    """
    Compare two screenshots pixel-by-pixel.
    Returns: diff_percent (0-100), diff image saved to disk.
    Fast local check — no API needed.
    """
    if not PIL_AVAILABLE:
        return {"success": False, "error": "pillow not installed"}

    try:
        before = Image.open(before_path).convert("RGB")
        after  = Image.open(after_path).convert("RGB")

        # Resize to same size if different
        if before.size != after.size:
            after = after.resize(before.size, Image.LANCZOS)

        diff = ImageChops.difference(before, after)

        # Calculate changed percentage
        pixels = list(diff.getdata())
        changed = sum(1 for r, g, b in pixels if r + g + b > 30)
        total = len(pixels)
        diff_pct = round((changed / total) * 100, 2)

        # Save diff image (amplified)
        diff_enhanced = diff.point(lambda p: min(255, p * 10))
        ts = int(time.time())
        diff_path = os.path.join(VERIFY_DIR, f"diff_{ts}.png")
        diff_enhanced.save(diff_path)

        return {
            "success": True,
            "diff_percent": diff_pct,
            "changed_pixels": changed,
            "total_pixels": total,
            "diff_image": diff_path,
            "changed": diff_pct > 0.5,  # >0.5% changed = something happened
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# VISION LLM ANALYSIS
# =============================================================================

def _encode_image_for_api(path: str) -> Optional[str]:
    """Load image and encode as base64 for vision API."""
    try:
        if PIL_AVAILABLE:
            img = Image.open(path).convert("RGB")
            if img.width > 1280:
                ratio = 1280 / img.width
                img = img.resize((1280, int(img.height * ratio)), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=85)
            return base64.b64encode(buf.getvalue()).decode()
        else:
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode()
    except Exception:
        return None


def llm_diff_analysis(
    before_path: str,
    after_path: str,
    description: str = "UI change",
) -> Dict:
    """
    Send before + after screenshots to vision LLM and ask it to describe the diff.
    Uses Gemini Vision or GPT-4V depending on what's configured.
    """
    try:
        from llm_engine import call_llm_vision
    except ImportError:
        return {"success": False, "error": "llm_engine not available"}

    before_b64 = _encode_image_for_api(before_path)
    after_b64  = _encode_image_for_api(after_path)

    if not before_b64 or not after_b64:
        return {"success": False, "error": "Could not encode screenshots"}

    prompt = f"""You are a UI verification expert. I'm showing you two screenshots.
BEFORE: The original UI state (first image)
AFTER: The UI after a {description} was applied (second image)

Please analyze:
1. What visually changed between before and after?
2. Did the change look successful? (new elements appeared, layout shifted, etc.)
3. Are there any visible errors, broken layouts, or unexpected changes?
4. Rate the change: "SUCCESS" / "PARTIAL" / "FAILED" / "NO_CHANGE"

Be specific and concise. Focus on actual UI differences."""

    try:
        analysis = call_llm_vision(
            prompt=prompt,
            images=[
                {"data": before_b64, "media_type": "image/jpeg"},
                {"data": after_b64,  "media_type": "image/jpeg"},
            ],
        )

        # Parse rating from response
        rating = "UNKNOWN"
        text_upper = analysis.upper()
        for r in ["SUCCESS", "PARTIAL", "FAILED", "NO_CHANGE"]:
            if r in text_upper:
                rating = r
                break

        return {
            "success": True,
            "analysis": analysis,
            "rating": rating,
            "before": before_path,
            "after": after_path,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# MAIN VERIFY FUNCTION
# =============================================================================

def verify_ui_change(
    action_fn: Optional[Callable] = None,
    action_delay: float = 2.0,
    description: str = "UI change",
    url: Optional[str] = None,
    use_llm: bool = True,
    region: Optional[Tuple[int, int, int, int]] = None,
) -> Dict:
    """
    Full verification flow:
    1. Take BEFORE screenshot
    2. Wait action_delay seconds (or call action_fn)
    3. Take AFTER screenshot
    4. Run pixel diff
    5. Optional: run LLM vision diff
    6. Return combined result

    Args:
        action_fn: Optional callable to run between before/after screenshots
        action_delay: Seconds to wait if no action_fn (e.g., after submitting code)
        description: Human-readable description of what changed
        url: If set, capture Playwright screenshot of this URL instead of screen
        use_llm: Whether to run vision LLM analysis
        region: Optional (x, y, w, h) to capture specific screen region
    """
    _log({"action": "verify_start", "description": description})

    # BEFORE screenshot
    if url:
        before = capture_url_screenshot(url, "before")
    elif region:
        before = _capture_region(*region, label="before")
    else:
        before = _capture_screen("before")

    if not before["success"]:
        return before

    # Execute action
    action_result = None
    if action_fn:
        try:
            action_result = action_fn()
        except Exception as e:
            action_result = {"error": str(e)}
        time.sleep(0.5)  # settle
    else:
        time.sleep(action_delay)

    # AFTER screenshot
    if url:
        after = capture_url_screenshot(url, "after")
    elif region:
        after = _capture_region(*region, label="after")
    else:
        after = _capture_screen("after")

    if not after["success"]:
        return after

    # Pixel diff
    diff = pixel_diff(before["path"], after["path"])

    # LLM analysis
    llm_result = None
    if use_llm and diff.get("changed", True):  # skip LLM if nothing changed
        llm_result = llm_diff_analysis(before["path"], after["path"], description)

    # Assemble result
    result = {
        "success": True,
        "description": description,
        "before_screenshot": before["path"],
        "after_screenshot": after["path"],
        "diff_percent": diff.get("diff_percent", 0),
        "changed": diff.get("changed", False),
        "diff_image": diff.get("diff_image"),
        "action_result": action_result,
        "llm_analysis": llm_result.get("analysis") if llm_result else None,
        "rating": llm_result.get("rating", "NO_LLM") if llm_result else "NO_LLM",
    }

    _log({
        "action": "verify_complete",
        "description": description,
        "diff_percent": diff.get("diff_percent", 0),
        "rating": result["rating"],
    })

    return result


# =============================================================================
# QUICK HELPERS
# =============================================================================

def quick_screenshot_diff(url: str = None, wait: float = 3.0) -> Dict:
    """
    Simple before/after diff with no action — just wait and check if page changed.
    Useful for monitoring dynamic pages.
    """
    return verify_ui_change(
        action_delay=wait,
        description="page change check",
        url=url,
        use_llm=False,
    )


def verify_code_patch(url: str, description: str = "code patch") -> Dict:
    """
    Take before screenshot of a URL, wait for server to reload, then take after.
    Used by self_modify.py after patching a file.
    """
    before = capture_url_screenshot(url, "before")
    if not before["success"]:
        return before

    time.sleep(3)  # wait for Flask reload

    after = capture_url_screenshot(url, "after")
    if not after["success"]:
        return after

    diff = pixel_diff(before["path"], after["path"])
    llm_result = llm_diff_analysis(before["path"], after["path"], description)

    return {
        "success": True,
        "before": before["path"],
        "after": after["path"],
        "diff_percent": diff.get("diff_percent", 0),
        "changed": diff.get("changed", False),
        "analysis": llm_result.get("analysis") if llm_result else None,
        "rating": llm_result.get("rating", "NO_LLM") if llm_result else "NO_LLM",
    }


def take_labeled_screenshot(label: str = "manual") -> Dict:
    """Just take a labeled screenshot and return path + b64."""
    result = _capture_screen(label)
    if "image" in result:
        del result["image"]  # remove non-serializable PIL object
    return result
