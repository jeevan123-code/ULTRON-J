"""LEBENX STUDIO — AI video production system.

Package layout:
    db.py          SQLite schema + DAO (workspace-scoped)
    storage.py     MediaStorageProvider abstraction (local backend shipped)
    providers/     Image / video / voice adapters behind one normalised API
    cost.py        Usage tracking, budgets, cost estimates
    jobs.py        Background job worker (retry, cancel, idempotency, logs)
    agents.py      Researcher / Writer / Director / Visual / Editor / QC / Critic
    prompts.py     Visual prompt engine (style profiles + provider adapters)
    timeline.py    Timeline model, auto-assembly, voice timing engine
    captions.py    SRT / WebVTT / cue generation
    render.py      Render pipeline (ffmpeg) + capability detection
    pipeline.py    Mission orchestration across pipeline stages
    routes.py      Flask blueprint
"""

__version__ = "1.0.0"
