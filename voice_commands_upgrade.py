"""
voice_commands_upgrade.py — Drop-in upgrade for voice_engine.py
================================================================
PASTE THIS INTO voice_engine.py — replaces _VOICE_CMDS and
execute_voice_command to add 60+ new commands.

New commands added:
  - Build/create projects ("build a snake game")
  - Save code from clipboard
  - Run project
  - Folder operations (create, open, delete)
  - File operations
  - Phone/mobile control
  - Claude.ai bridge
  - Google search by voice
  - Music control
  - System control (volume, lock, sleep)
  - Clipboard ops
  - Notifications
"""

import re
import os
import subprocess
import webbrowser
import platform
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# ─── Try optional imports ─────────────────────────────────────────────────────
try:
    import pyperclip
    CLIP_OK = True
except ImportError:
    CLIP_OK = False

try:
    import pyautogui
    GUI_OK = True
except ImportError:
    GUI_OK = False


# =============================================================================
# UPGRADED VOICE COMMAND MAP
# =============================================================================

UPGRADED_VOICE_CMDS = {
    # ── Time & Date ──────────────────────────────────────────────────────────
    r"what('s| is) (the )?(time|clock)":          "TIME",
    r"what('s| is) (the )?date":                   "DATE",
    r"what day (is it|today)":                     "DATE",

    # ── Weather ──────────────────────────────────────────────────────────────
    r"what('s| is) (the )?weather":                "WEATHER",
    r"how('s| is) (the )?weather":                 "WEATHER",
    r"will it rain":                                "WEATHER",

    # ── System modes ────────────────────────────────────────────────────────
    r"(switch|go) to local( mode)?":               "MODE:local",
    r"offline mode":                                "MODE:local",
    r"(switch|go) to cloud( mode)?":               "MODE:cloud",
    r"online mode":                                 "MODE:cloud",

    # ── System status ────────────────────────────────────────────────────────
    r"(system )?status":                            "STATUS",
    r"(system )?health( check)?":                  "HEALTH",
    r"what can you do":                             "CAPABILITIES",
    r"how are you (doing|running|feeling)":         "HEALTH",

    # ── Screenshots ──────────────────────────────────────────────────────────
    r"take (a )?screenshot":                        "SCREENSHOT",
    r"capture (the )?screen":                       "SCREENSHOT",
    r"screenshot":                                  "SCREENSHOT",
    r"(take|get) (a )?phone screenshot":            "PHONE_SCREENSHOT",
    r"screenshot (of |from )?my phone":             "PHONE_SCREENSHOT",

    # ── Folders ──────────────────────────────────────────────────────────────
    r"(create|make|new) (a )?folder (.+)":          "CREATE_FOLDER",
    r"open (the )?(.+) folder":                     "OPEN_FOLDER",
    r"open (folder|directory) (.+)":                "OPEN_FOLDER",
    r"show (me )?my (desktop|downloads|documents|pictures|music|videos)": "OPEN_SYSTEM_FOLDER",

    # ── Browser & Search ─────────────────────────────────────────────────────
    r"(open|launch) (chrome|browser|firefox|edge)": "BROWSER",
    r"google (.+)":                                 "GOOGLE_SEARCH",
    r"search (for |the web for )?(.+)":             "GOOGLE_SEARCH",
    r"open (https?://\S+)":                         "OPEN_URL",
    r"go to (https?://\S+)":                        "OPEN_URL",
    r"open youtube":                                "OPEN_URL:https://youtube.com",
    r"open gmail":                                  "OPEN_URL:https://mail.google.com",
    r"open (claude|claude ai)":                     "OPEN_URL:https://claude.ai",
    r"open chatgpt":                                "OPEN_URL:https://chat.openai.com",
    r"open gemini":                                 "OPEN_URL:https://gemini.google.com",
    r"open github":                                 "OPEN_URL:https://github.com",

    # ── App launching ────────────────────────────────────────────────────────
    r"(open|launch|start) (vs ?code|visual studio code)": "OPEN_APP:code",
    r"(open|launch|start) notepad":                "OPEN_APP:notepad",
    r"(open|launch|start) calculator":             "OPEN_APP:calc",
    r"(open|launch|start) task manager":           "OPEN_APP:taskmgr",
    r"(open|launch|start) file explorer":          "OPEN_APP:explorer",
    r"(open|launch|start) spotify":                "OPEN_APP:spotify",
    r"(open|launch|start) whatsapp":               "OPEN_APP:whatsapp",
    r"(open|launch|start) discord":                "OPEN_APP:discord",
    r"(open|launch|start) (.+)":                   "OPEN_APP",

    # ── Build / Code projects (THE BIG ONE) ──────────────────────────────────
    r"i want to build (.+)":                        "BUILD_PROJECT",
    r"i want to (create|make) (.+)":                "BUILD_PROJECT",
    r"(build|create|make) (a |an )?(game|app|website|tool|script|program|bot)": "BUILD_PROJECT",
    r"help me (build|create|make) (.+)":            "BUILD_PROJECT",
    r"write (a |an )?(.+) (game|app|script|program)": "BUILD_PROJECT",

    # ── Code saving & running ────────────────────────────────────────────────
    r"save (the )?code":                            "SAVE_CODE",
    r"copy (the )?code":                            "SAVE_CODE",
    r"(save|grab) (the )?code from clipboard":      "SAVE_CODE",
    r"run (the |my )?project":                      "RUN_PROJECT",
    r"run (the |my )?code":                         "RUN_PROJECT",
    r"execute (the |my )?code":                     "RUN_PROJECT",
    r"run it":                                      "RUN_PROJECT",
    r"open (the )?project folder":                  "OPEN_PROJECT_FOLDER",

    # ── Claude bridge ────────────────────────────────────────────────────────
    r"ask claude (.+)":                             "ASK_CLAUDE",
    r"open claude (for|to) (.+)":                   "ASK_CLAUDE",
    r"use claude (for|to) (.+)":                    "ASK_CLAUDE",

    # ── Clipboard ────────────────────────────────────────────────────────────
    r"(what's|what is|read) (the )?clipboard":     "READ_CLIPBOARD",
    r"clear (the )?clipboard":                      "CLEAR_CLIPBOARD",
    r"copy (.+) to clipboard":                      "WRITE_CLIPBOARD",

    # ── Volume control ───────────────────────────────────────────────────────
    r"volume up":                                   "VOLUME_UP",
    r"volume down":                                 "VOLUME_DOWN",
    r"(mute|silence)( everything| all)?":           "MUTE",
    r"unmute":                                      "UNMUTE",

    # ── System control ───────────────────────────────────────────────────────
    r"(lock|lock screen|lock (the )?computer)":     "LOCK_SCREEN",
    r"sleep( mode)?":                               "SLEEP",
    r"(empty|clear) (the )?(recycle bin|trash)":    "EMPTY_TRASH",

    # ── Phone control ────────────────────────────────────────────────────────
    r"(is my |check )phone connected":             "PHONE_STATUS",
    r"open (.+) on (my )?(phone|mobile)":          "PHONE_OPEN_APP",
    r"(phone|mobile) (go |)back":                  "PHONE_BACK",
    r"(phone|mobile) swipe (up|down|left|right)":  "PHONE_SWIPE",
    r"send (.+) to (my )?(phone|mobile)":          "PHONE_SEND_TEXT",

    # ── Voice control ────────────────────────────────────────────────────────
    r"(pause|stop) (listening|voice)":             "VOICE:stop",
    r"hey ultron":                                  "WAKE",

    # ── Page code extraction ─────────────────────────────────────────────────
    r"copy (the )?code from (.+)":                  "COPY_CODE_FROM_URL",
    r"extract (the )?code from (.+)":               "COPY_CODE_FROM_URL",
    r"grab (the )?code from (.+)":                  "COPY_CODE_FROM_URL",
    r"get code from (.+)":                          "COPY_CODE_FROM_URL",
    r"list (the )?code (on|at|from) (.+)":          "LIST_CODE_ON_URL",
    r"what code is (on|at) (.+)":                   "LIST_CODE_ON_URL",

    # ── Self-modification ────────────────────────────────────────────────────
    r"improve (your|the) (ui|interface|design|navbar|chat)(.*)":  "SELF_IMPROVE",
    r"make (the |your )?(ui|interface|design|navbar|chat) (.+)":  "SELF_IMPROVE",
    r"upgrade (your|the) (ui|interface|design)":                  "SELF_IMPROVE",
    r"get a better (ui|interface|design|navbar)(.*)":             "SELF_IMPROVE",
    r"ask claude (to |)improve(.*)":                               "SELF_IMPROVE_CLAUDE",
    r"rollback (the )?(last |)?change":                           "SELF_ROLLBACK",
    r"undo (the )?(last )?patch":                                  "SELF_ROLLBACK",

    # ── Wireless phone ──────────────────────────────────────────────────────
    r"connect (my |the )?phone (wirelessly|via wifi|over wifi)":  "PHONE_WIRELESS_ENABLE",
    r"enable wireless (adb|phone)":                                "PHONE_WIRELESS_ENABLE",
    r"reconnect (my |the )?phone":                                 "PHONE_WIRELESS_CONNECT",
    r"phone (volume |)up":                                         "PHONE_VOLUME_UP",
    r"phone (volume |)down":                                       "PHONE_VOLUME_DOWN",
    r"phone (home|go home)":                                       "PHONE_HOME",
    r"phone power":                                                "PHONE_POWER",

    # ── App window control ──────────────────────────────────────────────────
    r"(focus|switch to|bring up) (vs ?code|visual studio code)":  "FOCUS_APP:code",
    r"(focus|switch to|bring up) chrome":                         "FOCUS_APP:chrome",
    r"(focus|switch to|bring up) (.+) window":                    "FOCUS_APP",
    r"open new (chrome |browser )?tab( with (.+))?":              "CHROME_NEW_TAB",
    r"chrome (go to|open|navigate to) (.+)":                      "CHROME_NAVIGATE",
    r"(list|show) (all |open )?windows":                          "LIST_WINDOWS",
    r"save (the )?file in (vs ?code|vscode)":                     "VSCODE_SAVE",
    r"run in terminal (.+)":                                       "VSCODE_RUN_TERMINAL",
    r"open (the )?terminal":                                       "VSCODE_TERMINAL",
}


def _open_path(target) -> bool:
    """Open a file or folder in the OS file manager. NEVER through a shell.

    The old form was `Popen(f'explorer "{path}"', shell=True)`, which builds a
    command line out of a value derived from speech — the same class of bug the
    hardening batch removed from intent_router. List-form argv keeps the path a
    single argument no matter what characters it contains.
    """
    target = str(target)
    try:
        if platform.system() == "Windows":
            os.startfile(target)          # no shell, no quoting to get wrong
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", target])
        else:
            subprocess.Popen(["xdg-open", target])
        return True
    except Exception:
        return False


def _launch_app(name: str) -> bool:
    """Launch an application by name using list-form argv only.

    A name captured from speech must never be concatenated into a shell command
    line; on Windows `Popen(app, shell=True)` would happily run `calc & del ...`.
    """
    try:
        subprocess.Popen([name])
        return True
    except Exception:
        if platform.system() == "Windows":
            try:
                os.startfile(name)
                return True
            except Exception:
                return False
        return False


def parse_upgraded_voice_command(text: str) -> Optional[str]:
    """Parse voice command — returns command string or None."""
    tl = text.lower().strip()
    for pattern, cmd in UPGRADED_VOICE_CMDS.items():
        m = re.search(pattern, tl)
        if m:
            # Commands that need extracted text
            if cmd == "OPEN_APP" and m.lastindex and m.lastindex >= 2:
                return f"OPEN_APP:{m.group(m.lastindex)}"
            if cmd == "CREATE_FOLDER" and m.lastindex:
                return f"CREATE_FOLDER:{m.group(m.lastindex)}"
            if cmd == "OPEN_FOLDER" and m.lastindex:
                return f"OPEN_FOLDER:{m.group(m.lastindex)}"
            if cmd == "GOOGLE_SEARCH" and m.lastindex:
                return f"GOOGLE_SEARCH:{m.group(m.lastindex)}"
            if cmd == "ASK_CLAUDE" and m.lastindex:
                return f"ASK_CLAUDE:{m.group(m.lastindex)}"
            if cmd == "BUILD_PROJECT":
                # Get the best capture group for the project description
                for g in range(m.lastindex or 0, 0, -1):
                    val = m.group(g)
                    if val and len(val) > 2:
                        return f"BUILD_PROJECT:{val}"
                return f"BUILD_PROJECT:{text}"
            if cmd == "OPEN_URL" and m.lastindex:
                return f"OPEN_URL:{m.group(m.lastindex)}"
            if cmd == "PHONE_OPEN_APP" and m.lastindex:
                return f"PHONE_OPEN_APP:{m.group(1)}"
            if cmd == "PHONE_SWIPE" and m.lastindex:
                return f"PHONE_SWIPE:{m.group(m.lastindex)}"
            if cmd == "OPEN_SYSTEM_FOLDER" and m.lastindex:
                return f"OPEN_SYSTEM_FOLDER:{m.group(m.lastindex)}"
            if cmd == "WRITE_CLIPBOARD" and m.lastindex:
                return f"WRITE_CLIPBOARD:{m.group(1)}"
            if cmd == "PHONE_SEND_TEXT" and m.lastindex:
                return f"PHONE_SEND_TEXT:{m.group(1)}"
            return cmd
    return None


def execute_upgraded_voice_command(command: str, session_id: str = "default") -> str:
    """
    Execute a voice command. Returns spoken response text.
    Integrates with task_orchestrator for complex tasks.
    """
    from task_orchestrator import (
        orchestrate, save_and_run_from_clipboard,
        PhoneBridge, _active_builders, _WORK_DIR,
        create_folder, open_folder,
    )

    now = datetime.now()

    # ── Time & Date ──────────────────────────────────────────────────────────
    if command == "TIME":
        return f"It's {now.strftime('%I:%M %p')}."

    if command == "DATE":
        return f"Today is {now.strftime('%A, %B %d, %Y')}."

    # ── Screenshot ───────────────────────────────────────────────────────────
    if command == "SCREENSHOT":
        try:
            from computer_control import take_screenshot
            result = take_screenshot()
            if result["success"]:
                return "Screenshot taken and saved!"
        except Exception:
            pass
        return "Could not take screenshot. Make sure pyautogui is installed."

    # ── Folder operations ────────────────────────────────────────────────────
    if command.startswith("CREATE_FOLDER:"):
        name = command.split(":", 1)[1]
        result = create_folder(name)
        if result["success"]:
            return f"Folder created and opened: {name}"
        return f"Could not create folder: {result.get('error', 'unknown error')}"

    if command.startswith("OPEN_FOLDER:"):
        name = command.split(":", 1)[1]
        result = open_folder(name)
        if result["success"]:
            return f"Opening folder: {name}"
        return f"Could not find folder: {name}"

    if command.startswith("OPEN_SYSTEM_FOLDER:"):
        folder_name = command.split(":", 1)[1]
        paths = {
            "desktop":   Path.home() / "Desktop",
            "downloads": Path.home() / "Downloads",
            "documents": Path.home() / "Documents",
            "pictures":  Path.home() / "Pictures",
            "music":     Path.home() / "Music",
            "videos":    Path.home() / "Videos",
        }
        path = paths.get(folder_name.lower(), Path.home() / folder_name.title())
        try:
            if not _open_path(path):
                return f"Could not open {folder_name}."
            return f"Opening {folder_name}."
        except Exception:
            return f"Could not open {folder_name}."

    # ── Browser & Search ─────────────────────────────────────────────────────
    if command == "BROWSER":
        webbrowser.open("https://www.google.com")
        return "Browser opened."

    if command.startswith("GOOGLE_SEARCH:"):
        query = command.split(":", 1)[1]
        url   = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        webbrowser.open(url)
        return f"Searching Google for: {query}"

    if command.startswith("OPEN_URL:"):
        url = command.split(":", 1)[1]
        webbrowser.open(url)
        return f"Opening {url}"

    # ── App launching ────────────────────────────────────────────────────────
    if command.startswith("OPEN_APP:"):
        app = command.split(":", 1)[1]
        try:
            if not _launch_app(app):
                return f"Could not open {app}."
            return f"Opening {app}."
        except Exception as e:
            return f"Could not open {app}: {e}"

    # ── BUILD PROJECT (the main upgrade) ─────────────────────────────────────
    if command.startswith("BUILD_PROJECT:"):
        description = command.split(":", 1)[1]
        result = orchestrate(description, session_id=session_id)
        if result.get("needs_input"):
            questions = result.get("questions", [])
            q_text = " First question: " + questions[0] if questions else ""
            return (
                f"{result['message']}{q_text} "
                f"Answer my questions and I'll prepare everything."
            )
        return result.get("message", "Starting your project!")

    # ── Save and run code ────────────────────────────────────────────────────
    if command == "SAVE_CODE":
        result = save_and_run_from_clipboard(session_id)
        return result.get("message", "Code saved! Opening project folder and running it.")

    if command == "RUN_PROJECT":
        builder = _active_builders.get(session_id)
        if builder:
            result = builder.run_project()
            return result.get("message", "Running your project!")
        return "No active project. Say 'build a game' first to start one."

    if command == "OPEN_PROJECT_FOLDER":
        try:
            _open_path(_WORK_DIR)
            return "Opening your projects folder."
        except Exception:
            return "Could not open projects folder."

    # ── Claude bridge ────────────────────────────────────────────────────────
    if command.startswith("ASK_CLAUDE:"):
        query = command.split(":", 1)[1]
        webbrowser.open("https://claude.ai/new")
        if CLIP_OK:
            pyperclip.copy(query)
        return "Claude.ai is open. Your question was copied to clipboard — just paste it."

    # ── Clipboard ────────────────────────────────────────────────────────────
    if command == "READ_CLIPBOARD":
        if CLIP_OK:
            try:
                content = pyperclip.paste()
                if content:
                    short = content[:100] + "..." if len(content) > 100 else content
                    return f"Clipboard contains: {short}"
                return "Clipboard is empty."
            except Exception:
                pass
        return "Cannot read clipboard. Install pyperclip."

    if command == "CLEAR_CLIPBOARD":
        if CLIP_OK:
            try:
                pyperclip.copy("")
                return "Clipboard cleared."
            except Exception:
                pass
        return "Could not clear clipboard."

    if command.startswith("WRITE_CLIPBOARD:"):
        text = command.split(":", 1)[1]
        if CLIP_OK:
            try:
                pyperclip.copy(text)
                return f"Copied to clipboard: {text}"
            except Exception:
                pass
        return "Could not write to clipboard."

    # ── Volume (Windows) ─────────────────────────────────────────────────────
    if command == "VOLUME_UP":
        if platform.system() == "Windows":
            if GUI_OK:
                import pyautogui as pg
                for _ in range(5):
                    pg.press("volumeup")
                return "Volume up."
        return "Volume up command sent."

    if command == "VOLUME_DOWN":
        if platform.system() == "Windows":
            if GUI_OK:
                import pyautogui as pg
                for _ in range(5):
                    pg.press("volumedown")
                return "Volume down."
        return "Volume down command sent."

    if command == "MUTE":
        if GUI_OK:
            import pyautogui as pg
            pg.press("volumemute")
        return "Muted."

    if command == "UNMUTE":
        if GUI_OK:
            import pyautogui as pg
            pg.press("volumemute")
        return "Unmuted."

    # ── System control ───────────────────────────────────────────────────────
    if command == "LOCK_SCREEN":
        if platform.system() == "Windows":
            subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"])
        elif platform.system() == "Darwin":
            subprocess.run(["pmset", "displaysleepnow"])
        return "Screen locked."

    if command == "SLEEP":
        if platform.system() == "Windows":
            subprocess.run(["powercfg", "/hibernate", "off"], capture_output=True)
            subprocess.Popen("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True)
        return "Going to sleep mode."

    if command == "EMPTY_TRASH":
        if platform.system() == "Windows":
            try:
                import winshell
                winshell.recycle_bin().empty(confirm=False, show_progress=False, sound=False)
                return "Recycle bin emptied!"
            except Exception:
                subprocess.run(
                    'PowerShell -Command "Clear-RecycleBin -Force"',
                    shell=True, capture_output=True,
                )
                return "Recycle bin emptied."
        return "Could not empty trash on this OS."

    # ── Phone control ────────────────────────────────────────────────────────
    if command == "PHONE_STATUS":
        phone = PhoneBridge()
        if phone.is_connected():
            return "Your phone is connected via ADB. I can control it!"
        return (
            "Phone not connected. "
            "Connect via USB, enable USB debugging, and run: adb devices"
        )

    if command == "PHONE_SCREENSHOT":
        phone  = PhoneBridge()
        result = phone.take_screenshot()
        return result.get("message", result.get("error", "Phone screenshot done."))

    if command.startswith("PHONE_OPEN_APP:"):
        app_name = command.split(":", 1)[1]
        phone    = PhoneBridge()
        result   = phone.open_app(app_name)
        return result.get("message", result.get("error", "Done."))

    if command == "PHONE_BACK":
        phone = PhoneBridge()
        phone.press_back()
        return "Phone back button pressed."

    if command.startswith("PHONE_SWIPE:"):
        direction = command.split(":", 1)[1]
        phone     = PhoneBridge()
        phone.swipe(direction)
        return f"Phone swiped {direction}."

    if command.startswith("PHONE_SEND_TEXT:"):
        text  = command.split(":", 1)[1]
        phone = PhoneBridge()
        result = phone.send_text(text)
        return result.get("message", "Text sent to phone.")

    # ── Wake word ────────────────────────────────────────────────────────────
    if command == "WAKE":
        return "I'm here. What do you need?"

    # ── Legacy commands ──────────────────────────────────────────────────────
    if command == "VOICE:stop":
        return "Stopping voice listener."

    # ── Page code extraction ─────────────────────────────────────────────────
    if command.startswith("COPY_CODE_FROM_URL:"):
        url = command.split(":", 2)[1] if ":" in command else ""
        if not url:
            return "What URL should I extract code from? Say the full URL."
        try:
            from page_code_extractor import extract_and_save
            result = extract_and_save(url=url, voice_confirm=False)
            if result.get("success"):
                fname = os.path.basename(result.get("filepath", "file"))
                lang  = result.get("language", "unknown")
                return f"Code extracted and saved to {fname}. Language: {lang}. Done!"
            return f"Could not extract code: {result.get('error', 'page had no code blocks')}"
        except Exception as e:
            return f"Code extraction failed: {e}"

    if command.startswith("LIST_CODE_ON_URL:"):
        url = command.split(":", 2)[1] if ":" in command else ""
        if not url:
            return "Which URL should I check for code?"
        try:
            from page_code_extractor import list_all_code_on_page
            result = list_all_code_on_page(url)
            if result.get("success"):
                count = result.get("total_blocks", 0)
                if count == 0:
                    return "No code blocks found on that page."
                langs = [b.get("language", "?") for b in result.get("blocks", [])[:3]]
                return f"Found {count} code blocks on that page. Languages: {', '.join(langs)}. Say copy code from that URL to save one."
            return "Could not read that page."
        except Exception as e:
            return f"Could not check page: {e}"

    # ── Self-modification ────────────────────────────────────────────────────
    if command.startswith("SELF_IMPROVE:") or command == "SELF_IMPROVE":
        req = command.split(":", 1)[1] if ":" in command else "improve the UI with a better dark theme"
        try:
            from self_modify import self_improve
            result = self_improve(req, use_claude=False)  # use local LLM (no login needed)
            if result.get("success"):
                return f"Improvement applied to {result.get('target_file', 'the UI')}. Reloading now."
            return f"Could not apply improvement: {result.get('error', 'unknown error')}"
        except Exception as e:
            return f"Self-improve failed: {e}"

    if command.startswith("SELF_IMPROVE_CLAUDE:") or command == "SELF_IMPROVE_CLAUDE":
        req = command.split(":", 1)[1] if ":" in command else "give me a better UI"
        try:
            from self_modify import self_improve
            result = self_improve(req, use_claude=True)
            if result.get("success"):
                src = result.get("code_source", "AI")
                return f"Used {src} to improve {result.get('target_file', 'the UI')}. Done!"
            return f"Could not improve: {result.get('error', 'check Claude.ai session')}"
        except Exception as e:
            return f"Self-improve with Claude failed: {e}"

    if command == "SELF_ROLLBACK":
        try:
            from self_modify import rollback
            result = rollback("index.html")
            if result.get("success"):
                return "Last UI change rolled back. Restored previous version."
            return f"Rollback failed: {result.get('error', 'no backup found')}"
        except Exception as e:
            return f"Rollback failed: {e}"

    # ── Wireless phone ──────────────────────────────────────────────────────
    if command == "PHONE_WIRELESS_ENABLE":
        try:
            result = PhoneBridge.enable_wireless()
            if result.get("success"):
                ip = result.get("ip", "")
                return f"Wireless ADB enabled! Phone connected at {ip}. You can now unplug the USB cable."
            return f"Could not enable wireless: {result.get('error', 'make sure USB is connected')}"
        except Exception as e:
            return f"Wireless enable failed: {e}"

    if command == "PHONE_WIRELESS_CONNECT":
        try:
            result = PhoneBridge.connect_saved_wireless()
            if result.get("success"):
                return f"Reconnected to phone wirelessly at {result.get('ip', 'saved IP')}."
            return f"Could not reconnect: {result.get('error', 'run wireless enable first')}"
        except Exception as e:
            return f"Reconnect failed: {e}"

    if command == "PHONE_VOLUME_UP":
        try:
            import subprocess as sp
            sp.run(["adb", "shell", "input", "keyevent", "24"], timeout=5, capture_output=True)
            return "Phone volume increased."
        except Exception:
            return "Phone not connected."

    if command == "PHONE_VOLUME_DOWN":
        try:
            import subprocess as sp
            sp.run(["adb", "shell", "input", "keyevent", "25"], timeout=5, capture_output=True)
            return "Phone volume decreased."
        except Exception:
            return "Phone not connected."

    if command == "PHONE_HOME":
        try:
            import subprocess as sp
            sp.run(["adb", "shell", "input", "keyevent", "3"], timeout=5, capture_output=True)
            return "Phone home button pressed."
        except Exception:
            return "Phone not connected."

    if command == "PHONE_POWER":
        try:
            import subprocess as sp
            sp.run(["adb", "shell", "input", "keyevent", "26"], timeout=5, capture_output=True)
            return "Phone power button pressed."
        except Exception:
            return "Phone not connected."

    # ── App window control ──────────────────────────────────────────────────
    if command.startswith("FOCUS_APP:"):
        app_title = command.split(":", 1)[1]
        try:
            from app_control import focus_window
            result = focus_window(app_title)
            if result.get("success"):
                return f"Switched to {app_title}."
            return f"Could not find {app_title} window. Is it open?"
        except Exception as e:
            return f"Could not switch window: {e}"

    if command == "LIST_WINDOWS":
        try:
            from app_control import list_windows
            windows = list_windows()
            titles  = [w.get("title", "") for w in windows[:6] if w.get("title")]
            if titles:
                return f"Open windows: {', '.join(titles)}."
            return "No windows detected."
        except Exception:
            return "Could not list windows. App control not available."

    if command.startswith("CHROME_NEW_TAB:"):
        url = command.split(":", 1)[1] if ":" in command else "https://google.com"
        try:
            from app_control import control_app
            control_app("chrome_new_tab", {"url": url})
            return f"Opened new Chrome tab: {url}"
        except Exception:
            return "Chrome not available."

    if command.startswith("CHROME_NAVIGATE:"):
        url = command.split(":", 1)[1]
        try:
            from app_control import control_app
            control_app("chrome_navigate", {"url": url})
            return f"Chrome navigating to {url}"
        except Exception:
            return "Could not navigate Chrome."

    if command == "VSCODE_SAVE":
        try:
            from app_control import control_app
            control_app("vscode_save", {})
            return "File saved in VS Code."
        except Exception:
            return "VS Code not available."

    if command == "VSCODE_TERMINAL":
        try:
            from app_control import control_app
            control_app("vscode_terminal", {})
            return "VS Code terminal opened."
        except Exception:
            return "VS Code not available."

    if command.startswith("VSCODE_RUN_TERMINAL:"):
        cmd_str = command.split(":", 1)[1]
        try:
            from app_control import control_app
            control_app("vscode_run_in_terminal", {"cmd": cmd_str})
            return f"Running in VS Code terminal: {cmd_str}"
        except Exception:
            return "VS Code not available."

    return f"Command '{command}' received."
