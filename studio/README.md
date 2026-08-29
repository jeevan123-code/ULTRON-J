# 🎬 LEBENX STUDIO

**From one idea to a complete video.**

An AI video production system built into Ultron-J. A user enters an idea; an
agent team drives it through research, script, storyboard, asset generation,
narration, editing, and render — producing an **editable draft**, not a
one-shot artefact.

---

## The architectural principle

> LEBENX STUDIO must never pretend it can generate images, videos, voices, or
> music without an actual connected provider.

This is enforced structurally, not by convention:

| Where | What it guarantees |
|---|---|
| `providers/base.py` | Four distinct states — `connected`, `available`, `missing_credentials`, `unavailable`. Never a boolean. |
| `providers/registry.py` | `dispatchable()` returns **only** connected providers. There is no fallback that fabricates output. |
| `providers/base.py::map_status` | An unrecognised provider status maps to `FAILED`, never optimistically to `COMPLETED`. |
| `Capabilities` | Every field defaults to `False`. Undeclared means unsupported. |
| `jobs.update_progress` | `progress_pct` stays `NULL` unless a provider reported a real number. The UI shows a stage name instead. |
| `agents._sanitise_sources` | With no research tool connected, model-emitted URLs are stripped. A plausible fake citation is worse than none. |
| `timeline.analyse_timing` | Duration conflicts are *reported* with real measured numbers. Nothing is silently stretched or truncated. |
| `render.probe()` | No ffmpeg → render is refused with the install command, not a button that does nothing. |
| `cost.py` | Unknown cost is `None`, never `$0.00`. Estimates and provider-confirmed actuals live in separate columns. |

When nothing is connected, the system **refuses and explains**:

```json
{ "error": "no connected video provider",
  "providers": [{"provider": "replicate", "status": "missing_credentials",
                 "credential_env": ["REPLICATE_API_TOKEN"]}],
  "remedy": "Connect a provider in Studio Settings, then retry." }
```

---

## Module map

```
studio/
├── db.py          SQLite schema + DAO. assert_project() is the single
│                  ownership chokepoint for every workspace-scoped read.
├── storage.py     MediaStorageProvider abstraction (local backend shipped).
│                  Path-traversal containment lives here and nowhere else.
├── providers/
│   ├── base.py        Interfaces, states, Capabilities, errors
│   ├── http.py        Timeouts + retryable-error classification
│   ├── registry.py    Discovery, per-workspace config, connected-only dispatch
│   ├── image.py       OpenAI · Together · Pollinations (keyless)
│   ├── video.py       Replicate (async predictions)
│   └── voice.py       Edge TTS (keyless) · ElevenLabs + real duration measurement
├── cost.py        Estimates, usage records, budgets
├── jobs.py        Worker pool: retry, cancel, idempotency, logs, isolation
├── handlers.py    Job handlers, registered into the pool
├── agents.py      Researcher · Writer · Director · Critic · Editor · Thumbnails
├── prompts.py     Visual Prompt Engine (style profiles × provider formatters)
├── timeline.py    Timeline model, auto-assembly, voice timing engine
├── captions.py    Cue building, SRT/WebVTT, gap detection
├── quality.py     Quality Control Agent (measured, not LLM-guessed)
├── render.py      ffmpeg pipeline with real progress
├── pipeline.py    Mission orchestration, stop points, approval gates
└── routes.py      Flask blueprint (~65 endpoints)
```

---

## Adding a provider

Nothing outside the adapter changes — jobs, storage, cost, storyboard, and
timeline all speak the normalised interface.

```python
from studio.providers.base import ImageGenerationProvider, Capabilities
from studio.providers import registry

class MyProvider(ImageGenerationProvider):
    name, label = "myprov", "My Provider"
    credential_env = ("MYPROV_API_KEY",)

    def is_connected(self):  return bool(self._key())
    def capabilities(self):  return Capabilities(text_to_image=True, ...)
    def generate_image(self, request): ...
    def get_generation_status(self, handle): ...
    def verify_connection(self): ...    # a real call, not a claim

registry.register_provider(MyProvider)
```

Declare **only** what you have verified. `verify_connection()` exists so the
settings screen can distinguish *"we called it and it answered"* from
*"the adapter claims this"* — providers are labelled
`declared_unverified` until a real call succeeds.

---

## Running without any API keys

Phases 1 and 5 work fully with no credentials: projects, briefs, research
(model-only, clearly labelled), scripts, storyboards, scene management,
timeline editing, and caption export. Two keyless adapters —
**Pollinations** (images) and **Edge TTS** (voice, needs `pip install edge-tts`)
— let the asset and audio phases be exercised too.

Rendering additionally needs `ffmpeg` on the host.

---

## Configuration

| Variable | Purpose |
|---|---|
| `STUDIO_MEDIA_DIR` | Media root (default `./studio_media`) |
| `STUDIO_STORAGE_BACKEND` | `local` (only shipped backend) |
| `STUDIO_MONTHLY_BUDGET` | Default USD budget; `0` = unset, reported as unset |
| `STUDIO_JOB_WORKERS` | Concurrent generation workers (default 2) |
| `OPENAI_API_KEY` · `TOGETHER_API_KEY` | Image providers |
| `REPLICATE_API_TOKEN` | Video provider |
| `ELEVENLABS_API_KEY` | Voice provider |

Keys are read server-side only. `registry.describe_all()` redacts them and no
endpoint ever returns one.

---

## Tests

```bash
python -m pytest tests/test_studio.py -v      # 56 tests
```

The tests that matter most assert the system **refuses to fake things**: no
synthetic asset without a provider, no invented citation, no fabricated
percentage, no silent timing distortion, no cross-workspace leak.
