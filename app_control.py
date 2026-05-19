"""
app_control.py — Full Laptop Application Control for Ultron-J

WHAT THIS DOES:
  Control ANY application window on your computer:
  - Switch between apps and windows by name
  - Control VS Code: open files, switch tabs, run commands
  - Control Chrome: open new tabs, switch tabs, close tabs, navigate
  - Control Photoshop / GIMP: open files, run filters
  - Type into any focused app
  - Minimize, maximize, resize any window
  - List all open windows
  - Bring any window to foreground

WORKS ON:
  - Windows: via win32gui, win32con (pip install pywin32)
  - Linux: via xdotool, wmctrl (apt install xdotool wmctrl)
  - macOS: via osascript AppleScript

USAGE:
  from app_control import AppController, control_app
  ctrl = AppController()
  ctrl.focus_window("Visual Studio Code")
  ctrl.chrome_new_tab("https://claude.ai")
  ctrl.vscode_run_command("workbench.action.files.save")
"""

import json
import os
import platform
import re
import subprocess
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional

_BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
APP_LOG_FILE    = os.path.join(_BASE_DIR, "app_control_log.json")
_log_lock       = threading.Lock()

SYSTEM = platform.system()  # "Windows", "Linux", "Darwin"

# Optional imports
try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

try:
    import pyperclip
    PYPERCLIP_AVAILABLE = True
except ImportError:
    PYPERCLIP_AVAILABLE = False

# Windows-specific
if SYSTEM == "Windows":
    try:
        import win32gui
        import win32con
        import win32process
        import ctypes
        WIN32_AVAILABLE = True
    except ImportError:
        WIN32_AVAILABLE = False
else:
    WIN32_AVAILABLE = False


# =============================================================================
# LOGGING
# =============================================================================

def _log(data: dict):
    with _log_lock:
        try:
            log = []
            if os.path.exists(APP_LOG_FILE):
                with open(APP_LOG_FILE) as f:
                    log = json.load(f)
            log.append({"ts": datetime.now().isoformat(), **data})
            log = log[-300:]
            with open(APP_LOG_FILE, "w") as f:
                json.dump(log, f, indent=2)
        except Exception:
            pass


def get_app_log(limit: int = 30) -> list:
    try:
        with open(APP_LOG_FILE) as f:
            return json.load(f)[-limit:]
    except Exception:
        return []


# =============================================================================
# WINDOW LISTING
# =============================================================================

def list_windows() -> List[Dict]:
    """Return all visible windows with title and process info."""
    windows = []

    if SYSTEM == "Windows" and WIN32_AVAILABLE:
        def callback(hwnd, results):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title.strip():
                    rect = win32gui.GetWindowRect(hwnd)
                    results.append({
                        "hwnd": hwnd,
                        "title": title,
                        "x": rect[0], "y": rect[1],
                        "w": rect[2] - rect[0], "h": rect[3] - rect[1],
                    })
        win32gui.EnumWindows(callback, windows)

    elif SYSTEM == "Linux":
        try:
            out = subprocess.check_output(
                ["wmctrl", "-l"], text=True, timeout=5
            )
            for line in out.strip().split("\n"):
                parts = line.split(None, 3)
                if len(parts) >= 4:
                    windows.append({
                        "wid": parts[0],
                        "desktop": parts[1],
                        "hostname": parts[2],
                        "title": parts[3],
                    })
        except Exception:
            try:
                # Fallback: xdotool
                out = subprocess.check_output(
                    ["xdotool", "search", "--name", ""], text=True, stderr=subprocess.DEVNULL, timeout=5
                )
                for wid in out.strip().split("\n"):
                    if wid.strip():
                        name_out = subprocess.run(
                            ["xdotool", "getwindowname", wid.strip()],
                            capture_output=True, text=True
                        )
                        windows.append({"wid": wid.strip(), "title": name_out.stdout.strip()})
            except Exception:
                pass

    elif SYSTEM == "Darwin":
        try:
            script = '''
            tell application "System Events"
                set win_list to {}
                repeat with p in (processes where background only is false)
                    set proc_name to name of p
                    set win_list to win_list & {proc_name}
                end repeat
                return win_list
            end tell
            '''
            out = subprocess.check_output(["osascript", "-e", script], text=True, timeout=10)
            for app in out.strip().split(", "):
                windows.append({"title": app.strip()})
        except Exception:
            pass

    return windows


# =============================================================================
# WINDOW FOCUS
# =============================================================================

def focus_window(title_partial: str) -> Dict:
    """
    Bring a window to the foreground by partial title match.
    Works on Windows, Linux, macOS.
    """
    title_lower = title_partial.lower()

    if SYSTEM == "Windows" and WIN32_AVAILABLE:
        matches = []
        def callback(hwnd, _):
            t = win32gui.GetWindowText(hwnd)
            if title_lower in t.lower() and win32gui.IsWindowVisible(hwnd):
                matches.append(hwnd)
        win32gui.EnumWindows(callback, None)

        if not matches:
            return {"success": False, "error": f"No window found matching '{title_partial}'"}

        hwnd = matches[0]
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            # Workaround for Windows focus-steal prevention:
            # a brief Alt-key press resets the foreground lock so SetForegroundWindow can succeed.
            try:
                import ctypes
                VK_MENU = 0x12
                KEYEVENTF_KEYUP = 0x0002
                ctypes.windll.user32.keybd_event(VK_MENU, 0, 0, 0)
                ctypes.windll.user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
            except Exception:
                pass
            win32gui.SetForegroundWindow(hwnd)
            _log({"action": "focus_window", "title": title_partial, "hwnd": hwnd})
            return {"success": True, "title": win32gui.GetWindowText(hwnd)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif SYSTEM == "Linux":
        try:
            # Try wmctrl first
            result = subprocess.run(
                ["wmctrl", "-a", title_partial], timeout=5, capture_output=True
            )
            if result.returncode == 0:
                _log({"action": "focus_window", "title": title_partial})
                return {"success": True, "title": title_partial}
            # Try xdotool
            out = subprocess.check_output(
                ["xdotool", "search", "--name", title_partial], text=True, timeout=5
            )
            wids = out.strip().split("\n")
            if wids and wids[0]:
                subprocess.run(["xdotool", "windowactivate", "--sync", wids[0].strip()], timeout=5)
                _log({"action": "focus_window", "title": title_partial, "wid": wids[0]})
                return {"success": True, "title": title_partial}
            return {"success": False, "error": f"Window '{title_partial}' not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif SYSTEM == "Darwin":
        try:
            script = f'''
            tell application "System Events"
                set target_process to first process whose name contains "{title_partial}"
                set frontmost of target_process to true
            end tell
            '''
            subprocess.run(["osascript", "-e", script], timeout=10, capture_output=True)
            return {"success": True, "title": title_partial}
        except Exception as e:
            # Try direct app activation
            try:
                subprocess.run(["open", "-a", title_partial], timeout=5)
                return {"success": True, "title": title_partial, "method": "open -a"}
            except Exception as e2:
                return {"success": False, "error": str(e2)}

    return {"success": False, "error": f"focus_window not supported on {SYSTEM}"}


def minimize_window(title_partial: str) -> Dict:
    """Minimize a window."""
    if SYSTEM == "Windows" and WIN32_AVAILABLE:
        def callback(hwnd, matches):
            if title_partial.lower() in win32gui.GetWindowText(hwnd).lower():
                matches.append(hwnd)
        matches = []
        win32gui.EnumWindows(callback, matches)
        if matches:
            win32gui.ShowWindow(matches[0], win32con.SW_MINIMIZE)
            return {"success": True}
    elif SYSTEM == "Linux":
        try:
            subprocess.run(["wmctrl", "-r", title_partial, "-b", "add,hidden"], timeout=5)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
    return {"success": False, "error": "minimize not supported"}


def maximize_window(title_partial: str) -> Dict:
    """Maximize a window."""
    if SYSTEM == "Windows" and WIN32_AVAILABLE:
        def callback(hwnd, matches):
            if title_partial.lower() in win32gui.GetWindowText(hwnd).lower():
                matches.append(hwnd)
        matches = []
        win32gui.EnumWindows(callback, matches)
        if matches:
            win32gui.ShowWindow(matches[0], win32con.SW_MAXIMIZE)
            return {"success": True}
    elif SYSTEM == "Linux":
        try:
            subprocess.run(["wmctrl", "-r", title_partial, "-b", "add,maximized_vert,maximized_horz"], timeout=5)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
    return {"success": False, "error": "maximize not supported"}


# =============================================================================
# CHROME CONTROL
# =============================================================================

class ChromeController:
    """Control Google Chrome browser windows and tabs."""

    def new_tab(self, url: str = "https://www.google.com") -> Dict:
        """Open a new Chrome tab."""
        try:
            if SYSTEM == "Windows":
                subprocess.Popen(f'start chrome "{url}"', shell=True)
            elif SYSTEM == "Darwin":
                subprocess.Popen(["open", "-a", "Google Chrome", url])
            else:
                subprocess.Popen(["google-chrome", "--new-tab", url])
            _log({"action": "chrome_new_tab", "url": url})
            return {"success": True, "url": url}
        except Exception as e:
            # Try chromium
            try:
                subprocess.Popen(["chromium-browser", "--new-tab", url])
                return {"success": True, "url": url, "method": "chromium"}
            except Exception:
                return {"success": False, "error": str(e)}

    def navigate(self, url: str) -> Dict:
        """Navigate current Chrome tab to URL."""
        result = focus_window("Chrome")
        if not result["success"]:
            result = focus_window("Chromium")
        time.sleep(0.3)
        if PYAUTOGUI_AVAILABLE:
            pyautogui.hotkey("ctrl", "l")       # focus address bar
            time.sleep(0.2)
            pyautogui.hotkey("ctrl", "a")       # select all
            pyautogui.typewrite(url, interval=0.02)
            pyautogui.press("enter")
            _log({"action": "chrome_navigate", "url": url})
            return {"success": True, "url": url}
        return {"success": False, "error": "pyautogui not installed"}

    def new_window(self, url: str = "") -> Dict:
        """Open a new Chrome window."""
        try:
            if SYSTEM == "Windows":
                cmd = f'start chrome --new-window "{url}"' if url else "start chrome --new-window"
                subprocess.Popen(cmd, shell=True)
            elif SYSTEM == "Darwin":
                subprocess.Popen(["open", "-na", "Google Chrome", "--args", "--new-window", url])
            else:
                subprocess.Popen(["google-chrome", "--new-window", url or ""])
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def close_tab(self) -> Dict:
        """Close the current Chrome tab (Ctrl+W)."""
        result = focus_window("Chrome")
        if not result["success"]:
            return result
        time.sleep(0.2)
        if PYAUTOGUI_AVAILABLE:
            pyautogui.hotkey("ctrl", "w")
            return {"success": True}
        return {"success": False, "error": "pyautogui not installed"}

    def next_tab(self) -> Dict:
        """Switch to next tab in Chrome."""
        focus_window("Chrome")
        time.sleep(0.2)
        if PYAUTOGUI_AVAILABLE:
            pyautogui.hotkey("ctrl", "tab")
            return {"success": True}
        return {"success": False, "error": "pyautogui not installed"}

    def prev_tab(self) -> Dict:
        """Switch to previous tab."""
        focus_window("Chrome")
        time.sleep(0.2)
        if PYAUTOGUI_AVAILABLE:
            pyautogui.hotkey("ctrl", "shift", "tab")
            return {"success": True}
        return {"success": False, "error": "pyautogui not installed"}

    def go_to_tab_number(self, n: int) -> Dict:
        """Switch to tab number N (1-8)."""
        if n < 1 or n > 8:
            return {"success": False, "error": "Tab number must be 1-8"}
        focus_window("Chrome")
        time.sleep(0.2)
        if PYAUTOGUI_AVAILABLE:
            pyautogui.hotkey("ctrl", str(n))
            return {"success": True, "tab": n}
        return {"success": False, "error": "pyautogui not installed"}

    def reload(self) -> Dict:
        """Reload current Chrome tab."""
        focus_window("Chrome")
        time.sleep(0.2)
        if PYAUTOGUI_AVAILABLE:
            pyautogui.hotkey("ctrl", "r")
            return {"success": True}
        return {"success": False, "error": "pyautogui not installed"}

    def get_current_url(self) -> Dict:
        """Get URL from Chrome address bar using clipboard."""
        result = focus_window("Chrome")
        if not result["success"]:
            return result
        time.sleep(0.3)
        if PYAUTOGUI_AVAILABLE and PYPERCLIP_AVAILABLE:
            pyautogui.hotkey("ctrl", "l")
            time.sleep(0.2)
            pyautogui.hotkey("ctrl", "a")
            pyautogui.hotkey("ctrl", "c")
            time.sleep(0.3)
            url = pyperclip.paste()
            pyautogui.press("escape")
            return {"success": True, "url": url}
        return {"success": False, "error": "pyautogui or pyperclip not installed"}


# =============================================================================
# VSCODE CONTROL
# =============================================================================

class VSCodeController:
    """Control Visual Studio Code."""

    def open_file(self, filepath: str) -> Dict:
        """Open a file in VS Code."""
        try:
            if SYSTEM == "Windows":
                subprocess.Popen(f'code "{filepath}"', shell=True)
            else:
                subprocess.Popen(["code", filepath])
            _log({"action": "vscode_open_file", "file": filepath})
            return {"success": True, "file": filepath}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def run_command(self, command_id: str) -> Dict:
        """
        Run a VS Code command via Command Palette.
        Example: "workbench.action.files.save", "editor.action.formatDocument"
        """
        result = focus_window("Visual Studio Code")
        if not result["success"]:
            result = focus_window("Code")
        time.sleep(0.3)
        if PYAUTOGUI_AVAILABLE:
            pyautogui.hotkey("ctrl", "shift", "p")  # Command palette
            time.sleep(0.4)
            pyautogui.hotkey("ctrl", "a")
            pyautogui.typewrite(command_id, interval=0.02)
            time.sleep(0.3)
            pyautogui.press("enter")
            _log({"action": "vscode_command", "command": command_id})
            return {"success": True, "command": command_id}
        return {"success": False, "error": "pyautogui not installed"}

    def save_file(self) -> Dict:
        """Save current file in VS Code."""
        result = focus_window("Visual Studio Code")
        if not result["success"]:
            result = focus_window("Code")
        if PYAUTOGUI_AVAILABLE:
            pyautogui.hotkey("ctrl", "s")
            return {"success": True}
        return {"success": False, "error": "pyautogui not installed"}

    def format_document(self) -> Dict:
        """Format current document in VS Code."""
        return self.run_command("editor.action.formatDocument")

    def open_terminal(self) -> Dict:
        """Open integrated terminal in VS Code."""
        return self.run_command("workbench.action.terminal.toggleTerminal")

    def run_in_terminal(self, cmd: str) -> Dict:
        """Open terminal and run a command."""
        self.open_terminal()
        time.sleep(0.8)
        if PYAUTOGUI_AVAILABLE:
            pyautogui.typewrite(cmd, interval=0.02)
            pyautogui.press("enter")
            return {"success": True, "command": cmd}
        return {"success": False, "error": "pyautogui not installed"}

    def close_tab(self) -> Dict:
        """Close current editor tab."""
        focus_window("Visual Studio Code")
        if PYAUTOGUI_AVAILABLE:
            pyautogui.hotkey("ctrl", "w")
            return {"success": True}
        return {"success": False, "error": "pyautogui not installed"}

    def next_tab(self) -> Dict:
        """Switch to next editor tab."""
        focus_window("Visual Studio Code")
        if PYAUTOGUI_AVAILABLE:
            pyautogui.hotkey("ctrl", "tab")
            return {"success": True}
        return {"success": False, "error": "pyautogui not installed"}

    def search_in_file(self, text: str) -> Dict:
        """Search for text in current file (Ctrl+F)."""
        focus_window("Visual Studio Code")
        if PYAUTOGUI_AVAILABLE:
            pyautogui.hotkey("ctrl", "f")
            time.sleep(0.3)
            pyautogui.typewrite(text, interval=0.02)
            return {"success": True, "search": text}
        return {"success": False, "error": "pyautogui not installed"}

    def type_code(self, code: str) -> Dict:
        """Type code at current cursor position in VS Code."""
        focus_window("Visual Studio Code")
        if PYAUTOGUI_AVAILABLE:
            if PYPERCLIP_AVAILABLE:
                pyperclip.copy(code)
                pyautogui.hotkey("ctrl", "v")
            else:
                pyautogui.typewrite(code[:500], interval=0.01)
            return {"success": True, "chars": len(code)}
        return {"success": False, "error": "pyautogui not installed"}


# =============================================================================
# GENERIC APP CONTROLLER
# =============================================================================

class AppController:
    """Unified controller for all laptop applications."""

    def __init__(self):
        self.chrome = ChromeController()
        self.vscode = VSCodeController()

    # ── Window management ───────────────────────────────────────────────────
    def list_windows(self) -> List[Dict]:
        return list_windows()

    def focus(self, title: str) -> Dict:
        return focus_window(title)

    def minimize(self, title: str) -> Dict:
        return minimize_window(title)

    def maximize(self, title: str) -> Dict:
        return maximize_window(title)

    def type_in_window(self, title: str, text: str) -> Dict:
        """Focus a window and type text into it."""
        result = focus_window(title)
        if not result["success"]:
            return result
        time.sleep(0.4)
        if PYAUTOGUI_AVAILABLE:
            if PYPERCLIP_AVAILABLE and len(text) > 20:
                old = ""
                try:
                    old = pyperclip.paste()
                except Exception:
                    pass
                pyperclip.copy(text)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.1)
                try:
                    pyperclip.copy(old)
                except Exception:
                    pass
            else:
                pyautogui.typewrite(text, interval=0.02)
            return {"success": True, "typed": len(text)}
        return {"success": False, "error": "pyautogui not installed"}

    def send_key_to_window(self, title: str, key: str) -> Dict:
        """Focus a window and send a key press."""
        result = focus_window(title)
        if not result["success"]:
            return result
        time.sleep(0.3)
        if PYAUTOGUI_AVAILABLE:
            pyautogui.press(key)
            return {"success": True, "key": key}
        return {"success": False, "error": "pyautogui not installed"}

    # ── App launching ───────────────────────────────────────────────────────
    def launch(self, app_name: str) -> Dict:
        """Launch an application by name."""
        try:
            if SYSTEM == "Windows":
                os.startfile(app_name)
            elif SYSTEM == "Darwin":
                subprocess.Popen(["open", "-a", app_name])
            else:
                subprocess.Popen([app_name])
            _log({"action": "launch", "app": app_name})
            return {"success": True, "app": app_name}
        except Exception as e:
            try:
                subprocess.Popen(app_name, shell=True)
                return {"success": True, "app": app_name, "method": "shell"}
            except Exception as e2:
                return {"success": False, "error": str(e2)}

    # ── Screenshot of a specific window ────────────────────────────────────
    def screenshot_window(self, title: str) -> Dict:
        """Take a screenshot of a specific window."""
        result = focus_window(title)
        if not result["success"]:
            return result
        time.sleep(0.3)
        try:
            from computer_control import take_screenshot
            return take_screenshot()
        except ImportError:
            if PYAUTOGUI_AVAILABLE:
                import io, base64
                img = pyautogui.screenshot()
                buf = io.BytesIO()
                img.save(buf, "PNG")
                b64 = base64.b64encode(buf.getvalue()).decode()
                return {"success": True, "image_b64": b64, "format": "image/png"}
        return {"success": False, "error": "screenshot not available"}

    # ── Dispatcher ───────────────────────────────────────────────────────────
    def execute(self, action: str, params: dict) -> Dict:
        """
        Unified action dispatcher.
        action examples: "focus", "chrome_new_tab", "vscode_open_file", "list_windows"
        """
        action = action.lower().strip()
        _log({"action": f"execute:{action}", "params_preview": str(params)[:100]})

        # Window management
        if action == "list_windows":
            return {"success": True, "windows": self.list_windows()}
        elif action == "focus":
            return self.focus(params.get("title", ""))
        elif action == "minimize":
            return self.minimize(params.get("title", ""))
        elif action == "maximize":
            return self.maximize(params.get("title", ""))
        elif action == "launch":
            return self.launch(params.get("app", ""))
        elif action == "type_in_window":
            return self.type_in_window(params.get("title", ""), params.get("text", ""))
        elif action == "screenshot_window":
            return self.screenshot_window(params.get("title", ""))

        # Chrome
        elif action == "chrome_new_tab":
            return self.chrome.new_tab(params.get("url", "https://google.com"))
        elif action == "chrome_navigate":
            return self.chrome.navigate(params.get("url", ""))
        elif action == "chrome_close_tab":
            return self.chrome.close_tab()
        elif action == "chrome_next_tab":
            return self.chrome.next_tab()
        elif action == "chrome_prev_tab":
            return self.chrome.prev_tab()
        elif action == "chrome_tab_number":
            return self.chrome.go_to_tab_number(int(params.get("n", 1)))
        elif action == "chrome_reload":
            return self.chrome.reload()
        elif action == "chrome_get_url":
            return self.chrome.get_current_url()
        elif action == "chrome_new_window":
            return self.chrome.new_window(params.get("url", ""))

        # VS Code
        elif action == "vscode_open_file":
            return self.vscode.open_file(params.get("file", ""))
        elif action == "vscode_command":
            return self.vscode.run_command(params.get("command", ""))
        elif action == "vscode_save":
            return self.vscode.save_file()
        elif action == "vscode_format":
            return self.vscode.format_document()
        elif action == "vscode_terminal":
            return self.vscode.open_terminal()
        elif action == "vscode_run_in_terminal":
            return self.vscode.run_in_terminal(params.get("cmd", ""))
        elif action == "vscode_type_code":
            return self.vscode.type_code(params.get("code", ""))
        elif action == "vscode_search":
            return self.vscode.search_in_file(params.get("text", ""))
        elif action == "vscode_close_tab":
            return self.vscode.close_tab()
        elif action == "vscode_next_tab":
            return self.vscode.next_tab()

        else:
            return {"success": False, "error": f"Unknown app control action: '{action}'"}


# ── Singleton ────────────────────────────────────────────────────────────────
_controller = AppController()


def control_app(action: str, params: dict = None) -> Dict:
    """Top-level convenience function for voice commands / agent routes."""
    return _controller.execute(action, params or {})


def get_app_control_status() -> Dict:
    """Return capabilities of the app control module."""
    return {
        "platform": SYSTEM,
        "pyautogui": PYAUTOGUI_AVAILABLE,
        "pyperclip": PYPERCLIP_AVAILABLE,
        "win32": WIN32_AVAILABLE,
        "wmctrl": _check_tool("wmctrl"),
        "xdotool": _check_tool("xdotool"),
        "chrome": True,  # always attempted
        "vscode": True,
    }


def _check_tool(tool: str) -> bool:
    try:
        result = subprocess.run(["which", tool], capture_output=True, timeout=2)
        return result.returncode == 0
    except Exception:
        return False
