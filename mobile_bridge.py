"""
mobile_bridge.py — Telegram Bot Bridge for Ultron-J BEYOND JARVIS.

This makes Ultron-J accessible from your phone as if it were a mobile app.

Features:
- Chat with Ultron from anywhere via Telegram
- Send voice notes → STT → LLM → TTS reply sent back
- /status  — system health + mood
- /goals   — active goals
- /screen  — screenshot of your PC sent to phone
- /weather — Hyderabad weather
- /note    — save a note
- /run     — run Python code
- Image analysis: send a photo → Ultron describes it
- Ultron can send YOU proactive alerts via Telegram (not just respond)

Setup:
1. Create a bot at t.me/BotFather → get TELEGRAM_BOT_TOKEN
2. Get your chat ID: message @userinfobot
3. Set in .env: TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=...
4. Run: python mobile_bridge.py   (or it starts automatically with app.py)
"""

import io
import json
import os
import threading
import time
import traceback
from datetime import datetime
from typing import Optional

import requests

_BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
BRIDGE_LOG_FILE   = os.path.join(_BASE_DIR, "mobile_bridge_log.json")
VOICE_CACHE_DIR   = os.path.join(_BASE_DIR, "voice_cache")

# ── Config ─────────────────────────────────────────────────────────────────────
try:
    from config import (
        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
        JEEVAN_NAME, AGENT_NAME, JEEVAN_LOCATION,
    )
except ImportError:
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
    JEEVAN_NAME        = "Jeevan"
    AGENT_NAME         = "Ultron-J"
    JEEVAN_LOCATION    = "Hyderabad, Telangana, India"

ULTRON_BASE_URL = os.environ.get("ULTRON_BASE_URL", "http://localhost:5000")
_POLL_TIMEOUT   = 30
_RUNNING        = False
_LOG_LOCK       = threading.Lock()

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


# =============================================================================
# TELEGRAM API HELPERS
# =============================================================================

def _tg(method: str, data: dict = None, files: dict = None) -> dict:
    """Call Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN:
        return {}
    url = f"{TELEGRAM_API}/{method}"
    try:
        if files:
            r = requests.post(url, data=data or {}, files=files, timeout=30)
        else:
            r = requests.post(url, json=data or {}, timeout=30)
        return r.json()
    except Exception as e:
        print(f"[MobileBridge] Telegram API error: {e}")
        return {}


def send_message(text: str, chat_id: str = None, parse_mode: str = "Markdown") -> dict:
    """Send text message."""
    cid = chat_id or TELEGRAM_CHAT_ID
    if not cid:
        return {}
    # Telegram limit: 4096 chars
    if len(text) > 4000:
        text = text[:4000] + "\n\n_(truncated)_"
    return _tg("sendMessage", {"chat_id": cid, "text": text, "parse_mode": parse_mode})


def send_photo(image_path: str, caption: str = "", chat_id: str = None) -> dict:
    """Send photo."""
    cid = chat_id or TELEGRAM_CHAT_ID
    if not cid:
        return {}
    with open(image_path, "rb") as f:
        return _tg("sendPhoto", {"chat_id": cid, "caption": caption},
                   files={"photo": f})


def send_audio(audio_path: str, caption: str = "", chat_id: str = None) -> dict:
    """Send audio file."""
    cid = chat_id or TELEGRAM_CHAT_ID
    if not cid:
        return {}
    with open(audio_path, "rb") as f:
        return _tg("sendAudio", {"chat_id": cid, "caption": caption},
                   files={"audio": f})


def send_document(path: str, caption: str = "", chat_id: str = None) -> dict:
    """Send any file as document."""
    cid = chat_id or TELEGRAM_CHAT_ID
    if not cid:
        return {}
    with open(path, "rb") as f:
        return _tg("sendDocument", {"chat_id": cid, "caption": caption},
                   files={"document": f})


def send_typing(chat_id: str = None):
    """Show 'typing' indicator."""
    cid = chat_id or TELEGRAM_CHAT_ID
    if cid:
        _tg("sendChatAction", {"chat_id": cid, "action": "typing"})


# =============================================================================
# PROACTIVE ALERTS (Ultron → Phone)
# =============================================================================

def alert(message: str, priority: str = "normal"):
    """Send a proactive alert to Jeevan's phone."""
    icons = {"critical": "🚨", "high": "⚠️", "normal": "💬", "info": "ℹ️"}
    icon  = icons.get(priority, "💬")
    send_message(f"{icon} *Ultron-J Alert*\n\n{message}")
    _log({"action": "alert_sent", "message": message[:100], "priority": priority})


def morning_briefing_to_phone(briefing_text: str):
    send_message(f"🌅 *Good Morning, {JEEVAN_NAME}!*\n\n{briefing_text}")


def goal_completed_to_phone(goal_name: str, result: str):
    send_message(f"✅ *Goal Completed*\n*{goal_name}*\n\n{result[:300]}")


def error_detected_to_phone(errors: list):
    error_text = "\n".join(f"• {e.get('context', '')[:80]}" for e in errors[:3])
    send_message(f"🔴 *Error Detected on Screen*\n\n{error_text}")


# =============================================================================
# MESSAGE HANDLER
# =============================================================================

def _call_ultron(endpoint: str, method: str = "POST", data: dict = None) -> dict:
    """Call the local Ultron-J Flask API."""
    url = f"{ULTRON_BASE_URL}{endpoint}"
    try:
        if method == "GET":
            r = requests.get(url, timeout=30)
        else:
            r = requests.post(url, json=data or {}, timeout=30)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def _handle_command(text: str, chat_id: str) -> str:
    """Handle /commands."""
    cmd = text.strip().lower()

    if cmd in ("/start", "/help"):
        return (
            f"👋 *Ultron-J Mobile Bridge*\n\n"
            f"Commands:\n"
            f"`/status` — System health + mood\n"
            f"`/goals` — Active goals\n"
            f"`/screen` — Screenshot of your PC\n"
            f"`/weather` — Hyderabad weather\n"
            f"`/note <text>` — Save a note\n"
            f"`/run <code>` — Run Python\n"
            f"`/mood` — Current mood\n"
            f"`/memory <query>` — Search memory\n"
            f"\nOr just *talk normally* — I'll reply!"
        )

    if cmd == "/status":
        r = _call_ultron("/status", "GET")
        mood   = r.get("personality", {}).get("mood", "?")
        energy = r.get("personality", {}).get("energy", 0)
        mem    = r.get("system", {}).get("ram_percent", "?")
        return (f"⚡ *Ultron-J Status*\n"
                f"Mood: {mood} | Energy: {int(energy*100)}%\n"
                f"RAM: {mem}% used")

    if cmd == "/mood":
        r = _call_ultron("/personality", "GET")
        return f"🎭 Mood: *{r.get('mood','?')}*\n_{r.get('phrase','')}_"

    if cmd == "/goals":
        r = _call_ultron("/agent/goals", "GET")
        goals = r.get("goals", [])
        if not goals:
            return "No active goals right now."
        lines = [f"• [{g.get('status','?').upper()}] {g.get('description','')[:60]}"
                 for g in goals[:5]]
        return "🎯 *Active Goals*\n" + "\n".join(lines)

    if cmd == "/weather":
        r = _call_ultron("/weather", "GET")
        return f"🌤️ {r.get('weather', r.get('error', 'Unavailable'))}"

    if cmd.startswith("/note "):
        note_text = text[6:].strip()
        r = _call_ultron("/note", data={"title": "Mobile note", "content": note_text})
        return "📝 Note saved!" if r.get("success") else f"Error: {r.get('error')}"

    if cmd.startswith("/run "):
        code = text[5:].strip()
        r = _call_ultron("/run_code", data={"code": code})
        output = r.get("output", r.get("error", "No output"))
        return f"```\n{output[:1000]}\n```"

    if cmd.startswith("/memory "):
        query = text[8:].strip()
        r = _call_ultron("/agent/memory/search", data={"query": query})
        results = r.get("results", [])
        if not results:
            return "Nothing found in memory."
        lines = [f"• {res.get('content','')[:80]}" for res in results[:5]]
        return "🧠 *Memory Results*\n" + "\n".join(lines)

    if cmd == "/screen":
        return None  # Handled separately in _handle_message

    return None   # Not a command


def _handle_message(update: dict):
    """Process one incoming Telegram update."""
    try:
        message  = update.get("message", {})
        chat_id  = str(message.get("chat", {}).get("id", ""))
        text     = message.get("text", "")
        voice    = message.get("voice")
        photo    = message.get("photo")

        if not chat_id:
            return

        # Security: only accept from authorized chat
        if TELEGRAM_CHAT_ID and chat_id != str(TELEGRAM_CHAT_ID):
            send_message("⛔ Unauthorized.", chat_id=chat_id)
            return

        send_typing(chat_id)

        # Screen command — send screenshot
        if text.strip().lower() == "/screen":
            from screen_engine import take_screenshot
            import tempfile
            img = take_screenshot(save=False)
            if img:
                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                    img.save(tmp.name, "JPEG", quality=70)
                    send_photo(tmp.name, caption="📸 Current screen", chat_id=chat_id)
                    os.unlink(tmp.name)
            else:
                send_message("❌ Screenshot failed.", chat_id=chat_id)
            return

        # Command
        if text.startswith("/"):
            reply = _handle_command(text, chat_id)
            if reply:
                send_message(reply, chat_id=chat_id)
                return

        # Voice message → STT → Ultron
        if voice:
            file_id = voice.get("file_id")
            file_info = _tg("getFile", {"file_id": file_id})
            file_path = file_info.get("result", {}).get("file_path", "")
            if file_path:
                audio_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
                audio_bytes = requests.get(audio_url, timeout=15).content
                r = _call_ultron("/voice/stt", data={"audio_b64": audio_bytes.hex()})
                text = r.get("text", "")
                if not text:
                    send_message("❌ Could not transcribe voice.", chat_id=chat_id)
                    return

        # Photo → analyze
        if photo:
            file_id = photo[-1].get("file_id")
            file_info = _tg("getFile", {"file_id": file_id})
            file_path = file_info.get("result", {}).get("file_path", "")
            if file_path:
                img_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
                r = _call_ultron("/analyze_image", data={"url": img_url,
                                                          "prompt": "Describe this image in detail."})
                reply = r.get("analysis", r.get("error", "Could not analyze image."))
                send_message(reply, chat_id=chat_id)
            return

        # Text → Ultron chat
        if text:
            r = _call_ultron("/chat", data={"message": text, "session_id": f"telegram_{chat_id}"})
            reply = r.get("response", r.get("error", "No response from Ultron."))
            send_message(reply, chat_id=chat_id)
            _log({"action": "chat", "message": text[:80], "reply_len": len(reply)})

    except Exception as e:
        _log({"action": "handle_error", "error": str(e), "tb": traceback.format_exc()[:300]})


# =============================================================================
# POLLING LOOP
# =============================================================================

_last_update_id = 0

def _poll_loop():
    global _last_update_id, _RUNNING
    print(f"[MobileBridge] Polling Telegram for updates...")
    _RUNNING = True

    while _RUNNING:
        try:
            r = _tg("getUpdates", {
                "offset": _last_update_id + 1,
                "timeout": _POLL_TIMEOUT,
                "allowed_updates": ["message"],
            })
            updates = r.get("result", [])
            for update in updates:
                _last_update_id = update.get("update_id", _last_update_id)
                threading.Thread(target=_handle_message, args=(update,), daemon=True).start()
        except Exception as e:
            print(f"[MobileBridge] Poll error: {e}")
            time.sleep(5)


def start(background: bool = True):
    """Start the Telegram bot polling."""
    if not TELEGRAM_BOT_TOKEN:
        print("[MobileBridge] No TELEGRAM_BOT_TOKEN set — bot disabled")
        return False

    if background:
        t = threading.Thread(target=_poll_loop, daemon=True, name="telegram_bot")
        t.start()
        print(f"[MobileBridge] Telegram bot started in background")
    else:
        _poll_loop()
    return True


def stop():
    global _RUNNING
    _RUNNING = False


def get_status() -> dict:
    return {
        "enabled":     bool(TELEGRAM_BOT_TOKEN),
        "running":     _RUNNING,
        "chat_id_set": bool(TELEGRAM_CHAT_ID),
    }


# =============================================================================
# LOG
# =============================================================================

def _log(data: dict):
    with _LOG_LOCK:
        try:
            log = []
            if os.path.exists(BRIDGE_LOG_FILE):
                with open(BRIDGE_LOG_FILE) as f:
                    log = json.load(f)
            log.append({"ts": datetime.now().isoformat(), **data})
            if len(log) > 200:
                log = log[-200:]
            with open(BRIDGE_LOG_FILE, "w") as f:
                json.dump(log, f, indent=2)
        except Exception:
            pass

_LOG_LOCK = threading.Lock()

if __name__ == "__main__":
    start(background=False)
