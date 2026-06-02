"""
ultron_listener.py — Jarvis-mode Passive Voice Listener for Ultron-J ULTIMATE v3

HOW IT WORKS (JARVIS MODE):
  1. Server starts → plays "Olla Jeevan, I am Ultron. How can I help you?"
  2. Starts listening to microphone 24/7
  3. Detects wake word "Ultron" / "Hey Ultron" locally (no internet needed)
  4. Records your full command until you stop talking
  5. Sends audio to Flask server → STT → LLM → TTS
  6. Plays audio response through speakers sentence by sentence
  7. Goes back to listening immediately — zero gap, always ready
  8. JARVIS MODE: after greeting, listens for first query WITHOUT needing wake word
     (first 10 seconds = open ears, then wake-word required after)

INSTALL:
  pip install faster-whisper pyaudio edge-tts aiohttp requests
  Optional wake word: pip install pvporcupine pvrecorder (free key: picovoice.ai)

RUN:
  Terminal 1: python app.py
  Terminal 2: python ultron_listener.py
"""

import os
import sys
import io
import time
import wave
import json
import tempfile
import threading
import subprocess
import struct
import math
try:
    import audioop
    _AUDIOOP_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    _AUDIOOP_AVAILABLE = False
import requests
import asyncio
from datetime import datetime
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
ULTRON_SERVER       = "http://localhost:5000"

# Strict wake words — match anywhere in the utterance.
# These are unambiguous: any time they appear, treat as a wake.
WAKE_WORDS          = [
    "ok ultron", "okay ultron", "hey ultron", "yo ultron",
    "hello ultron", "ultron", "hey ultra", "ok ultra",
    "ok altron", "ok all tron",
    # "ultra" and "altron" removed — Whisper hallucinates these from background audio
]

# Bare "ok" / "okay" wake support — primary trigger Jeevan asked for.
# To avoid every casual "ok" firing, this fires only when the utterance
# STARTS with "ok " and the rest looks like a command (verb-led, or
# multi-word and not a filler/confirmation).
BARE_OK_WAKE_ENABLED = True

# Words that should NOT be treated as command starts after "ok" — these are
# typically casual confirmations or thinking-aloud filler.
_OK_FOLLOWUP_FILLERS = {
    "yeah", "yes", "no", "right", "sure", "cool", "fine", "good", "great",
    "nice", "gotcha", "alright", "perfect", "thanks", "thank", "wait", "hold",
    "hmm", "hm", "uh", "um", "let", "actually", "anyway", "so", "well",
    "but", "and", "or", "ok", "okay",
}

# Words that, if first after "ok", strongly indicate a command intent.
_OK_FOLLOWUP_COMMAND_VERBS = {
    "open", "close", "play", "pause", "stop", "start", "search", "find",
    "show", "tell", "what", "when", "where", "who", "why", "how", "make",
    "create", "delete", "remove", "move", "copy", "take", "go", "get",
    "read", "write", "send", "summarize", "summarise", "explain", "elaborate",
    "translate", "convert", "calculate", "compute", "check", "list",
    "remember", "recall", "forget", "mute", "unmute", "volume", "screen",
    "screenshot", "click", "type", "scroll", "minimize", "maximize", "focus",
    "launch", "give", "do", "ask", "search",
}


def matches_wake(spoken: str) -> bool:
    """
    Return True if `spoken` contains a wake word that should activate Ultron.

    Strict wake words (e.g. 'ok ultron', 'yo ultron') match anywhere.
    Bare 'ok' / 'okay' matches only when the utterance starts with it AND
    the remainder looks like a command (verb-led or multi-word non-filler).
    This stops casual phrases like 'ok yeah', 'ok let me think', or
    'ok cool that works' from waking the assistant.
    """
    if not spoken:
        return False
    # Strip ALL punctuation Whisper adds (commas, periods, question marks,
    # apostrophes inside contractions like "i'll", quotes). Previously the
    # bare-ok wake bailed because parts[0] was "okay," not "okay".
    import re as _re
    s = _re.sub(r"[^\w\s]", " ", spoken.lower()).strip()
    s = _re.sub(r"\s+", " ", s)   # collapse double spaces
    if not s:
        return False
    # Strict words — match anywhere
    if any(w in s for w in WAKE_WORDS):
        return True
    # Bare "ok" / "okay" wake
    if not BARE_OK_WAKE_ENABLED:
        return False
    parts = s.split()
    if not parts or parts[0] not in ("ok", "okay"):
        return False
    rest = parts[1:]
    if not rest:
        return False  # bare "ok" alone — ignore
    first = rest[0]
    if first in _OK_FOLLOWUP_FILLERS:
        return False
    if first in _OK_FOLLOWUP_COMMAND_VERBS:
        return True
    # Otherwise: accept only if 3+ word command (long enough to be intentional)
    return len(rest) >= 3
SAMPLE_RATE         = 16000
CHANNELS            = 1
CHUNK               = 1024
RECORD_SECONDS_MAX  = 12
SILENCE_THRESHOLD   = 900     # raised; auto-calibrated at startup anyway
SILENCE_TIMEOUT     = 2.8
VAD_CHECK_INTERVAL  = 0.3
PICOVOICE_KEY       = os.environ.get("PICOVOICE_ACCESS_KEY", "").strip() or None

# ── Finger-snap wake detector ──────────────────────────────────────────────
# Tony-Stark style: double-snap within ~1.2s = wake. No voice needed,
# no accent issues, no Whisper hallucinations. Detection signature:
#   - A snap is a SHARP transient: current chunk energy spikes from quiet
#     to very high in ONE chunk window (~64 ms at 16 kHz / 1024 samples).
#   - Speech rises gradually over many chunks; a snap is one explosion.
# So we look for: (current_energy / max(prev_energy, 1)) > rise_ratio,
# AND current_energy > absolute floor (filters out tiny mic noise).
# Single snaps are ignored. TWO snaps inside the window = wake.
SNAP_WAKE_ENABLED    = os.environ.get("ULTRON_SNAP_WAKE", "1").strip() != "0"
# Tunings reflect reality: many mics saturate at 32767 (int16 ceiling).
# A 6× rise is physically impossible when ambient sits at 20k+. We instead
# look for the PEAK itself: a single chunk reaching near-saturation,
# even if ambient is already noisy. The double-snap pattern (two such
# peaks inside the window) is the actual false-positive filter — a
# single random thump won't fire, but two distinct snaps will.
SNAP_RISE_RATIO      = 2.5    # stricter rise — speech bursts rise ~1.5× gradually,
                              # snaps spike instantly. 2.5× is hard to fake with voice.
SNAP_ABS_FLOOR       = 12000  # raised back from 7000 — was firing on any speech burst.
                              # 12k cuts off normal speech (which peaks ~8-10k) while
                              # still catching clear snaps (the user's good snaps were
                              # 13k–22k). Combined with the rise-ratio bump above,
                              # this should stop false wakes from TV / talking nearby.
SNAP_DOUBLE_WINDOW_S = 1.2    # second snap must fall within this window
SNAP_DOUBLE_MIN_S    = 0.35   # ...but not within 350 ms — filters snap echo
                              # (room reverb fires a fake "second snap" ~150-300ms
                              # after the first, causing false wakes followed by
                              # "no speech detected" because the user never spoke).
                              # Genuine human double-snaps land 400-700ms apart.
SNAP_DEBUG           = False  # set True to log every near-miss for re-tuning

# Jarvis mode — first N seconds after startup: listen without wake word
# Reduced from 12 to 6; also uses a stricter energy threshold (×3 instead of ×1.5)
JARVIS_OPEN_EARS_SECONDS = 6

# Startup greeting (Jeevan's custom)
STARTUP_GREETING = "Olla Jeevan, I am Ultron. How can I help you?"
STARTUP_VOICE    = "en-US-GuyNeural"

VOICE_ID_ENABLED   = False
VOICE_ID_THRESHOLD = 0.82
STRANGER_RESPONSE  = True

# ─────────────────────────────────────────────────────────────────────────────
# OPTIONAL IMPORTS
# ─────────────────────────────────────────────────────────────────────────────
try:
    import sounddevice as sd
    import numpy as np
    PYAUDIO_AVAILABLE = True
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False
    SOUNDDEVICE_AVAILABLE = False

try:
    from faster_whisper import WhisperModel
    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    FASTER_WHISPER_AVAILABLE = False

try:
    import pvporcupine
    from pvrecorder import PvRecorder
    PICOVOICE_AVAILABLE = True
except ImportError:
    PICOVOICE_AVAILABLE = False

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False

try:
    import playsound
    PLAYSOUND_AVAILABLE = True
except ImportError:
    PLAYSOUND_AVAILABLE = False

try:
    from voice_identity import verify_speaker, is_enrolled
    VOICE_ID_AVAILABLE = True
except ImportError:
    VOICE_ID_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# STATE
# ─────────────────────────────────────────────────────────────────────────────
_running        = True
_is_processing  = False
_tts_playing    = False
_whisper_model  = None
_whisper_lock   = threading.Lock()
_startup_time   = time.time()

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────
COLORS = {
    "INFO":   "\033[0m",
    "OK":     "\033[92m",
    "ERR":    "\033[91m",
    "WARN":   "\033[93m",
    "WAKE":   "\033[95m",
    "SPEAK":  "\033[96m",
    "LISTEN": "\033[94m",
}
RESET = "\033[0m"

def log(msg: str, level: str = "INFO"):
    ts    = datetime.now().strftime("%H:%M:%S")
    color = COLORS.get(level, "")
    print(f"{color}[{ts}] [{level:6s}] {msg}{RESET}")

# ─────────────────────────────────────────────────────────────────────────────
# SERVER HEALTH CHECK
# ─────────────────────────────────────────────────────────────────────────────
def check_server() -> bool:
    for attempt in range(15):
        try:
            r = requests.get(f"{ULTRON_SERVER}/status", timeout=3)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        if attempt < 14:
            time.sleep(2)
            log(f"Waiting for server... attempt {attempt+1}/15", "WARN")
    return False

# ─────────────────────────────────────────────────────────────────────────────
# WHISPER MODEL
# ─────────────────────────────────────────────────────────────────────────────
def _load_whisper():
    global _whisper_model
    with _whisper_lock:
        if _whisper_model is None and FASTER_WHISPER_AVAILABLE:
            try:
                # Model controlled by ULTRON_WHISPER_MODEL env var.
                # Defaults to "base" (~142MB, much better than "tiny" at
                # accented English, still fast enough for live wake-word).
                #   tiny    ~75MB   weakest  fastest
                #   base   ~142MB   good     fast    ← default
                #   small  ~461MB   better   medium
                #   medium ~1.5GB   strong   slow
                #   large-v3 ~3.0GB best     slowest
                model_size = os.environ.get("ULTRON_WHISPER_MODEL", "base").strip() or "base"
                log(f"Loading Whisper model ({model_size})...", "INFO")
                _whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8")
                log(f"Whisper ready ({model_size})", "OK")
            except Exception as e:
                log(f"Whisper load failed: {e}", "ERR")

def transcribe_locally(audio_path: str) -> str:
    with _whisper_lock:
        if _whisper_model is None:
            return ""
    try:
        segments, _ = _whisper_model.transcribe(
            audio_path,
            beam_size=1,
            language="en",
            vad_filter=True,           # filters out non-speech (fixes Whisper hallucination on noise/silence)
            vad_parameters={
                "min_silence_duration_ms": 500,
                "speech_pad_ms": 200,
                "threshold": 0.5,      # Silero VAD confidence — must be 50%+ speech to process
            },
            no_speech_threshold=0.6,   # skip segments where Whisper itself thinks it's not speech
        )
        text = " ".join(s.text for s in segments).lower().strip()
        # Reject common Whisper hallucinations on silence/noise
        _HALLUCINATED_PHRASES = {
            "you", "thank you", "thanks", "thank you for watching",
            "bye", "goodbye", ".", " ", "", "uh", "um", "hmm",
            "the", "a", "i", "okay", "oh", "ah",
        }
        if text in _HALLUCINATED_PHRASES:
            return ""
        return text
    except Exception:
        return ""

# ─────────────────────────────────────────────────────────────────────────────
# AUDIO UTILITIES
# ─────────────────────────────────────────────────────────────────────────────
def rms(data: bytes) -> float:
    if _AUDIOOP_AVAILABLE:
        try:
            return audioop.rms(data, 2)
        except Exception:
            pass
    try:
        import numpy as _np
        arr = _np.frombuffer(data, dtype=_np.int16).astype(_np.float32)
        return float(_np.sqrt(_np.mean(arr ** 2))) if len(arr) else 0.0
    except Exception:
        count = len(data) // 2
        if count == 0:
            return 0.0
        shorts = struct.unpack(f"{count}h", data[:count * 2])
        return math.sqrt(sum(s * s for s in shorts) / count)

def save_wav(frames: list, path: str):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(b"".join(frames))

# ─────────────────────────────────────────────────────────────────────────────
# AUDIO PLAYBACK
# ─────────────────────────────────────────────────────────────────────────────
def play_audio_bytes(audio_bytes: bytes):
    """Play audio bytes through speakers."""
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio_bytes)
            tmp = f.name
        _play_file(tmp)
        try:
            os.unlink(tmp)
        except Exception:
            pass
    except Exception as e:
        log(f"Playback error: {e}", "WARN")

def _play_file(path: str):
    """Cross-platform audio file playback."""
    import platform
    system = platform.system()
    try:
        if PLAYSOUND_AVAILABLE:
            playsound.playsound(path, block=True)
        elif system == "Windows":
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME)
        elif system == "Darwin":
            subprocess.run(["afplay", path], check=True, timeout=30)
        else:
            # Linux — try multiple players. Each has its OWN flag set;
            # the previous "-q" applied to all was wrong (ffplay rejects -q
            # as unknown, falls through to aplay, which then tries to play
            # the MP3 as raw PCM → garbled noise). aplay only handles WAV,
            # so we exclude MP3 files from it.
            is_mp3 = path.lower().endswith(".mp3")
            attempts = [
                ["mpg123",  "-q", path],
                ["mpg321",  "-q", path],
                ["ffplay",  "-nodisp", "-autoexit", "-loglevel", "quiet", path],
                ["paplay",  path],   # PulseAudio / PipeWire — handles wav + many formats
            ]
            if not is_mp3:
                attempts.append(["aplay", "-q", path])    # aplay only for WAV
            for cmd in attempts:
                try:
                    subprocess.run(cmd, timeout=30,
                                   capture_output=True, check=True)
                    return
                except (FileNotFoundError, subprocess.CalledProcessError):
                    continue
    except Exception:
        pass

def play_edge_tts_sync(text: str, voice: str = "en-US-GuyNeural"):
    """Speak text using Edge TTS synchronously (blocks until done)."""
    if not EDGE_TTS_AVAILABLE:
        log(f"[TTS unavailable] {text}", "SPEAK")
        return
    try:
        async def _gen():
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                tmp = f.name
            comm = edge_tts.Communicate(text, voice)
            await comm.save(tmp)
            return tmp

        loop = asyncio.new_event_loop()
        tmp  = loop.run_until_complete(_gen())
        loop.close()
        _play_file(tmp)
        try:
            os.unlink(tmp)
        except Exception:
            pass
    except Exception as e:
        log(f"TTS error: {e}", "WARN")

# ─────────────────────────────────────────────────────────────────────────────
# STARTUP GREETING — "Olla Jeevan, I am Ultron..."
# ─────────────────────────────────────────────────────────────────────────────
def play_startup_greeting():
    """Play the Jarvis-style startup greeting."""
    log("Playing startup greeting...", "SPEAK")
    log(f"  \"{STARTUP_GREETING}\"", "SPEAK")
    play_edge_tts_sync(STARTUP_GREETING, STARTUP_VOICE)

def _in_open_ears_window() -> bool:
    """True if we are within the first N seconds after startup (open ears)."""
    return (time.time() - _startup_time) < JARVIS_OPEN_EARS_SECONDS

# ─────────────────────────────────────────────────────────────────────────────
# SEND TO ULTRON SERVER — full streaming loop
# ─────────────────────────────────────────────────────────────────────────────
def send_to_ultron(audio_path: str) -> bool:
    global _is_processing, _tts_playing
    _is_processing = True
    log("Sending to Ultron brain...", "INFO")

    try:
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        resp = requests.post(
            f"{ULTRON_SERVER}/api/voice/stream_chat",
            files={"audio": ("voice.wav", audio_bytes, "audio/wav")},
            data={"session_id": "listener_session"},
            stream=True,
            timeout=90,
        )

        if not resp.ok:
            log(f"Server error: {resp.status_code}", "ERR")
            _is_processing = False
            return False

        full_text   = ""
        user_text   = ""
        audio_count = 0

        for line in resp.iter_lines():
            if not line:
                continue
            try:
                line_str = line.decode("utf-8") if isinstance(line, bytes) else line
                if not line_str.startswith("data: "):
                    continue
                evt = json.loads(line_str[6:].strip())
            except Exception:
                continue

            t = evt.get("type", "")

            if t == "transcript":
                user_text = evt.get("text", "")
                log(f"You said: \"{user_text}\"", "INFO")

            elif t == "sentence":
                sentence  = evt.get("text", "")
                audio_b64 = evt.get("audio_b64", "")
                full_text += sentence + " "
                if audio_b64:
                    import base64
                    audio_chunk = base64.b64decode(audio_b64)
                    if audio_count == 0:
                        log(f"Ultron: {sentence}", "SPEAK")
                    else:
                        log(f"        {sentence}", "SPEAK")
                    # Suppress wake-word listening while OUR audio is playing —
                    # otherwise the mic picks up the speaker output, Whisper
                    # transcribes it, and the bare-ok rule false-triggers on
                    # Ultron's own response (we saw this loop happen live).
                    _tts_playing = True
                    try:
                        play_audio_bytes(audio_chunk)
                    finally:
                        _tts_playing = False
                    audio_count += 1
                else:
                    log(f"Ultron: {sentence}", "SPEAK")

            elif t == "text_only":
                full_text += evt.get("text", "") + " "

            elif t == "command":
                cmd_text  = evt.get("text", "")
                audio_b64 = evt.get("audio_b64", "")
                log(f"Command executed: {cmd_text}", "OK")
                if audio_b64:
                    import base64
                    _tts_playing = True
                    try:
                        play_audio_bytes(base64.b64decode(audio_b64))
                    finally:
                        _tts_playing = False

            elif t == "done":
                if not full_text.strip():
                    full_text = evt.get("full_text", "")
                log(f"Response complete ({audio_count} audio chunks)", "OK")
                break

            elif t == "error":
                log(f"Server error: {evt.get('msg', '')}", "ERR")
                # Still try to speak the error so Jeevan knows
                err_msg = evt.get("msg", "Something went wrong. Please try again.")
                _tts_playing = True
                try:
                    play_edge_tts_sync(err_msg[:200])
                finally:
                    _tts_playing = False
                break

        _is_processing = False
        return True

    except Exception as e:
        log(f"Send error: {e}", "ERR")
        _is_processing = False
        return False

# ─────────────────────────────────────────────────────────────────────────────
# RECORD SPEECH UNTIL SILENCE
# ─────────────────────────────────────────────────────────────────────────────
def record_until_silence(pa, stream) -> list:
    """
    Record audio until silence is detected.
    Returns list of audio frame chunks.
    """
    frames          = []
    silent_chunks   = 0
    silence_limit   = int(SILENCE_TIMEOUT * SAMPLE_RATE / CHUNK)
    max_chunks      = int(RECORD_SECONDS_MAX * SAMPLE_RATE / CHUNK)
    min_chunks      = int(0.8 * SAMPLE_RATE / CHUNK)  # at least 0.8s (was 0.4s — a noise burst could pass)
    speech_detected = False

    log("Recording... (speak now)", "LISTEN")

    for _ in range(max_chunks):
        try:
            data_arr, _ = stream.read(CHUNK)
            data = data_arr.tobytes()
            frames.append(data)
            energy = rms(data)

            if energy > SILENCE_THRESHOLD:
                speech_detected = True
                silent_chunks   = 0
            else:
                if speech_detected:
                    silent_chunks += 1
                    if silent_chunks >= silence_limit:
                        break
        except Exception:
            break

    if len(frames) < min_chunks:
        return []
    return frames

# ─────────────────────────────────────────────────────────────────────────────
# PROCESS AND CLEANUP
# ─────────────────────────────────────────────────────────────────────────────
def _process_and_cleanup(audio_path: str):
    global _tts_playing
    try:
        success = send_to_ultron(audio_path)
        if not success:
            _tts_playing = True
            try:
                play_edge_tts_sync("Sorry, I couldn't process that. Make sure the server is running.")
            finally:
                _tts_playing = False
    finally:
        try:
            os.unlink(audio_path)
        except Exception:
            pass
        log("Ready — listening for wake word...", "LISTEN")

# ─────────────────────────────────────────────────────────────────────────────
# PICOVOICE LISTENER (most accurate)
# ─────────────────────────────────────────────────────────────────────────────
def run_picovoice_listener():
    global _tts_playing
    log("Starting Picovoice wake word engine...", "INFO")
    porcupine = None
    recorder  = None

    try:
        porcupine = pvporcupine.create(
            access_key=PICOVOICE_KEY,
            keywords=["ultron"],
            sensitivities=[0.6],
        )
        recorder = PvRecorder(frame_length=porcupine.frame_length, device_index=-1)

        sd_stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=CHANNELS,
            dtype='int16', blocksize=CHUNK,
        )
        sd_stream.start()

        recorder.start()
        log("Picovoice ready — say 'OK Ultron' anytime", "OK")
        log("=" * 52, "INFO")

        # Startup greeting
        play_startup_greeting()
        log("Ready — listening...", "LISTEN")

        while _running:
            try:
                if _tts_playing:
                    time.sleep(0.05)
                    continue
                # Check if we are in open-ears window (first query after startup)
                if _in_open_ears_window() and not _is_processing:
                    # Check for ANY speech (not just wake word) during first 6s
                    data_arr, _ = sd_stream.read(CHUNK)
                    data = data_arr.tobytes()
                    energy = rms(data)
                    if energy > SILENCE_THRESHOLD * 2.5:  # stricter: was 1.5x (AC/fan could trigger)
                        log("OPEN EARS — capturing first command", "WAKE")
                        frames = [data] + record_until_silence(None, sd_stream)
                        if len(frames) >= 5:
                            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                                tmp_path = tmp.name
                            save_wav(frames, tmp_path)
                            threading.Thread(
                                target=_process_and_cleanup, args=(tmp_path,), daemon=True
                            ).start()
                    continue

                pcm    = recorder.read()
                result = porcupine.process(pcm)

                if result >= 0:
                    if _is_processing:
                        log("Still processing — ignoring wake word", "WARN")
                        continue

                    log("WAKE WORD DETECTED!", "WAKE")
                    _tts_playing = True
                    play_edge_tts_sync("Yes?", STARTUP_VOICE)
                    _tts_playing = False
                    try:
                        for _ in range(int(0.5 * SAMPLE_RATE / CHUNK)):
                            sd_stream.read(CHUNK)
                    except Exception:
                        pass

                    frames = record_until_silence(None, sd_stream)
                    if len(frames) < 5:
                        log("Too short — ignoring", "WARN")
                        continue

                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                        tmp_path = tmp.name
                    save_wav(frames, tmp_path)

                    threading.Thread(
                        target=_process_and_cleanup, args=(tmp_path,), daemon=True
                    ).start()

            except Exception as e:
                if _running:
                    log(f"Listener loop error: {e}", "ERR")
                    time.sleep(0.5)

    except Exception as e:
        log(f"Picovoice init error: {e}", "ERR")
        log("Falling back to VAD-based detection...", "WARN")
        run_vad_listener()
    finally:
        for obj in (recorder, porcupine):
            if obj:
                try:
                    obj.stop() if hasattr(obj, "stop") else None
                    obj.delete()
                except Exception:
                    pass

# ─────────────────────────────────────────────────────────────────────────────
# VAD LISTENER (fallback — no Picovoice key needed)
# ─────────────────────────────────────────────────────────────────────────────
def run_vad_listener():
    if not SOUNDDEVICE_AVAILABLE:
        log("sounddevice not installed. pip install sounddevice", "ERR")
        return
    if not FASTER_WHISPER_AVAILABLE:
        log("faster-whisper not installed. pip install faster-whisper", "ERR")
        return

    _load_whisper()

    log("Starting always-on listener — say 'ok' or 'ok ultron' to activate", "INFO")
    log("Wake words: ok <command> / ok ultron / hey ultron / yo ultron / ultron", "OK")

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE, channels=CHANNELS,
        dtype='int16', blocksize=CHUNK,
    )
    stream.start()

    # ── Mic calibration — auto-set threshold from ambient noise ──────────────
    log("Mic calibration: stay quiet for 2 seconds...", "INFO")
    cal_energies = []
    for _ in range(int(2 * SAMPLE_RATE / CHUNK)):
        d, _ = stream.read(CHUNK)
        cal_energies.append(rms(d.tobytes()))
    # Use the QUIETEST 33% of samples as the ambient floor. Plain average
    # gets ruined if speech, a cough, the startup greeting, or a fan-spin-up
    # interrupts the 2-second calibration window — the quietest third is a
    # much more honest estimate of true room ambient.
    sorted_cal = sorted(cal_energies)
    quiet_count = max(1, len(sorted_cal) // 3)
    ambient = sum(sorted_cal[:quiet_count]) / quiet_count
    global SILENCE_THRESHOLD, _tts_playing
    # Threshold formula: 3x ambient, clamped to [300, 8000].
    # - 3x ambient catches normal indoor speech while filtering fan/AC drone.
    # - Floor 300 prevents zero-threshold edge cases.
    # - Ceiling 8000 prevents bogus-calibration runaway (if the 2-second
    #   calibration window happened to overlap with speech, TV, or the
    #   startup greeting, ambient inflates and threshold becomes
    #   unreachable — even shouting won't trigger). Normal indoor speech
    #   measures 8000-25000 on most mics, so 8000 is a safe upper bound.
    SILENCE_THRESHOLD = max(300, min(int(ambient * 3), 8000))
    log(f"Ambient noise: {ambient:.0f}  ->  threshold set to {SILENCE_THRESHOLD:.0f}", "OK")

    # Startup greeting
    play_startup_greeting()
    log("Ready — say 'OK Ultron' now...", "LISTEN")
    log("=" * 52, "INFO")

    wake_buffer        = []
    wake_buffer_max    = int(SAMPLE_RATE / CHUNK * 2.0)   # 2 seconds of rolling context (was 1.5)
    above_thresh_count = 0
    # Snap-detector state
    snap_prev_energy   = 0.0
    snap_first_time    = None       # timestamp of unmatched first snap, or None
    if SNAP_WAKE_ENABLED:
        log("Snap wake ENABLED — double-snap your fingers to wake (Tony Stark mode)", "OK")
    ENERGY_TRIGGER     = 8    # ~0.5s of sustained speech needed.
                              # Was 15 (~1s) which natural inter-word pauses
                              # break — short commands like "OK Ultron pause"
                              # never accumulated 15 consecutive above-threshold
                              # chunks. False-positives (cough, single loud noise)
                              # are still filtered downstream by the 2-word
                              # minimum + wake-word match.
    _debug_counter     = 0

    while _running:
        try:
            if _tts_playing:
                time.sleep(0.05)
                continue
            data_arr, _ = stream.read(CHUNK)
            data = data_arr.tobytes()
            energy = rms(data)
            wake_buffer.append(data)
            if len(wake_buffer) > wake_buffer_max:
                wake_buffer.pop(0)

            # ── Finger-snap wake detection ─────────────────────────────────
            # Runs first so a snap can fire even while speech-energy is also
            # being accumulated. Sharp rise + high absolute peak = snap.
            if SNAP_WAKE_ENABLED and not _is_processing:
                rise_ratio = energy / max(snap_prev_energy, 1.0)
                is_snap = (rise_ratio >= SNAP_RISE_RATIO and
                           energy >= SNAP_ABS_FLOOR)
                # Log near-misses so we can see how close real snaps are to
                # the thresholds — invaluable for tuning per-mic.
                if SNAP_DEBUG and energy >= SNAP_ABS_FLOOR * 0.6 and rise_ratio >= 1.5:
                    log(f"[snap?] energy={energy:.0f} rise={rise_ratio:.1f}x "
                        f"(need ≥{SNAP_ABS_FLOOR} and ≥{SNAP_RISE_RATIO}x) "
                        f"{'FIRE' if is_snap else 'miss'}", "INFO")
                snap_prev_energy = energy
                if is_snap:
                    now_s = time.time()
                    if snap_first_time is None:
                        snap_first_time = now_s
                    else:
                        gap = now_s - snap_first_time
                        if gap < SNAP_DOUBLE_MIN_S:
                            # Echo / glitch — keep waiting for a real second snap
                            pass
                        elif gap <= SNAP_DOUBLE_WINDOW_S:
                            # DOUBLE SNAP — fire wake (Tony Stark mode)
                            log(f"DOUBLE SNAP DETECTED (gap {gap*1000:.0f}ms) — waking", "WAKE")
                            snap_first_time    = None
                            above_thresh_count = 0
                            _tts_playing = True
                            try:
                                play_edge_tts_sync("Yes?", STARTUP_VOICE)
                            finally:
                                _tts_playing = False
                            # Flush 0.5s of mic after TTS — avoid hearing own tail
                            try:
                                for _ in range(int(0.5 * SAMPLE_RATE / CHUNK)):
                                    stream.read(CHUNK)
                            except Exception:
                                pass
                            wake_buffer = []
                            frames = record_until_silence(None, stream)
                            if len(frames) >= 3:
                                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_f:
                                    cmd_path = tmp_f.name
                                save_wav(frames, cmd_path)
                                threading.Thread(
                                    target=_process_and_cleanup, args=(cmd_path,), daemon=True
                                ).start()
                            else:
                                log("Too short — ignoring", "WARN")
                            continue
                        else:
                            # First snap is stale — treat this one as the new first
                            snap_first_time = now_s
                elif snap_first_time is not None:
                    # No snap this chunk — expire stale first-snap waiting
                    if (time.time() - snap_first_time) > SNAP_DOUBLE_WINDOW_S:
                        snap_first_time = None

            # Print energy every ~5 seconds so user can see mic is alive
            _debug_counter += 1
            if _debug_counter >= int(5 * SAMPLE_RATE / CHUNK):
                _debug_counter = 0
                log(f"[mic] energy={energy:.0f}  threshold={SILENCE_THRESHOLD:.0f}  {'SPEECH' if energy > SILENCE_THRESHOLD else 'quiet'}", "INFO")

            if energy > SILENCE_THRESHOLD:
                above_thresh_count += 1
            else:
                above_thresh_count = max(0, above_thresh_count - 1)

            # Trigger on speech energy
            if above_thresh_count >= ENERGY_TRIGGER and not _is_processing:
                above_thresh_count = 0

                # ── Open ears window: no wake word needed ─────────────────────
                if _in_open_ears_window() and energy > SILENCE_THRESHOLD * 2.5:
                    log("OPEN EARS — capturing first command", "WAKE")
                    frames = list(wake_buffer) + record_until_silence(None, stream)
                    wake_buffer = []
                    if len(frames) >= 5:
                        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                            tmp_path = tmp.name
                        save_wav(frames, tmp_path)
                        threading.Thread(
                            target=_process_and_cleanup, args=(tmp_path,), daemon=True
                        ).start()
                    continue

                # ── Normal mode: check for wake word ─────────────────────────
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    wake_path = tmp.name
                save_wav(list(wake_buffer), wake_path)

                spoken = transcribe_locally(wake_path)
                try:
                    os.unlink(wake_path)
                except Exception:
                    pass

                if spoken:
                    log(f"[heard] \"{spoken}\"", "INFO")
                # Reject transcriptions shorter than 2 words — single words are almost always noise artefacts
                if len(spoken.split()) < 2:
                    wake_buffer = []
                    continue
                has_wake = matches_wake(spoken)

                if has_wake:
                    log(f"WAKE WORD DETECTED: \"{spoken}\"", "WAKE")
                    _tts_playing = True
                    play_edge_tts_sync("Yes?", STARTUP_VOICE)
                    _tts_playing = False
                    try:
                        for _ in range(int(0.5 * SAMPLE_RATE / CHUNK)):
                            stream.read(CHUNK)
                    except Exception:
                        pass

                    wake_buffer = []
                    frames = record_until_silence(None, stream)

                    if len(frames) < 3:
                        log("Too short — ignoring", "WARN")
                        continue

                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                        cmd_path = tmp.name
                    save_wav(frames, cmd_path)

                    # Voice identity check
                    if VOICE_ID_AVAILABLE and VOICE_ID_ENABLED and is_enrolled():
                        id_result = verify_speaker(cmd_path, threshold=VOICE_ID_THRESHOLD)
                        if not id_result["is_owner"]:
                            log(f"STRANGER detected — ignoring", "WARN")
                            if STRANGER_RESPONSE:
                                play_edge_tts_sync(
                                    "I don't recognize your voice. I only respond to Jeevan."
                                )
                            try:
                                os.unlink(cmd_path)
                            except Exception:
                                pass
                            continue
                        log(f"Speaker verified: {id_result.get('owner','Jeevan')}", "OK")

                    threading.Thread(
                        target=_process_and_cleanup, args=(cmd_path,), daemon=True
                    ).start()

        except KeyboardInterrupt:
            break
        except Exception as e:
            if _running:
                log(f"VAD error: {e}", "WARN")
                time.sleep(0.2)

    stream.stop()
    stream.close()

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    global _running, _startup_time

    print()
    print("=" * 52)
    print("  ULTRON-J -- Always-On Voice Listener v4")
    print("  Say 'OK Ultron' anytime -- no button needed")
    print("=" * 52)
    print()

    if not check_server():
        print("\n[ERROR] Ultron server not responding.")
        print("Start it first: py -3.14 app.py\n")
        sys.exit(1)

    if not SOUNDDEVICE_AVAILABLE:
        log("sounddevice not installed!", "ERR")
        log("Run: pip install sounddevice", "ERR")
        sys.exit(1)

    log(f"faster-whisper : {'+' if FASTER_WHISPER_AVAILABLE else '! (pip install faster-whisper)'}", "INFO")
    log(f"Picovoice      : {'+' if (PICOVOICE_AVAILABLE and PICOVOICE_KEY) else '! (optional, skip for now)'}", "INFO")
    log(f"Edge TTS       : {'+' if EDGE_TTS_AVAILABLE else '! (pip install edge-tts)'}", "INFO")
    log(f"Playsound      : {'+' if PLAYSOUND_AVAILABLE else '! (optional)'}", "INFO")
    log(f"Server         : {ULTRON_SERVER}", "INFO")
    print()

    _startup_time = time.time()

    try:
        if PICOVOICE_AVAILABLE and PICOVOICE_KEY:
            log("Using Picovoice wake word engine (most accurate)", "OK")
            run_picovoice_listener()
        elif FASTER_WHISPER_AVAILABLE:
            log("Always-on mode: sounddevice mic + faster-whisper wake word detection", "OK")
            log("Say 'OK Ultron' at any time to give a command", "OK")
            run_vad_listener()
        else:
            log("No STT engine available!", "ERR")
            log("Install: pip install faster-whisper", "ERR")
            sys.exit(1)
    except KeyboardInterrupt:
        _running = False
        print()
        log("Listener stopped by user", "INFO")


if __name__ == "__main__":
    main()
