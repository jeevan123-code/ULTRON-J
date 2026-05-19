"""
interrupt_engine.py — Mid-Sentence Interruption + Noise Cancellation for Ultron-J.

Solves:
1. Can't interrupt mid-sentence  → InterruptEngine stops TTS playback instantly
2. No noise cancellation         → NoiseCanceller cleans audio before STT
3. Can't reason long documents   → LongDocReasoner (chunked map-reduce)

BEYOND JARVIS: You can say "stop" mid-sentence and Ultron halts immediately.
Audio noise is filtered before STT so it works in loud rooms.
Long documents (PDFs, codebases) are reasoned across in chunks.
"""

import io
import json
import math
import os
import queue
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, Generator, List, Optional


_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Optional audio libraries ───────────────────────────────────────────────────
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

try:
    import noisereduce as nr
    NOISEREDUCE_AVAILABLE = True
except ImportError:
    NOISEREDUCE_AVAILABLE = False

try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False


# =============================================================================
# INTERRUPT ENGINE
# =============================================================================

class InterruptEngine:
    """
    Intercepts TTS playback and stops it when interrupted.

    Works by wrapping the audio playback with a killable thread.
    Call interrupt() from voice listener or keyboard to stop mid-sentence.

    Usage:
        engine = InterruptEngine()
        engine.play_audio_interruptible(audio_path, on_complete_fn)
        # ... user says "stop" ...
        engine.interrupt()
    """

    INTERRUPT_PHRASES = {
        "stop", "halt", "enough", "shut up", "cancel", "nevermind",
        "never mind", "wait", "pause", "quiet", "silence", "ok stop",
        "that's enough", "stop talking",
    }

    def __init__(self):
        self._interrupt_event  = threading.Event()
        self._playback_thread: Optional[threading.Thread] = None
        self._is_speaking      = False
        self._lock             = threading.Lock()
        self._on_interrupted:  Optional[Callable] = None

    def is_speaking(self) -> bool:
        return self._is_speaking

    def interrupt(self, reason: str = "user_request"):
        """Stop any ongoing TTS playback immediately."""
        if self._is_speaking:
            self._interrupt_event.set()
            print(f"[InterruptEngine] ⛔ Interrupted ({reason})")
            if self._on_interrupted:
                self._on_interrupted(reason)
        self._is_speaking = False

    def check_interrupt_phrase(self, text: str) -> bool:
        """Returns True if text contains an interrupt phrase."""
        text_lower = text.lower().strip()
        for phrase in self.INTERRUPT_PHRASES:
            if phrase in text_lower:
                return True
        return False

    def play_audio_interruptible(self, audio_path: str,
                                  on_complete: Callable = None,
                                  on_interrupted: Callable = None):
        """
        Play audio file in a separate thread.
        Can be interrupted mid-playback.
        """
        self._interrupt_event.clear()
        self._is_speaking    = True
        self._on_interrupted = on_interrupted

        def _play():
            try:
                if SOUNDDEVICE_AVAILABLE and NUMPY_AVAILABLE:
                    import soundfile as sf
                    data, samplerate = sf.read(audio_path)
                    chunk_size = samplerate // 10     # 100ms chunks

                    for i in range(0, len(data), chunk_size):
                        if self._interrupt_event.is_set():
                            break
                        chunk = data[i:i+chunk_size]
                        sd.play(chunk, samplerate=samplerate, blocking=True)
                else:
                    # Fallback: use system player
                    import subprocess, platform
                    p = platform.system()
                    if p == "Windows":
                        proc = subprocess.Popen(["powershell", "-c",
                            f"(New-Object Media.SoundPlayer '{audio_path}').PlaySync()"])
                    elif p == "Darwin":
                        proc = subprocess.Popen(["afplay", audio_path])
                    else:
                        proc = subprocess.Popen(["aplay", audio_path])

                    while proc.poll() is None:
                        if self._interrupt_event.is_set():
                            proc.terminate()
                            break
                        time.sleep(0.05)

            except Exception as e:
                print(f"[InterruptEngine] Playback error: {e}")
            finally:
                self._is_speaking = False
                if not self._interrupt_event.is_set() and on_complete:
                    on_complete()

        self._playback_thread = threading.Thread(target=_play, daemon=True, name="tts_playback")
        self._playback_thread.start()

    def stream_interruptible(self, text_generator: Generator,
                              tts_fn: Callable[[str], str],
                              on_complete: Callable = None):
        """
        Stream text from LLM → TTS → play, interruptibly.
        tts_fn(text) → audio_file_path
        """
        self._interrupt_event.clear()
        self._is_speaking = True
        audio_queue: queue.Queue = queue.Queue()

        def _generate():
            buffer = ""
            for chunk in text_generator:
                if self._interrupt_event.is_set():
                    break
                buffer += chunk
                # Send to TTS when we hit sentence boundary
                if any(buffer.rstrip().endswith(p) for p in [".", "!", "?", ":", "\n"]):
                    sentence = buffer.strip()
                    buffer   = ""
                    if sentence:
                        try:
                            audio_path = tts_fn(sentence)
                            audio_queue.put(audio_path)
                        except Exception:
                            pass
            if buffer.strip() and not self._interrupt_event.is_set():
                try:
                    audio_path = tts_fn(buffer.strip())
                    audio_queue.put(audio_path)
                except Exception:
                    pass
            audio_queue.put(None)   # sentinel

        def _play():
            while True:
                if self._interrupt_event.is_set():
                    break
                try:
                    path = audio_queue.get(timeout=15)
                except queue.Empty:
                    break
                if path is None:
                    break
                if not self._interrupt_event.is_set():
                    self.play_audio_interruptible(path)
                    # Wait for chunk to finish
                    while self._is_speaking and not self._interrupt_event.is_set():
                        time.sleep(0.05)
            self._is_speaking = False
            if on_complete and not self._interrupt_event.is_set():
                on_complete()

        threading.Thread(target=_generate, daemon=True, name="tts_generator").start()
        threading.Thread(target=_play, daemon=True, name="tts_player").start()


# =============================================================================
# NOISE CANCELLER
# =============================================================================

class NoiseCanceller:
    """
    Clean audio before sending to STT.
    Uses noisereduce library (spectral subtraction).
    Falls back to basic high-pass filter if not available.
    """

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate

    def clean_bytes(self, audio_bytes: bytes, fmt: str = "wav") -> bytes:
        """
        Takes raw audio bytes, returns cleaned audio bytes.
        fmt: "wav", "mp3", "ogg", etc.
        """
        if not NUMPY_AVAILABLE:
            return audio_bytes   # passthrough

        try:
            audio_array = self._bytes_to_array(audio_bytes, fmt)
            cleaned     = self._denoise(audio_array)
            return self._array_to_bytes(cleaned, fmt)
        except Exception as e:
            print(f"[NoiseCanceller] Error: {e}")
            return audio_bytes

    def clean_file(self, input_path: str, output_path: str = None) -> str:
        """Clean audio file in-place or to new path."""
        if output_path is None:
            base, ext = os.path.splitext(input_path)
            output_path = base + "_clean" + ext

        if not NUMPY_AVAILABLE:
            return input_path

        try:
            import soundfile as sf
            data, sr = sf.read(input_path)
            if data.ndim > 1:
                data = data.mean(axis=1)   # mono
            cleaned = self._denoise(data.astype(float), sr)
            sf.write(output_path, cleaned.astype("float32"), sr)
            return output_path
        except Exception as e:
            print(f"[NoiseCanceller] File clean error: {e}")
            return input_path

    def _denoise(self, audio: "np.ndarray", sr: int = None) -> "np.ndarray":
        sr = sr or self.sample_rate
        if NOISEREDUCE_AVAILABLE:
            return nr.reduce_noise(y=audio, sr=sr, stationary=False,
                                   prop_decrease=0.85)
        else:
            # Fallback: simple high-pass filter
            return self._highpass_filter(audio)

    def _highpass_filter(self, data: "np.ndarray",
                          cutoff: float = 80.0) -> "np.ndarray":
        """Remove low-frequency rumble below cutoff Hz."""
        if not NUMPY_AVAILABLE:
            return data
        n      = len(data)
        fft    = np.fft.rfft(data)
        freqs  = np.fft.rfftfreq(n, d=1.0/self.sample_rate)
        fft[freqs < cutoff] = 0
        return np.fft.irfft(fft, n=n)

    def _bytes_to_array(self, audio_bytes: bytes, fmt: str) -> "np.ndarray":
        try:
            import soundfile as sf
            buf = io.BytesIO(audio_bytes)
            data, _ = sf.read(buf)
            return data if data.ndim == 1 else data.mean(axis=1)
        except Exception:
            # Try raw PCM
            return np.frombuffer(audio_bytes, dtype=np.int16).astype(float) / 32768.0

    def _array_to_bytes(self, data: "np.ndarray", fmt: str) -> bytes:
        try:
            import soundfile as sf
            buf = io.BytesIO()
            sf.write(buf, data.astype("float32"), self.sample_rate, format=fmt.upper())
            return buf.getvalue()
        except Exception:
            return (data * 32767).astype(np.int16).tobytes()


# =============================================================================
# LONG DOCUMENT REASONER
# =============================================================================

class LongDocReasoner:
    """
    Process documents too long for a single LLM context window.

    Strategy: Map-Reduce
    1. CHUNK: Split doc into overlapping chunks
    2. MAP: Ask LLM to extract relevant info from each chunk
    3. REDUCE: Ask LLM to synthesize all chunk answers into final answer

    Supports: plain text, PDF (via PyPDF2), code files, markdown.
    """

    def __init__(self, llm_call_fn: Callable[[str, str], str],
                 chunk_size: int = 3000, overlap: int = 300,
                 max_chunks: int = 20):
        """
        llm_call_fn(system_prompt, user_prompt) → response_str
        chunk_size: characters per chunk
        overlap: overlap between consecutive chunks (context continuity)
        """
        self.llm         = llm_call_fn
        self.chunk_size  = chunk_size
        self.overlap     = overlap
        self.max_chunks  = max_chunks

    # ── INGESTION ──────────────────────────────────────────────────────────────

    def ingest_text(self, text: str) -> List[str]:
        """Split plain text into overlapping chunks."""
        chunks = []
        step   = self.chunk_size - self.overlap
        for i in range(0, len(text), step):
            chunk = text[i:i + self.chunk_size]
            if chunk.strip():
                chunks.append(chunk)
            if len(chunks) >= self.max_chunks:
                break
        return chunks

    def ingest_file(self, filepath: str) -> List[str]:
        """Ingest a file and return chunks."""
        ext = os.path.splitext(filepath)[1].lower()

        if ext == ".pdf":
            return self._ingest_pdf(filepath)
        elif ext in (".py", ".js", ".ts", ".jsx", ".java", ".cpp", ".c", ".go"):
            return self._ingest_code(filepath)
        else:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                return self.ingest_text(f.read())

    def _ingest_pdf(self, path: str) -> List[str]:
        try:
            from pypdf import PdfReader
            reader = PdfReader(path)
            text   = "\n".join(p.extract_text() or "" for p in reader.pages)
            return self.ingest_text(text)
        except ImportError:
            return [f"[PDF] pypdf not installed. pip install pypdf"]
        except Exception as e:
            return [f"[PDF] Error reading {path}: {e}"]

    def _ingest_code(self, path: str) -> List[str]:
        """Code files: chunk by function/class boundary when possible."""
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        # Simple split: every N lines, preferring blank line boundaries
        chunk_lines = max(50, self.chunk_size // 80)
        chunks, buf = [], []
        for i, line in enumerate(lines):
            buf.append(line)
            if len(buf) >= chunk_lines and (not line.strip() or i == len(lines)-1):
                chunks.append("".join(buf))
                buf = buf[-10:]    # small overlap for context
                if len(chunks) >= self.max_chunks:
                    break
        if buf:
            chunks.append("".join(buf))
        return chunks

    # ── MAP ────────────────────────────────────────────────────────────────────

    def map_chunk(self, chunk: str, question: str, chunk_num: int, total: int) -> str:
        system = (
            "You are extracting relevant information from a document chunk. "
            "Be concise. Only include what's relevant to the question. "
            "If this chunk has no relevant info, say 'No relevant info in this section.'"
        )
        user = (
            f"Document chunk {chunk_num}/{total}:\n\n{chunk}\n\n"
            f"Question: {question}\n\n"
            f"What's relevant to the question in this chunk? Be concise."
        )
        try:
            return self.llm(system, user)
        except Exception as e:
            return f"[Error processing chunk {chunk_num}: {e}]"

    # ── REDUCE ─────────────────────────────────────────────────────────────────

    def reduce(self, question: str, chunk_answers: List[str]) -> str:
        combined = "\n\n---\n\n".join(
            f"[Section {i+1}]: {ans}"
            for i, ans in enumerate(chunk_answers)
            if "No relevant info" not in ans
        )
        if not combined.strip():
            return "No relevant information was found in the document."

        system = (
            "You are synthesizing information from multiple document sections "
            "into a single, comprehensive, well-organized answer. "
            "Cite section numbers when relevant."
        )
        user = (
            f"Question: {question}\n\n"
            f"Information from document sections:\n\n{combined}\n\n"
            f"Provide a complete, organized answer."
        )
        try:
            return self.llm(system, user)
        except Exception as e:
            return f"Synthesis error: {e}"

    # ── FULL PIPELINE ──────────────────────────────────────────────────────────

    def ask(self, text_or_path: str, question: str,
            progress_callback: Callable = None) -> Dict:
        """
        Full map-reduce pipeline.
        text_or_path: file path or raw text string
        question: what to answer about the document
        progress_callback(done, total): optional progress updates
        """
        # Ingest
        if os.path.exists(text_or_path):
            chunks = self.ingest_file(text_or_path)
            source = os.path.basename(text_or_path)
        else:
            chunks = self.ingest_text(text_or_path)
            source = "text input"

        if not chunks:
            return {"success": False, "error": "No content to process"}

        total = len(chunks)

        # Map phase
        chunk_answers = []
        for i, chunk in enumerate(chunks, 1):
            answer = self.map_chunk(chunk, question, i, total)
            chunk_answers.append(answer)
            if progress_callback:
                progress_callback(i, total)

        # Reduce phase
        final_answer = self.reduce(question, chunk_answers)

        return {
            "success":       True,
            "question":      question,
            "source":        source,
            "chunks_read":   total,
            "answer":        final_answer,
            "chunk_answers": chunk_answers,
        }

    def summarize(self, text_or_path: str) -> Dict:
        """Summarize a document without a specific question."""
        return self.ask(text_or_path, "Summarize the main points and key information in this document.")

    def extract_todos(self, text_or_path: str) -> Dict:
        """Extract action items / TODOs from a document."""
        return self.ask(text_or_path, "List all action items, TODO items, tasks, and things that need to be done.")


# =============================================================================
# MODULE-LEVEL SINGLETONS
# =============================================================================

_interrupt_engine  = InterruptEngine()
_noise_canceller   = NoiseCanceller()

def get_interrupt_engine() -> InterruptEngine:
    return _interrupt_engine

def get_noise_canceller() -> NoiseCanceller:
    return _noise_canceller

def interrupt_speech():
    _interrupt_engine.interrupt()

def is_ultron_speaking() -> bool:
    return _interrupt_engine.is_speaking()

def clean_audio(audio_bytes: bytes, fmt: str = "wav") -> bytes:
    return _noise_canceller.clean_bytes(audio_bytes, fmt)

def make_long_doc_reasoner(llm_call_fn: Callable) -> LongDocReasoner:
    return LongDocReasoner(llm_call_fn)
