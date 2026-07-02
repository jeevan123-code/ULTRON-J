"""
computer_control.py — Computer Control Engine for Ultron-J
Jeevan's AI can now SEE your screen and CONTROL your computer.

CAPABILITIES:
- Screenshot + describe screen
- Type text anywhere
- Click / double-click / right-click
- Scroll
- Open URLs in browser
- Open applications
- Read/write clipboard
- Hotkeys and key combos
- Find image on screen and click it
- Get active window title
- Send email via Gmail SMTP

SAFETY:
- All actions logged to computer_action_log.json
- Destructive actions (delete, format) are blocked
- Jeevan must approve any file system changes via /computer/approve
"""

import os
import sys
import json
import time
import base64
import platform
import subprocess
import threading
import webbrowser
import smtplib
import io
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ─────────────────────────────────────────────────────────────────────────────
# OPTIONAL IMPORTS
# ─────────────────────────────────────────────────────────────────────────────
try:
    import pyautogui
    pyautogui.FAILSAFE = True          # move mouse to top-left to abort
    pyautogui.PAUSE    = 0.05          # small pause between actions
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

try:
    from PIL import Image, ImageGrab
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import pyperclip
    PYPERCLIP_AVAILABLE = True
except ImportError:
    PYPERCLIP_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
_BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
ACTION_LOG_FILE = os.path.join(_BASE_DIR, "computer_action_log.json")


def _resolve_desktop_dir() -> Path:
    onedrive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer") or os.environ.get("OneDriveCommercial")
    if onedrive:
        candidate = Path(onedrive) / "Desktop"
        if candidate.is_dir():
            return candidate
    return Path.home() / "Desktop"


_SCREENSHOT_DIR = _resolve_desktop_dir() / "ultron_screenshots"
_log_lock       = threading.Lock()

try:
    from config import (
        GMAIL_USER, GMAIL_APP_PASSWORD,
        COMPUTER_CONTROL_ENABLED,
    )
except ImportError:
    GMAIL_USER               = os.environ.get("GMAIL_USER", "")
    GMAIL_APP_PASSWORD       = os.environ.get("GMAIL_APP_PASSWORD", "")
    COMPUTER_CONTROL_ENABLED = True

# Blocked commands for safety
BLOCKED_COMMANDS = [
    "rm -rf", "format", "del /f", "rmdir /s", ":(){:|:&};:",
    "shutdown", "reboot", "mkfs", "dd if=",
]

# =============================================================================
# ACTION LOG
# =============================================================================

def _log_action(action: str, params: dict, result: dict):
    entry = {
        "timestamp": datetime.now().isoformat(),
        "action":    action,
        "params":    {k: str(v)[:200] for k, v in params.items()},
        "success":   result.get("success", False),
        "error":     result.get("error", ""),
    }
    with _log_lock:
        try:
            log = []
            if os.path.exists(ACTION_LOG_FILE):
                with open(ACTION_LOG_FILE, "r", encoding="utf-8") as f:
                    log = json.load(f)
            log.append(entry)
            log = log[-200:]
            with open(ACTION_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(log, f, indent=2)
        except Exception:
            pass


def get_action_log(n: int = 20) -> list:
    try:
        with open(ACTION_LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)[-n:]
    except Exception:
        return []

# =============================================================================
# SCREEN — SCREENSHOT
# =============================================================================

def _play_shutter_sound():
    try:
        import winsound
        wav = r"C:\Windows\Media\Windows Print screen.wav"
        if os.path.exists(wav):
            winsound.PlaySound(wav, winsound.SND_FILENAME | winsound.SND_ASYNC)
        else:
            winsound.MessageBeep(winsound.MB_OK)
    except Exception:
        pass


def _show_capture_flash():
    flash_script = (
        "import tkinter as tk;"
        "r=tk.Tk();"
        "r.attributes('-fullscreen', True);"
        "r.attributes('-alpha', 0.5);"
        "r.attributes('-topmost', True);"
        "r.configure(bg='white');"
        "r.overrideredirect(True);"
        "r.after(120, r.destroy);"
        "r.mainloop()"
    )
    try:
        # The flash is purely cosmetic. Detach it fully: redirect its std
        # streams to DEVNULL so it can't hold the parent's inherited stdout/
        # stderr pipe open (which blocks any reader — a shell pipe or a Flask
        # response stream — if the tkinter mainloop fails to self-destruct on
        # some window managers), and start_new_session so it never keeps the
        # parent's process session / fds alive.
        subprocess.Popen(
            [sys.executable, "-c", flash_script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass


def _ask_save_path(default_name: str, initial_dir: str) -> str:
    dialog_script = (
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "r = tk.Tk()\n"
        "r.withdraw()\n"
        "r.attributes('-topmost', True)\n"
        "p = filedialog.asksaveasfilename(\n"
        "    defaultextension='.png',\n"
        "    filetypes=[('PNG image', '*.png'), ('All files', '*.*')],\n"
        f"    initialfile={default_name!r},\n"
        f"    initialdir={initial_dir!r},\n"
        "    title='Save screenshot as...'\n"
        ")\n"
        "print(p or '', end='')\n"
    )
    try:
        out = subprocess.run(
            [sys.executable, "-c", dialog_script],
            capture_output=True, text=True, timeout=120,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def _open_in_file_manager(filepath: Path):
    try:
        if platform.system() == "Windows":
            subprocess.Popen(["explorer", "/select,", str(filepath)])
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", "-R", str(filepath)])
        else:
            subprocess.Popen(["xdg-open", str(filepath.parent)])
    except Exception:
        pass


def take_screenshot(region: Optional[Tuple] = None, prompt_save: bool = False,
                    save_path: str = None) -> Dict:
    """
    Capture the screen.
    region: optional (left, top, width, height)
    save_path: explicit file or directory path to save the screenshot to.
               If it's a directory, a timestamped filename is used inside it.
               If None, saves to ~/Desktop/ultron_screenshots/screenshot_TIMESTAMP.png.
    prompt_save: if True and save_path is None, opens a Save As dialog (Windows only).
    """
    result = {"success": False}
    try:
        img = None
        if PIL_AVAILABLE:
            try:
                img = ImageGrab.grab(bbox=region)
            except Exception:
                img = None
        if img is None and PYAUTOGUI_AVAILABLE:
            img = pyautogui.screenshot(region=region)
        if img is None:
            return {"success": False, "error": "Screenshot failed: install pillow (pip install pillow)"}

        _play_shutter_sound()
        _show_capture_flash()

        if img.width > 1280:
            ratio = 1280 / img.width
            img   = img.resize((1280, int(img.height * ratio)), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        image_b64 = base64.b64encode(buf.getvalue()).decode()

        ts           = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"screenshot_{ts}.png"

        # Resolve where to save
        if save_path:
            sp = Path(os.path.expandvars(os.path.expanduser(save_path)))
            if sp.is_dir() or (not sp.suffix):
                sp.mkdir(parents=True, exist_ok=True)
                filepath = sp / default_name
            else:
                filepath = sp
                filepath.parent.mkdir(parents=True, exist_ok=True)
            img.save(str(filepath), format="PNG")
            cancelled = False
        elif prompt_save:
            _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            chosen = _ask_save_path(default_name, str(_SCREENSHOT_DIR))
            if chosen:
                filepath = Path(chosen)
                filepath.parent.mkdir(parents=True, exist_ok=True)
                img.save(str(filepath), format="PNG")
                cancelled = False
                _open_in_file_manager(filepath)
            else:
                filepath = _SCREENSHOT_DIR / default_name
                img.save(str(filepath), format="PNG")
                cancelled = True
        else:
            _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            filepath = _SCREENSHOT_DIR / default_name
            img.save(str(filepath), format="PNG")
            cancelled = False

        result = {
            "success":   True,
            "image_b64": image_b64,
            "format":    "image/png",
            "size":      list(img.size),
            "path":      str(filepath),
            "filename":  filepath.name,
            "cancelled": cancelled if not save_path else False,
            "message":   f"Screenshot saved to {filepath}",
        }
    except Exception as e:
        result = {"success": False, "error": str(e)}

    _log_action("screenshot", {"region": str(region), "save_path": save_path or ""}, result)
    return result


def get_screen_size() -> Dict:
    """Return the screen resolution."""
    try:
        if PYAUTOGUI_AVAILABLE:
            w, h = pyautogui.size()
            return {"success": True, "width": w, "height": h}
        return {"success": False, "error": "pyautogui not installed"}
    except Exception as e:
        return {"success": False, "error": str(e)}

# =============================================================================
# MOUSE — CLICK, MOVE, SCROLL
# =============================================================================

def click(x: int, y: int, button: str = "left", clicks: int = 1) -> Dict:
    """
    Click at screen coordinates.
    button: "left", "right", "middle"
    clicks: 1 for single, 2 for double
    """
    result = {"success": False}
    if not PYAUTOGUI_AVAILABLE:
        return {"success": False, "error": "pyautogui not installed. pip install pyautogui"}
    try:
        pyautogui.click(x, y, button=button, clicks=clicks, interval=0.1)
        result = {"success": True, "x": x, "y": y, "button": button, "clicks": clicks}
    except Exception as e:
        result = {"success": False, "error": str(e)}
    _log_action("click", {"x": x, "y": y, "button": button}, result)
    return result


def move_mouse(x: int, y: int, duration: float = 0.3) -> Dict:
    """Move mouse to coordinates smoothly."""
    if not PYAUTOGUI_AVAILABLE:
        return {"success": False, "error": "pyautogui not installed"}
    try:
        pyautogui.moveTo(x, y, duration=duration)
        return {"success": True, "x": x, "y": y}
    except Exception as e:
        return {"success": False, "error": str(e)}


def scroll(direction: str = "down", clicks: int = 3, x: int = None, y: int = None) -> Dict:
    """
    Scroll the mouse wheel.
    direction: "up" or "down"
    clicks: number of scroll units
    """
    result = {"success": False}
    if not PYAUTOGUI_AVAILABLE:
        return {"success": False, "error": "pyautogui not installed"}
    try:
        amount = clicks if direction == "up" else -clicks
        if x and y:
            pyautogui.scroll(amount, x=x, y=y)
        else:
            pyautogui.scroll(amount)
        result = {"success": True, "direction": direction, "clicks": clicks}
    except Exception as e:
        result = {"success": False, "error": str(e)}
    _log_action("scroll", {"direction": direction, "clicks": clicks}, result)
    return result

# =============================================================================
# KEYBOARD — TYPE, HOTKEYS
# =============================================================================

def type_text(text: str, interval: float = 0.02) -> Dict:
    """
    Type text as keyboard input at the current cursor position.
    Works in any focused text field.
    """
    result = {"success": False}
    if not PYAUTOGUI_AVAILABLE:
        return {"success": False, "error": "pyautogui not installed"}
    if not text:
        return {"success": False, "error": "No text provided"}
    try:
        # Use pyperclip + paste for longer text (faster, handles unicode)
        if PYPERCLIP_AVAILABLE and len(text) > 20:
            old_clipboard = ""
            try:
                old_clipboard = pyperclip.paste()
            except Exception:
                pass
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.1)
            try:
                pyperclip.copy(old_clipboard)
            except Exception:
                pass
        else:
            pyautogui.typewrite(text, interval=interval)
        result = {"success": True, "chars_typed": len(text)}
    except Exception as e:
        result = {"success": False, "error": str(e)}
    _log_action("type_text", {"text_preview": text[:50]}, result)
    return result


def press_key(key: str) -> Dict:
    """
    Press a single key (e.g., 'enter', 'escape', 'tab', 'f5').
    """
    result = {"success": False}
    if not PYAUTOGUI_AVAILABLE:
        return {"success": False, "error": "pyautogui not installed"}
    try:
        pyautogui.press(key)
        result = {"success": True, "key": key}
    except Exception as e:
        result = {"success": False, "error": str(e)}
    _log_action("press_key", {"key": key}, result)
    return result


def hotkey(*keys: str) -> Dict:
    """
    Press a key combination (e.g., hotkey("ctrl", "c") for copy).
    """
    result = {"success": False}
    if not PYAUTOGUI_AVAILABLE:
        return {"success": False, "error": "pyautogui not installed"}
    try:
        pyautogui.hotkey(*keys)
        result = {"success": True, "keys": list(keys)}
    except Exception as e:
        result = {"success": False, "error": str(e)}
    _log_action("hotkey", {"keys": list(keys)}, result)
    return result

# =============================================================================
# CLIPBOARD
# =============================================================================

def get_clipboard() -> Dict:
    """Read current clipboard content."""
    if not PYPERCLIP_AVAILABLE:
        return {"success": False, "error": "pyperclip not installed"}
    try:
        content = pyperclip.paste()
        return {"success": True, "content": content, "length": len(content)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def set_clipboard(text: str) -> Dict:
    """Write text to clipboard."""
    if not PYPERCLIP_AVAILABLE:
        return {"success": False, "error": "pyperclip not installed"}
    try:
        pyperclip.copy(text)
        return {"success": True, "length": len(text)}
    except Exception as e:
        return {"success": False, "error": str(e)}

# =============================================================================
# APPS & BROWSER
# =============================================================================

def open_url(url: str, browser: str = None) -> Dict:
    """Open URL in specified browser, or default if None."""
    import webbrowser
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    system = platform.system()

    if browser:
        browser = browser.lower().strip()
        browsers_win = {
            "brave":   r'C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe',
            "chrome":  r'C:\Program Files\Google\Chrome\Application\chrome.exe',
            "edge":    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
            "firefox": r'C:\Program Files\Mozilla Firefox\firefox.exe',
        }
        browsers_linux = {
            "brave":   ["brave-browser", "brave"],
            "chrome":  ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"],
            "firefox": ["firefox"],
            "edge":    ["microsoft-edge", "microsoft-edge-stable"],
            "opera":   ["opera"],
        }
        if system == "Windows" and browser in browsers_win:
            exe = browsers_win[browser]
            if not os.path.exists(exe):
                alt = exe.replace("Program Files\\", "Program Files (x86)\\")
                if os.path.exists(alt):
                    exe = alt
                else:
                    alt2 = exe.replace("Program Files (x86)\\", "Program Files\\")
                    if os.path.exists(alt2):
                        exe = alt2
            if os.path.exists(exe):
                try:
                    subprocess.Popen([exe, url])
                    result = {"success": True, "url": url, "browser": browser}
                    _log_action("open_url", {"url": url, "browser": browser}, result)
                    return result
                except Exception:
                    pass  # fall through to shell
            try:
                # Phase 7.4 — quote interpolated values. browser + url
                # can both come from an LLM; `start` is a cmd.exe
                # built-in so we can't drop shell=True here.
                import shlex
                subprocess.Popen(
                    f'start {shlex.quote(browser)} "{shlex.quote(url)}"',
                    shell=True,
                )
                result = {"success": True, "url": url, "browser": browser, "method": "shell"}
                _log_action("open_url", {"url": url, "browser": browser}, result)
                return result
            except Exception:
                pass
        elif system in ("Linux", "Darwin"):
            candidates = browsers_linux.get(browser, [browser])
            autoplay_flag = "--autoplay-policy=no-user-gesture-required"
            chromium_family = {"brave", "chrome", "edge", "opera"}
            for candidate in candidates:
                if shutil.which(candidate):
                    try:
                        args = [candidate, autoplay_flag, url] if browser in chromium_family else [candidate, url]
                        subprocess.Popen(args)
                        result = {"success": True, "url": url, "browser": browser, "method": "exec"}
                        _log_action("open_url", {"url": url, "browser": browser}, result)
                        return result
                    except Exception:
                        pass
            # Fall through to default if named browser not found

    # No browser specified (or named browser not found) → default
    try:
        webbrowser.open(url)
        result = {"success": True, "url": url, "browser": browser or "default"}
    except Exception as e:
        result = {"success": False, "error": str(e)}
    _log_action("open_url", {"url": url}, result)
    return result


# ── Known Windows app aliases ────────────────────────────────────────────────
_WIN_APPS = {
    "chrome":        'start chrome',
    "google chrome": 'start chrome',
    "firefox":       'start firefox',
    "edge":          'start msedge',
    "notepad":       'start notepad',
    "calculator":    'start calc',
    "explorer":      'start explorer',
    "file manager":  'start explorer',
    "files":         'start explorer',
    "cmd":           'start cmd',
    "terminal":      'start cmd',
    "vs code":       'start code',
    "vscode":        'start code',
    "spotify":       'start spotify',
    "discord":       'start discord',
    "telegram":      'start telegram',
    "paint":         'start mspaint',
    "task manager":  'start taskmgr',
    "youtube":       'start chrome "https://www.youtube.com"',
    "claude":        'start chrome "https://claude.ai"',
    "chatgpt":       'start chrome "https://chat.openai.com"',
    "google":        'start chrome "https://www.google.com"',
    "github":        'start chrome "https://github.com"',
    "whatsapp":      'start chrome "https://web.whatsapp.com"',
    "antigravity":   'start python -c "import antigravity"',
}

# ── Dynamic Start Menu scanner (discovers every installed app) ────────────────
_app_cache: dict = {}
_app_cache_time: float = 0.0

def _get_installed_apps() -> dict:
    """
    Scan Windows Start Menu shortcuts and return {lowercase_name: lnk_path}.
    Result is cached for 5 minutes so new installs are picked up automatically.
    """
    import time, glob as _glob
    global _app_cache, _app_cache_time
    if _app_cache and (time.time() - _app_cache_time) < 300:
        return _app_cache
    apps: dict = {}
    dirs = [
        os.path.expandvars(r'%ProgramData%\Microsoft\Windows\Start Menu\Programs'),
        os.path.expandvars(r'%APPDATA%\Microsoft\Windows\Start Menu\Programs'),
    ]
    for d in dirs:
        for lnk in _glob.glob(os.path.join(d, '**', '*.lnk'), recursive=True):
            name = os.path.splitext(os.path.basename(lnk))[0].lower().strip()
            apps[name] = lnk
    _app_cache = apps
    _app_cache_time = time.time()
    return apps


def open_app(app_name: str) -> Dict:
    """Open any app or file by name. Searches aliases, Start Menu, then falls back to shell."""
    result   = {"success": False}
    system   = platform.system()
    app_name = app_name.strip()
    key      = app_name.lower()

    # Safety: block dangerous commands
    for blocked in BLOCKED_COMMANDS:
        if blocked.lower() in key:
            return {"success": False, "error": f"Blocked command: {blocked}"}

    # If it looks like a file path, open it directly
    if os.path.exists(app_name):
        try:
            os.startfile(app_name)
            return {"success": True, "app": app_name, "method": "file"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # Dynamic index lookup — covers any installed app/shortcut
    try:
        from system_index import find_app
        _idx_path = find_app(app_name)
        if _idx_path:
            if _idx_path.endswith(".lnk"):
                os.startfile(_idx_path)
            elif _idx_path.endswith(".exe"):
                subprocess.Popen([_idx_path])
            else:
                os.startfile(_idx_path)
            _log_action("open_app", {"app": app_name}, {"success": True})
            return {"success": True, "app": app_name,
                    "method": "sys_index", "path": _idx_path}
    except Exception:
        pass  # fall through to existing logic

    if system == "Windows":
        # 1. Hardcoded alias
        cmd = _WIN_APPS.get(key)
        if cmd:
            subprocess.Popen(cmd, shell=True)
            return {"success": True, "app": app_name, "method": "alias"}

        # 2. Start Menu scan — exact match, then word-boundary partial
        # match. The old `if key in name` partial match let 2-char pronouns
        # ("it", "or") hijack arbitrary app names by interior substring
        # (e.g. "it" → "speech recogn**it**ion"). Now we require the query
        # to match a whole word or a word prefix in the app name, AND to be
        # at least 3 chars long — so "code" still finds Visual Studio Code,
        # but "it" / "the" don't find anything.
        installed = _get_installed_apps()
        lnk = installed.get(key)
        if not lnk and len(key) >= 3 and key not in (
            "it", "that", "this", "the", "or", "and", "but",
            "one", "thing", "yes", "no", "is", "in", "on", "of", "to", "by",
        ):
            for name, path in installed.items():
                if any(w == key or w.startswith(key) for w in name.split()):
                    lnk = path
                    break
        if lnk:
            os.startfile(lnk)
            return {"success": True, "app": app_name, "method": "startmenu"}

        # 3. Web fallback for known web services (app-first, web-second)
        _WEB_SERVICES = {
            "chatgpt":    "https://chat.openai.com",
            "chat gpt":   "https://chat.openai.com",
            "claude":     "https://claude.ai",
            "gemini":     "https://gemini.google.com",
            "perplexity": "https://perplexity.ai",
            "github":     "https://github.com",
            "youtube":    "https://www.youtube.com",
            "whatsapp":   "https://web.whatsapp.com",
            "gmail":      "https://mail.google.com",
            "drive":      "https://drive.google.com",
            "maps":       "https://www.google.com/maps",
            "translate":  "https://translate.google.com",
            "spotify":    "https://open.spotify.com",
            "netflix":    "https://www.netflix.com",
        }
        _web_url = _WEB_SERVICES.get(key)
        if _web_url:
            try:
                import webbrowser
                webbrowser.open(_web_url)
                _log_action("open_app", {"app": app_name}, {"success": True})
                return {"success": True, "app": app_name,
                        "method": "web_fallback", "url": _web_url}
            except Exception as _we:
                return {"success": False, "error": str(_we)}

        # 4. Shell fallback — only if the exe is resolvable on PATH
        if shutil.which(app_name):
            try:
                # Phase 7.4 — app_name was validated by shutil.which but
                # quote it anyway: defense in depth, and the empty `""`
                # title argument stays literal.
                import shlex
                subprocess.Popen(
                    f'start "" "{shlex.quote(app_name)}"',
                    shell=True,
                )
                result = {"success": True, "app": app_name, "method": "shell"}
            except Exception as e:
                result = {"success": False, "error": str(e)}
        else:
            result = {"success": False, "error": f"App '{app_name}' not found"}

    elif system == "Darwin":
        try:
            subprocess.Popen(["open", "-a", app_name])
            result = {"success": True, "app": app_name, "os": system}
        except Exception as e:
            result = {"success": False, "error": str(e)}
    else:
        # Linux — resolve common app aliases first, then try the name directly.
        _LINUX_APPS = {
            "terminal":       ["gnome-terminal", "x-terminal-emulator", "xfce4-terminal", "xterm", "konsole", "tilix", "alacritty"],
            "the terminal":   ["gnome-terminal", "x-terminal-emulator", "xfce4-terminal", "xterm", "konsole"],
            "file manager":   ["nautilus", "thunar", "nemo", "dolphin"],
            "files":          ["nautilus", "thunar", "nemo", "dolphin"],
            "text editor":    ["gedit", "kate", "mousepad", "xed", "nano"],
            "calculator":     ["gnome-calculator", "kcalc", "galculator"],
            "task manager":   ["gnome-system-monitor", "htop", "ksysguard"],
            "system monitor": ["gnome-system-monitor", "htop"],
            "firefox":        ["firefox"],
            "chrome":         ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"],
            "brave":          ["brave-browser", "brave"],
            "brave browser":  ["brave-browser", "brave"],
            "vs code":        ["code"],
            "vscode":         ["code"],
            "discord":        ["discord"],
            "spotify":        ["spotify"],
            "vlc":            ["vlc"],
            "gimp":           ["gimp"],
        }
        _LINUX_WEB_APPS = {
            "youtube":   ("https://www.youtube.com", ["brave-browser", "brave", "google-chrome", "firefox"]),
            "google":    ("https://www.google.com",  ["brave-browser", "brave", "google-chrome", "firefox"]),
            "gmail":     ("https://mail.google.com", ["brave-browser", "brave", "google-chrome", "firefox"]),
            "claude":    ("https://claude.ai",        ["brave-browser", "brave", "google-chrome", "firefox"]),
            "chatgpt":   ("https://chat.openai.com", ["brave-browser", "brave", "google-chrome", "firefox"]),
            "github":    ("https://github.com",       ["brave-browser", "brave", "google-chrome", "firefox"]),
            "whatsapp":  ("https://web.whatsapp.com",["brave-browser", "brave", "google-chrome", "firefox"]),
        }
        if key in _LINUX_WEB_APPS:
            url, browsers = _LINUX_WEB_APPS[key]
            for b in browsers:
                if shutil.which(b):
                    try:
                        subprocess.Popen([b, url])
                        result = {"success": True, "app": key, "method": "web", "browser": b}
                        break
                    except Exception as e:
                        result = {"success": False, "error": str(e)}
            else:
                import webbrowser as _wb
                _wb.open(url)
                result = {"success": True, "app": key, "method": "webbrowser"}
        else:
            candidates = _LINUX_APPS.get(key, [app_name])
            for candidate in candidates:
                if shutil.which(candidate):
                    try:
                        subprocess.Popen([candidate])
                        result = {"success": True, "app": candidate, "os": system}
                        break
                    except Exception as e:
                        result = {"success": False, "error": str(e)}
            else:
                result = {"success": False, "error": f"Couldn't open '{app_name}': none of {candidates} found on PATH"}

    _log_action("open_app", {"app": app_name}, result)
    return result


def run_command(command: str, timeout: int = 10) -> Dict:
    """
    Run a shell command and return output.
    Dangerous commands are blocked.
    """
    for blocked in BLOCKED_COMMANDS:
        if blocked.lower() in command.lower():
            return {"success": False, "error": f"Blocked command contains: {blocked}"}

    result = {"success": False}
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        result = {
            "success":   proc.returncode == 0,
            "stdout":    proc.stdout[:2000],
            "stderr":    proc.stderr[:500],
            "returncode": proc.returncode,
        }
    except subprocess.TimeoutExpired:
        result = {"success": False, "error": f"Command timed out after {timeout}s"}
    except Exception as e:
        result = {"success": False, "error": str(e)}

    _log_action("run_command", {"command": command[:100]}, result)
    return result


def get_active_window() -> Dict:
    """Return the title of the currently focused window."""
    try:
        system = platform.system()
        if system == "Windows":
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf    = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            return {"success": True, "title": buf.value, "os": "windows"}
        elif system == "Darwin":
            script = 'tell application "System Events" to get name of first application process whose frontmost is true'
            result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
            return {"success": True, "title": result.stdout.strip(), "os": "mac"}
        else:
            result = subprocess.run(["xdotool", "getwindowfocus", "getwindowname"], capture_output=True, text=True)
            return {"success": True, "title": result.stdout.strip(), "os": "linux"}
    except Exception as e:
        return {"success": False, "error": str(e)}

# =============================================================================
# EMAIL — via Gmail SMTP
# =============================================================================

def send_email(to: str, subject: str, body: str, html: bool = False) -> Dict:
    """
    Send an email via Gmail SMTP.
    Requires GMAIL_USER and GMAIL_APP_PASSWORD in .env

    Get App Password: Google Account → Security → 2-Step Verification → App passwords
    """
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        return {
            "success": False,
            "error": "Set GMAIL_USER and GMAIL_APP_PASSWORD in .env to enable email.",
        }

    result = {"success": False}
    try:
        msg = MIMEMultipart("alternative")
        msg["From"]    = GMAIL_USER
        msg["To"]      = to
        msg["Subject"] = subject

        if html:
            msg.attach(MIMEText(body, "html"))
        else:
            msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, to, msg.as_string())

        result = {"success": True, "to": to, "subject": subject}
    except Exception as e:
        result = {"success": False, "error": str(e)}

    _log_action("send_email", {"to": to, "subject": subject}, result)
    return result

# =============================================================================
# COMPUTER STATUS
# =============================================================================

def get_computer_status() -> Dict:
    """Return capabilities of the computer control module."""
    return {
        "pyautogui":    PYAUTOGUI_AVAILABLE,
        "pil":          PIL_AVAILABLE,
        "pyperclip":    PYPERCLIP_AVAILABLE,
        "email":        bool(GMAIL_USER and GMAIL_APP_PASSWORD),
        "platform":     platform.system(),
        "screen_size":  get_screen_size() if PYAUTOGUI_AVAILABLE else {},
        "enabled":      COMPUTER_CONTROL_ENABLED,
    }


# =============================================================================
# HIGH-LEVEL ACTIONS — for agent use
# =============================================================================

def execute_computer_action(action: str, params: dict) -> Dict:
    """
    Unified dispatcher for computer actions.
    Called by action_engine.py

    Actions:
      screenshot, click, type, scroll, press_key, hotkey,
      open_url, open_app, run_command, get_clipboard, set_clipboard,
      send_email, get_window, get_status
    """
    if not COMPUTER_CONTROL_ENABLED:
        return {"success": False, "error": "Computer control is disabled in config"}

    action = action.lower().strip()

    if action == "screenshot":
        region    = params.get("region")
        save_path = params.get("save_path") or params.get("path")
        return take_screenshot(region, save_path=save_path)

    elif action == "click":
        # Phase 1.5 — coerce + bounds-check. pyautogui clamps coordinates
        # internally on most platforms, but a bad clicks value (e.g.
        # 1_000_000) would hammer the desktop for minutes. 4096 covers
        # any plausible monitor width/height; 10 clicks covers any sane
        # human double/triple-click chain.
        def _coord(name, lo, hi, default):
            try:
                v = int(params.get(name, default))
            except (TypeError, ValueError):
                return None
            return v if lo <= v <= hi else None
        x = _coord("x", 0, 4096, 0)
        y = _coord("y", 0, 4096, 0)
        clicks_n = _coord("clicks", 1, 10, 1)
        if x is None or y is None or clicks_n is None:
            return {"success": False,
                    "error": "x,y must be in [0,4096], clicks in [1,10]"}
        return click(
            x      = x,
            y      = y,
            button = params.get("button", "left"),
            clicks = clicks_n,
        )

    elif action in ("type", "type_text"):
        return type_text(
            text     = params.get("text", ""),
            interval = float(params.get("interval", 0.02)),
        )

    elif action == "scroll":
        return scroll(
            direction = params.get("direction", "down"),
            clicks    = int(params.get("clicks", 3)),
            x         = params.get("x"),
            y         = params.get("y"),
        )

    elif action == "press_key":
        return press_key(params.get("key", "enter"))

    elif action == "hotkey":
        keys = params.get("keys", [])
        if isinstance(keys, str):
            keys = keys.split("+")
        return hotkey(*keys)

    elif action == "open_url":
        return open_url(params.get("url", ""))

    elif action == "open_app":
        return open_app(params.get("app", ""))

    elif action == "run_command":
        return run_command(
            command = params.get("command", ""),
            timeout = int(params.get("timeout", 10)),
        )

    elif action == "get_clipboard":
        return get_clipboard()

    elif action == "set_clipboard":
        return set_clipboard(params.get("text", ""))

    elif action == "send_email":
        return send_email(
            to      = params.get("to", ""),
            subject = params.get("subject", ""),
            body    = params.get("body", ""),
            html    = bool(params.get("html", False)),
        )

    elif action == "get_window":
        return get_active_window()

    elif action == "get_status":
        return get_computer_status()

    elif action == "move_mouse":
        return move_mouse(
            x        = int(params.get("x", 0)),
            y        = int(params.get("y", 0)),
            duration = float(params.get("duration", 0.3)),
        )

    elif action == "smart_click":
        try:
            from screen_parser import click_element
            return click_element(params.get("element", ""))
        except Exception as e:
            return {"success": False, "error": str(e)}

    else:
        return {"success": False, "error": f"Unknown computer action: '{action}'"}
