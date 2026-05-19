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

_PREFERRED_BROWSER = "chrome"

_BROWSER_PATHS = {
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ],
    "brave": [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
    ],
}

_KNOWN_BROWSERS = ("brave", "chrome", "edge", "firefox", "safari", "opera")


def _launch_browser(url: str, browser: str = None) -> str:
    """Launch browser with autoplay unrestricted. Returns browser name used."""
    name = (browser or _PREFERRED_BROWSER).lower()
    for exe in _BROWSER_PATHS.get(name, []):
        if os.path.exists(exe):
            subprocess.Popen([exe, "--autoplay-policy=no-user-gesture-required", url])
            return name
    subprocess.Popen(f'start {name} "{url}"', shell=True)
    return name


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

def handle_set_browser(task_params: list) -> Dict:
    global _PREFERRED_BROWSER
    browser_name = (task_params[0] or "").lower() if task_params else ""
    if browser_name in _BROWSER_PATHS:
        _PREFERRED_BROWSER = browser_name
        return {"success": True, "action_taken": "set_browser",
                "message": f"Got it — I'll use {browser_name.title()} from now on."}
    return {"success": False, "action_taken": "set_browser",
            "message": "I support Chrome and Brave. Say 'use brave' or 'use chrome'."}


def handle_play_media(text: str, task_params: list) -> Dict:
    query  = _extract_play_query(text) or (task_params[0] if task_params else text)
    browser = _detect_browser_hint(text)
    try:
        import urllib.request as _ur
        search_url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
        req = _ur.Request(search_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
        })
        html = _ur.urlopen(req, timeout=10).read().decode("utf-8", errors="ignore")
        ids = re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', html)
        if ids:
            video_url = f"https://www.youtube.com/watch?v={ids[0]}&autoplay=1"
            used = _launch_browser(video_url, browser)
            return {"success": True, "action_taken": "play_media",
                    "message": f"Playing '{query}' on YouTube ({used.title()})"}
        used = _launch_browser(search_url, browser)
        return {"success": True, "action_taken": "play_media",
                "message": f"Opened YouTube search for '{query}' ({used.title()})"}
    except Exception as e:
        return {"success": False, "error": str(e), "action_taken": "play_media"}


def handle_pause_resume_media(task_type: str) -> Dict:
    try:
        import pyautogui
        try:
            import pygetwindow as gw
            yt_wins = [w for w in gw.getAllWindows()
                       if 'youtube' in w.title.lower() and w.title]
            if yt_wins:
                yt_wins[0].activate()
                time.sleep(0.4)
        except Exception:
            pass
        pyautogui.press('k')
        msg = "Paused." if task_type == "pause_media" else "Resumed."
        return {"success": True, "action_taken": task_type, "message": msg}
    except Exception as e:
        return {"success": False, "error": str(e), "action_taken": task_type}


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
