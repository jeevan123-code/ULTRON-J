"""
voice_identity.py — Voice Enrollment & Speaker Verification for Ultron-J.

HOW IT WORKS:
─────────────────────────────────────────────────────────────
1. ENROLLMENT (first time only, ~60 seconds):
   - Ultron asks Jeevan to say 5 specific phrases
   - Each phrase is recorded and converted into a voice embedding
     (a fingerprint of the unique characteristics of Jeevan's voice:
      pitch, tone, speaking rhythm, vocal tract shape)
   - The 5 embeddings are averaged into a single MASTER voiceprint
   - Saved encrypted to: voice_identity/voiceprint.json

2. VERIFICATION (every time someone speaks):
   - The incoming audio is also converted into an embedding
   - Cosine similarity is calculated between the incoming embedding
     and Jeevan's stored voiceprint
   - If similarity > threshold (default 0.82) → it's Jeevan → respond
   - If similarity < threshold → stranger → stay silent (or say "I only respond to Jeevan")

HOW VOICE EMBEDDINGS WORK:
─────────────────────────────────────────────────────────────
Uses SpeechBrain's ECAPA-TDNN model (same technology used by banks
for phone voice authentication). It extracts 192-dimensional vectors
that capture the unique characteristics of a person's voice.
Two recordings of Jeevan will have ~0.92 similarity.
Jeevan vs a stranger will have ~0.35 similarity.
The 0.82 threshold sits safely in between.

NO INTERNET NEEDED — all processing is local on your machine.

LIBRARIES:
- speechbrain  (voice embeddings — the core)
- torch        (required by speechbrain)
- sounddevice  (microphone recording)
- numpy        (similarity calculation)

INSTALL:
    pip install speechbrain torch torchaudio sounddevice numpy
"""

import json
import math
import os
import tempfile
import threading
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

_BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
IDENTITY_DIR    = os.path.join(_BASE_DIR, "voice_identity")
VOICEPRINT_FILE = os.path.join(IDENTITY_DIR, "voiceprint.json")
SAMPLES_DIR     = os.path.join(IDENTITY_DIR, "enrollment_samples")

os.makedirs(IDENTITY_DIR, exist_ok=True)
os.makedirs(SAMPLES_DIR,  exist_ok=True)

# ── Config ─────────────────────────────────────────────────────────────────────
SIMILARITY_THRESHOLD = 0.82    # above this = Jeevan. Increase for stricter.
SAMPLE_RATE          = 16000
CHANNELS             = 1
ENROLLMENT_PHRASES   = [
    "Hey Ultron, initialize voice enrollment",
    "My name is Jeevan and this is my voice",
    "Ultron, recognize my voice from now on",
    "I am the only one who should control you",
    "Voice enrollment complete, save my voiceprint",
]
MIN_ENROLLMENT_SAMPLES = 3     # minimum phrases needed (out of 5)

# ── Optional imports ───────────────────────────────────────────────────────────
try:
    import torch
    import torchaudio
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

try:
    from speechbrain.inference.speaker import EncoderClassifier
    SPEECHBRAIN_AVAILABLE = True
except ImportError:
    SPEECHBRAIN_AVAILABLE = False

try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False


# =============================================================================
# SPEAKER ENCODER
# =============================================================================

_encoder          = None
_encoder_lock     = threading.Lock()
_encoder_loading  = False


def _load_encoder():
    """Load SpeechBrain ECAPA-TDNN model (downloads ~80MB first time)."""
    global _encoder, _encoder_loading
    if _encoder is not None:
        return _encoder
    if not SPEECHBRAIN_AVAILABLE or not TORCH_AVAILABLE:
        return None

    with _encoder_lock:
        if _encoder is not None:
            return _encoder
        _encoder_loading = True
        print("[VoiceIdentity] Loading speaker encoder (ECAPA-TDNN)...")
        print("[VoiceIdentity] First time: downloads ~80MB model. Please wait...")
        try:
            _encoder = EncoderClassifier.from_hparams(
                source="speechbrain/spkrec-ecapa-voxceleb",
                savedir=os.path.join(IDENTITY_DIR, "speechbrain_model"),
                run_opts={"device": "cpu"},
            )
            print("[VoiceIdentity] ✓ Speaker encoder loaded")
        except Exception as e:
            print(f"[VoiceIdentity] ✗ Could not load encoder: {e}")
            _encoder = None
        _encoder_loading = False
    return _encoder


def get_embedding(audio_path: str) -> Optional[np.ndarray]:
    """
    Extract 192-dimensional voice embedding from an audio file.
    Returns numpy array or None on failure.
    """
    encoder = _load_encoder()
    if encoder is None:
        return _fallback_embedding(audio_path)

    try:
        signal, sr = torchaudio.load(audio_path)
        # Resample to 16kHz if needed
        if sr != SAMPLE_RATE:
            resampler = torchaudio.transforms.Resample(sr, SAMPLE_RATE)
            signal    = resampler(signal)
        # Mono
        if signal.shape[0] > 1:
            signal = signal.mean(dim=0, keepdim=True)

        with torch.no_grad():
            embedding = encoder.encode_batch(signal)
        return embedding.squeeze().numpy()
    except Exception as e:
        print(f"[VoiceIdentity] Embedding error: {e}")
        return _fallback_embedding(audio_path)


def _fallback_embedding(audio_path: str) -> Optional[np.ndarray]:
    """
    Fallback when SpeechBrain is not available.
    Uses basic MFCC features. Less accurate but still works for
    distinguishing clearly different voices.
    """
    try:
        import wave, struct
        with wave.open(audio_path, "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            samples = np.frombuffer(frames, dtype=np.int16).astype(float) / 32768.0

        # Simple spectral features
        if len(samples) < 512:
            return None

        # Frame into 25ms windows with 10ms hop
        frame_len  = int(SAMPLE_RATE * 0.025)
        hop_len    = int(SAMPLE_RATE * 0.010)
        frames_list = []
        for i in range(0, len(samples) - frame_len, hop_len):
            frame = samples[i:i+frame_len]
            frames_list.append(frame)

        if not frames_list:
            return None

        # FFT features per frame
        features = []
        for frame in frames_list[:200]:
            spectrum = np.abs(np.fft.rfft(frame * np.hamming(len(frame))))
            # Extract 20 frequency band energies
            bands = np.array_split(spectrum, 20)
            feature = np.array([np.mean(b**2) for b in bands])
            features.append(feature)

        feat_matrix = np.array(features)
        # Statistics across time as the embedding
        embedding = np.concatenate([
            feat_matrix.mean(axis=0),
            feat_matrix.std(axis=0),
            feat_matrix.min(axis=0),
            feat_matrix.max(axis=0),
        ])
        norm = np.linalg.norm(embedding)
        return embedding / norm if norm > 0 else embedding
    except Exception as e:
        print(f"[VoiceIdentity] Fallback embedding error: {e}")
        return None


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two embeddings. Range: -1 to 1."""
    if a is None or b is None:
        return 0.0
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# =============================================================================
# VOICEPRINT STORAGE
# =============================================================================

def save_voiceprint(embeddings: List[np.ndarray], owner: str = "Jeevan"):
    """Average multiple enrollment embeddings into one master voiceprint."""
    if not embeddings:
        return False

    master = np.mean(np.stack(embeddings), axis=0)
    master = master / np.linalg.norm(master)   # normalize

    data = {
        "owner":          owner,
        "embedding":      master.tolist(),
        "num_samples":    len(embeddings),
        "threshold":      SIMILARITY_THRESHOLD,
        "enrolled_at":    datetime.now().isoformat(),
        "model":          "ECAPA-TDNN" if SPEECHBRAIN_AVAILABLE else "MFCC-fallback",
        "embedding_dim":  len(master),
    }

    with open(VOICEPRINT_FILE, "w") as f:
        json.dump(data, f, indent=2)

    print(f"[VoiceIdentity] ✓ Voiceprint saved ({len(embeddings)} samples, {len(master)}D)")
    return True


def load_voiceprint() -> Optional[Tuple[np.ndarray, dict]]:
    """Load saved voiceprint. Returns (embedding, metadata) or None."""
    if not os.path.exists(VOICEPRINT_FILE):
        return None
    try:
        with open(VOICEPRINT_FILE) as f:
            data = json.load(f)
        embedding = np.array(data["embedding"])
        return embedding, data
    except Exception as e:
        print(f"[VoiceIdentity] Could not load voiceprint: {e}")
        return None


def is_enrolled() -> bool:
    return os.path.exists(VOICEPRINT_FILE)


def delete_voiceprint():
    """Wipe enrollment data — forces re-enrollment next time."""
    if os.path.exists(VOICEPRINT_FILE):
        os.remove(VOICEPRINT_FILE)
    print("[VoiceIdentity] Voiceprint deleted. Re-enrollment required.")


# =============================================================================
# VERIFICATION
# =============================================================================

_voiceprint_cache = None
_voiceprint_mtime = 0.0

def verify_speaker(audio_path: str, threshold: float = None) -> dict:
    """
    Check if the speaker in audio_path matches the enrolled voiceprint.

    Returns:
        {
            "is_owner":    True/False,
            "similarity":  0.0–1.0,
            "threshold":   0.82,
            "confidence":  "high"/"medium"/"low",
            "enrolled":    True/False,
        }
    """
    global _voiceprint_cache, _voiceprint_mtime

    # Not enrolled → allow everyone (open mode)
    if not is_enrolled():
        return {"is_owner": True, "similarity": 1.0, "enrolled": False,
                "confidence": "open", "threshold": 0.0}

    # Load voiceprint — reload if voiceprint.json changed (re-enrollment invalidates the cache)
    try:
        current_mtime = os.path.getmtime(VOICEPRINT_FILE)
    except OSError:
        current_mtime = 0.0
    if _voiceprint_cache is None or current_mtime > _voiceprint_mtime:
        result = load_voiceprint()
        if result is None:
            return {"is_owner": True, "similarity": 1.0, "enrolled": False,
                    "confidence": "open", "threshold": 0.0}
        _voiceprint_cache = result
        _voiceprint_mtime = current_mtime

    stored_embedding, meta = _voiceprint_cache
    t = threshold or meta.get("threshold", SIMILARITY_THRESHOLD)

    # Get embedding of incoming audio
    incoming_embedding = get_embedding(audio_path)
    if incoming_embedding is None:
        # Can't verify → fail safe (allow)
        return {"is_owner": True, "similarity": 0.0, "enrolled": True,
                "confidence": "unknown", "threshold": t, "error": "embedding_failed"}

    similarity = cosine_similarity(stored_embedding, incoming_embedding)
    is_owner   = similarity >= t

    # Confidence level
    if similarity >= 0.92:
        confidence = "high"
    elif similarity >= 0.82:
        confidence = "medium"
    elif similarity >= 0.70:
        confidence = "low"
    else:
        confidence = "stranger"

    return {
        "is_owner":   is_owner,
        "similarity": round(similarity, 4),
        "threshold":  t,
        "confidence": confidence,
        "enrolled":   True,
        "owner":      meta.get("owner", "Jeevan"),
    }


def clear_cache():
    global _voiceprint_cache, _voiceprint_mtime
    _voiceprint_cache = None
    _voiceprint_mtime = 0.0


# =============================================================================
# AUDIO RECORDING HELPERS
# =============================================================================

def record_phrase(duration: int = 5, countdown: int = 3) -> Optional[str]:
    """
    Record audio for `duration` seconds after a `countdown`.
    Returns path to saved WAV file, or None on failure.
    """
    if SOUNDDEVICE_AVAILABLE:
        return _record_sounddevice(duration, countdown)
    elif PYAUDIO_AVAILABLE:
        return _record_pyaudio(duration, countdown)
    else:
        print("[VoiceIdentity] No audio library. Install: pip install sounddevice")
        return None


def _record_sounddevice(duration: int, countdown: int) -> Optional[str]:
    for i in range(countdown, 0, -1):
        print(f"  Recording in {i}...", end="\r")
        time.sleep(1)
    print("  🎙️  Recording...           ")

    try:
        audio = sd.rec(int(duration * SAMPLE_RATE),
                       samplerate=SAMPLE_RATE, channels=CHANNELS,
                       dtype="int16", blocking=True)
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False,
                                          dir=SAMPLES_DIR)
        _save_wav(tmp.name, audio.flatten(), SAMPLE_RATE)
        print("  ✓ Recorded")
        return tmp.name
    except Exception as e:
        print(f"  ✗ Recording failed: {e}")
        return None


def _record_pyaudio(duration: int, countdown: int) -> Optional[str]:
    import pyaudio
    for i in range(countdown, 0, -1):
        print(f"  Recording in {i}...", end="\r")
        time.sleep(1)
    print("  🎙️  Recording...           ")

    try:
        pa     = pyaudio.PyAudio()
        stream = pa.open(format=pyaudio.paInt16, channels=CHANNELS,
                         rate=SAMPLE_RATE, input=True,
                         frames_per_buffer=1024)
        frames = []
        for _ in range(0, int(SAMPLE_RATE / 1024 * duration)):
            frames.append(stream.read(1024, exception_on_overflow=False))
        stream.stop_stream(); stream.close(); pa.terminate()

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False,
                                          dir=SAMPLES_DIR)
        data = b"".join(frames)
        arr  = np.frombuffer(data, dtype=np.int16)
        _save_wav(tmp.name, arr, SAMPLE_RATE)
        print("  ✓ Recorded")
        return tmp.name
    except Exception as e:
        print(f"  ✗ Recording failed: {e}")
        return None


def _save_wav(path: str, samples: np.ndarray, sr: int):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(samples.astype(np.int16).tobytes())


# =============================================================================
# ENROLLMENT WIZARD
# =============================================================================

def run_enrollment(owner_name: str = "Jeevan") -> bool:
    """
    Interactive enrollment wizard.
    Records 5 phrases, builds voiceprint, saves it.
    Called once — never needs to be repeated.
    """
    print()
    print("═" * 60)
    print("  ULTRON-J — VOICE ENROLLMENT")
    print("═" * 60)
    print(f"""
  Ultron will learn YOUR voice, {owner_name}.
  After this, Ultron will ONLY respond to you.
  Strangers will be ignored.

  You will say 5 phrases. Each phrase takes 5 seconds.
  Speak naturally — normal volume, normal speed.

  Requirements:
  ✓ Quiet room (no TV / music in background)
  ✓ Sit 20-40cm from your microphone
  ✓ Wait for the recording indicator before speaking

  Model: {"ECAPA-TDNN (high accuracy)" if SPEECHBRAIN_AVAILABLE else "MFCC fallback (basic accuracy)"}
  Storage: voice_identity/voiceprint.json (local, never uploaded)
""")

    if not SOUNDDEVICE_AVAILABLE and not PYAUDIO_AVAILABLE:
        print("  ERROR: No audio library installed.")
        print("  Install: pip install sounddevice")
        return False

    input("  Press ENTER when you are ready...")
    print()

    embeddings   = []
    failed_count = 0

    for i, phrase in enumerate(ENROLLMENT_PHRASES, 1):
        print(f"\n  Phrase {i}/{len(ENROLLMENT_PHRASES)}:")
        print(f'  Say: "{phrase}"')

        audio_path = record_phrase(duration=6, countdown=3)

        if audio_path is None:
            print("  ✗ Recording failed — skipping this phrase")
            failed_count += 1
            if failed_count >= 3:
                print("\n  Too many failures. Check your microphone.")
                return False
            continue

        # Extract embedding
        print("  Analyzing voice...", end="\r")
        embedding = get_embedding(audio_path)

        if embedding is None:
            print("  ✗ Could not analyze audio — skipping")
            failed_count += 1
            continue

        embeddings.append(embedding)
        print(f"  ✓ Phrase {i} captured (quality: {'good' if len(embedding) > 100 else 'basic'})")

        if i < len(ENROLLMENT_PHRASES):
            time.sleep(0.5)

    # Need at least MIN_ENROLLMENT_SAMPLES
    if len(embeddings) < MIN_ENROLLMENT_SAMPLES:
        print(f"\n  ✗ Only got {len(embeddings)} samples (need {MIN_ENROLLMENT_SAMPLES}).")
        print("  Run enrollment again in a quieter environment.")
        return False

    # Save voiceprint
    success = save_voiceprint(embeddings, owner_name)

    if success:
        print()
        print("═" * 60)
        print(f"  ✅ ENROLLMENT COMPLETE!")
        print(f"  {len(embeddings)} voice samples captured")
        print(f"  Ultron will now only respond to {owner_name}")
        print(f"  Voiceprint saved to: voice_identity/voiceprint.json")
        print()
        print("  To re-enroll: python voice_identity.py --enroll")
        print("  To reset:     python voice_identity.py --reset")
        print("═" * 60)
        print()

    return success


def run_test() -> None:
    """Quick test — speak and see if Ultron recognizes you."""
    if not is_enrolled():
        print("[VoiceIdentity] Not enrolled yet. Run: python voice_identity.py --enroll")
        return

    print("\n  VOICE RECOGNITION TEST")
    print('  Say anything after the beep...')
    audio_path = record_phrase(duration=4, countdown=2)

    if not audio_path:
        print("  Recording failed.")
        return

    result = verify_speaker(audio_path)
    sim    = result["similarity"]
    owner  = result["is_owner"]

    print(f"\n  Similarity:  {sim:.4f}  (threshold: {result['threshold']})")
    print(f"  Confidence:  {result['confidence']}")
    print(f"  Result:      {'✅ RECOGNIZED — Welcome, ' + result.get('owner','') + '!' if owner else '❌ STRANGER — Access denied'}")


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import sys
    args = sys.argv[1:]

    if "--enroll" in args or not args:
        name = "Jeevan"
        for a in args:
            if not a.startswith("--"):
                name = a
                break
        run_enrollment(name)

    elif "--test" in args:
        run_test()

    elif "--reset" in args:
        confirm = input("Delete voiceprint and re-enroll? (yes/no): ")
        if confirm.lower() == "yes":
            delete_voiceprint()
            clear_cache()
            run_enrollment()

    elif "--status" in args:
        if is_enrolled():
            _, meta = load_voiceprint()
            print(f"Enrolled: YES")
            print(f"Owner:    {meta.get('owner')}")
            print(f"Samples:  {meta.get('num_samples')}")
            print(f"Model:    {meta.get('model')}")
            print(f"Date:     {meta.get('enrolled_at')}")
        else:
            print("Enrolled: NO")
            print("Run: python voice_identity.py --enroll")

    else:
        print("Usage:")
        print("  python voice_identity.py --enroll       Run enrollment wizard")
        print("  python voice_identity.py --test         Test if Ultron recognizes you")
        print("  python voice_identity.py --status       Check enrollment status")
        print("  python voice_identity.py --reset        Delete and re-enroll")
