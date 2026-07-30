# Cloned voice (Chatterbox) — setup

Gives Ultron a **cloned voice** (e.g. a JARVIS-style one) from a short
reference clip, using [Chatterbox](https://github.com/resemble-ai/chatterbox)
(MIT, zero-shot — no training).

Default **OFF**. `edge` stays the fast path unless you switch it on.

## Why it runs in a separate venv

`chatterbox-tts` pins `numpy<2`, `torch==2.6` and `transformers==5.2`.
Ultron's `.venv` runs numpy 2.4 / torch 2.12 / transformers 5.8 because
**chromadb + sentence-transformers need them, and those back the live RAG**
(8036 docs). Installing chatterbox alongside would downgrade the stack and
take semantic memory down with it.

So chatterbox lives in `.venv-chatterbox`, `chatterbox_sidecar.py` is the only
module that imports it, and `voice_engine._tts_chatterbox` speaks to it over
localhost HTTP. Ultron's venv is never touched.

## 1. Install (once, ~3GB)

CPU-only wheels — this machine has Intel HD 620, so the default CUDA build
would waste ~3GB on nvidia libs that can never run:

```bash
python3 -m venv .venv-chatterbox
.venv-chatterbox/bin/pip install --index-url https://download.pytorch.org/whl/cpu \
    torch==2.6.0 torchaudio==2.6.0
.venv-chatterbox/bin/pip install chatterbox-tts
```

## 2. Provide a reference clip

**This is the whole "voice".** There is no model file to download — Chatterbox
clones zero-shot from audio you supply.

```bash
mkdir -p voices
# put a clean 5-15s WAV here, one speaker, no music, no background noise
cp ~/Downloads/jarvis.wav voices/jarvis.wav
```

Quality of the clone tracks quality of the clip more than anything else.
`voices/` is gitignored (binary, and often not ours to redistribute).

## 3. Start the sidecar

```bash
HF_HUB_DISABLE_XET=1 .venv-chatterbox/bin/python chatterbox_sidecar.py --port 17580
# --preload loads the model at startup instead of on the first request
```

Health check: `curl http://127.0.0.1:17580/health`

### `HF_HUB_DISABLE_XET=1` is not optional here

The first run downloads ~1GB of model weights from HuggingFace. Measured on
this machine 2026-07-30:

| transfer path | rate |
|---|---|
| HF Xet (the default) | **~515 B/s** — effectively never finishes |
| Xet disabled | **~1 MB/s** — ~17 min |

Unauthenticated Xet requests get throttled hard. Setting `HF_TOKEN` to a free
HuggingFace token is the other fix; disabling Xet needs no account.

Note that each restart **abandons the partial download and starts a new blob**
rather than resuming — so let the first run finish rather than restarting it.

## 4. Turn it on in Ultron

```bash
export ULTRON_TTS_CHATTERBOX=1
export ULTRON_CHATTERBOX_REF=/home/jeevan/ULTRON_WEB/voices/jarvis.wav
# optional, defaults to http://127.0.0.1:17580
export ULTRON_CHATTERBOX_URL=http://127.0.0.1:17580
```

Restart Ultron. `chatterbox` now leads the TTS chain; everything else is
unchanged behind it.

## ⛔ This does NOT run on this laptop — measured 2026-07-30

The model loads fine. Generation does not. One sentence was killed at **216s**
having completed roughly **1 of up to 1000 sampling steps**.

The sidecar needs **~4.0GB RSS**. This machine has 7.6GB total and ~3.8GB free
with Ultron running, so it went straight into swap:

| | |
|---|---|
| swap | **2.0Gi of 2.0Gi — fully exhausted** |
| CPU in I/O wait | **67–89%** |
| major page faults | 131,897 (~370MB/s paging from disk) |
| available RAM | **98Mi** |

That is thrashing, not slowness — waiting longer does not help. The sidecar was
killed to stop Ultron being OOM-killed. **Do not retry locally.** The Turbo
(350M) variant is lighter, but a load is three models (t3 + s3gen + voice
encoder) and will not close a 4GB-vs-3.8GB gap.

### What to do instead

1. **ElevenLabs** — the only realistic cloned voice on this hardware.
   `_tts_elevenlabs` is already wired at chain priority; it needs only
   `ELEVENLABS_API_KEY` (cloning requires a paid tier).
2. **Run this sidecar on another machine.** It is plain HTTP, so
   `ULTRON_CHATTERBOX_URL=http://<that-box>:17580` works unchanged — a GPU
   desktop, a cloud VM, or Colab. Nothing in the integration assumes localhost.
   (Bind with `--host 0.0.0.0` there, and don't expose it to the open internet.)
3. **Restore piper** for a local/offline voice if cloning is not the point.

The integration itself is correct and stays: 11 tests green, and the chain
**falls through to edge** whenever the sidecar is absent, slow or erroring, so
Ultron never goes silent (`test_sidecar_down_falls_through_to_edge`).
Ultron also caches TTS by text+mood, so repeats are instant.

## Notes

- Chatterbox applies **PerTh watermarking** to every generation.
- Cloning a real actor's voice is fine for personal use; don't redistribute it.
- `exaggeration` is Chatterbox's one expressive dial (0 = monotone). Ultron
  maps it per mood in `voice_engine._CHATTERBOX_EXAGGERATION`.

## Tests

```bash
.venv/bin/python -m pytest tests/test_tts_chatterbox.py \
    tests/test_chatterbox_sidecar.py tests/test_chatterbox_integration.py -q
```

11 tests. They run in Ultron's venv with the synthesiser faked, so they pass
whether or not `.venv-chatterbox` exists — the sidecar's HTTP contract is
exercised for real, only the model is stubbed.
