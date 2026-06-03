"""
screen_engine.py — Real-Time Screen Vision + OCR for Ultron-J BEYOND JARVIS.

Capabilities:
- Continuous screen capture loop (configurable FPS)
- OCR: extract all text visible on screen right now
- Vision LLM: "what's on my screen?" sent to Gemini/GPT-4V
- Change detection: alert when screen content changes significantly
- Error detector: spot Python tracebacks, error dialogs, red text
- Active window tracking: know what app Jeevan is using
- Clip region: OCR/vision only a portion of the screen
- Screenshot on demand

BEYOND JARVIS: Ultron watches your screen like FRIDAY.
It sees your errors before you ask, reads documents you open,
and notices when you're stuck.
"""

import base64
import io
import json
import os
import re
import threading
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

_BASE_DIR          = os.path.dirname(os.path.abspath(__file__))
SCREEN_LOG_FILE    = os.path.join(_BASE_DIR, "screen_log.json")
SCREEN_CACHE_DIR   = os.path.join(_BASE_DIR, "screen_cache")

os.makedirs(SCREEN_CACHE_DIR, exist_ok=True)

# ── Optional imports ──────────────────────────────────────────────────────────
try:
    from PIL import Image, ImageGrab, ImageFilter
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

if OCR_AVAILABLE:
    import platform as _plat, os as _os, shutil as _shutil
    if _plat.system() == "Windows" and not _shutil.which("tesseract"):
        for _tess_path in [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]:
            if _os.path.exists(_tess_path):
                pytesseract.pytesseract.tesseract_cmd = _tess_path
                print(f"[ScreenEngine] Tesseract bound to {_tess_path}")
                break

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

# ── Active window (platform-specific) ─────────────────────────────────────────
import platform
_PLATFORM = platform.system()

def get_active_window_title() -> str:
    try:
        if _PLATFORM == "Windows":
            import ctypes
            hwnd  = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd) + 1
            buf   = ctypes.create_unicode_buffer(length)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length)
            return buf.value
        elif _PLATFORM == "Darwin":
            import subprocess
            script = 'tell application "System Events" to get name of first application process whose frontmost is true'
            return subprocess.check_output(["osascript", "-e", script]).decode().strip()
        elif _PLATFORM == "Linux":
            import subprocess
            return subprocess.check_output(["xdotool", "getactivewindow", "getwindowname"]).decode().strip()
    except Exception:
        pass
    return "Unknown"


# =============================================================================
# SCREENSHOT
# =============================================================================

def take_screenshot(region: Optional[Tuple[int,int,int,int]] = None,
                    save: bool = False) -> Optional["Image.Image"]:
    """Capture screen. region = (x, y, w, h). Returns PIL Image."""
    if not PIL_AVAILABLE:
        return None
    try:
        if region:
            x, y, w, h = region
            img = ImageGrab.grab(bbox=(x, y, x+w, y+h))
        else:
            img = ImageGrab.grab()
        if save:
            path = os.path.join(SCREEN_CACHE_DIR, f"screen_{int(time.time())}.png")
            img.save(path)
        return img
    except Exception as e:
        print(f"[ScreenEngine] Screenshot failed: {e}")
        return None


def screenshot_as_base64(region: Optional[Tuple] = None) -> Optional[str]:
    """Return screenshot as base64 JPEG string for vision API."""
    img = take_screenshot(region)
    if img is None:
        return None
    try:
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=70)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


# =============================================================================
# OCR
# =============================================================================

def ocr_screen(region: Optional[Tuple] = None, lang: str = "eng") -> Dict:
    """Extract all text from screen via Tesseract OCR."""
    if not OCR_AVAILABLE:
        return {"success": False, "error": "pytesseract not installed. pip install pytesseract"}
    if not PIL_AVAILABLE:
        return {"success": False, "error": "Pillow not installed."}

    img = take_screenshot(region)
    if img is None:
        return {"success": False, "error": "Screenshot failed"}

    try:
        # Preprocess for better OCR
        gray = img.convert("L")
        data = pytesseract.image_to_data(gray, lang=lang,
                                          output_type=pytesseract.Output.DICT)
        words = [w for w, c in zip(data["text"], data["conf"])
                 if str(w).strip() and int(c) > 40]
        full_text = " ".join(words)

        return {
            "success":     True,
            "text":        full_text,
            "word_count":  len(words),
            "window":      get_active_window_title(),
            "timestamp":   datetime.now().isoformat(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def ocr_region(x: int, y: int, w: int, h: int) -> Dict:
    return ocr_screen(region=(x, y, w, h))


# =============================================================================
# ERROR DETECTOR
# =============================================================================

_ERROR_PATTERNS = [
    r"Traceback \(most recent call last\)",
    r"Error:\s+\w+",
    r"Exception:\s+\w+",
    r"FAILED|FAILURE|ERROR|CRITICAL",
    r"\d{3}\s+Internal Server Error",
    r"Permission denied",
    r"FileNotFoundError",
    r"SyntaxError",
    r"ModuleNotFoundError",
]

def detect_errors_on_screen() -> Dict:
    """OCR the screen and look for error patterns."""
    result = ocr_screen()
    if not result["success"]:
        return result

    text    = result["text"]
    found   = []
    for pattern in _ERROR_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            start = max(0, match.start() - 40)
            end   = min(len(text), match.end() + 100)
            found.append({
                "pattern": pattern,
                "context": text[start:end].strip(),
            })

    return {
        "success":       True,
        "errors_found":  len(found) > 0,
        "errors":        found,
        "window":        result.get("window", ""),
        "full_text":     text[:2000],
    }


# =============================================================================
# CHANGE DETECTION
# =============================================================================

_last_screen_hash: Optional[str] = None
_change_callbacks: List[Callable] = []

def _image_hash(img: "Image.Image", size: int = 8) -> str:
    """Perceptual hash of image for change detection."""
    try:
        small = img.convert("L").resize((size, size), Image.LANCZOS)
        pixels = list(small.getdata())
        avg   = sum(pixels) / len(pixels)
        bits  = "".join("1" if p > avg else "0" for p in pixels)
        return hex(int(bits, 2))[2:]
    except Exception:
        return ""


def on_screen_change(callback: Callable):
    """Register a callback for screen change events."""
    _change_callbacks.append(callback)


# =============================================================================
# VISION LLM ANALYSIS
# =============================================================================

def analyze_screen_with_vision(llm_vision_fn, prompt: str = None,
                                region: Optional[Tuple] = None) -> Dict:
    """
    Send current screen to a vision LLM.
    llm_vision_fn(base64_image, prompt) → str
    """
    b64 = screenshot_as_base64(region)
    if not b64:
        return {"success": False, "error": "Screenshot failed"}

    default_prompt = (
        "You are Ultron-J, a personal AI. Describe what is on the screen "
        "in 2-3 sentences. Note any errors, important content, or what the "
        "user appears to be working on."
    )
    try:
        response = llm_vision_fn(b64, prompt or default_prompt)
        _log({"action": "vision_analysis", "prompt": prompt})
        return {"success": True, "analysis": response, "timestamp": datetime.now().isoformat()}
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# CONTINUOUS MONITOR LOOP
# =============================================================================

_monitor_thread:  Optional[threading.Thread] = None
_monitor_running: bool = False
_monitor_interval: float = 3.0    # seconds between checks
# OCR is expensive (full-screen Tesseract pass); throttle to at most one run per
# this many seconds, independent of _monitor_interval. Changing the monitor
# interval no longer changes OCR cadence — they are decoupled by design.
_OCR_MIN_INTERVAL: float = 6.0
_latest_ocr_text: str = ""
_latest_window:   str = ""


def start_screen_monitor(interval: float = 3.0,
                          on_error_detected: Optional[Callable] = None,
                          on_window_change:  Optional[Callable] = None):
    """
    Start background screen monitor.
    - Checks for errors every `interval` seconds
    - Calls on_error_detected(errors) if errors found
    - Calls on_window_change(old, new) on app switch
    """
    global _monitor_thread, _monitor_running, _monitor_interval
    # Phase 4.1 — gate through loop_supervisor / config.LOOPS. Screen
    # monitor takes screenshots + runs OCR — defaults OFF in the registry.
    from loop_supervisor import loop_enabled, loop_interval_s, should_skip_heavy_tick
    if not loop_enabled("screen_monitor"):
        print("[ScreenEngine] loop disabled by config.LOOPS — not starting")
        return
    interval = loop_interval_s("screen_monitor", interval)
    if _monitor_running:
        return

    _monitor_interval = interval
    _monitor_running  = True

    def _loop():
        global _last_screen_hash, _latest_ocr_text, _latest_window
        _last_ocr_at = 0.0

        while _monitor_running:
            # Phase 4.2 — skip OCR + screenshot tick under memory backpressure
            if should_skip_heavy_tick():
                time.sleep(_monitor_interval)
                continue
            try:
                # Active window check
                current_window = get_active_window_title()
                if current_window != _latest_window and on_window_change:
                    on_window_change(_latest_window, current_window)
                _latest_window = current_window

                # OCR + error detection — throttled by _OCR_MIN_INTERVAL because
                # Tesseract over a full screen is CPU-expensive. The window /
                # change-detection block below still runs every cycle.
                now = time.time()
                if OCR_AVAILABLE and (now - _last_ocr_at) >= _OCR_MIN_INTERVAL:
                    err_result = detect_errors_on_screen()
                    if err_result.get("errors_found") and on_error_detected:
                        on_error_detected(err_result["errors"])
                    _latest_ocr_text = err_result.get("full_text", "")
                    _last_ocr_at = now

                # Change detection
                if PIL_AVAILABLE:
                    img = take_screenshot()
                    if img:
                        h = _image_hash(img)
                        if h != _last_screen_hash and _last_screen_hash is not None:
                            for cb in _change_callbacks:
                                try:
                                    cb(img)
                                except Exception:
                                    pass
                        _last_screen_hash = h

            except Exception as e:
                print(f"[ScreenEngine] Monitor loop error: {e}")

            time.sleep(_monitor_interval)

    _monitor_thread = threading.Thread(target=_loop, daemon=True, name="screen_monitor")
    _monitor_thread.start()
    print(f"[ScreenEngine] Monitor started - interval={interval}s, "
          f"OCR={'Y' if OCR_AVAILABLE else 'N'}, "
          f"PIL={'Y' if PIL_AVAILABLE else 'N'}")


def stop_screen_monitor():
    global _monitor_running
    _monitor_running = False


def get_screen_status() -> Dict:
    return {
        "monitor_running":   _monitor_running,
        "ocr_available":     OCR_AVAILABLE,
        "pil_available":     PIL_AVAILABLE,
        "pyautogui_available": PYAUTOGUI_AVAILABLE,
        "cv2_available":     CV2_AVAILABLE,
        "active_window":     _latest_window,
        "last_ocr_chars":    len(_latest_ocr_text),
        "platform":          _PLATFORM,
    }


def get_latest_screen_text() -> str:
    return _latest_ocr_text


# =============================================================================
# LOG
# =============================================================================

_log_lock = threading.Lock()

def _log(data: dict):
    with _log_lock:
        try:
            log = []
            if os.path.exists(SCREEN_LOG_FILE):
                with open(SCREEN_LOG_FILE) as f:
                    log = json.load(f)
            log.append({"ts": datetime.now().isoformat(), **data})
            if len(log) > 200:
                log = log[-200:]
            with open(SCREEN_LOG_FILE, "w") as f:
                json.dump(log, f, indent=2)
        except Exception:
            pass
