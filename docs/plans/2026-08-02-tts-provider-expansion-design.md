# TTS provider expansion (kokoro, espeak fallback, OmniVoice) — design

**Date:** 2026-08-02
**Status:** approved, awaiting implementation plan
**Branch:** `phase13-strict-validation` (design written after `b50e480`)

## Problem

Live audit on 2026-08-02 confirmed Ultron's `auto` TTS chain
(`voice_engine.py::tts`, code order: chatterbox → piper → kokoro →
elevenlabs → openai → edge) has only one working link: **edge**.

- `piper-tts` is in `requirements.txt:99` but not installed; `piper_voices/`
  doesn't exist.
- `kokoro-onnx` is not installed; `kokoro-v1.0.onnx` / `voices-v1.0.bin`
  were never downloaded.
- No `ELEVENLABS_API_KEY` / `OPENAI_API_KEY` in `.env`.
- Chatterbox sidecar (`.venv-chatterbox/`) is built but the flag is off, and
  it's independently confirmed unable to run on this hardware (RAM wall,
  see `CHATTERBOX_README.md` / project memory).

So Ultron currently speaks 100% via Microsoft's cloud, with zero offline
fallback. Separately, the laptop has speech-related software installed that
was never connected: system `espeak-ng` (library only, no CLI), and an
unrelated cloned repo `/home/jeevan/repo-tests/OmniVoice/` (k2-fsa
OmniVoice, zero-shot voice cloning, 600+ languages) with a fully populated
`.venv` that has never been run.

User decision (2026-08-02): restore kokoro, add an espeak-ng offline
last-resort fallback, and test-then-maybe-wire OmniVoice. Piper restoration
was explicitly *not* selected — out of scope for this pass.

## What already exists (reuse, don't rewrite)

| Piece | Where | Status |
|---|---|---|
| Provider chain builder + fallback loop | `voice_engine.py::tts` (~L479-563) | Works, extend in place |
| Per-provider synth functions | `voice_engine.py::_tts_{elevenlabs,openai,edge,piper,kokoro,chatterbox}` | Pattern to follow for `_tts_espeak` |
| Local-provider availability flags | `PIPER_AVAILABLE`, `KOKORO_AVAILABLE` (try/import at module load) | Pattern to follow for `ESPEAK_AVAILABLE` |
| Kokoro getter + model paths | `_get_kokoro()`, `_KOKORO_ONNX_PATH`, `_KOKORO_VOICES_PATH` | Already correct, just needs the package + files |
| Warmup pre-loading | `warmup_tts()` | Already warms kokoro; no change needed |
| Isolated cross-venv sidecar pattern | `.venv-chatterbox/`, `chatterbox_sidecar.py`, `_tts_chatterbox` HTTP client, `ULTRON_TTS_CHATTERBOX` flag, `ULTRON_CHATTERBOX_URL` override | Template to clone for OmniVoice |
| Cross-venv orphan allowance | `orphan_guard.ALLOWED_ORPHANS` (contains `chatterbox_sidecar`) | Add `omnivoice_sidecar` here too |
| Subprocess hardening convention | `voice_commands_upgrade.py`, `intent_router.py` (2026-07-03/07-26 fixes: list-form argv, no `shell=True`) | Must follow for `_tts_espeak` |

## Component 1 — Restore kokoro (ops only, no code change)

`pip install kokoro-onnx soundfile` into `ULTRON_WEB/.venv`. Download
`kokoro-v1.0.onnx` + `voices-v1.0.bin` into the project root (paths are
already hardcoded). `KOKORO_AVAILABLE` flips true automatically on next
import; the auto chain already includes `"kokoro"` right after `"piper"`.

No source change. Verification is the only "test": `warmup_tts()` logs
`Kokoro pre-warmed`, and a direct `tts("test text", provider="kokoro")`
call returns bytes with `provider == "kokoro"`.

## Component 2 — espeak-ng offline last-resort fallback

`sudo apt install espeak-ng` gives the CLI binary (the currently-installed
`libespeak-ng1` is a shared library only, has no executable, and `spd-say`
speaks straight to the system audio device rather than returning bytes —
neither can serve Ultron's browser-playback pipeline as-is).

New code in `voice_engine.py`:

```python
import shutil
ESPEAK_AVAILABLE = shutil.which("espeak-ng") is not None

def _tts_espeak(text: str, mood: str) -> bytes:
    if not ESPEAK_AVAILABLE:
        raise RuntimeError("espeak-ng not installed")
    rate = VOICE_SPEAKING_RATES.get(mood, 1.0)
    wpm = int(175 * rate)  # espeak default ~175wpm baseline
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        subprocess.run(
            ["espeak-ng", "-v", "en-us", "-s", str(wpm), "-w", tmp_path,
             text[:VOICE_MAX_TTS_CHARS]],
            check=True, capture_output=True, timeout=15,
        )
        return Path(tmp_path).read_bytes()
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
```

List-form `argv`, no `shell=True` — matches the hardening convention
already applied elsewhere in this codebase.

**Chain placement — after edge, in both code paths of `tts()`:**
- auto mode: `chain.append("edge")` then, if `ESPEAK_AVAILABLE`,
  `chain.append("espeak")`
- explicit-provider override: `chain = [provider, "edge"]` becomes
  `chain = [provider, "edge"] + (["espeak"] if ESPEAK_AVAILABLE else [])`

This makes espeak fire only when edge itself fails (e.g. no network) —
the true last resort, so Ultron never goes fully silent.

**Tests (TDD order):** failing test asserting `_tts_espeak` returns bytes
starting with `b"RIFF"` (valid WAV) → confirm fails (function doesn't
exist) → implement → confirm passes. Second test asserts chain order
places `"espeak"` after `"edge"` when `ESPEAK_AVAILABLE` is patched `True`.

## Component 3 — OmniVoice: test before wiring, not wire-then-hope

Chatterbox OOM'd this exact machine (7.6GB RAM, CPU-only, no swap
headroom) after being wired in on faith. OmniVoice does not get the same
treatment.

### Step A — isolated RAM-safety probe (no Ultron code touched yet)

A standalone script run directly inside
`/home/jeevan/repo-tests/OmniVoice/.venv` (not as a server, not attached to
Ultron): load the model, synthesize one short sentence, while a parallel
watcher thread samples `/proc/meminfo` (available RAM, swap used) every 2s.

**Hard kill-switches** (the chatterbox postmortem showed 216s of thrashing
before manual intervention — this must self-abort far faster):
- swap usage > 70% → kill immediately
- available RAM < 500MB → kill immediately
- wall-clock > 120s without completion → kill

Result (pass/fail + measured peak RSS/swap) is reported before any wiring
work starts.

### Step B — only if Step A passes: wire as an isolated opt-in sidecar

Exact structural clone of the chatterbox integration:
- `omnivoice_sidecar.py` (stdlib HTTP server, own port — `17581`, chatterbox
  already owns `17580`) running inside OmniVoice's own `.venv`
- `_tts_omnivoice(text, mood) -> bytes` HTTP client in `voice_engine.py`
- Flag `ULTRON_TTS_OMNIVOICE=1` (default OFF), `ULTRON_OMNIVOICE_URL`
  override (default `http://127.0.0.1:17581`)
- Chain placement: front of the auto chain, same opt-in slot logic as
  chatterbox (`if os.environ.get("ULTRON_TTS_OMNIVOICE") == "1":
  chain.append("omnivoice")` ahead of the chatterbox check) — falls
  through to the rest of the chain on any sidecar failure so Ultron never
  goes silent because of it
- `orphan_guard.ALLOWED_ORPHANS` gets `omnivoice_sidecar` added (same
  reason as chatterbox: it lives in a different venv, unimportable by
  design)
- Tests mirror the chatterbox suite: a real `ThreadingHTTPServer` +
  real `requests.post` contract test, plus a deliberately-broken-path
  test (`/generate` → wrong path) proving the test actually has teeth

### Step C — only if Step A fails

Document as CANNOT RUN LOCALLY, same verdict class as chatterbox. No
`voice_engine.py` changes for OmniVoice. `.venv` stays in place — same
precedent as chatterbox, where `ULTRON_CHATTERBOX_URL` can point at a
remote machine; `ULTRON_OMNIVOICE_URL` would offer the same escape hatch
later if desired.

## Out of scope

- Piper restoration (explicitly deferred by user decision)
- Any change to the STT chain
- Any change to `smart_memory`/mem0 (unrelated dormant item, tracked
  separately)

## Risks

- espeak-ng CLI install is a `sudo apt` system change — approved by user,
  small standard package, trivially removable
- OmniVoice may fail Step A exactly like chatterbox did; that is a valid,
  fully-anticipated outcome, not a plan failure
- Torch version mismatch between Ultron's `.venv` (2.12.0) and OmniVoice's
  `.venv` (2.13.0+cpu) is why OmniVoice stays sidecar-isolated rather than
  installed into the main venv, even though numpy already matches (2.4.6)
