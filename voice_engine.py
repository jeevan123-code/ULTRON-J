"""
voice_engine.py — BEYOND JARVIS Voice Engine for Ultron-J
Personal AI for Jeevan — Hyderabad, Telangana, India.

CAPABILITIES:
- Multi-tier TTS: ElevenLabs → OpenAI → Edge TTS (FREE, always works)
- Multi-tier STT: OpenAI Whisper API → Local Whisper (faster-whisper)
- STREAMING TTS PIPELINE: LLM → sentence chunking → TTS → play
  First audio starts in ~2s instead of 10-15s
- Mood-aware voice profiles (each emotional state = different voice)
- Markdown stripping (clean speech, no "asterisk bold asterisk")
- Voice command fast-path (time, weather, status — zero LLM latency)
- Audio caching (repeated phrases play instantly)
- Voice log (every interaction stored)
- Morning/evening spoken briefings
"""

import asyncio
import base64
import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Generator, Iterator, List, Optional, Tuple

import requests

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from config import (
        VOICE_CACHE_DIR, VOICE_LOG_FILE,
        ELEVENLABS_API_KEY, OPENAI_API_KEY,
        ELEVENLABS_VOICES, OPENAI_TTS_VOICES, EDGE_TTS_VOICES,
        VOICE_SPEAKING_RATES, VOICE_MAX_TTS_CHARS,
        VOICE_CACHE_MAX_FILES, VOICE_RESPONSE_MAX_WORDS,
        JEEVAN_NAME, AGENT_NAME,
    )
except ImportError:
    VOICE_CACHE_DIR           = os.path.join(_BASE_DIR, "voice_cache")
    VOICE_LOG_FILE            = os.path.join(_BASE_DIR, "voice_log.json")
    ELEVENLABS_API_KEY        = os.environ.get("ELEVENLABS_API_KEY", "").strip() or None
    OPENAI_API_KEY            = os.environ.get("OPENAI_API_KEY", "").strip() or None
    ELEVENLABS_VOICES         = {
        "FOCUSED":    {"voice_id": "onwK4N9gsSGsGA4xWAcb", "name": "Daniel"},
        "CURIOUS":    {"voice_id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel"},
        "ALERT":      {"voice_id": "ODq5zmih8GrVes37Dizd", "name": "Patrick"},
        "CONCERNED":  {"voice_id": "Xb0lHlNL5OcN7IvsDmeB", "name": "Alice"},
        "DETERMINED": {"voice_id": "iP3nJ0z0nHcGdpLBXOS9", "name": "Chris"},
        "ANALYTICAL": {"voice_id": "yoZ06aMxZJJ28mfd3POQ", "name": "Sam"},
        "IDLE":       {"voice_id": "onwK4N9gsSGsGA4xWAcb", "name": "Daniel"},
    }
    OPENAI_TTS_VOICES         = {
        "FOCUSED": "echo", "CURIOUS": "nova", "ALERT": "echo",
        "CONCERNED": "alloy", "DETERMINED": "onyx",
        "ANALYTICAL": "shimmer", "IDLE": "fable",
    }
    EDGE_TTS_VOICES           = {
        "FOCUSED":    "en-US-GuyNeural",
        "CURIOUS":    "en-US-AnaNeural",
        "ALERT":      "en-US-ChristopherNeural",
        "CONCERNED":  "en-US-AriaNeural",
        "DETERMINED": "en-US-ChristopherNeural",
        "ANALYTICAL": "en-US-GuyNeural",
        "IDLE":       "en-US-GuyNeural",
    }
    VOICE_SPEAKING_RATES      = {
        "FOCUSED": 1.1, "CURIOUS": 1.0, "ALERT": 1.25,
        "CONCERNED": 0.95, "DETERMINED": 1.1, "ANALYTICAL": 0.9, "IDLE": 1.0,
    }
    VOICE_MAX_TTS_CHARS        = 500
    VOICE_CACHE_MAX_FILES      = 200
    VOICE_RESPONSE_MAX_WORDS   = 80
    JEEVAN_NAME                = "Jeevan"
    AGENT_NAME                 = "Ultron-J"

# ─────────────────────────────────────────────────────────────────────────────
# OPTIONAL IMPORTS
# ─────────────────────────────────────────────────────────────────────────────
try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False

try:
    from faster_whisper import WhisperModel as _FasterWhisperModel
    FASTER_WHISPER_AVAILABLE = True
    _fw_model = None   # lazy-loaded
except ImportError:
    FASTER_WHISPER_AVAILABLE = False
    _fw_model = None

try:
    import whisper as _whisper
    LOCAL_WHISPER_AVAILABLE = True
    _local_whisper_model = None  # lazy-loaded
except ImportError:
    LOCAL_WHISPER_AVAILABLE = False
    _local_whisper_model = None

try:
    from kokoro_onnx import Kokoro as _KokoroTTS
    import soundfile as _soundfile
    KOKORO_AVAILABLE = True
    _kokoro_model = None  # lazy-loaded
    _KOKORO_ONNX_PATH   = os.path.join(_BASE_DIR, "kokoro-v1.0.onnx")
    _KOKORO_VOICES_PATH = os.path.join(_BASE_DIR, "voices-v1.0.bin")
except ImportError:
    KOKORO_AVAILABLE = False
    _kokoro_model = None
    _KOKORO_ONNX_PATH = ""
    _KOKORO_VOICES_PATH = ""

# ─────────────────────────────────────────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────────────────────────────────────────
os.makedirs(VOICE_CACHE_DIR, exist_ok=True)
_log_lock   = threading.Lock()
_cache_lock = threading.Lock()

# Sentence boundary regex — splits on . ! ? followed by whitespace or end
# Avoids splitting on common abbreviations
_SENT_END_RE = re.compile(
    r'(?<=[.!?])'
    r'(?=\s+[A-Z]|\s*$)'
)

# =============================================================================
# TEXT PREPROCESSING
# =============================================================================

def strip_for_voice(text: str) -> str:
    """Remove markdown formatting so TTS speaks clean natural English."""
    if not text:
        return ""
    text = re.sub(r"```[\s\S]*?```", " [code block] ", text)
    text = re.sub(r"`[^`]+`", lambda m: m.group(0)[1:-1], text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,3}([^*\n]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,2}([^_\n]+)_{1,2}", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\|.*\|", "", text)
    text = re.sub(r"^[-=*]{3,}$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def split_sentences(text: str) -> List[str]:
    """
    Split text into speakable sentences for streaming TTS.
    Returns list of clean sentence strings.
    """
    text = strip_for_voice(text)
    if not text:
        return []

    parts = _SENT_END_RE.split(text)
    sentences = []
    for p in parts:
        p = p.strip()
        if p and len(p) > 2:
            sentences.append(p)
    return sentences if sentences else [text]


def prepare_for_tts(text: str) -> str:
    """Strip markdown, limit length."""
    clean = strip_for_voice(text)
    words = clean.split()
    if len(words) > VOICE_RESPONSE_MAX_WORDS:
        trunc = " ".join(words[:VOICE_RESPONSE_MAX_WORDS])
        stop  = max(trunc.rfind("."), trunc.rfind("!"), trunc.rfind("?"))
        clean = trunc[:stop + 1] if stop > len(trunc) * 0.6 else trunc + "..."
    return clean


# =============================================================================
# AUDIO CACHE
# =============================================================================

def _cache_key(text: str, mood: str, provider: str) -> str:
    return hashlib.md5(f"{text}|{mood}|{provider}".encode()).hexdigest()


def _get_cached(text: str, mood: str, provider: str) -> Optional[bytes]:
    key  = _cache_key(text, mood, provider)
    path = Path(VOICE_CACHE_DIR) / f"tts_{key}.mp3"
    with _cache_lock:
        return path.read_bytes() if path.exists() else None


def _set_cached(text: str, mood: str, provider: str, audio: bytes):
    key  = _cache_key(text, mood, provider)
    path = Path(VOICE_CACHE_DIR) / f"tts_{key}.mp3"
    with _cache_lock:
        path.write_bytes(audio)
    files = sorted(Path(VOICE_CACHE_DIR).glob("tts_*.mp3"), key=os.path.getmtime)
    while len(files) > VOICE_CACHE_MAX_FILES:
        try:
            files.pop(0).unlink()
        except Exception:
            break


# =============================================================================
# TTS PROVIDERS
# =============================================================================

def _tts_elevenlabs(text: str, mood: str) -> bytes:
    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY not set")
    vc = ELEVENLABS_VOICES.get(mood, ELEVENLABS_VOICES["FOCUSED"])
    resp = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{vc['voice_id']}",
        headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"},
        json={
            "text": text[:VOICE_MAX_TTS_CHARS],
            "model_id": "eleven_monolingual_v1",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.3, "use_speaker_boost": True},
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.content


def _tts_openai(text: str, mood: str) -> bytes:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set")
    voice = OPENAI_TTS_VOICES.get(mood, "echo")
    rate  = VOICE_SPEAKING_RATES.get(mood, 1.0)
    resp = requests.post(
        "https://api.openai.com/v1/audio/speech",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        json={"model": "tts-1", "voice": voice, "input": text[:VOICE_MAX_TTS_CHARS], "speed": round(rate, 1)},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.content


async def _edge_tts_async(text: str, voice: str, rate_str: str, path: str):
    communicate = edge_tts.Communicate(text, voice, rate=rate_str)
    await communicate.save(path)


def _tts_edge(text: str, mood: str) -> bytes:
    if not EDGE_TTS_AVAILABLE:
        raise RuntimeError("edge-tts not installed. pip install edge-tts")
    voice    = EDGE_TTS_VOICES.get(mood, "en-US-GuyNeural")
    rate_val = VOICE_SPEAKING_RATES.get(mood, 1.0)
    pct      = int((rate_val - 1.0) * 100)
    rate_str = f"+{pct}%" if pct >= 0 else f"{pct}%"
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_edge_tts_async(text[:VOICE_MAX_TTS_CHARS], voice, rate_str, tmp_path))
        loop.close()
        return Path(tmp_path).read_bytes()
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def _get_kokoro():
    global _kokoro_model
    if _kokoro_model is None:
        if not os.path.exists(_KOKORO_ONNX_PATH) or not os.path.exists(_KOKORO_VOICES_PATH):
            raise RuntimeError(
                f"Kokoro model files not found. Download to project root:\n"
                f"  kokoro-v1.0.onnx  → {_KOKORO_ONNX_PATH}\n"
                f"  voices-v1.0.bin   → {_KOKORO_VOICES_PATH}"
            )
        print("[VoiceEngine] Loading Kokoro model (one-time ~5s)...")
        _kokoro_model = _KokoroTTS(_KOKORO_ONNX_PATH, _KOKORO_VOICES_PATH)
    return _kokoro_model


def warmup_tts():
    """Pre-load the Kokoro ONNX model on a background thread so the very first
    /api/voice/speak request doesn't pay the ~5s cold-load cost. Pure
    pre-warming — does not change synthesis behavior or voice output in any
    way. Safe to call once at server startup; subsequent calls are no-ops
    because _get_kokoro() is idempotent.
    """
    if not KOKORO_AVAILABLE:
        return
    if not (os.path.exists(_KOKORO_ONNX_PATH) and os.path.exists(_KOKORO_VOICES_PATH)):
        return

    def _bg():
        try:
            _get_kokoro()
            print("[VoiceEngine] Kokoro pre-warmed (first TTS call will be instant).")
        except Exception as _e:
            print(f"[VoiceEngine] Kokoro pre-warm skipped: {_e}")

    threading.Thread(target=_bg, daemon=True, name="kokoro-warmup").start()


def warmup_stt():
    """Pre-load the faster-whisper model so the first /api/voice/transcribe
    slow-path doesn't pay the ~10s cold-load cost. Pure pre-warming — does
    not change transcription behavior. Safe to call once at startup;
    subsequent loads are no-ops because `_fw_model` is module-level singleton.
    """
    if not FASTER_WHISPER_AVAILABLE:
        return

    def _bg():
        global _fw_model
        try:
            if _fw_model is None:
                _fw_model = _FasterWhisperModel("small", device="cpu", compute_type="int8")
                print("[VoiceEngine] faster-whisper pre-warmed (first STT slow-path will be ~10s faster).")
        except Exception as _e:
            print(f"[VoiceEngine] faster-whisper pre-warm skipped: {_e}")

    threading.Thread(target=_bg, daemon=True, name="whisper-warmup").start()


def _tts_kokoro(text: str, mood: str) -> bytes:
    """Kokoro ONNX local TTS — no API key, fully offline."""
    if not KOKORO_AVAILABLE:
        raise RuntimeError("kokoro-onnx not installed. pip install kokoro-onnx soundfile")
    kokoro = _get_kokoro()
    # mood → voice mapping; af_bella is a clear neutral English voice
    voice_map = {
        "FOCUSED":    "af_bella",
        "CURIOUS":    "af_sky",
        "ALERT":      "am_michael",
        "CONCERNED":  "af_nicole",
        "DETERMINED": "am_michael",
        "ANALYTICAL": "af_bella",
        "IDLE":       "af_bella",
    }
    voice = voice_map.get(mood, "af_bella")
    rate  = VOICE_SPEAKING_RATES.get(mood, 1.0)
    samples, sample_rate = kokoro.create(
        text[:VOICE_MAX_TTS_CHARS], voice=voice, speed=rate, lang="en-us"
    )
    cache_key = hashlib.md5(f"{text}|{mood}|kokoro".encode()).hexdigest()[:8]
    out_path  = os.path.join(VOICE_CACHE_DIR, f"kokoro_{cache_key}.wav")
    _soundfile.write(out_path, samples, sample_rate)
    return Path(out_path).read_bytes()


# =============================================================================
# TTS — UNIFIED
# =============================================================================

def tts(text: str, mood: str = "FOCUSED", provider: str = "auto") -> Tuple[bytes, str]:
    """
    Convert text to MP3 bytes.
    Auto-selects best available provider:
      ElevenLabs (if key) → OpenAI (if key) → Edge TTS (free, no key)
    Returns: (audio_bytes, provider_name)
    """
    clean = prepare_for_tts(text) or "Done."

    cached = _get_cached(clean, mood, provider)
    if cached:
        return cached, f"{provider}:cached"

    if provider == "auto":
        chain = []
        if ELEVENLABS_API_KEY:
            chain.append("elevenlabs")
        if OPENAI_API_KEY:
            chain.append("openai")
        if KOKORO_AVAILABLE:
            chain.append("kokoro")
        chain.append("edge")
    else:
        chain = [provider, "edge"]

    last_err = None
    for prov in chain:
        try:
            if prov == "elevenlabs":
                audio = _tts_elevenlabs(clean, mood)
            elif prov == "openai":
                audio = _tts_openai(clean, mood)
            elif prov == "kokoro":
                audio = _tts_kokoro(clean, mood)
            elif prov == "edge":
                audio = _tts_edge(clean, mood)
            else:
                continue
            _set_cached(clean, mood, prov, audio)
            _log_voice("tts", {"mood": mood, "provider": prov, "chars": len(clean)})
            return audio, prov
        except Exception as e:
            last_err = str(e)
            print(f"[VoiceEngine] {prov} TTS failed: {e}")

    raise RuntimeError(f"All TTS providers failed. Last: {last_err}")


# =============================================================================
# STREAMING TTS PIPELINE
# The KEY upgrade: LLM tokens → sentences → TTS → audio chunks
# First audio plays in ~2s instead of 10-15s
# =============================================================================

def stream_tts_from_llm(
    llm_generator,    # generator that yields "data: {...}" SSE strings
    mood: str = "FOCUSED",
) -> Generator[Dict, None, None]:
    """
    Consume an LLM SSE stream, split into sentences, TTS each sentence,
    yield audio chunks as they're ready.

    Yields dicts:
      {"type": "transcript_start"}                       — LLM started
      {"type": "sentence", "text": "...", "audio_b64": "...", "index": N}  — audio chunk
      {"type": "text_token", "token": "..."}             — raw token (for text display)
      {"type": "done", "full_text": "..."}               — all done
      {"type": "error", "msg": "..."}                    — error
    """
    sentence_buf = ""
    full_text    = ""
    chunk_index  = 0

    yield {"type": "transcript_start"}

    try:
        for sse_line in llm_generator:
            if not isinstance(sse_line, str) or not sse_line.startswith("data: "):
                continue

            data_str = sse_line[6:].strip()
            if not data_str or data_str == "[DONE]":
                continue

            try:
                d = json.loads(data_str)
            except Exception:
                continue

            # Final full response signal
            if d.get("_full"):
                full_text = d["_full"]
                break

            token = d.get("token", "")
            if not token:
                continue

            full_text    += token
            sentence_buf += token

            # Yield token for real-time text display
            yield {"type": "text_token", "token": token}

            # Check for sentence boundary
            if _SENT_END_RE.search(sentence_buf):
                parts = _SENT_END_RE.split(sentence_buf)
                complete_parts = parts[:-1]
                sentence_buf   = parts[-1]   # keep incomplete tail

                for sentence in complete_parts:
                    sentence = sentence.strip()
                    if len(sentence) < 4:
                        continue
                    try:
                        audio_bytes, prov = tts(sentence, mood=mood)
                        yield {
                            "type":      "sentence",
                            "text":      sentence,
                            "audio_b64": base64.b64encode(audio_bytes).decode(),
                            "index":     chunk_index,
                            "provider":  prov,
                        }
                        chunk_index += 1
                    except Exception as e:
                        # TTS failed for this sentence — yield text only
                        yield {"type": "text_only", "text": sentence, "index": chunk_index}
                        chunk_index += 1

        # Handle leftover buffer
        remainder = sentence_buf.strip()
        if remainder and len(remainder) > 3:
            try:
                audio_bytes, prov = tts(remainder, mood=mood)
                yield {
                    "type":      "sentence",
                    "text":      remainder,
                    "audio_b64": base64.b64encode(audio_bytes).decode(),
                    "index":     chunk_index,
                    "provider":  prov,
                }
            except Exception:
                yield {"type": "text_only", "text": remainder, "index": chunk_index}

    except Exception as e:
        yield {"type": "error", "msg": str(e)}

    yield {"type": "done", "full_text": full_text, "total_chunks": chunk_index}


# =============================================================================
# STT PROVIDERS
# =============================================================================

def _stt_groq(audio_bytes: bytes) -> Dict:
    """Groq Whisper — GPU-accelerated, ~200ms, uses existing GROQ_API_KEY."""
    try:
        from config import GROQ_API_KEY as _gkey
    except ImportError:
        _gkey = os.environ.get("GROQ_API_KEY", "")
    if not _gkey:
        raise RuntimeError("GROQ_API_KEY not set")
    resp = requests.post(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {_gkey}"},
        files={"file": ("audio.webm", audio_bytes, "audio/webm")},
        data={"model": "whisper-large-v3-turbo", "response_format": "json", "language": "en"},
        timeout=15,
    )
    resp.raise_for_status()
    result = resp.json()
    return {
        "text":       result.get("text", "").strip(),
        "language":   "en",
        "confidence": 0.95,
        "provider":   "groq_whisper",
    }


def _stt_openai(audio_bytes: bytes) -> Dict:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set")
    resp = requests.post(
        "https://api.openai.com/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        files={"file": ("audio.webm", audio_bytes, "audio/webm")},
        data={"model": "whisper-1", "response_format": "verbose_json"},
        timeout=60,
    )
    resp.raise_for_status()
    result = resp.json()
    return {
        "text":       result.get("text", "").strip(),
        "language":   result.get("language", "en"),
        "confidence": 0.93,
        "provider":   "openai_whisper",
    }


def _stt_faster_whisper(audio_path: str) -> Dict:
    """faster-whisper: significantly faster than openai-whisper, same quality."""
    global _fw_model
    if not FASTER_WHISPER_AVAILABLE:
        raise RuntimeError("faster-whisper not installed. pip install faster-whisper")
    if _fw_model is None:
        print("[VoiceEngine] Loading faster-whisper 'small' model (one-time ~10s)...")
        _fw_model = _FasterWhisperModel("small", device="cpu", compute_type="int8")
    segments, info = _fw_model.transcribe(audio_path, language="en", beam_size=1, vad_filter=True)
    text = " ".join(s.text for s in segments).strip()
    return {
        "text":       text,
        "language":   info.language,
        "confidence": round(float(info.language_probability), 2),
        "provider":   "faster_whisper",
    }


def _stt_local_whisper(audio_path: str) -> Dict:
    global _local_whisper_model
    if not LOCAL_WHISPER_AVAILABLE:
        raise RuntimeError("openai-whisper not installed. pip install openai-whisper")
    if _local_whisper_model is None:
        print("[VoiceEngine] Loading Whisper 'base' model (one-time ~30s)...")
        _local_whisper_model = _whisper.load_model("base")
    result = _local_whisper_model.transcribe(audio_path, language="en")
    return {
        "text":       result.get("text", "").strip(),
        "language":   "en",
        "confidence": 0.88,
        "provider":   "local_whisper",
    }


# =============================================================================
# STT — UNIFIED
# =============================================================================

def stt(audio_input, provider: str = "auto") -> Dict:
    """
    Convert audio to text.
    audio_input: bytes or file path string
    Returns: {text, confidence, language, provider}
    """
    audio_bytes = None
    audio_path  = None

    if isinstance(audio_input, (bytes, bytearray)):
        audio_bytes = audio_input
    elif isinstance(audio_input, str) and os.path.exists(audio_input):
        audio_path  = audio_input
        audio_bytes = Path(audio_path).read_bytes()
    else:
        return {"text": "", "confidence": 0, "error": "Invalid audio input", "provider": "none"}

    if provider == "auto":
        chain = []
        # Groq Whisper first — GPU-backed, ~200ms, free tier, no extra install
        try:
            from config import GROQ_API_KEY as _gk
        except ImportError:
            _gk = os.environ.get("GROQ_API_KEY", "")
        if _gk:
            chain.append("groq")
        if OPENAI_API_KEY:
            chain.append("openai")
        if FASTER_WHISPER_AVAILABLE:
            chain.append("faster_whisper")
        elif LOCAL_WHISPER_AVAILABLE:
            chain.append("local_whisper")
    else:
        chain = [provider]

    if not chain:
        return {
            "text": "", "confidence": 0,
            "error": "No STT available. Set GROQ_API_KEY, OPENAI_API_KEY, or run: pip install faster-whisper",
            "provider": "none",
        }

    last_err = None
    for prov in chain:
        try:
            if prov == "groq":
                result = _stt_groq(audio_bytes)
            elif prov == "openai":
                result = _stt_openai(audio_bytes)
            elif prov in ("faster_whisper", "local_whisper"):
                if audio_path is None:
                    # Detect format from magic bytes; default to webm
                    if audio_bytes[:4] == b'OggS':
                        raw_suffix = ".ogg"
                    elif audio_bytes[:4] == b'fLaC':
                        raw_suffix = ".flac"
                    elif audio_bytes[:3] == b'ID3' or audio_bytes[:2] == b'\xff\xfb':
                        raw_suffix = ".mp3"
                    else:
                        raw_suffix = ".webm"
                    with tempfile.NamedTemporaryFile(suffix=raw_suffix, delete=False) as tmp:
                        tmp.write(audio_bytes)
                        raw_path = tmp.name
                    wav_path = raw_path.rsplit(".", 1)[0] + ".wav"
                    try:
                        from pydub import AudioSegment
                        AudioSegment.from_file(raw_path).export(wav_path, format="wav")
                        audio_path = wav_path
                    except Exception:
                        audio_path = raw_path
                if prov == "faster_whisper":
                    result = _stt_faster_whisper(audio_path)
                else:
                    result = _stt_local_whisper(audio_path)
            else:
                continue
            _log_voice("stt", {"preview": result.get("text", "")[:50], "provider": prov})
            return result
        except Exception as e:
            last_err = str(e)
            print(f"[VoiceEngine] {prov} STT failed: {e}")

    return {"text": "", "confidence": 0, "error": f"All STT failed: {last_err}", "provider": "none"}


# =============================================================================
# SPEAKER IDENTITY GATE
# =============================================================================

def verify_caller_identity(audio_bytes: bytes, format_hint: str = "webm") -> Dict:
    """
    Speaker verification gate for voice endpoints. Default is LOG-ONLY:
    the check runs and the result is recorded, but nothing is blocked
    until ULTRON_VOICE_IDENTITY_ENFORCE=1 is set in the environment.
    Fail-open on any error so a library / ffmpeg / model hiccup never
    locks the enrolled owner out of their own assistant.

    Returns: {enrolled, enforced, allow, is_owner, similarity, threshold,
              confidence, error?}
    """
    enforce = os.environ.get("ULTRON_VOICE_IDENTITY_ENFORCE", "0") == "1"
    try:
        from voice_identity import verify_speaker, is_enrolled
    except Exception as e:
        return {"enrolled": False, "enforced": enforce, "allow": True,
                "is_owner": True, "similarity": 1.0,
                "error": f"identity module: {e}"}

    if not is_enrolled():
        return {"enrolled": False, "enforced": enforce, "allow": True,
                "is_owner": True, "similarity": 1.0}

    src_path = None
    wav_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=f".{format_hint}", delete=False) as tmp:
            tmp.write(audio_bytes)
            src_path = tmp.name

        verify_path = src_path
        try:
            from pydub import AudioSegment
            wav_path = src_path.rsplit(".", 1)[0] + ".id.wav"
            AudioSegment.from_file(src_path).export(wav_path, format="wav")
            verify_path = wav_path
        except Exception:
            pass  # fall back to source container

        result = verify_speaker(verify_path)
        allow = bool(result.get("is_owner", True)) or not enforce
        _log_voice("identity", {
            "enforced":   enforce,
            "is_owner":   result.get("is_owner"),
            "similarity": round(result.get("similarity", 0.0), 3),
            "threshold":  result.get("threshold"),
            "confidence": result.get("confidence"),
            "allowed":    allow,
        })
        return {"enrolled": True, "enforced": enforce, "allow": allow, **result}
    except Exception as e:
        _log_voice("identity", {"error": str(e), "enforced": enforce, "allowed": True})
        return {"enrolled": True, "enforced": enforce, "allow": True,
                "is_owner": True, "similarity": 0.0, "error": str(e)}
    finally:
        for p in (src_path, wav_path):
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass


# =============================================================================
# VOICE COMMAND FAST-PATH
# =============================================================================

_VOICE_CMDS = {
    r"what('s| is) (the )?(time|clock)":           "TIME",
    r"what('s| is) (the )?date":                    "DATE",
    r"what day (is it|today)":                      "DATE",
    r"what('s| is) (the )?weather":                 "WEATHER",
    r"how('s| is) (the )?weather":                  "WEATHER",
    r"will it rain":                                 "WEATHER",
    r"(switch|go) to local( mode)?":                "MODE:local",
    r"offline mode":                                 "MODE:local",
    r"(switch|go) to cloud( mode)?":                "MODE:cloud",
    r"online mode":                                  "MODE:cloud",
    r"(system )?status":                             "STATUS",
    r"(system )?health( check)?":                   "HEALTH",
    r"what can you do":                              "CAPABILITIES",
    r"how are you (doing|running|feeling)":          "HEALTH",
    r"(open|launch) (chrome|browser|firefox|edge)": "BROWSER",
    r"(open|launch) (.+)":                           "OPEN_APP",
    r"take (a )?screenshot":                         "SCREENSHOT",
    r"(pause|stop) (listening|voice)":               "VOICE:stop",
}


def parse_voice_command(text: str) -> Optional[str]:
    tl = text.lower().strip()
    for pattern, cmd in _VOICE_CMDS.items():
        m = re.search(pattern, tl)
        if m:
            if cmd == "OPEN_APP" and m.lastindex and m.lastindex >= 2:
                return f"OPEN_APP:{m.group(2)}"
            return cmd
    return None


def execute_voice_command(command: str) -> str:
    """Execute a fast-path command. Returns spoken response text."""
    now = datetime.now()

    if command == "TIME":
        return f"It's {now.strftime('%I:%M %p')}."

    if command == "DATE":
        return f"Today is {now.strftime('%A, %B %d, %Y')}."

    if command == "WEATHER":
        try:
            from action_engine import fetch_weather
            w = fetch_weather()
            if w.get("success"):
                return (
                    f"Currently {w['temp_c']} degrees Celsius in {w['location']}. "
                    f"{w['description']}. Humidity {w['humidity']} percent."
                )
        except Exception:
            pass
        return "Weather data unavailable right now."

    if command == "HEALTH":
        try:
            from system_monitor import get_system_health_score, get_memory_usage
            score = get_system_health_score()
            ram   = get_memory_usage().get("percent", 0)
            return f"System health {score} out of 100. RAM usage at {ram} percent. All systems nominal."
        except Exception:
            pass
        return "System status nominal."

    if command == "STATUS":
        try:
            from personality import get_mood
            from autonomous_loop import is_loop_running
            mood = get_mood()
            loop = "active" if is_loop_running() else "standby"
            return (
                f"{AGENT_NAME} online. Mood: {mood.lower()}. "
                f"Autonomous loop {loop}. "
                f"All systems operational."
            )
        except Exception:
            pass
        return f"{AGENT_NAME} online and fully operational."

    if command == "CAPABILITIES":
        return (
            "I can answer questions, search the web, control your computer, "
            "send emails, run code, monitor your system, remember things, "
            "and work autonomously in the background. What do you need?"
        )

    if command == "SCREENSHOT":
        try:
            from computer_control import take_screenshot
            result = take_screenshot()
            if result.get("success"):
                return f"Screenshot taken. Screen is {result['size'][0]} by {result['size'][1]} pixels."
            return "Screenshot failed: " + result.get("error", "unknown error")
        except Exception as e:
            return f"Screenshot unavailable: {e}"

    if command == "BROWSER":
        try:
            from computer_control import open_url
            open_url("https://www.google.com")
            return "Opening browser."
        except Exception:
            return "Could not open browser."

    if command.startswith("OPEN_APP:"):
        app = command.split(":", 1)[1]
        try:
            from computer_control import open_app
            result = open_app(app)
            if result.get("success"):
                return f"Opening {app}."
            return f"Couldn't open {app}: {result.get('error', '')}"
        except Exception:
            return f"Could not open {app}."

    if command.startswith("MODE:"):
        mode = command.split(":", 1)[1]
        return f"Switching to {mode} mode."

    if command == "VOICE:stop":
        return "Voice interface paused."

    return "Command acknowledged."


# =============================================================================
# VOICE LOG
# =============================================================================

def _log_voice(event_type: str, data: dict):
    entry = {"timestamp": datetime.now().isoformat(), "event": event_type, **data}
    with _log_lock:
        try:
            log = []
            if os.path.exists(VOICE_LOG_FILE):
                with open(VOICE_LOG_FILE, "r", encoding="utf-8") as f:
                    log = json.load(f)
            log.append(entry)
            log = log[-500:]
            with open(VOICE_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(log, f, indent=2)
        except Exception:
            pass


def get_voice_log(n: int = 20) -> list:
    try:
        with open(VOICE_LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)[-n:]
    except Exception:
        return []


# =============================================================================
# STATUS
# =============================================================================

def get_voice_status() -> dict:
    kokoro_model_ready = (
        KOKORO_AVAILABLE and
        os.path.exists(_KOKORO_ONNX_PATH) and
        os.path.exists(_KOKORO_VOICES_PATH)
    )
    active_tts = (
        "elevenlabs" if ELEVENLABS_API_KEY else
        "openai"     if OPENAI_API_KEY else
        "kokoro"     if kokoro_model_ready else
        "edge"       if EDGE_TTS_AVAILABLE else "none"
    )
    _groq_key = ""
    try:
        from config import GROQ_API_KEY as _gk
        _groq_key = _gk
    except Exception:
        _groq_key = os.environ.get("GROQ_API_KEY", "")
    active_stt = (
        "openai_whisper"  if OPENAI_API_KEY else
        "groq_whisper"    if _groq_key else
        "faster_whisper"  if FASTER_WHISPER_AVAILABLE else
        "local_whisper"   if LOCAL_WHISPER_AVAILABLE else "none"
    )
    return {
        "tts": {
            "elevenlabs":  bool(ELEVENLABS_API_KEY),
            "openai":      bool(OPENAI_API_KEY),
            "kokoro":      kokoro_model_ready,
            "edge_tts":    EDGE_TTS_AVAILABLE,
            "active":      active_tts,
        },
        "stt": {
            "openai_whisper":  bool(OPENAI_API_KEY),
            "groq_whisper":    bool(_groq_key),
            "faster_whisper":  FASTER_WHISPER_AVAILABLE,
            "local_whisper":   LOCAL_WHISPER_AVAILABLE,
            "active":          active_stt,
        },
        "streaming":    True,
        "wake_word":    "browser_web_speech_api",
        "cache_files":  len(list(Path(VOICE_CACHE_DIR).glob("tts_*.mp3"))) if os.path.exists(VOICE_CACHE_DIR) else 0,
        "ready":        active_tts != "none",
    }


# =============================================================================
# VOICE BRIEFING
# =============================================================================

def generate_voice_briefing(kind: str = "morning") -> str:
    now         = datetime.now()
    weather_str = "weather unavailable"
    goal_str    = "no pending tasks"
    health_str  = "system nominal"

    try:
        from action_engine import fetch_weather
        w = fetch_weather()
        if w.get("success"):
            weather_str = f"{w['temp_c']} degrees, {w['description'].lower()}"
    except Exception:
        pass

    try:
        from decision_engine import load_goals, GoalStatus
        pending = [g for g in load_goals() if g["status"] == GoalStatus.PENDING]
        if pending:
            goal_str = f"{len(pending)} pending tasks, priority: {pending[0]['title']}"
    except Exception:
        pass

    try:
        from system_monitor import get_system_health_score
        score = get_system_health_score()
        health_str = f"system health at {score} percent"
    except Exception:
        pass

    if kind == "morning":
        return (
            f"Good morning, {JEEVAN_NAME}. "
            f"It's {now.strftime('%A, %B %d')}. "
            f"Currently {weather_str} in Hyderabad. "
            f"You have {goal_str}. "
            f"{health_str.capitalize()}. "
            "Ready when you are."
        )
    return (
        f"Good evening, {JEEVAN_NAME}. "
        f"Currently {weather_str} outside. "
        f"You have {goal_str}. "
        "I'll keep monitoring things overnight."
    )
    
    # ================= TEST BLOCK =================
if __name__ == "__main__":
    import pyttsx3

    engine = pyttsx3.init('sapi5')
    engine.say("Voice engine test successful")
    engine.runAndWait()