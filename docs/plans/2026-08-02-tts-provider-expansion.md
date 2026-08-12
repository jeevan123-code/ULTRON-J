# TTS Provider Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore kokoro as a working local TTS provider, add an espeak-ng offline last-resort fallback so Ultron never goes fully silent, and safely determine (before writing any integration code) whether OmniVoice can run on this laptop as a third cloned-voice option alongside chatterbox.

**Architecture:** Kokoro is a pure dependency-restoration (the code path already exists in `voice_engine.py`). espeak-ng follows the exact same in-process provider-function pattern as `_tts_edge`/`_tts_piper`. OmniVoice follows the exact isolated-sidecar pattern already proven by chatterbox (`.venv-chatterbox` + `chatterbox_sidecar.py` + HTTP client) — but only gets built if a standalone RAM/swap safety probe proves the laptop can survive it, because chatterbox already OOM'd this exact machine once.

**Tech Stack:** Python 3, Flask (existing app), `kokoro-onnx` + `soundfile`, system `espeak-ng` CLI via `subprocess`, `omnivoice` package (isolated venv) + stdlib `http.server` sidecar + `requests` client, `pytest` + `unittest.mock`.

## Global Constraints

- Repo: `/home/jeevan/ULTRON_WEB`, branch `phase13-strict-validation`.
- Baseline: **1563 tests passing**, 0 failures (confirmed 2026-08-02 via `.venv/bin/python -m pytest tests/ --tb=no -q`). Every task must end with this number equal or higher, never lower.
- Always use `.venv/bin/python` (or `.venv/bin/pip`) for this repo — never bare `python`/`pip`. OmniVoice work uses `/home/jeevan/repo-tests/OmniVoice/.venv/bin/python` — never mix the two venvs.
- TDD: write the failing test, confirm it fails, write the minimal implementation, confirm it passes, commit. (Task 1's chain-order test is the one exception — see Task 1 note.)
- **Never** `git add -A` or `git add .` — stage explicit file paths only.
- **Never** restructure existing files — surgical edits at the cited line numbers only.
- No `shell=True` in any new `subprocess` call — this codebase had two prior security fixes (2026-07-03, 2026-07-26) specifically removing `shell=True`; use list-form argv.
- Commit message prefixes: `feat(...)`, `fix(...)`, `test(...)`, `docs(...)`, `chore(...)`.
- Design doc: `docs/plans/2026-08-02-tts-provider-expansion-design.md` — read it first for the full rationale.

---

## File Structure

| File | Change | Task |
|---|---|---|
| `.venv/` | install `kokoro-onnx`, `soundfile` | 1 |
| `kokoro-v1.0.onnx`, `voices-v1.0.bin` (project root) | download | 1 |
| `tests/test_tts_kokoro.py` | create | 1 |
| system package `espeak-ng` | `sudo apt install` | 2 |
| `voice_engine.py` | modify (imports, `ESPEAK_AVAILABLE`, `_tts_espeak`, chain wiring) | 2 |
| `tests/test_tts_espeak.py` | create | 2 |
| `/home/jeevan/repo-tests/OmniVoice/ram_safety_probe.py` | create | 3 |
| `omnivoice_sidecar.py` (ULTRON_WEB root) | create — **only if Task 3 passes** | 4 |
| `tests/test_omnivoice_sidecar.py` | create — **only if Task 3 passes** | 4 |
| `voice_engine.py` | modify (`_tts_omnivoice`, chain wiring) — **only if Task 3 passes** | 5 |
| `tests/test_tts_omnivoice.py` | create — **only if Task 3 passes** | 5 |
| `tests/test_omnivoice_integration.py` | create — **only if Task 3 passes** | 6 |
| `orphan_guard.py` | modify (`ALLOWED_ORPHANS`) — **only if Task 3 passes** | 6 |

---

## Task 1: Restore kokoro as a working local TTS provider

**Files:**
- Create: `tests/test_tts_kokoro.py`
- Modify: none in `voice_engine.py` — the chain-selection code at `voice_engine.py:528-529` (`if KOKORO_AVAILABLE: chain.append("kokoro")`) is already correct; it has just never had `kokoro-onnx` installed to exercise it.
- Ops: `.venv/` gets two new packages; two model files land in the project root.

**Interfaces:**
- Consumes: `ve.tts(text, mood="FOCUSED", provider="auto")` (existing, `voice_engine.py:479`), `ve.KOKORO_AVAILABLE` (existing module-level flag, `voice_engine.py:113`/`118`), `ve._tts_kokoro(text, mood)` (existing, `voice_engine.py:427`).
- Produces: nothing new for later tasks — this task is self-contained.

**Note on TDD ordering:** the chain-selection logic already exists and is already correct (nothing in `voice_engine.py` changes in this task), so the regression test below passes immediately on first run rather than failing-then-passing. That's expected — the goal is to close a real gap (no test currently locks down kokoro's chain placement; only `test_tts_chatterbox.py` forces it *off*) before installing the real dependency, not to drive new production code.

- [ ] **Step 1: Write the regression test locking down kokoro's chain placement**

Create `tests/test_tts_kokoro.py`:

```python
"""Kokoro TTS provider — local, offline, no API key required.

Restores the auto chain's second local option (after piper) now that
kokoro-onnx + the onnx/voices model files are installed. See
docs/plans/2026-08-02-tts-provider-expansion-design.md.
"""
import pytest

import voice_engine as ve


@pytest.fixture(autouse=True)
def _no_cache_deterministic_chain(monkeypatch):
    """Bypass the TTS cache and pin every other backend off, so the chain
    the test observes is the chain the code actually built."""
    monkeypatch.setattr(ve, "_get_cached", lambda *a, **k: None)
    monkeypatch.setattr(ve, "_set_cached", lambda *a, **k: None)
    monkeypatch.setattr(ve, "PIPER_AVAILABLE", False)
    monkeypatch.setattr(ve, "ELEVENLABS_API_KEY", "")
    monkeypatch.setattr(ve, "OPENAI_API_KEY", "")
    monkeypatch.delenv("ULTRON_TTS_CHATTERBOX", raising=False)


def test_kokoro_selected_when_available_and_nothing_ahead_of_it(monkeypatch):
    """With piper/elevenlabs/openai off, kokoro must win over edge."""
    monkeypatch.setattr(ve, "KOKORO_AVAILABLE", True)
    monkeypatch.setattr(ve, "_tts_kokoro", lambda t, m: b"KOKORO")
    monkeypatch.setattr(ve, "_tts_edge", lambda t, m: b"EDGE")

    audio, provider = ve.tts("hello", provider="auto")

    assert provider == "kokoro"
    assert audio == b"KOKORO"


def test_kokoro_absent_from_chain_when_not_installed(monkeypatch):
    """If kokoro-onnx / model files are missing, must not be attempted."""
    monkeypatch.setattr(ve, "KOKORO_AVAILABLE", False)
    called = []
    monkeypatch.setattr(
        ve, "_tts_kokoro", lambda t, m: called.append(t) or b"KOKORO")
    monkeypatch.setattr(ve, "_tts_edge", lambda t, m: b"EDGE")

    audio, provider = ve.tts("hello", provider="auto")

    assert provider == "edge"
    assert called == []
```

- [ ] **Step 2: Run the test and confirm it passes**

Run: `.venv/bin/python -m pytest tests/test_tts_kokoro.py -v`
Expected: 2 passed (this locks in existing correct behavior).

- [ ] **Step 3: Install the real dependencies**

```bash
.venv/bin/pip install kokoro-onnx soundfile
```

- [ ] **Step 4: Download the model files into the project root**

```bash
cd /home/jeevan/ULTRON_WEB
curl -L -o kokoro-v1.0.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -L -o voices-v1.0.bin https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```

Verify both files exist and are non-trivial in size (`ls -la kokoro-v1.0.onnx voices-v1.0.bin` — onnx is roughly 300MB+, voices roughly 25MB+). If the URLs 404 (release assets move), check the current release listing at `https://github.com/thewh1teagle/kokoro-onnx/releases` and substitute the correct asset URLs — the destination filenames must stay exactly `kokoro-v1.0.onnx` and `voices-v1.0.bin` since `voice_engine.py:115-116` hardcodes those names.

- [ ] **Step 5: Real functional verification (manual, not part of the pytest suite — too slow/heavy to run on every CI pass)**

```bash
.venv/bin/python -c "
import voice_engine as ve
audio, provider = ve.tts('This is a kokoro verification test.', provider='kokoro')
assert provider == 'kokoro'
assert len(audio) > 1000
print(f'OK: kokoro returned {len(audio)} bytes')
"
```

Expected output: `[VoiceEngine] Loading Kokoro model (one-time ~5s)...` followed by `OK: kokoro returned N bytes`.

- [ ] **Step 6: Run the full suite to confirm no regressions**

Run: `.venv/bin/python -m pytest tests/ --tb=no -q`
Expected: `1565 passed` (1563 baseline + 2 new).

- [ ] **Step 7: Commit**

```bash
git add tests/test_tts_kokoro.py
git commit -m "$(cat <<'EOF'
test(tts): lock down kokoro chain placement, restore it as a working provider

kokoro-onnx + soundfile installed, kokoro-v1.0.onnx + voices-v1.0.bin
downloaded to project root. The chain-selection code already existed and
was already correct — this closes the gap where nothing tested it.
EOF
)"
```

Note: `kokoro-v1.0.onnx` and `voices-v1.0.bin` are binary model files — check `.gitignore` before staging anything beyond the test file; if these aren't already ignored, do not add them to git (matches how `piper_voices/` was never committed either).

---

## Task 2: espeak-ng offline last-resort fallback

**Files:**
- Modify: `voice_engine.py:24-26` (imports), `voice_engine.py:123-135` (availability-flag block), after `voice_engine.py:294-313` (`_tts_edge`, new function goes right after it), `voice_engine.py:519-537` (chain construction), `voice_engine.py:540-555` (dispatch loop)
- Create: `tests/test_tts_espeak.py`

**Interfaces:**
- Consumes: `ve.VOICE_SPEAKING_RATES` (existing dict, mood → float multiplier), `ve.VOICE_MAX_TTS_CHARS` (existing int).
- Produces: `ve.ESPEAK_AVAILABLE: bool`, `ve._tts_espeak(text: str, mood: str) -> bytes` — both consumed only within this task; no downstream task depends on them.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tts_espeak.py`:

```python
"""espeak-ng — absolute last-resort offline TTS fallback.

Fires only when every other provider (including edge) has failed, e.g. no
network. Zero API key, zero model download — just the system espeak-ng
CLI, if installed. See docs/plans/2026-08-02-tts-provider-expansion-design.md.
"""
from unittest.mock import MagicMock
import pytest

import voice_engine as ve


@pytest.fixture(autouse=True)
def _no_cache_deterministic_chain(monkeypatch):
    monkeypatch.setattr(ve, "_get_cached", lambda *a, **k: None)
    monkeypatch.setattr(ve, "_set_cached", lambda *a, **k: None)
    monkeypatch.setattr(ve, "PIPER_AVAILABLE", False)
    monkeypatch.setattr(ve, "KOKORO_AVAILABLE", False)
    monkeypatch.setattr(ve, "ELEVENLABS_API_KEY", "")
    monkeypatch.setattr(ve, "OPENAI_API_KEY", "")
    monkeypatch.delenv("ULTRON_TTS_CHATTERBOX", raising=False)


def test_espeak_not_attempted_when_edge_succeeds(monkeypatch):
    """espeak is a last resort — a healthy edge must win first."""
    monkeypatch.setattr(ve, "ESPEAK_AVAILABLE", True)
    monkeypatch.setattr(ve, "_tts_edge", lambda t, m: b"EDGE")
    called = []
    monkeypatch.setattr(
        ve, "_tts_espeak", lambda t, m: called.append(t) or b"ESPEAK")

    audio, provider = ve.tts("hello", provider="auto")

    assert provider == "edge"
    assert audio == b"EDGE"
    assert called == []


def test_espeak_used_when_everything_else_fails(monkeypatch):
    """The never-silent guarantee: edge down + no local models -> espeak."""
    monkeypatch.setattr(ve, "ESPEAK_AVAILABLE", True)

    def _edge_down(t, m):
        raise RuntimeError("no network")

    monkeypatch.setattr(ve, "_tts_edge", _edge_down)
    monkeypatch.setattr(ve, "_tts_espeak", lambda t, m: b"ESPEAK")

    audio, provider = ve.tts("hello", provider="auto")

    assert provider == "espeak"
    assert audio == b"ESPEAK"


def test_espeak_absent_from_chain_when_binary_not_installed(monkeypatch):
    monkeypatch.setattr(ve, "ESPEAK_AVAILABLE", False)

    def _edge_down(t, m):
        raise RuntimeError("no network")

    monkeypatch.setattr(ve, "_tts_edge", _edge_down)
    called = []
    monkeypatch.setattr(
        ve, "_tts_espeak", lambda t, m: called.append(t) or b"ESPEAK")

    with pytest.raises(RuntimeError, match="All TTS providers failed"):
        ve.tts("hello", provider="auto")

    assert called == []


def test_espeak_appended_after_edge_for_explicit_provider_override(monkeypatch):
    """provider='piper' with piper failing must still fall through edge -> espeak."""
    monkeypatch.setattr(ve, "ESPEAK_AVAILABLE", True)

    def _piper_down(t, m):
        raise RuntimeError("piper not installed")

    def _edge_down(t, m):
        raise RuntimeError("no network")

    monkeypatch.setattr(ve, "_tts_piper", _piper_down)
    monkeypatch.setattr(ve, "_tts_edge", _edge_down)
    monkeypatch.setattr(ve, "_tts_espeak", lambda t, m: b"ESPEAK")

    audio, provider = ve.tts("hello", provider="piper")

    assert provider == "espeak"
    assert audio == b"ESPEAK"


def test_tts_espeak_invokes_cli_and_returns_wav_bytes(monkeypatch):
    """Real subprocess contract: espeak-ng writes a WAV via -w, we read it back."""
    monkeypatch.setattr(ve, "ESPEAK_AVAILABLE", True)

    def _fake_run(cmd, check, capture_output, timeout):
        wav_path = cmd[cmd.index("-w") + 1]
        with open(wav_path, "wb") as f:
            f.write(b"RIFF....WAVEfmt fake-espeak-audio")
        return MagicMock(returncode=0)

    monkeypatch.setattr(ve.subprocess, "run", _fake_run)

    audio = ve._tts_espeak("Hello there.", "FOCUSED")

    assert audio.startswith(b"RIFF")


def test_tts_espeak_uses_list_form_argv_no_shell(monkeypatch):
    """Hardening convention (2026-07-03/07-26 fixes): never shell=True."""
    monkeypatch.setattr(ve, "ESPEAK_AVAILABLE", True)
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        wav_path = cmd[cmd.index("-w") + 1]
        with open(wav_path, "wb") as f:
            f.write(b"RIFF")
        return MagicMock(returncode=0)

    monkeypatch.setattr(ve.subprocess, "run", _fake_run)

    ve._tts_espeak("hi", "FOCUSED")

    assert isinstance(captured["cmd"], list)
    assert captured["kwargs"].get("shell", False) is False


def test_tts_espeak_raises_when_binary_missing(monkeypatch):
    monkeypatch.setattr(ve, "ESPEAK_AVAILABLE", False)
    with pytest.raises(RuntimeError, match="espeak-ng not installed"):
        ve._tts_espeak("hi", "FOCUSED")
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `.venv/bin/python -m pytest tests/test_tts_espeak.py -v`
Expected: FAIL — `AttributeError: module 'voice_engine' has no attribute 'ESPEAK_AVAILABLE'` (and `_tts_espeak`).

- [ ] **Step 3: Install the espeak-ng CLI**

```bash
sudo apt install -y espeak-ng
command -v espeak-ng   # must print a path, e.g. /usr/bin/espeak-ng
```

- [ ] **Step 4: Add imports**

In `voice_engine.py`, the import block currently reads (lines 18-29):

```python
import asyncio
import base64
import hashlib
import json
import math
import os
import re
import tempfile
import threading
```

Change to:

```python
import asyncio
import base64
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
```

- [ ] **Step 5: Add the availability flag**

In `voice_engine.py`, immediately after the Piper block that currently ends at line 134 (`_PIPER_MODEL_PATH = ""`) and the following blank line 135, insert:

```python

# espeak-ng — absolute last-resort offline fallback. No API key, no model
# download, works with zero network — but robotic quality. Only ever fires
# if every provider ahead of it, including edge, has already failed.
ESPEAK_AVAILABLE = shutil.which("espeak-ng") is not None
```

- [ ] **Step 6: Add `_tts_espeak`**

In `voice_engine.py`, immediately after `_tts_edge` ends (currently line 313, the `pass` inside its `finally` block) and before the blank lines leading into `_get_piper` (line 316), insert:

```python


def _tts_espeak(text: str, mood: str) -> bytes:
    """espeak-ng — offline, zero-setup, absolute last resort.

    Only reached when every provider ahead of it (including edge) has
    already failed, e.g. no network and no local model installed.
    """
    if not ESPEAK_AVAILABLE:
        raise RuntimeError("espeak-ng not installed")
    rate = VOICE_SPEAKING_RATES.get(mood, 1.0)
    wpm = int(175 * rate)  # espeak-ng default baseline is ~175 wpm
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

- [ ] **Step 7: Wire it into the chain**

In `voice_engine.py`, the chain-construction block currently reads (lines 519-537):

```python
    if provider == "auto":
        chain = []
        # Cloned voice first when explicitly enabled — it is slower than the
        # rest, so it is opt-in and only chosen because it is *wanted*.
        if os.environ.get("ULTRON_TTS_CHATTERBOX") == "1":
            chain.append("chatterbox")
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
```

Change the last three lines to:

```python
        chain.append("edge")
        # Absolute last resort — only reached if edge itself failed too.
        if ESPEAK_AVAILABLE:
            chain.append("espeak")
    else:
        chain = [provider, "edge"]
        if ESPEAK_AVAILABLE:
            chain.append("espeak")
```

- [ ] **Step 8: Add the dispatch branch**

In `voice_engine.py`, the provider dispatch loop currently includes (around line 552):

```python
            elif prov == "edge":
                audio = _tts_edge(clean, mood)
```

Add a new branch immediately after it:

```python
            elif prov == "edge":
                audio = _tts_edge(clean, mood)
            elif prov == "espeak":
                audio = _tts_espeak(clean, mood)
```

- [ ] **Step 9: Run the tests and confirm they pass**

Run: `.venv/bin/python -m pytest tests/test_tts_espeak.py -v`
Expected: 7 passed.

- [ ] **Step 10: Manual real-CLI smoke test (not part of the automated suite)**

```bash
.venv/bin/python -c "
import voice_engine as ve
assert ve.ESPEAK_AVAILABLE, 'espeak-ng CLI not found on PATH'
audio = ve._tts_espeak('This is an espeak fallback test.', 'FOCUSED')
assert audio.startswith(b'RIFF')
print(f'OK: espeak returned {len(audio)} bytes')
"
```

- [ ] **Step 11: Run the full suite to confirm no regressions**

Run: `.venv/bin/python -m pytest tests/ --tb=no -q`
Expected: `1572 passed` (1565 after Task 1 + 7 new).

- [ ] **Step 12: Commit**

```bash
git add voice_engine.py tests/test_tts_espeak.py
git commit -m "$(cat <<'EOF'
feat(tts): add espeak-ng as the absolute last-resort offline fallback

Ultron currently goes fully silent if edge fails (no piper/kokoro
installed, no elevenlabs/openai keys). espeak-ng is zero-setup, already
present as a library on this machine, and needs only the CLI package.
Wired in after edge in both the auto chain and explicit-provider
override, so it only ever fires when everything else already has.
EOF
)"
```

---

## Task 3: OmniVoice RAM-safety probe (no Ultron code touched)

This step will consume significant RAM/CPU on the real machine for up to
~2 minutes. That is expected and intentional — the kill-switches bound the
worst case. Chatterbox previously thrashed this exact 7.6GB CPU-only
laptop to a near-halt (4.0GB RSS, swap fully exhausted, 216s before manual
kill) after being wired in without this kind of check first. This probe
must not repeat that mistake.

**Files:**
- Create: `/home/jeevan/repo-tests/OmniVoice/ram_safety_probe.py`

**Interfaces:**
- Consumes: nothing from this repo — runs entirely inside OmniVoice's own `.venv` (`omnivoice==0.2.1`, `torch==2.13.0+cpu`, already installed there).
- Produces: a PASS/FAIL verdict that gates Tasks 4-6. No function signatures are consumed by later tasks (only the verdict is).

- [ ] **Step 1: Write the probe script**

Create `/home/jeevan/repo-tests/OmniVoice/ram_safety_probe.py`:

```python
"""RAM/swap safety probe for OmniVoice on this laptop (7.6GB RAM,
CPU-only, no GPU). Chatterbox previously thrashed this exact machine
to a near-halt before being killed manually (~216s in, 4.0GB RSS,
swap fully exhausted). This script self-aborts fast instead of
waiting for a human to notice.

Run from the OmniVoice repo root, using OmniVoice's own venv:

    .venv/bin/python ram_safety_probe.py

It does NOT touch Ultron or voice_engine.py. Model load + one short
synthesis run in a child process; this script only watches
system-wide memory/swap and kills the child if a kill-switch trips.
"""
from __future__ import annotations

import subprocess
import sys
import time

SWAP_PCT_LIMIT = 0.70
MIN_AVAILABLE_MB = 500
WALLCLOCK_LIMIT_S = 120
POLL_INTERVAL_S = 2

_GENERATE_SNIPPET = """
import time
t0 = time.time()
import torch
from omnivoice import OmniVoice
model = OmniVoice.from_pretrained(
    "k2-fsa/OmniVoice", device_map="cpu", dtype=torch.float32,
)
print(f"[probe] model loaded in {time.time() - t0:.1f}s", flush=True)
audio = model.generate(
    text="This is a short safety probe sentence.", num_step=16,
)
print(f"[probe] generation complete in {time.time() - t0:.1f}s, "
      f"{len(audio[0])} samples", flush=True)
"""


def _read_meminfo() -> dict:
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, _, rest = line.partition(":")
            value_kb = int(rest.strip().split()[0])
            info[key] = value_kb
    return info


def _swap_fraction_used(info: dict) -> float:
    total = info.get("SwapTotal", 0)
    if total == 0:
        return 0.0
    free = info.get("SwapFree", 0)
    return (total - free) / total


def main() -> int:
    proc = subprocess.Popen(
        [sys.executable, "-c", _GENERATE_SNIPPET],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    start = time.time()
    peak_swap_pct = 0.0
    peak_used_mb = 0.0

    while True:
        ret = proc.poll()
        info = _read_meminfo()
        swap_pct = _swap_fraction_used(info)
        avail_mb = info.get("MemAvailable", 0) / 1024
        total_mb = info.get("MemTotal", 0) / 1024
        used_mb = total_mb - avail_mb
        peak_swap_pct = max(peak_swap_pct, swap_pct)
        peak_used_mb = max(peak_used_mb, used_mb)
        elapsed = time.time() - start

        if ret is not None:
            out = proc.stdout.read() if proc.stdout else ""
            if ret == 0:
                print(f"[probe] PASS in {elapsed:.1f}s — "
                      f"peak used {peak_used_mb:.0f}MB, "
                      f"peak swap {peak_swap_pct:.0%}")
                print(out)
                return 0
            print(f"[probe] FAIL — child exited {ret} after {elapsed:.1f}s")
            print(out)
            return 1

        if swap_pct > SWAP_PCT_LIMIT:
            proc.kill()
            print(f"[probe] ABORT — swap usage {swap_pct:.0%} exceeded "
                  f"{SWAP_PCT_LIMIT:.0%} limit after {elapsed:.1f}s "
                  f"(peak used {peak_used_mb:.0f}MB)")
            return 2
        if avail_mb < MIN_AVAILABLE_MB:
            proc.kill()
            print(f"[probe] ABORT — available RAM {avail_mb:.0f}MB below "
                  f"{MIN_AVAILABLE_MB}MB floor after {elapsed:.1f}s "
                  f"(peak swap {peak_swap_pct:.0%})")
            return 2
        if elapsed > WALLCLOCK_LIMIT_S:
            proc.kill()
            print(f"[probe] ABORT — exceeded {WALLCLOCK_LIMIT_S}s "
                  f"wall-clock limit (peak used {peak_used_mb:.0f}MB, "
                  f"peak swap {peak_swap_pct:.0%})")
            return 2

        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Make sure Ultron is running (representative conditions)**

The point is to check whether OmniVoice can coexist with Ultron, not
whether it can run on an otherwise-idle machine. Check first:

```bash
pgrep -f 'python app.py' || (cd /home/jeevan/ULTRON_WEB && nohup .venv/bin/python app.py > /tmp/ultron_probe_run.log 2>&1 &)
```

- [ ] **Step 3: Run the probe for real**

```bash
cd /home/jeevan/repo-tests/OmniVoice
.venv/bin/python ram_safety_probe.py
echo "exit code: $?"
```

Record the exit code and the full printed output. `0` = PASS, `1` = the
child process errored out for a non-memory reason (e.g. a bad
`device_map` value — check the printed traceback), `2` = a kill-switch
aborted it (this is the chatterbox-shaped outcome).

- [ ] **Step 4: Document the verdict**

Append a dated entry to the "Risks" section of
`docs/plans/2026-08-02-tts-provider-expansion-design.md` recording the
exit code, the printed PASS/FAIL/ABORT line, and peak used-MB / peak
swap-% from the output. This is the record Tasks 4-6 are gated on.

- [ ] **Step 5: Commit**

```bash
cd /home/jeevan/repo-tests/OmniVoice
git add ram_safety_probe.py
git commit -m "$(cat <<'EOF'
feat(probe): add RAM/swap safety probe for OmniVoice on this laptop

Chatterbox OOM'd this exact 7.6GB CPU-only machine after being wired
in without a check first. This probe measures peak RAM/swap during a
real model load + generation, with hard kill-switches (swap >70%,
available RAM <500MB, wall-clock >120s) so a bad outcome self-aborts
in seconds instead of thrashing the box for minutes.
EOF
)"
cd /home/jeevan/ULTRON_WEB
git add docs/plans/2026-08-02-tts-provider-expansion-design.md
git commit -m "docs(design): record OmniVoice RAM-safety probe verdict"
```

**STOP HERE if the verdict was FAIL/ABORT.** Do not proceed to Tasks 4-6.
The outcome is fully documented and that is a complete, valid result —
matching the chatterbox precedent (`CHATTERBOX_README.md`), not a plan
failure. If it was ABORT specifically, note in the design doc that
OmniVoice — like chatterbox — is a candidate for `ULTRON_OMNIVOICE_URL`
pointing at a remote machine in the future, not for this laptop.

---

## Task 4: OmniVoice sidecar (execute ONLY if Task 3's verdict was PASS) — SKIPPED, see design doc 2026-08-12 entry

**Files:**
- Create: `omnivoice_sidecar.py` (ULTRON_WEB root, alongside `chatterbox_sidecar.py`)
- Create: `tests/test_omnivoice_sidecar.py`

**Interfaces:**
- Consumes: OmniVoice's `omnivoice.OmniVoice.from_pretrained(...)` / `model.generate(text=..., ref_audio=..., ref_text=..., speed=...)` (only inside `_load_model`/`_real_synthesise`, never at module import time — mirrors `chatterbox_sidecar.py:63-84`).
- Produces: HTTP contract for Task 5 to consume — `POST /generate` with JSON body `{"text": str, "ref_audio": str, "ref_text": str, "speed": float}` returns `200` + `audio/wav` bytes on success, `400` on empty text, `404` on unknown path, `500` on synthesis failure (server keeps serving after). `GET /health` returns `{"ok": true, "model_loaded": bool}`. Also: `set_synthesiser(fn)`, `_reset_for_test()`, `build_server(port=..., host=...)`, `DEFAULT_PORT = 17581`.

- [ ] **Step 1: Write the failing sidecar contract tests**

Create `tests/test_omnivoice_sidecar.py`:

```python
"""HTTP contract of the OmniVoice sidecar.

The sidecar runs under /home/jeevan/repo-tests/OmniVoice/.venv (where the
omnivoice package and its own torch pin live). These tests run under
Ultron's own venv, where omnivoice is deliberately NOT installed — so the
module must import without it, and the model load must stay behind a lazy
seam. Mirrors tests/test_chatterbox_sidecar.py exactly.
"""
import json
import threading
from http.client import HTTPConnection

import pytest

import omnivoice_sidecar as ov


@pytest.fixture()
def server():
    """A real sidecar on a real port, with a fake synthesiser injected."""
    calls = []

    def fake_synth(text, ref_audio, ref_text, speed):
        calls.append({"text": text, "ref_audio": ref_audio,
                      "ref_text": ref_text, "speed": speed})
        return b"RIFF-FAKE-WAV"

    ov.set_synthesiser(fake_synth)
    httpd = ov.build_server(port=0)          # port 0 = let the OS pick
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield port, calls
    httpd.shutdown()
    ov._reset_for_test()


def _post(port, path, payload):
    conn = HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("POST", path, json.dumps(payload),
                 {"Content-Type": "application/json"})
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, body


def test_generate_returns_synthesised_audio(server):
    port, calls = server

    status, body = _post(port, "/generate", {
        "text": "Good evening, sir.",
        "ref_audio": "/voices/jarvis.wav",
        "ref_text": "Reference transcription.",
        "speed": 1.1,
    })

    assert status == 200
    assert body == b"RIFF-FAKE-WAV"
    assert calls == [{"text": "Good evening, sir.",
                      "ref_audio": "/voices/jarvis.wav",
                      "ref_text": "Reference transcription.",
                      "speed": 1.1}]


def test_empty_text_is_rejected_without_loading_the_model(server):
    port, calls = server

    status, _ = _post(port, "/generate", {"text": "   "})

    assert status == 400
    assert calls == []


def test_unknown_path_404s(server):
    port, _ = server
    status, _ = _post(port, "/nope", {"text": "hi"})
    assert status == 404


def test_synth_failure_returns_500_and_keeps_serving(server):
    """One bad generation must not take the sidecar down — Ultron retries."""
    port, calls = server

    def boom(text, ref_audio, ref_text, speed):
        raise RuntimeError("model exploded")

    ov.set_synthesiser(boom)
    status, _ = _post(port, "/generate", {"text": "hi"})
    assert status == 500

    ov.set_synthesiser(lambda t, r, rt, s: b"RIFF-OK")
    status, body = _post(port, "/generate", {"text": "hi"})
    assert status == 200
    assert body == b"RIFF-OK"


def test_module_imports_without_omnivoice_installed():
    """Ultron's venv has no omnivoice package; importing must not explode."""
    assert ov.build_server is not None
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `.venv/bin/python -m pytest tests/test_omnivoice_sidecar.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omnivoice_sidecar'`.

- [ ] **Step 3: Write `omnivoice_sidecar.py`**

Create `omnivoice_sidecar.py` in the ULTRON_WEB root (this file is
version-controlled with Ultron but only ever executed by OmniVoice's
venv — same split as `chatterbox_sidecar.py`):

```python
"""OmniVoice TTS sidecar — zero-shot voice-cloning synthesis in an
isolated process.

Why this exists as a separate process instead of a provider inside
voice_engine.py: OmniVoice's own venv pins torch==2.13.0+cpu against
Ultron's torch==2.12.0. Installing it alongside would risk destabilizing
the numpy 2 / torch 2.12 stack that chromadb + sentence-transformers run
on (the live RAG). So OmniVoice lives in
/home/jeevan/repo-tests/OmniVoice/.venv and this script is the only thing
that imports it. Ultron talks to it over localhost HTTP — same pattern
as chatterbox_sidecar.py, just a different venv and port.

Run it (from the OmniVoice repo root):

    .venv/bin/python /home/jeevan/ULTRON_WEB/omnivoice_sidecar.py --port 17581

Then point Ultron at it:

    export ULTRON_TTS_OMNIVOICE=1
    export ULTRON_OMNIVOICE_REF=/home/jeevan/ULTRON_WEB/voices/jarvis.wav
    export ULTRON_OMNIVOICE_REF_TEXT="Reference clip transcription."

Stdlib-only on purpose — no framework in the dependency path, so the
sidecar venv holds nothing beyond omnivoice itself.
"""
from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional

# Injectable seam. Tests set a fake; production installs the real model
# loader on first use. Keeps this module importable where omnivoice is
# absent.
_synthesiser: Optional[Callable[[str, str, str, float], bytes]] = None
_model_lock = threading.Lock()
_model = None

DEFAULT_PORT = 17581


def set_synthesiser(fn: Optional[Callable[[str, str, str, float], bytes]]) -> None:
    """Install the function that turns (text, ref_audio, ref_text, speed) -> WAV."""
    global _synthesiser
    _synthesiser = fn


def _reset_for_test() -> None:
    global _synthesiser, _model
    _synthesiser = None
    _model = None


def _load_model():
    """Import and load OmniVoice once. Only ever runs in the sidecar venv."""
    global _model
    with _model_lock:
        if _model is None:
            import torch
            from omnivoice import OmniVoice
            print("[omnivoice] loading model on cpu (first call is slow)…",
                  flush=True)
            _model = OmniVoice.from_pretrained(
                "k2-fsa/OmniVoice", device_map="cpu", dtype=torch.float32)
            print("[omnivoice] model ready", flush=True)
    return _model


def _real_synthesise(text: str, ref_audio: str, ref_text: str,
                      speed: float) -> bytes:
    """Generate WAV bytes, cloned if a reference is given, auto-voice otherwise."""
    import io
    import soundfile as sf
    model = _load_model()
    kwargs = {"text": text, "speed": speed}
    if ref_audio and ref_text:
        kwargs["ref_audio"] = ref_audio
        kwargs["ref_text"] = ref_text
    audio = model.generate(**kwargs)
    buf = io.BytesIO()
    sf.write(buf, audio[0], 24000, format="WAV")
    return buf.getvalue()


def _synthesise(text: str, ref_audio: str, ref_text: str, speed: float) -> bytes:
    fn = _synthesiser or _real_synthesise
    return fn(text, ref_audio, ref_text, speed)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, obj: dict) -> None:
        self._send(status, json.dumps(obj).encode(), "application/json")

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/generate":
            self._send_json(404, {"error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, TypeError):
            self._send_json(400, {"error": "invalid JSON body"})
            return

        text = (payload.get("text") or "").strip()
        if not text:
            self._send_json(400, {"error": "text is required"})
            return

        try:
            audio = _synthesise(
                text,
                payload.get("ref_audio") or "",
                payload.get("ref_text") or "",
                float(payload.get("speed", 1.0)),
            )
        except Exception as e:
            print(f"[omnivoice] synthesis failed: {e}", flush=True)
            self._send_json(500, {"error": str(e)})
            return

        self._send(200, audio, "audio/wav")

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") in ("/health", ""):
            self._send_json(200, {"ok": True, "model_loaded": _model is not None})
        else:
            self._send_json(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        return


def build_server(port: int = DEFAULT_PORT, host: str = "127.0.0.1"):
    """Build (but do not start) the sidecar server. port=0 picks a free port."""
    return ThreadingHTTPServer((host, port), _Handler)


def main() -> None:
    ap = argparse.ArgumentParser(description="OmniVoice TTS sidecar")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--preload", action="store_true",
                     help="load the model at startup instead of on first request")
    args = ap.parse_args()

    if args.preload:
        _load_model()

    httpd = build_server(port=args.port, host=args.host)
    print(f"[omnivoice] sidecar listening on http://{args.host}:{args.port}",
          flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[omnivoice] shutting down", flush=True)
        httpd.shutdown()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `.venv/bin/python -m pytest tests/test_omnivoice_sidecar.py -v`
Expected: 5 passed.

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `.venv/bin/python -m pytest tests/ --tb=no -q`
Expected: `1577 passed` (1572 after Task 2 + 5 new).

- [ ] **Step 6: Commit**

```bash
git add omnivoice_sidecar.py tests/test_omnivoice_sidecar.py
git commit -m "$(cat <<'EOF'
feat(tts): add OmniVoice sidecar HTTP contract

Isolated cross-venv sidecar for OmniVoice, structurally identical to
chatterbox_sidecar.py (own venv, own port 17581, lazy model load,
injectable synthesiser seam for testing without the real package
installed here). Gated on the 2026-08-02 RAM-safety probe passing.
EOF
)"
```

---

## Task 5: `_tts_omnivoice` client + chain wiring (execute ONLY if Task 3's verdict was PASS) — SKIPPED, see design doc 2026-08-12 entry

**Files:**
- Modify: `voice_engine.py` (new config block near the chatterbox config block, new `_tts_omnivoice` function near `_tts_chatterbox`, chain wiring in `tts()`, dispatch loop)
- Create: `tests/test_tts_omnivoice.py`

**Interfaces:**
- Consumes: `omnivoice_sidecar`'s HTTP contract from Task 4 (`POST /generate` with `{text, ref_audio, ref_text, speed}` → `audio/wav` bytes).
- Produces: `ve._tts_omnivoice(text: str, mood: str) -> bytes`, env vars `ULTRON_TTS_OMNIVOICE`, `ULTRON_OMNIVOICE_URL` (default `http://127.0.0.1:17581`), `ULTRON_OMNIVOICE_REF`, `ULTRON_OMNIVOICE_REF_TEXT`. Consumed by Task 6's integration test.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tts_omnivoice.py` (mirrors `tests/test_tts_chatterbox.py`):

```python
"""OmniVoice provider — zero-shot cloned/auto voice via an isolated sidecar.

Default OFF — edge stays the fast path unless ULTRON_TTS_OMNIVOICE=1.
See docs/plans/2026-08-02-tts-provider-expansion-design.md.
"""
from unittest.mock import patch, MagicMock
import pytest

import voice_engine as ve


@pytest.fixture(autouse=True)
def _no_cache_deterministic_chain(monkeypatch):
    monkeypatch.setattr(ve, "_get_cached", lambda *a, **k: None)
    monkeypatch.setattr(ve, "_set_cached", lambda *a, **k: None)
    monkeypatch.setattr(ve, "PIPER_AVAILABLE", False)
    monkeypatch.setattr(ve, "KOKORO_AVAILABLE", False)
    monkeypatch.setattr(ve, "ELEVENLABS_API_KEY", "")
    monkeypatch.setattr(ve, "OPENAI_API_KEY", "")
    monkeypatch.delenv("ULTRON_TTS_CHATTERBOX", raising=False)
    monkeypatch.delenv("ULTRON_TTS_OMNIVOICE", raising=False)


def test_omnivoice_absent_from_auto_chain_when_flag_off(monkeypatch):
    monkeypatch.setattr(ve, "_tts_edge", lambda t, m: b"EDGE")
    called = []
    monkeypatch.setattr(
        ve, "_tts_omnivoice", lambda t, m: called.append(t) or b"OV")

    audio, provider = ve.tts("hello", provider="auto")

    assert provider == "edge"
    assert called == []


def test_omnivoice_leads_auto_chain_when_enabled(monkeypatch):
    monkeypatch.setenv("ULTRON_TTS_OMNIVOICE", "1")
    monkeypatch.setattr(ve, "_tts_edge", lambda t, m: b"EDGE")
    monkeypatch.setattr(ve, "_tts_omnivoice", lambda t, m: b"OV")

    audio, provider = ve.tts("hello", provider="auto")

    assert provider == "omnivoice"
    assert audio == b"OV"


def test_omnivoice_takes_priority_over_chatterbox_when_both_enabled(monkeypatch):
    monkeypatch.setenv("ULTRON_TTS_OMNIVOICE", "1")
    monkeypatch.setenv("ULTRON_TTS_CHATTERBOX", "1")
    monkeypatch.setattr(ve, "_tts_edge", lambda t, m: b"EDGE")
    monkeypatch.setattr(ve, "_tts_omnivoice", lambda t, m: b"OV")
    monkeypatch.setattr(ve, "_tts_chatterbox", lambda t, m: b"CB")

    audio, provider = ve.tts("hello", provider="auto")

    assert provider == "omnivoice"


def test_tts_omnivoice_posts_text_to_sidecar_and_returns_audio(monkeypatch):
    monkeypatch.setenv("ULTRON_OMNIVOICE_URL", "http://127.0.0.1:17581")
    monkeypatch.setenv("ULTRON_OMNIVOICE_REF", "/voices/jarvis.wav")
    monkeypatch.setenv("ULTRON_OMNIVOICE_REF_TEXT", "Reference transcription.")

    resp = MagicMock(status_code=200, content=b"RIFF-CLONED-AUDIO")
    resp.raise_for_status = MagicMock()

    with patch.object(ve.requests, "post", return_value=resp) as post:
        audio = ve._tts_omnivoice("Good evening, sir.", "FOCUSED")

    assert audio == b"RIFF-CLONED-AUDIO"
    sent = post.call_args
    assert sent.args[0].startswith("http://127.0.0.1:17581")
    assert sent.kwargs["json"]["text"] == "Good evening, sir."
    assert sent.kwargs["json"]["ref_audio"] == "/voices/jarvis.wav"
    assert sent.kwargs["json"]["ref_text"] == "Reference transcription."


def test_sidecar_down_falls_through_to_edge(monkeypatch):
    monkeypatch.setenv("ULTRON_TTS_OMNIVOICE", "1")
    attempted = []

    def _refused(*a, **k):
        attempted.append(a)
        raise OSError("connection refused")

    monkeypatch.setattr(ve.requests, "post", _refused)
    monkeypatch.setattr(ve, "_tts_edge", lambda t, m: b"EDGE")

    audio, provider = ve.tts("hello", provider="auto")

    assert attempted, "omnivoice sidecar was never contacted"
    assert provider == "edge"
    assert audio == b"EDGE"
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `.venv/bin/python -m pytest tests/test_tts_omnivoice.py -v`
Expected: FAIL — `AttributeError: module 'voice_engine' has no attribute '_tts_omnivoice'`.

- [ ] **Step 3: Add the config block**

In `voice_engine.py`, immediately after the chatterbox config block (the
one ending with `_CHATTERBOX_EXAGGERATION = {...}`, right before the
`# SETUP` section comment), insert:

```python

# OmniVoice — zero-shot voice cloning / auto-voice, 600+ languages.
#
# Deliberately NOT imported here. OmniVoice's own venv pins torch==2.13.0+cpu
# against Ultron's torch==2.12.0; keeping it sidecar-isolated avoids any risk
# to the numpy 2 / torch 2.12 stack chromadb + sentence-transformers run on
# (the live RAG). It lives in /home/jeevan/repo-tests/OmniVoice/.venv behind
# a small HTTP sidecar (omnivoice_sidecar.py) and we only ever speak to it
# over localhost.
#
# Env is read at call time, not import time, so the sidecar can be started,
# stopped or repointed without restarting Ultron.
_OMNIVOICE_DEFAULT_URL = "http://127.0.0.1:17581"
_OMNIVOICE_TIMEOUT     = 180  # CPU synthesis on this box is slow, not hung
```

- [ ] **Step 4: Add `_tts_omnivoice`**

In `voice_engine.py`, immediately after `_tts_chatterbox` ends, insert:

```python


def _tts_omnivoice(text: str, mood: str) -> bytes:
    """Zero-shot voice (cloned if a reference is set, auto otherwise) via
    the isolated local sidecar.

    Thin HTTP client by design — the model itself never loads in this
    process. Any failure raises so the unified chain falls through to
    edge/chatterbox and Ultron still speaks.
    """
    url      = os.environ.get("ULTRON_OMNIVOICE_URL", _OMNIVOICE_DEFAULT_URL).rstrip("/")
    ref      = os.environ.get("ULTRON_OMNIVOICE_REF", "")
    ref_text = os.environ.get("ULTRON_OMNIVOICE_REF_TEXT", "")
    rate     = VOICE_SPEAKING_RATES.get(mood, 1.0)
    resp = requests.post(
        f"{url}/generate",
        json={
            "text":     text[:VOICE_MAX_TTS_CHARS],
            "ref_audio": ref,
            "ref_text":  ref_text,
            "speed":     rate,
        },
        timeout=_OMNIVOICE_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.content
```

- [ ] **Step 5: Wire it into the auto chain**

In `voice_engine.py`, the chain-construction block (after Task 2's
change) currently starts:

```python
    if provider == "auto":
        chain = []
        # Cloned voice first when explicitly enabled — it is slower than the
        # rest, so it is opt-in and only chosen because it is *wanted*.
        if os.environ.get("ULTRON_TTS_CHATTERBOX") == "1":
            chain.append("chatterbox")
```

Change to:

```python
    if provider == "auto":
        chain = []
        # Cloned/zero-shot voices first when explicitly enabled — both are
        # slower than the local providers, so both are opt-in and only
        # chosen because they are *wanted*. OmniVoice takes priority if
        # both happen to be enabled at once.
        if os.environ.get("ULTRON_TTS_OMNIVOICE") == "1":
            chain.append("omnivoice")
        if os.environ.get("ULTRON_TTS_CHATTERBOX") == "1":
            chain.append("chatterbox")
```

- [ ] **Step 6: Add the dispatch branch**

In `voice_engine.py`, the dispatch loop currently includes:

```python
            elif prov == "chatterbox":
                audio = _tts_chatterbox(clean, mood)
```

Add immediately after it:

```python
            elif prov == "chatterbox":
                audio = _tts_chatterbox(clean, mood)
            elif prov == "omnivoice":
                audio = _tts_omnivoice(clean, mood)
```

- [ ] **Step 7: Run the tests and confirm they pass**

Run: `.venv/bin/python -m pytest tests/test_tts_omnivoice.py -v`
Expected: 5 passed.

- [ ] **Step 8: Run the full suite to confirm no regressions**

Run: `.venv/bin/python -m pytest tests/ --tb=no -q`
Expected: `1582 passed` (1577 after Task 4 + 5 new).

- [ ] **Step 9: Commit**

```bash
git add voice_engine.py tests/test_tts_omnivoice.py
git commit -m "$(cat <<'EOF'
feat(tts): wire OmniVoice as an opt-in zero-shot voice provider

Thin HTTP client to the omnivoice_sidecar, same opt-in-and-leads-the-chain
pattern as chatterbox. Default OFF via ULTRON_TTS_OMNIVOICE; takes
priority over chatterbox if both are enabled. Falls through to the rest
of the chain on any sidecar failure.
EOF
)"
```

---

## Task 6: End-to-end integration test + orphan_guard + final verification (execute ONLY if Task 3's verdict was PASS) — SKIPPED, see design doc 2026-08-12 entry

**Files:**
- Create: `tests/test_omnivoice_integration.py`
- Modify: `orphan_guard.py` (`ALLOWED_ORPHANS` dict)

**Interfaces:**
- Consumes: `omnivoice_sidecar.build_server`/`set_synthesiser`/`_reset_for_test` (Task 4) and `ve._tts_omnivoice`/`ve.tts` (Task 5).
- Produces: nothing further — this is the final task.

- [ ] **Step 1: Write the failing integration test**

Create `tests/test_omnivoice_integration.py` (mirrors
`tests/test_chatterbox_integration.py`):

```python
"""The seam: voice_engine's omnivoice provider talking to the real sidecar
over HTTP.

Both halves are unit-tested separately, but they are developed against a
contract written twice — once in the client, once in the handler. This
test runs a genuine ThreadingHTTPServer and a genuine requests.post
between them, so a drift in path, field names or content handling fails
here.
"""
import threading

import pytest

import omnivoice_sidecar as ov
import voice_engine as ve


@pytest.fixture()
def live_sidecar(monkeypatch):
    received = {}

    def fake_synth(text, ref_audio, ref_text, speed):
        received.update(text=text, ref_audio=ref_audio,
                         ref_text=ref_text, speed=speed)
        return b"RIFF....WAVEfmt cloned-audio"

    ov.set_synthesiser(fake_synth)
    httpd = ov.build_server(port=0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    monkeypatch.setenv("ULTRON_OMNIVOICE_URL", f"http://127.0.0.1:{port}")
    yield received
    httpd.shutdown()
    ov._reset_for_test()


def test_provider_reaches_sidecar_and_gets_audio_back(live_sidecar, monkeypatch):
    monkeypatch.setenv("ULTRON_OMNIVOICE_REF", "/voices/jarvis.wav")
    monkeypatch.setenv("ULTRON_OMNIVOICE_REF_TEXT", "Reference transcription.")

    audio = ve._tts_omnivoice("Good evening, sir.", "FOCUSED")

    assert audio == b"RIFF....WAVEfmt cloned-audio"
    assert live_sidecar["text"] == "Good evening, sir."
    assert live_sidecar["ref_audio"] == "/voices/jarvis.wav"
    assert live_sidecar["ref_text"] == "Reference transcription."


def test_full_tts_chain_uses_sidecar_when_enabled(live_sidecar, monkeypatch):
    """End to end through the public tts() entry point, not the private one."""
    monkeypatch.setenv("ULTRON_TTS_OMNIVOICE", "1")
    monkeypatch.setattr(ve, "_get_cached", lambda *a, **k: None)
    monkeypatch.setattr(ve, "_set_cached", lambda *a, **k: None)

    audio, provider = ve.tts("Systems nominal.", provider="auto")

    assert provider == "omnivoice"
    assert audio == b"RIFF....WAVEfmt cloned-audio"
    assert live_sidecar["text"] == "Systems nominal."
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `.venv/bin/python -m pytest tests/test_omnivoice_integration.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omnivoice_sidecar'`
if run before Task 4, or passes trivially-wrong if run out of order. In
the normal Task 1→6 order this simply confirms the file didn't exist
before this step.

- [ ] **Step 3: Add `omnivoice_sidecar` to the orphan allowlist**

In `orphan_guard.py`, the `ALLOWED_ORPHANS` dict currently reads
(lines 31-46):

```python
ALLOWED_ORPHANS: Dict[str, str] = {
    # Standalone entry points — run directly, never imported.
    "ultron_listener": "standalone always-on voice listener process",
    "wiring_audit": "human-facing audit script",
    "setup_integrations": "one-shot setup script",
    # Runs under .venv-chatterbox, not this venv — it imports chatterbox-tts,
    # whose numpy<2 / torch 2.6 pins would break chromadb + sentence-transformers
    # here. voice_engine._tts_chatterbox reaches it over localhost HTTP, so it
    # is unimportable by design rather than disconnected. See CHATTERBOX_README.md.
    "chatterbox_sidecar": "cloned-voice TTS sidecar, runs in .venv-chatterbox",
    # Stray root-level test file, kept out of tests/ — pre-existing.
    "test_t17": "stray root-level test file (pre-existing debt)",
    # The four grandfathered orphans are gone — all were wired via
    # startup_wiring.py rather than retired, because each was the missing half
    # of a feature that already had consumers.
}
```

Add a new entry after the `chatterbox_sidecar` line:

```python
    "chatterbox_sidecar": "cloned-voice TTS sidecar, runs in .venv-chatterbox",
    # Same reasoning, different venv: runs under
    # /home/jeevan/repo-tests/OmniVoice/.venv, which pins torch==2.13.0+cpu
    # against this venv's torch==2.12.0. voice_engine._tts_omnivoice reaches
    # it over localhost HTTP.
    "omnivoice_sidecar": "zero-shot voice-cloning TTS sidecar, runs in repo-tests/OmniVoice/.venv",
```

- [ ] **Step 4: Run the integration test and confirm it passes**

Run: `.venv/bin/python -m pytest tests/test_omnivoice_integration.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run `wiring_audit` to confirm 0 unexpected orphans**

Run: `.venv/bin/python wiring_audit.py`
Expected: reports 0 unexpected orphans (matches the state from the
2026-07-26 audit).

- [ ] **Step 6: Run the full suite to confirm no regressions**

Run: `.venv/bin/python -m pytest tests/ --tb=no -q`
Expected: `1584 passed` (1582 after Task 5 + 2 new).

- [ ] **Step 7: Manual real-sidecar smoke test (not part of the automated suite)**

```bash
cd /home/jeevan/repo-tests/OmniVoice
.venv/bin/python /home/jeevan/ULTRON_WEB/omnivoice_sidecar.py --port 17581 &
sleep 2
curl -s http://127.0.0.1:17581/health
cd /home/jeevan/ULTRON_WEB
ULTRON_TTS_OMNIVOICE=1 .venv/bin/python -c "
import voice_engine as ve
audio, provider = ve.tts('This is an OmniVoice end to end test.', provider='auto')
assert provider == 'omnivoice'
assert len(audio) > 1000
print(f'OK: omnivoice returned {len(audio)} bytes')
"
kill %1
```

- [ ] **Step 8: Commit**

```bash
git add tests/test_omnivoice_integration.py orphan_guard.py
git commit -m "$(cat <<'EOF'
test(tts): end-to-end OmniVoice integration test + orphan_guard allowlist

Closes the loop: a real ThreadingHTTPServer + real requests.post prove
the omnivoice_sidecar contract and the voice_engine client agree.
orphan_guard now expects omnivoice_sidecar as a cross-venv module,
unimportable by design rather than disconnected — same as
chatterbox_sidecar.
EOF
)"
```

---

## Final Summary (after all applicable tasks)

If Task 3 PASSED: 6 tasks, 1584 tests passing (1563 baseline + 21 new),
Ultron's auto TTS chain becomes `omnivoice (opt-in) → chatterbox (opt-in)
→ piper (still missing, out of scope) → kokoro (restored) → elevenlabs
(no key) → openai (no key) → edge → espeak (last resort)`.

If Task 3 FAILED/ABORTED: 3 tasks, 1572 tests passing (1563 baseline +
9 new), chain becomes `chatterbox (opt-in) → piper (still missing) →
kokoro (restored) → elevenlabs (no key) → openai (no key) → edge →
espeak (last resort)` — Ultron never goes silent even with zero network,
and the OmniVoice verdict is documented for future reference.
