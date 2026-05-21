"""
browser_tasks.py — Browser/media handlers for Ultron's orchestrator.
Extracted from task_orchestrator.py to keep that file manageable.
"""
import os
import re
import subprocess
import time
import webbrowser
from typing import Dict, List, Optional

# =============================================================================
# BROWSER PREFERENCE & UTILITIES
# =============================================================================

import platform as _platform
import shutil as _shutil

_PREFERRED_BROWSER = "brave"

# Windows executable paths (tried in order; first existing one wins).
_WIN_BROWSER_PATHS = {
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ],
    "brave": [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
    ],
    "edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "firefox": [
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
    ],
}

# Linux/macOS binary candidates (tried via shutil.which in order).
_LINUX_BROWSER_BINS = {
    "brave":   ["brave-browser", "brave"],
    "chrome":  ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"],
    "firefox": ["firefox"],
    "edge":    ["microsoft-edge", "microsoft-edge-stable"],
    "opera":   ["opera"],
    "safari":  ["safari"],
}

_KNOWN_BROWSERS = ("brave", "chrome", "edge", "firefox", "safari", "opera")

# Chromium-family browsers that accept --autoplay-policy
_CHROMIUM_FAMILY = {"brave", "chrome", "edge", "opera", "chromium"}


def _find_browser_bin(name: str) -> Optional[str]:
    """Return the first executable found for the requested browser, or None."""
    for candidate in _LINUX_BROWSER_BINS.get(name, [name]):
        path = _shutil.which(candidate)
        if path:
            return path
    return None


def _launch_browser(url: str, browser: str = None) -> str:
    """
    Launch a browser with autoplay unrestricted. Cross-platform.
    Returns the browser name actually used.
    """
    name = (browser or _PREFERRED_BROWSER).lower()
    system = _platform.system()
    autoplay_flag = "--autoplay-policy=no-user-gesture-required"

    if system == "Windows":
        # Try known exe paths first
        for exe in _WIN_BROWSER_PATHS.get(name, []):
            if os.path.exists(exe):
                args = [exe, autoplay_flag, url] if name in _CHROMIUM_FAMILY else [exe, url]
                subprocess.Popen(args)
                return name
        # Fall back to Windows `start` built-in
        subprocess.Popen(f'start {name} "{url}"', shell=True)
        return name

    elif system == "Darwin":
        bin_path = _find_browser_bin(name)
        if bin_path:
            args = [bin_path, autoplay_flag, url] if name in _CHROMIUM_FAMILY else [bin_path, url]
            subprocess.Popen(args)
            return name
        subprocess.Popen(["open", "-a", name.title(), url])
        return name

    else:  # Linux
        bin_path = _find_browser_bin(name)
        if bin_path:
            args = [bin_path, autoplay_flag, url] if name in _CHROMIUM_FAMILY else [bin_path, url]
            subprocess.Popen(args)
            return name
        # Browser not found by name — try xdg-open as last resort
        xdg = _shutil.which("xdg-open")
        if xdg:
            subprocess.Popen([xdg, url])
            return "default"
        raise RuntimeError(f"Browser '{name}' not found. Install it or set a different default.")


def _detect_browser_hint(text: str) -> Optional[str]:
    """Return the browser name the user named, or None."""
    if not text:
        return None
    tl = text.lower()
    m = re.search(
        r"\b(?:in|on|using|with|via|through)\s+(" + "|".join(_KNOWN_BROWSERS) + r")\b",
        tl,
    )
    if m:
        return m.group(1)
    m = re.search(r"\bopen\s+(" + "|".join(_KNOWN_BROWSERS) + r")\b", tl)
    if m:
        return m.group(1)
    return None


def _extract_play_query(text: str) -> str:
    """Pull the song/video name out of a play-instruction."""
    if not text:
        return ""
    tl = text.lower()
    m = re.search(
        r"\b(?:play(?:ing)?|sing(?:ing)?|listen\s+to|put\s+on|watch(?:ing)?)\b\s+(.+)$",
        tl,
    )
    q = m.group(1) if m else tl
    q = re.sub(
        r"\b(?:in|on|using|with|via)\s+(?:" + "|".join(_KNOWN_BROWSERS) + r")\b.*$",
        "", q,
    )
    q = re.sub(r"\bon\s+youtube\b.*$", "", q)
    q = re.sub(r"\b(?:song|video|track|music|please|now|asap)\b", " ", q)
    if not m:
        q = re.sub(r"\b(?:open|start|launch|youtube|and|the|a|an)\b", " ", q)
    q = re.sub(r"^(?:and|then|please|of|for)\s+", "", q.strip())
    q = re.sub(r"\s+", " ", q).strip(" .,!?")
    return q


# =============================================================================
# HANDLER FUNCTIONS  (called by orchestrate())
# =============================================================================

def _press_browser_key(*keys: str) -> Dict:
    """
    Send a keyboard shortcut to the browser window.
    On Linux, uses xdotool to find and activate the browser window first.
    Falls back to pyautogui when xdotool is unavailable.
    """
    import subprocess as _sp, shutil as _sh, time as _tm
    xdt_key = "+".join(keys)

    if _platform.system() == "Linux":
        xdt = _sh.which("xdotool")
        if xdt:
            for search_args in [
                ["--name", "YouTube"],
                ["--class", "Brave-browser"],
                ["--class", "Google-chrome"],
                ["--class", "Firefox"],
            ]:
                try:
                    r = _sp.run([xdt, "search"] + search_args,
                                capture_output=True, text=True, timeout=2)
                    if r.returncode == 0 and r.stdout.strip():
                        wid = r.stdout.strip().split("\n")[-1]
                        _sp.run([xdt, "windowactivate", "--sync", wid], timeout=2)
                        _tm.sleep(0.2)
                        _sp.run([xdt, "key", "--clearmodifiers", xdt_key], timeout=2)
                        return {"success": True}
                except Exception:
                    pass
    try:
        import pyautogui
        if len(keys) == 1:
            pyautogui.press(keys[0])
        else:
            pyautogui.hotkey(*keys)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def handle_set_browser(task_params: list) -> Dict:
    global _PREFERRED_BROWSER
    browser_name = (task_params[0] or "").lower() if task_params else ""
    if browser_name in _KNOWN_BROWSERS:
        _PREFERRED_BROWSER = browser_name
        return {"success": True, "action_taken": "set_browser",
                "message": f"Got it — I'll use {browser_name.title()} from now on."}
    return {"success": False, "action_taken": "set_browser",
            "message": f"I support: {', '.join(_KNOWN_BROWSERS)}. Say 'use brave' or 'use chrome'."}


def _activate_browser_and_play(browser_name: str):
    """
    After opening a YouTube watch URL, wait for page load then force-play.
    Uses xdotool on Linux to focus the browser window, then presses 'k'.
    """
    import time as _time
    import subprocess as _sp, shutil as _sh
    _time.sleep(4)  # wait for page + video element to load

    if _platform.system() == "Linux":
        xdt = _sh.which("xdotool")
        if xdt:
            search_classes = {
                "brave":   ["Brave-browser", "brave-browser"],
                "chrome":  ["Google-chrome", "Chromium"],
                "firefox": ["Firefox"],
            }
            classes = search_classes.get(browser_name.lower(), ["Brave-browser", "Google-chrome", "Firefox"])
            for cls in classes:
                try:
                    r = _sp.run([xdt, "search", "--class", cls],
                                capture_output=True, text=True, timeout=3)
                    if r.returncode == 0 and r.stdout.strip():
                        wid = r.stdout.strip().split("\n")[-1]
                        _sp.run([xdt, "windowactivate", "--sync", wid], timeout=2)
                        _time.sleep(0.3)
                        # Click the center of the screen to focus video player
                        _sp.run([xdt, "mousemove", "--window", wid, "640", "360"], timeout=2)
                        _sp.run([xdt, "click", "1"], timeout=2)
                        _time.sleep(0.3)
                        # Press 'k' (YouTube play/pause toggle)
                        _sp.run([xdt, "key", "--clearmodifiers", "--window", wid, "k"], timeout=2)
                        return
                except Exception:
                    pass
    # Fallback: pyautogui spacebar press
    try:
        import pyautogui as _pg
        _pg.press('k')
    except Exception:
        pass


def _youtube_play(query: str, browser: str = None) -> Dict:
    """
    Core YouTube play logic shared by all call sites.
    Fetches search-results HTML, extracts the first real video ID,
    then opens the direct watch URL with autoplay=1.
    Falls back to the search-results page if no ID is found.
    Returns a result dict with action_taken, message, success.
    """
    import urllib.request as _ur, urllib.parse as _up
    encoded    = _up.quote(query)
    search_url = f"https://www.youtube.com/results?search_query={encoded}"
    try:
        req  = _ur.Request(
            search_url,
            headers={"User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            )},
        )
        html = _ur.urlopen(req, timeout=10).read().decode("utf-8", errors="ignore")
        ids  = [v for v in re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', html) if len(v) == 11]
        if ids:
            video_url = f"https://www.youtube.com/watch?v={ids[0]}&autoplay=1"
            used = _launch_browser(video_url, browser=browser)
            # Force play in a background thread — browser needs time to load
            import threading as _thr
            _thr.Thread(
                target=_activate_browser_and_play,
                args=(used,),
                daemon=True,
            ).start()
            return {
                "success": True,
                "action_taken": "youtube_play",
                "message": f"Playing '{query}' on YouTube in {used.title()}",
                "video_id": ids[0],
                "browser": used,
            }
        # No video ID found in page — open search results as fallback
        used = _launch_browser(search_url, browser=browser)
        return {
            "success": True,
            "action_taken": "youtube_play",
            "message": f"Opened YouTube search for '{query}' in {used.title()} (no direct video found)",
            "browser": used,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "action_taken": "youtube_play"}


def handle_play_media(text: str, task_params: list) -> Dict:
    query  = _extract_play_query(text) or (task_params[0] if task_params else text)
    browser = _detect_browser_hint(text)
    return _youtube_play(query, browser=browser)


def handle_pause_resume_media(task_type: str) -> Dict:
    """Pause or resume YouTube playback using the 'k' keyboard shortcut."""
    r = _press_browser_key("k")
    msg = "Paused." if task_type == "pause_media" else "Resumed."
    return {**r, "action_taken": task_type,
            "message": msg if r.get("success") else r.get("error", "Failed.")}


def handle_media_next() -> Dict:
    """Skip to the next YouTube video (Shift+N)."""
    r = _press_browser_key("shift", "n")
    return {**r, "action_taken": "media_next",
            "message": "Skipped to next video." if r.get("success") else r.get("error", "Failed.")}


def handle_media_prev() -> Dict:
    """Go to the previous YouTube video (Shift+P)."""
    r = _press_browser_key("shift", "p")
    return {**r, "action_taken": "media_prev",
            "message": "Playing previous video." if r.get("success") else r.get("error", "Failed.")}


def handle_open_url(task: dict, text: str) -> Dict:
    url     = task["params"][0] if task["params"] else ""
    browser = _detect_browser_hint(text)
    if "youtube.com/results" in url or "youtube.com/watch" in url:
        try:
            used = _launch_browser(url, browser=browser)
            time.sleep(4)
            try:
                import pyautogui
                pyautogui.press('tab')
                time.sleep(0.3)
                pyautogui.press('enter')
            except Exception:
                pass
            return {"success": True, "action_taken": "open_url",
                    "browser": used,
                    "message": f"Opened YouTube in {used} and clicked first video"}
        except Exception as e:
            return {"success": False, "error": str(e), "action_taken": "open_url"}
    try:
        used = _launch_browser(url, browser=browser)
        return {"success": True, "action_taken": "open_url",
                "browser": used, "message": f"Opened {url} in {used}"}
    except Exception:
        webbrowser.open(url)
        return {"success": True, "action_taken": "open_url", "message": f"Opened: {url}"}


def handle_volume_control(task: dict, text: str) -> Dict:
    try:
        import pyautogui
        tl = text.lower()

        def _press_burst(key: str, n: int):
            _old = pyautogui.PAUSE
            pyautogui.PAUSE = 0.0
            try:
                for _ in range(n):
                    pyautogui.press(key)
            finally:
                pyautogui.PAUSE = _old

        _level = None
        _m = re.search(r"\b(?:to|at)\s+(\d{1,3})\s*%?", tl)
        if _m:
            _level = max(0, min(100, int(_m.group(1))))
        elif task.get("params"):
            for p in task["params"]:
                if isinstance(p, str) and p.isdigit():
                    _v = int(p)
                    if 0 <= _v <= 100:
                        _level = _v
                        break

        if _level is not None:
            try:
                from ctypes import cast, POINTER
                from comtypes import CLSCTX_ALL
                from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
                devs  = AudioUtilities.GetSpeakers()
                iface = devs.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                vol   = cast(iface, POINTER(IAudioEndpointVolume))
                vol.SetMasterVolumeLevelScalar(_level / 100.0, None)
                return {"success": True, "action_taken": "volume_control",
                        "message": f"Volume set to {_level}%."}
            except Exception:
                pass
            _press_burst('volumedown', 50)
            _press_burst('volumeup',   max(0, min(50, round(_level / 2))))
            return {"success": True, "action_taken": "volume_control",
                    "message": f"Volume set to about {_level}% (approximate — install pycaw for exact: `pip install pycaw comtypes`)."}

        if any(w in tl for w in ['max', 'maximum', 'full']):
            _press_burst('volumeup', 50)
            return {"success": True, "action_taken": "volume_control",
                    "message": "Volume set to maximum."}
        if 'unmute' in tl:
            pyautogui.press('volumemute')
            return {"success": True, "action_taken": "volume_control", "message": "Unmuted."}
        if 'mute' in tl:
            pyautogui.press('volumemute')
            return {"success": True, "action_taken": "volume_control", "message": "Muted."}
        if any(w in tl for w in ['increase', 'raise', 'louder', 'higher', 'boost', 'crank', 'turn up']):
            for _ in range(5):
                pyautogui.press('volumeup')
            return {"success": True, "action_taken": "volume_control",
                    "message": "Volume increased."}
        if any(w in tl for w in ['decrease', 'lower', 'reduce', 'drop', 'dim', 'soften', 'quieter', 'softer', 'less', 'turn down']):
            for _ in range(5):
                pyautogui.press('volumedown')
            return {"success": True, "action_taken": "volume_control",
                    "message": "Volume decreased."}
        if task.get("params"):
            direction = (task["params"][0] or "").lower()
            if direction in ('up', 'increase', 'raise', 'louder', 'higher'):
                for _ in range(5):
                    pyautogui.press('volumeup')
                return {"success": True, "action_taken": "volume_control",
                        "message": "Volume increased."}
            if direction in ('down', 'decrease', 'reduce', 'lower', 'quieter', 'softer'):
                for _ in range(5):
                    pyautogui.press('volumedown')
                return {"success": True, "action_taken": "volume_control",
                        "message": "Volume decreased."}
        for _ in range(5):
            pyautogui.press('volumedown')
        return {"success": True, "action_taken": "volume_control",
                "message": "Volume decreased."}
    except Exception as e:
        return {"success": False, "error": str(e), "action_taken": "volume_control"}
