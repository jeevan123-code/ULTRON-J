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
import math
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
        "CURIOUS":    {"voice_id": "onwK4N9gsSGsGA4xWAcb", "name": "Daniel"},
        "ALERT":      {"voice_id": "onwK4N9gsSGsGA4xWAcb", "name": "Daniel"},
        "CONCERNED":  {"voice_id": "onwK4N9gsSGsGA4xWAcb", "name": "Daniel"},
        "DETERMINED": {"voice_id": "onwK4N9gsSGsGA4xWAcb", "name": "Daniel"},
        "ANALYTICAL": {"voice_id": "onwK4N9gsSGsGA4xWAcb", "name": "Daniel"},
        "IDLE":       {"voice_id": "onwK4N9gsSGsGA4xWAcb", "name": "Daniel"},
    }
    OPENAI_TTS_VOICES         = {
        "FOCUSED": "onyx", "CURIOUS": "onyx", "ALERT": "onyx",
        "CONCERNED": "onyx", "DETERMINED": "onyx",
        "ANALYTICAL": "onyx", "IDLE": "onyx",
    }
    EDGE_TTS_VOICES           = {
        "FOCUSED":    "en-US-ChristopherNeural",
        "CURIOUS":    "en-US-ChristopherNeural",
        "ALERT":      "en-US-ChristopherNeural",
        "CONCERNED":  "en-US-ChristopherNeural",
        "DETERMINED": "en-US-ChristopherNeural",
        "ANALYTICAL": "en-US-GuyNeural",
        "IDLE":       "en-US-ChristopherNeural",
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

# Piper TTS — deep professional male voice (Ryan), ~1s synthesis on CPU.
# This is the primary TTS for Ultron: local, fast, no API cost, no echo of
# online services. Falls back to edge_tts if anything goes wrong.
try:
    from piper import PiperVoice as _PiperVoice
    PIPER_AVAILABLE = True
    _piper_voice = None  # lazy-loaded
    _PIPER_MODEL_PATH = os.path.join(_BASE_DIR, "piper_voices", "en_US-ryan-high.onnx")
except ImportError:
    PIPER_AVAILABLE = False
    _piper_voice = None
    _PIPER_MODEL_PATH = ""

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

# Early-split boundary for the FIRST chunk only — splits on , ; : —
# so the very first audio chunk plays in ~1s instead of after a full sentence.
_EARLY_SPLIT_RE = re.compile(r'(?<=[,;:—])\s+')
_EARLY_MIN_WORDS = 5    # don't split before at least 5 words have arrived

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
        clean = trunc[:stop + 1] if stop > 0 and stop > len(trunc) * 0.6 else trunc + "..."
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
            "voice_settings": {"stability": 0.65, "similarity_boost": 0.80, "style": 0.10, "use_speaker_boost": True},
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


def _get_piper():
    global _piper_voice
    if _piper_voice is None:
        if not os.path.exists(_PIPER_MODEL_PATH):
            raise RuntimeError(f"Piper model not found: {_PIPER_MODEL_PATH}")
        print("[VoiceEngine] Loading Piper Ryan voice (one-time ~1s)...")
        _piper_voice = _PiperVoice.load(_PIPER_MODEL_PATH)
    return _piper_voice


def _tts_piper(text: str, mood: str) -> bytes:
    """Piper local TTS — deep professional male voice (Ryan). ~1s on CPU.
    Returns WAV bytes (browsers play this fine via the audio/mpeg response).
    """
    if not PIPER_AVAILABLE:
        raise RuntimeError("piper-tts not installed")
    voice = _get_piper()

    import io as _io
    import wave as _wave
    from piper import SynthesisConfig as _SynthesisConfig

    # Mood → speech rate. length_scale lower = faster. Baseline 0.85 puts
    # Ultron at ~15% faster than Piper's default (still natural, clearly
    # intelligible — verified). Mood adjustments multiply this baseline.
    rate         = VOICE_SPEAKING_RATES.get(mood, 1.0)
    length_scale = max(0.55, min(1.40, 0.85 / rate))
    # Lower noise scales reduce variance — slightly less "warm" but cleaner
    # and ~5% faster decode because fewer recovery passes are needed.
    syn_cfg = _SynthesisConfig(
        length_scale=length_scale,
        noise_scale=0.55,
        noise_w_scale=0.7,
        normalize_audio=True,
    )

    buf = _io.BytesIO()
    with _wave.open(buf, "wb") as wf:
        voice.synthesize_wav(
            text[:VOICE_MAX_TTS_CHARS],
            wf,
            syn_config=syn_cfg,
        )
    return buf.getvalue()


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
    """Pre-load local TTS models on a background thread so the very first
    synthesis call doesn't pay cold-load cost. Pure pre-warming — does not
    change synthesis behavior. Safe to call once at server startup; subsequent
    calls are no-ops because the getter functions are idempotent.
    """
    def _bg_piper():
        if not (PIPER_AVAILABLE and os.path.exists(_PIPER_MODEL_PATH)):
            return
        try:
            _get_piper()
            print("[VoiceEngine] Piper Ryan voice pre-warmed.")
        except Exception as _e:
            print(f"[VoiceEngine] Piper pre-warm skipped: {_e}")

    def _bg_kokoro():
        if not KOKORO_AVAILABLE:
            return
        if not (os.path.exists(_KOKORO_ONNX_PATH) and os.path.exists(_KOKORO_VOICES_PATH)):
            return
        try:
            _get_kokoro()
            print("[VoiceEngine] Kokoro pre-warmed.")
        except Exception as _e:
            print(f"[VoiceEngine] Kokoro pre-warm skipped: {_e}")

    threading.Thread(target=_bg_piper,  daemon=True, name="piper-warmup").start()
    threading.Thread(target=_bg_kokoro, daemon=True, name="kokoro-warmup").start()


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
        "FOCUSED":    "am_michael",
        "CURIOUS":    "am_michael",
        "ALERT":      "am_michael",
        "CONCERNED":  "am_michael",
        "DETERMINED": "am_michael",
        "ANALYTICAL": "am_michael",
        "IDLE":       "am_michael",
    }
    voice = voice_map.get(mood, "am_michael")
    rate  = VOICE_SPEAKING_RATES.get(mood, 1.0)
    samples, sample_rate = kokoro.create(
        text[:VOICE_MAX_TTS_CHARS], voice=voice, speed=rate, lang="en-us"
    )
    import io as _io
    buf = _io.BytesIO()
    _soundfile.write(buf, samples, sample_rate, format="WAV")
    return buf.getvalue()


# =============================================================================
# TTS — UNIFIED
# =============================================================================

def tts(text: str, mood: str = "FOCUSED", provider: str = "auto") -> Tuple[bytes, str]:
    """
    Convert text to MP3 bytes.

    Phase 7.6 — Piper-first chain (matches the original design intent
    of the surrounding comment). Order:

      auto: Piper (local, free, ~1s) -> Kokoro (local) -> ElevenLabs
            (if key) -> OpenAI (if key) -> Edge (cloud, no key needed)

    Local-first means zero per-call API cost, no network round-trip,
    no API-key requirement, and offline operation. The cloud providers
    stay as fallbacks if Piper/Kokoro models aren't installed.

    Override with `provider=<name>` to force a specific backend; "edge"
    is always appended as a last-resort no-key fallback.

    Returns: (audio_bytes, provider_name)
    """
    clean = prepare_for_tts(text) or "Done."

    cached = _get_cached(clean, mood, provider)
    if cached:
        return cached, f"{provider}:cached"

    if provider == "auto":
        chain = []
        # Local providers first (free, no API cost, no network).
        if PIPER_AVAILABLE and os.path.exists(_PIPER_MODEL_PATH):
            chain.append("piper")
        if KOKORO_AVAILABLE:
            chain.append("kokoro")
        # Cloud premium voices as fallback if local isn't installed.
        if ELEVENLABS_API_KEY:
            chain.append("elevenlabs")
        if OPENAI_API_KEY:
            chain.append("openai")
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
            elif prov == "piper":
                audio = _tts_piper(clean, mood)
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
    Consume an LLM SSE stream, split into sentences, synthesize TTS in parallel
    with token streaming, yield audio chunks in order as they're ready.

    Two design changes vs the original blocking version:
      1. TTS runs in a ThreadPoolExecutor — the token loop never blocks waiting
         for synthesis, so text_token events keep flowing at LLM speed.
      2. The FIRST chunk splits on a comma/semicolon after ≥5 words, so the
         first audio plays in ~1s instead of waiting for a full `.!?` boundary.

    Audio chunks are yielded in strict order (so the browser's FIFO queue
    plays them sequentially with no gaps).

    Yields dicts:
      {"type": "transcript_start"}
      {"type": "text_token", "token": "..."}
      {"type": "sentence", "text": "...", "audio_b64": "...", "index": N}
      {"type": "text_only", "text": "...", "index": N}   — TTS failed for chunk
      {"type": "done", "full_text": "..."}
      {"type": "error", "msg": "..."}
    """
    from concurrent.futures import ThreadPoolExecutor
    from queue import Queue

    output_q: "Queue[Optional[Dict]]" = Queue()
    SENTINEL: Dict = {"__sentinel__": True}
    pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="tts-stream")
    pending: List[tuple] = []          # [(idx, sentence, future), ...] in submission order
    pending_lock = threading.Lock()
    flush_lock   = threading.Lock()    # serialises concurrent done-callbacks → no out-of-order audio

    def _flush_in_order():
        """Drain the head of `pending` while the next future is done."""
        with flush_lock:               # only one thread flushes at a time — prevents out-of-order audio
            while True:
                with pending_lock:
                    if not pending or not pending[0][2].done():
                        return
                    idx, sentence, fut = pending.pop(0)
                try:
                    audio_bytes = fut.result()
                    output_q.put({
                        "type":      "sentence",
                        "text":      sentence,
                        "audio_b64": base64.b64encode(audio_bytes).decode(),
                        "index":     idx,
                    })
                except Exception:
                    output_q.put({"type": "text_only", "text": sentence, "index": idx})

    def _submit(sentence: str, idx: int):
        fut = pool.submit(lambda s=sentence: tts(s, mood=mood)[0])
        with pending_lock:
            pending.append((idx, sentence, fut))
        # Fire flush on completion so audio arrives the instant it's ready,
        # even if the LLM is paused and no new tokens are arriving.
        fut.add_done_callback(lambda _f: _flush_in_order())

    def producer():
        sentence_buf = ""
        full_text    = ""
        chunk_index  = 0
        first_chunk_emitted = False

        try:
            output_q.put({"type": "transcript_start"})

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

                if d.get("_full"):
                    full_text = d["_full"]
                    break

                # Skip status markers — these are for the chat UI's spinner
                # ("⚡ Processing...", "🧠 Thinking...", "🔍 Analyzing deeply..."),
                # NOT speech content. Previously these leaked into the TTS
                # stream and were read aloud as "high voltage processing".
                if d.get("type") == "status":
                    continue

                token = d.get("token", "")
                if not token:
                    continue

                full_text    += token
                sentence_buf += token

                # Emit text token immediately — never blocked by TTS now.
                output_q.put({"type": "text_token", "token": token})

                # Early-split for the FIRST chunk only: kick off TTS at a
                # comma/semicolon after ≥5 words so audio starts in ~1s.
                if not first_chunk_emitted:
                    m = _EARLY_SPLIT_RE.search(sentence_buf)
                    if m and len(sentence_buf[:m.start()].split()) >= _EARLY_MIN_WORDS:
                        head = sentence_buf[:m.start()].strip()
                        sentence_buf = sentence_buf[m.end():]
                        if len(head) >= 4:
                            _submit(head, chunk_index)
                            chunk_index += 1
                            first_chunk_emitted = True
                            continue

                # Normal sentence boundary
                if _SENT_END_RE.search(sentence_buf):
                    parts = _SENT_END_RE.split(sentence_buf)
                    complete_parts = parts[:-1]
                    sentence_buf   = parts[-1]
                    for sentence in complete_parts:
                        sentence = sentence.strip()
                        if len(sentence) < 4:
                            continue
                        _submit(sentence, chunk_index)
                        chunk_index += 1
                        first_chunk_emitted = True

            # Flush any tail
            remainder = sentence_buf.strip()
            if remainder and len(remainder) > 3:
                _submit(remainder, chunk_index)
                chunk_index += 1

            # Wait for every queued synthesis to flush.
            while True:
                with pending_lock:
                    if not pending:
                        break
                    head_fut = pending[0][2]
                try:
                    head_fut.result()
                except Exception:
                    pass
                _flush_in_order()

            output_q.put({"type": "done", "full_text": full_text, "total_chunks": chunk_index})
        except Exception as e:
            output_q.put({"type": "error", "msg": str(e)})
        finally:
            output_q.put(SENTINEL)

    threading.Thread(target=producer, daemon=True, name="tts-producer").start()

    try:
        while True:
            item = output_q.get()
            if item is SENTINEL:
                return
            yield item
    finally:
        # Best-effort: cancel pending work if the client disconnected.
        pool.shutdown(wait=False)


# =============================================================================
# STT PROVIDERS
# =============================================================================

# Whisper hallucinates these phrases on silence / non-speech audio
# (well-documented behavior — door sounds, fan noise, TTS bleed, non-English
# background speech with language=en all trigger them)
_WHISPER_HALLUCINATIONS = frozenset({
    # YouTube/captions training bias
    "thank you", "thanks", "thanks for watching", "thank you for watching",
    "thanks for watching!", "thank you for watching!", "thanks so much for watching",
    "thanks for watching the video", "thank you so much for watching",
    "please subscribe", "subscribe", "like and subscribe", "see you next time",
    "see you in the next video", "see you in the next one", "see you guys",
    "subtitles by", "captions by", "transcribed by", "translated by",
    "subtitles by the amara org community",
    # Farewells / sign-offs
    "bye", "bye bye", "goodbye", "see you", "see ya", "later",
    # YouTube intro/outro family
    "welcome back", "welcome to", "hello everyone", "hi everyone", "hey guys",
    # Affirmation-only fragments (real commands always carry a verb)
    "alright", "all right", "right", "okay then", "alright then", "okay so",
    # Single low-info tokens
    "you", "the", "okay", "ok", "yeah", "yes", "no", "huh", "what", "why",
    # Filler / noise tokens
    "uh", "um", "hmm", "mm", "hm", "ah", "oh", "mhm", "mhmm",
    "music", "applause", "silence", "background noise", "no audio",
    # Common Whisper noise outputs
    "i love you", "i love you.", "love you", "love you.",
    "the end", "the end.", "to be continued", "to be continued.",
    # Indian-English Whisper noise patterns (seen in this user's voice log)
    "jeevan", "hyderabad", "jeevan in hyderabad",
    "personal assistant", "personal assistant for jeevan",
})

# Pattern-matched hallucination families. These fire when Whisper substitutes
# a high-probability training-data phrase for noise/non-English audio.
# The "I'm going to..." family is the single most common one observed on
# Hindi/Telugu background speech with language=en forced.
_WHISPER_HALLUCINATION_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in (
        # "I'm going to..." family — the #1 hallucination on noise
        r"^i['’]?m (going|gonna) (to )?(go to |head to |get to )?[a-z' ]{0,40}[.!?]?$",
        r"^i['’]?m (sorry|okay|fine|good|tired|happy|hungry|thirsty)[a-z' ]{0,20}[.!?]?$",
        # "I'll..." farewells
        r"^i['’]?ll (go|head|see you|talk to you|catch you|be back|let you know|do that)[a-z' ]{0,40}[.!?]?$",
        # "We're..." / "Let's..." filler
        r"^we['’]?re (going|gonna|here|back)[a-z' ]{0,40}[.!?]?$",
        r"^let['’]?s (go|see|talk|start|begin|continue|do this)[a-z' ]{0,20}[.!?]?$",
        # See-you farewells
        r"^(see|catch|talk to) you (later|soon|tomorrow|next time|guys|all)[!.]?$",
        # Going-to obligations
        r"^(i|we) (have|need|got|gotta)?\s*to (go|leave|head)[a-z' ]{0,30}[.!?]?$",
        # Don't-know / hedging
        r"^i don['’]?t know[a-z' ]{0,20}[.!?]?$",
        r"^i['’]?m not sure[a-z' ]{0,20}[.!?]?$",
        # YouTube intro/outro template
        r"^(welcome|welcome back|hi|hello|hey) (to|everyone|guys|friends|y['’]?all)[a-z' ]{0,30}[!.]?$",
        # Caption-credit family — Whisper often appends "by amara.org community"
        r"^(subtitles?|captions?|transcribed|translated)\s+by\b.*$",
        # Repetition: triplet of same short token
        r"^(.{1,15})\s+\1\s+\1",
        # Bare proper nouns from this user's named context — strong noise signal
        r"^(jeevan|ultron|hyderabad|india|telangana)[!.,? ]{0,3}$",
    )
]

# Whisper occasionally echoes its own prompt-bias hint on near-silence.
# Detect transcripts that are >=70% substring overlap with the prompt itself.
def _is_prompt_echo(text: str, prompt: str) -> bool:
    t = re.sub(r"[^\w ]", " ", text.lower()).strip()
    p = re.sub(r"[^\w ]", " ", prompt.lower()).strip()
    if len(t) < 4:
        return False
    t_words = set(t.split())
    p_words = set(p.split())
    if not t_words or not p_words:
        return False
    # If >=70% of transcript words are also prompt words AND short transcript,
    # it's an echo (real commands of similar length share <40% vocabulary).
    overlap = len(t_words & p_words) / len(t_words)
    return overlap >= 0.7 and len(t_words) <= 6


def _is_whisper_hallucination(text: str) -> bool:
    """True if the transcribed text is a known Whisper noise-hallucination."""
    cleaned = re.sub(r"[\[\]\(\)\.!?,;:\"'\s]+", " ", text.lower()).strip()
    if cleaned in _WHISPER_HALLUCINATIONS:
        return True
    raw = text.strip()
    for pat in _WHISPER_HALLUCINATION_PATTERNS:
        if pat.match(raw):
            return True
    return False


def _stt_groq(audio_bytes: bytes) -> Dict:
    """Groq Whisper — GPU-accelerated, ~200ms, uses existing GROQ_API_KEY.

    Anti-hallucination:
      - response_format=verbose_json gives per-segment no_speech_prob + avg_logprob
      - temperature=0 minimizes Whisper's tendency to invent text on noise
      - prompt biases vocabulary toward our domain (reduces "Ultron" -> "Altron")
      - segment scores compute real confidence (was hardcoded 0.95 before)
      - known hallucination phrases ("Thank you.", "Bye.") are filtered out
    """
    try:
        from config import GROQ_API_KEY as _gkey
    except ImportError:
        _gkey = os.environ.get("GROQ_API_KEY", "")
    if not _gkey:
        raise RuntimeError("GROQ_API_KEY not set")
    # Prompt biases Whisper toward command vocabulary instead of named entities.
    # CRITICAL: previously we used "Ultron-J personal assistant for Jeevan in
    # Hyderabad" — Whisper hallucinated "Jeevan in Hyderabad" verbatim on noise
    # (the prompt acts as fall-back text the model emits when audio is unclear).
    # Generic verbs are safer — they don't form an utterance Whisper can echo.
    _whisper_prompt = (
        "open close play pause search browser screenshot lock email volume "
        "screenshot type click scroll terminal calculator weather time"
    )
    resp = requests.post(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {_gkey}"},
        files={"file": ("audio.webm", audio_bytes, "audio/webm")},
        data={
            "model":            "whisper-large-v3-turbo",
            "response_format":  "verbose_json",
            "language":         "en",
            "temperature":      "0.0",
            "prompt":           _whisper_prompt,
        },
        timeout=15,
    )
    resp.raise_for_status()
    result   = resp.json()
    text     = (result.get("text") or "").strip()
    segments = result.get("segments") or []

    # No segments returned — no speech detected
    if not segments or not text:
        return {"text": "", "confidence": 0.0, "language": "en",
                "provider": "groq_whisper", "error": "no_speech"}

    # Reject if Whisper itself flagged any segment as silence.
    # 0.5 threshold is lenient enough for accented/noisy speech while still
    # catching clear non-speech segments (was 0.4 — too tight for Indian English).
    max_no_speech = max(float(s.get("no_speech_prob", 0)) for s in segments)
    if max_no_speech > 0.5:
        return {"text": "", "confidence": 0.0, "language": "en",
                "provider": "groq_whisper", "error": "no_speech_prob_high",
                "filtered_text": text, "no_speech_prob": round(max_no_speech, 3)}

    # Reject if Whisper produced repetitive / gibberish output.
    # OpenAI reference is 2.4; we want strict for voice commands.
    max_compression = max(float(s.get("compression_ratio", 0)) for s in segments)
    if max_compression > 2.0:
        return {"text": "", "confidence": 0.0, "language": "en",
                "provider": "groq_whisper", "error": "compression_ratio_high",
                "filtered_text": text, "compression_ratio": round(max_compression, 2)}

    # Real confidence from token-level log-probabilities (geometric mean).
    # Real speech: avg_logprob typically -0.2 to -0.5 (confidence 0.6-0.8).
    # Hallucinations on noise: typically -0.6 to -1.5 (confidence 0.2-0.55).
    avg_logprob = sum(float(s.get("avg_logprob", -1.0)) for s in segments) / len(segments)
    confidence  = max(0.0, min(1.0, math.exp(avg_logprob)))

    # Loosened from -0.6 → -0.75 — Indian English / accented speech scores lower
    # on Whisper (trained on US/UK data); -0.75 passes more real speech through.
    if avg_logprob < -0.75:
        return {"text": "", "confidence": round(confidence, 3), "language": "en",
                "provider": "groq_whisper", "error": "avg_logprob_low",
                "filtered_text": text, "avg_logprob": round(avg_logprob, 3)}

    # Reject if Whisper echoed back our own prompt-bias hint (sign of near-silence)
    if _is_prompt_echo(text, _whisper_prompt):
        return {"text": "", "confidence": 0.0, "language": "en",
                "provider": "groq_whisper", "error": "prompt_echo",
                "filtered_text": text}

    # Filter known Whisper hallucinations on noise (phrase + pattern based)
    if _is_whisper_hallucination(text):
        return {"text": "", "confidence": 0.0, "language": "en",
                "provider": "groq_whisper", "error": "hallucination_filtered",
                "filtered_text": text}

    return {
        "text":       text,
        "language":   "en",
        "confidence": round(confidence, 3),
        "provider":   "groq_whisper",
    }


def _stt_openai(audio_bytes: bytes) -> Dict:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set")
    resp = requests.post(
        "https://api.openai.com/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        files={"file": ("audio.webm", audio_bytes, "audio/webm")},
        data={"model": "whisper-1", "response_format": "verbose_json", "temperature": "0.0"},
        timeout=60,
    )
    resp.raise_for_status()
    result   = resp.json()
    text     = (result.get("text") or "").strip()
    segments = result.get("segments") or []

    if not segments or not text:
        return {"text": "", "confidence": 0.0, "language": "en",
                "provider": "openai_whisper", "error": "no_speech"}

    max_no_speech = max(float(s.get("no_speech_prob", 0)) for s in segments)
    if max_no_speech > 0.5:
        return {"text": "", "confidence": 0.0, "language": "en",
                "provider": "openai_whisper", "error": "no_speech_prob_high",
                "filtered_text": text}

    avg_logprob = sum(float(s.get("avg_logprob", -1.0)) for s in segments) / len(segments)
    confidence  = max(0.0, min(1.0, math.exp(avg_logprob)))
    if avg_logprob < -0.75:
        return {"text": "", "confidence": round(confidence, 3), "language": "en",
                "provider": "openai_whisper", "error": "avg_logprob_low",
                "filtered_text": text}

    return {
        "text":       text,
        "language":   result.get("language", "en"),
        "confidence": round(confidence, 3),
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
                _local_audio = audio_path   # may already be a path if caller passed one
                _raw_tmp = _wav_tmp = None
                try:
                    if _local_audio is None:
                        if audio_bytes[:4] == b'OggS':
                            raw_suffix = ".ogg"
                        elif audio_bytes[:4] == b'fLaC':
                            raw_suffix = ".flac"
                        elif audio_bytes[:3] == b'ID3' or audio_bytes[:2] == b'\xff\xfb':
                            raw_suffix = ".mp3"
                        else:
                            raw_suffix = ".webm"
                        with tempfile.NamedTemporaryFile(suffix=raw_suffix, delete=False) as _t:
                            _t.write(audio_bytes)
                            _raw_tmp = _t.name
                        _wav_tmp = _raw_tmp.rsplit(".", 1)[0] + ".wav"
                        try:
                            from pydub import AudioSegment
                            # Export at 16kHz mono — avoids double-resampling inside faster-whisper
                            (AudioSegment.from_file(_raw_tmp)
                                .set_frame_rate(16000)
                                .set_channels(1)
                                .export(_wav_tmp, format="wav"))
                            _local_audio = _wav_tmp
                        except Exception:
                            _local_audio = _raw_tmp
                    if prov == "faster_whisper":
                        result = _stt_faster_whisper(_local_audio)
                    else:
                        result = _stt_local_whisper(_local_audio)
                finally:
                    for _p in (_raw_tmp, _wav_tmp):
                        if _p and os.path.exists(_p):
                            try:
                                os.unlink(_p)
                            except Exception:
                                pass
            else:
                continue
            # Apply hallucination/echo filtering for non-groq providers (groq filters internally)
            if prov != "groq" and result.get("text"):
                _wp = ("open close play pause search browser screenshot lock email "
                       "volume type click scroll terminal calculator weather time")
                if _is_prompt_echo(result["text"], _wp) or _is_whisper_hallucination(result["text"]):
                    result = {
                        "text": "", "confidence": 0.0,
                        "language": result.get("language", "en"),
                        "provider": prov, "error": "hallucination_filtered",
                        "filtered_text": result["text"],
                    }
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
    # Greetings — fast-path so "Hi" / "Hello" reply instantly, no LLM round-trip
    r"^(hi|hello|hey|yo|hii+|helloo+)( there| ultron| j| jay| ultron[- ]?j)?[!.\?]*$":
                                                    "GREETING",
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
    import os as _os
    # Phase 2b: passively record EVERY transcript for autonomous research.
    import os as _os_p2b
    if _os_p2b.environ.get("ULTRON_PHASE2B_ENABLED", "0") == "1":
        try:
            import conversation_listener as _cl
            _cl.record(text)
        except Exception:
            pass

    # Phase 3b: route consent responses to a pending proactive offer.
    import os as _os_p3b
    if _os_p3b.environ.get("ULTRON_PHASE3B_ENABLED", "0") == "1":
        try:
            import proactive_offer as _po
            if _po.peek_pending_offer() is not None:
                from consent_manager import parse_consent as _parse_c
                from consent_types import ConsentMode as _Cm
                _mode = _parse_c(text)
                if _mode != _Cm.NONE:
                    _po.confirm_offer(_mode)
                    return None
        except Exception as _ce:
            try:
                with open("ultron_log.txt", "a") as _f:
                    _f.write(f"[phase3b][consent_error] {_ce!r}\n")
            except Exception:
                pass

    if _os.environ.get("ULTRON_PHASE1_ENABLED", "0") == "1":
        try:
            from phase1_pipeline import process_user_utterance as _process_p1
            _p1_plan = _process_p1(raw=text, context={"recent_topics": []}, last_action=None)
            with open("ultron_log.txt", "a") as _f:
                _f.write(f"[phase1] plan = {_p1_plan.to_dict()}\n")

            # Phase 2a: if the plan is a research action, execute it.
            if _os.environ.get("ULTRON_PHASE2A_ENABLED", "0") == "1":
                if _p1_plan.steps and _p1_plan.steps[0].get("action") == "research":
                    try:
                        from phase2_executor import execute as _p2_execute
                        _p2_result = _p2_execute(_p1_plan)
                        with open("ultron_log.txt", "a") as _f:
                            _f.write(f"[phase2a] result = {_p2_result}\n")
                        # Research consumed the utterance — short-circuit the fast-path.
                        return None
                    except Exception as _pe:
                        with open("ultron_log.txt", "a") as _f:
                            _f.write(f"[phase2a][execute_error] {_pe!r}\n")
        except Exception as _e:
            try:
                with open("ultron_log.txt", "a") as _f:
                    _f.write(f"[phase1][error] {_e!r}\n")
            except Exception:
                pass

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

    if command == "GREETING":
        h = now.hour
        if   h < 12: tod = "morning"
        elif h < 17: tod = "afternoon"
        else:        tod = "evening"
        return f"Good {tod}, {JEEVAN_NAME}. What do you need?"

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
    piper_model_ready = (
        PIPER_AVAILABLE and os.path.exists(_PIPER_MODEL_PATH)
    )
    active_tts = (
        "elevenlabs" if ELEVENLABS_API_KEY else
        "openai"     if OPENAI_API_KEY else
        "piper"      if piper_model_ready else
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
            "piper":       piper_model_ready,
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
