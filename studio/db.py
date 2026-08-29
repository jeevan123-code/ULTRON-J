"""
studio/db.py — Persistence layer for LEBENX STUDIO.

One SQLite file (`studio.db`, sibling of `ultron.db`) holding the whole
video-production domain. It is deliberately separate from `ultron.db` so
that Studio schema churn can never corrupt the agent's episodic memory.

Design rules that the rest of the package depends on:

  * **Every row is workspace-scoped.** `studio_project.workspace` is the
    ownership root; child rows carry `project_id` and are reachable only
    through a project the caller owns. `assert_project()` is the single
    chokepoint that enforces it.
  * **Nothing is fabricated.** Status columns record what actually
    happened. A scene with no generated asset stays `pending`; a job that
    never reached a provider stays `draft`. There is no column that lets
    the UI display progress the backend did not observe.
  * **JSON columns for open-ended structures** (settings, metadata, cue
    lists) — normalised tables for anything we filter or join on.
  * **Auditability.** Every mutation touches `updated_at`; generation and
    render jobs additionally append to `job_log`, which is append-only.

Threading: Flask serves requests on multiple threads and the job worker
runs on its own. Each call opens a short-lived connection (WAL mode) via
`_conn()`, so there is no shared cursor to race on.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterable, Optional

try:
    from config import STUDIO_DB_FILE
except ImportError:  # config not importable (e.g. isolated unit test)
    STUDIO_DB_FILE = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "studio.db"
    )

_INIT_LOCK = threading.Lock()
_INITIALISED = False


# =============================================================================
# CONNECTION
# =============================================================================

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(STUDIO_DB_FILE, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def _conn():
    """Short-lived connection + transaction. Commits on clean exit."""
    init_db()
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def new_id(prefix: str) -> str:
    """Prefixed ULID-ish id — sortable by creation time, readable in logs."""
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def now() -> float:
    return time.time()


def _dumps(value: Any) -> str:
    return json.dumps(value if value is not None else None, default=str)


def _loads(raw: Any, fallback: Any = None):
    if raw in (None, ""):
        return fallback
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return fallback


def row_to_dict(row: Optional[sqlite3.Row], json_fields: Iterable[str] = ()) -> Optional[dict]:
    if row is None:
        return None
    out = dict(row)
    for field in json_fields:
        if field in out:
            out[field] = _loads(out[field], None)
    return out


# =============================================================================
# SCHEMA
# =============================================================================

SCHEMA = """
-- ── Projects ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS studio_project (
    id            TEXT PRIMARY KEY,
    workspace     TEXT NOT NULL,
    owner         TEXT NOT NULL DEFAULT '',
    title         TEXT NOT NULL,
    idea          TEXT NOT NULL DEFAULT '',
    video_type    TEXT NOT NULL DEFAULT 'youtube_video',
    mode          TEXT NOT NULL DEFAULT 'assisted',      -- full_auto|assisted|manual
    approval_level TEXT NOT NULL DEFAULT 'expensive',    -- full_auto|expensive|manual
    status        TEXT NOT NULL DEFAULT 'draft',
    stage         TEXT NOT NULL DEFAULT 'brief',
    archived      INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_project_workspace ON studio_project(workspace, archived, updated_at DESC);

-- ── Brief ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS video_brief (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES studio_project(id) ON DELETE CASCADE,
    topic         TEXT NOT NULL DEFAULT '',
    audience      TEXT NOT NULL DEFAULT '',
    platform      TEXT NOT NULL DEFAULT 'youtube',
    duration_s    INTEGER NOT NULL DEFAULT 300,
    tone          TEXT NOT NULL DEFAULT '',
    visual_style  TEXT NOT NULL DEFAULT 'cinematic',
    language      TEXT NOT NULL DEFAULT 'en',
    aspect_ratio  TEXT NOT NULL DEFAULT '16:9',
    notes         TEXT NOT NULL DEFAULT '',
    approved      INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_brief_project ON video_brief(project_id);

-- ── Research ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS research_report (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES studio_project(id) ON DELETE CASCADE,
    key_points    TEXT NOT NULL DEFAULT '[]',
    facts         TEXT NOT NULL DEFAULT '[]',
    statistics    TEXT NOT NULL DEFAULT '[]',
    misconceptions TEXT NOT NULL DEFAULT '[]',
    hook          TEXT NOT NULL DEFAULT '',
    sources       TEXT NOT NULL DEFAULT '[]',
    uncertainties TEXT NOT NULL DEFAULT '[]',
    -- 'search' when a research tool actually ran, 'model_only' when the
    -- report came from model priors alone. The UI must show the difference.
    evidence_mode TEXT NOT NULL DEFAULT 'model_only',
    status        TEXT NOT NULL DEFAULT 'draft',
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_research_project ON research_report(project_id);

-- ── Script ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS video_script (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES studio_project(id) ON DELETE CASCADE,
    version       INTEGER NOT NULL DEFAULT 1,
    is_current    INTEGER NOT NULL DEFAULT 1,
    title         TEXT NOT NULL DEFAULT '',
    hook          TEXT NOT NULL DEFAULT '',
    body          TEXT NOT NULL DEFAULT '',
    call_to_action TEXT NOT NULL DEFAULT '',
    word_count    INTEGER NOT NULL DEFAULT 0,
    source        TEXT NOT NULL DEFAULT 'ai',           -- ai|user|hybrid
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_script_project ON video_script(project_id, is_current, version DESC);

CREATE TABLE IF NOT EXISTS script_segment (
    id            TEXT PRIMARY KEY,
    script_id     TEXT NOT NULL REFERENCES video_script(id) ON DELETE CASCADE,
    project_id    TEXT NOT NULL,
    idx           INTEGER NOT NULL,
    start_s       REAL NOT NULL DEFAULT 0,
    end_s         REAL NOT NULL DEFAULT 0,
    text          TEXT NOT NULL DEFAULT '',
    created_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_segment_script ON script_segment(script_id, idx);

-- ── Storyboard + scenes ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS storyboard (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES studio_project(id) ON DELETE CASCADE,
    version       INTEGER NOT NULL DEFAULT 1,
    is_current    INTEGER NOT NULL DEFAULT 1,
    style         TEXT NOT NULL DEFAULT '',
    pacing        TEXT NOT NULL DEFAULT '',
    notes         TEXT NOT NULL DEFAULT '',
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_storyboard_project ON storyboard(project_id, is_current, version DESC);

CREATE TABLE IF NOT EXISTS scene (
    id            TEXT PRIMARY KEY,
    storyboard_id TEXT NOT NULL REFERENCES storyboard(id) ON DELETE CASCADE,
    project_id    TEXT NOT NULL,
    idx           INTEGER NOT NULL,
    start_s       REAL NOT NULL DEFAULT 0,
    duration_s    REAL NOT NULL DEFAULT 5,
    narration     TEXT NOT NULL DEFAULT '',
    visual_description TEXT NOT NULL DEFAULT '',
    camera        TEXT NOT NULL DEFAULT '',
    transition    TEXT NOT NULL DEFAULT 'cut',
    transition_duration REAL NOT NULL DEFAULT 0.5,
    asset_type    TEXT NOT NULL DEFAULT 'ai_image',
    generation_prompt TEXT NOT NULL DEFAULT '',
    negative_prompt TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'pending',
    selected_asset_id TEXT,
    character_refs TEXT NOT NULL DEFAULT '[]',
    error         TEXT NOT NULL DEFAULT '',
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scene_storyboard ON scene(storyboard_id, idx);
CREATE INDEX IF NOT EXISTS idx_scene_project ON scene(project_id, status);

-- ── Media assets ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS media_asset (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES studio_project(id) ON DELETE CASCADE,
    scene_id      TEXT,
    kind          TEXT NOT NULL,                        -- image|video|audio|voiceover|music|caption|upload
    storage_key   TEXT NOT NULL DEFAULT '',
    filename      TEXT NOT NULL DEFAULT '',
    mime          TEXT NOT NULL DEFAULT '',
    bytes         INTEGER NOT NULL DEFAULT 0,
    duration_s    REAL,
    width         INTEGER,
    height        INTEGER,
    source        TEXT NOT NULL DEFAULT 'generated',    -- generated|upload|stock
    provider      TEXT NOT NULL DEFAULT '',
    model         TEXT NOT NULL DEFAULT '',
    prompt        TEXT NOT NULL DEFAULT '',
    settings      TEXT NOT NULL DEFAULT '{}',
    meta          TEXT NOT NULL DEFAULT '{}',
    thumbnail_key TEXT NOT NULL DEFAULT '',
    created_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_asset_project ON media_asset(project_id, kind, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_asset_scene ON media_asset(scene_id);

-- ── Generation jobs ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS generation_job (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES studio_project(id) ON DELETE CASCADE,
    workspace     TEXT NOT NULL DEFAULT 'default',
    owner         TEXT NOT NULL DEFAULT '',
    scene_id      TEXT,
    job_type      TEXT NOT NULL,                        -- research|script|storyboard|image|video|voice|caption|render
    provider      TEXT NOT NULL DEFAULT '',
    model         TEXT NOT NULL DEFAULT '',
    prompt        TEXT NOT NULL DEFAULT '',
    settings      TEXT NOT NULL DEFAULT '{}',
    status        TEXT NOT NULL DEFAULT 'draft',
    stage         TEXT NOT NULL DEFAULT '',
    -- progress_pct is NULL unless the provider reports a real number.
    progress_pct  REAL,
    cost_estimate REAL,
    actual_cost   REAL,
    external_id   TEXT NOT NULL DEFAULT '',
    result_asset_id TEXT,
    error         TEXT NOT NULL DEFAULT '',
    attempts      INTEGER NOT NULL DEFAULT 0,
    max_attempts  INTEGER NOT NULL DEFAULT 3,
    idempotency_key TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    started_at    REAL,
    finished_at   REAL
);
CREATE INDEX IF NOT EXISTS idx_job_project ON generation_job(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_job_status ON generation_job(status, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_job_idem ON generation_job(idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS job_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        TEXT NOT NULL,
    ts            REAL NOT NULL,
    level         TEXT NOT NULL DEFAULT 'info',
    message       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_joblog_job ON job_log(job_id, id);

-- ── Audio ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS voiceover (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES studio_project(id) ON DELETE CASCADE,
    scene_id      TEXT,
    segment_id    TEXT,
    asset_id      TEXT,
    provider      TEXT NOT NULL DEFAULT '',
    voice_id      TEXT NOT NULL DEFAULT '',
    voice_name    TEXT NOT NULL DEFAULT '',
    language      TEXT NOT NULL DEFAULT 'en',
    speed         REAL NOT NULL DEFAULT 1.0,
    text          TEXT NOT NULL DEFAULT '',
    duration_s    REAL,
    status        TEXT NOT NULL DEFAULT 'pending',
    error         TEXT NOT NULL DEFAULT '',
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vo_project ON voiceover(project_id, scene_id);

CREATE TABLE IF NOT EXISTS music_track (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES studio_project(id) ON DELETE CASCADE,
    asset_id      TEXT,
    title         TEXT NOT NULL DEFAULT '',
    source        TEXT NOT NULL DEFAULT 'upload',       -- upload|licensed|generated
    -- Rights attestation: we never assume the user holds a licence.
    rights_status TEXT NOT NULL DEFAULT 'unverified',   -- unverified|user_attested|licensed
    rights_note   TEXT NOT NULL DEFAULT '',
    start_s       REAL NOT NULL DEFAULT 0,
    duration_s    REAL,
    volume        REAL NOT NULL DEFAULT 0.25,
    fade_in_s     REAL NOT NULL DEFAULT 1.5,
    fade_out_s    REAL NOT NULL DEFAULT 2.0,
    ducking       INTEGER NOT NULL DEFAULT 1,
    duck_to       REAL NOT NULL DEFAULT 0.08,
    scene_id      TEXT,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_music_project ON music_track(project_id);

-- ── Captions ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS caption_track (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES studio_project(id) ON DELETE CASCADE,
    language      TEXT NOT NULL DEFAULT 'en',
    style         TEXT NOT NULL DEFAULT 'minimal',
    style_config  TEXT NOT NULL DEFAULT '{}',
    cues          TEXT NOT NULL DEFAULT '[]',
    -- 'script' = derived from planned timings, 'voice' = derived from real
    -- measured narration durations, 'alignment' = forced-aligner output.
    timing_source TEXT NOT NULL DEFAULT 'script',
    burned_in     INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_caption_project ON caption_track(project_id);

-- ── Timeline ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS timeline (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES studio_project(id) ON DELETE CASCADE,
    fps           INTEGER NOT NULL DEFAULT 30,
    width         INTEGER NOT NULL DEFAULT 1920,
    height        INTEGER NOT NULL DEFAULT 1080,
    aspect_ratio  TEXT NOT NULL DEFAULT '16:9',
    duration_s    REAL NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_timeline_project ON timeline(project_id);

CREATE TABLE IF NOT EXISTS timeline_track (
    id            TEXT PRIMARY KEY,
    timeline_id   TEXT NOT NULL REFERENCES timeline(id) ON DELETE CASCADE,
    project_id    TEXT NOT NULL,
    kind          TEXT NOT NULL,                        -- video|voice|music|caption|overlay
    label         TEXT NOT NULL DEFAULT '',
    idx           INTEGER NOT NULL DEFAULT 0,
    muted         INTEGER NOT NULL DEFAULT 0,
    volume        REAL NOT NULL DEFAULT 1.0,
    locked        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_track_timeline ON timeline_track(timeline_id, idx);

CREATE TABLE IF NOT EXISTS timeline_clip (
    id            TEXT PRIMARY KEY,
    track_id      TEXT NOT NULL REFERENCES timeline_track(id) ON DELETE CASCADE,
    timeline_id   TEXT NOT NULL,
    project_id    TEXT NOT NULL,
    asset_id      TEXT,
    scene_id      TEXT,
    idx           INTEGER NOT NULL DEFAULT 0,
    start_s       REAL NOT NULL DEFAULT 0,
    duration_s    REAL NOT NULL DEFAULT 0,
    in_s          REAL NOT NULL DEFAULT 0,
    out_s         REAL,
    volume        REAL NOT NULL DEFAULT 1.0,
    transition_in TEXT NOT NULL DEFAULT 'cut',
    transition_in_s REAL NOT NULL DEFAULT 0,
    text          TEXT NOT NULL DEFAULT '',
    settings      TEXT NOT NULL DEFAULT '{}',
    created_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clip_track ON timeline_clip(track_id, start_s);
CREATE INDEX IF NOT EXISTS idx_clip_timeline ON timeline_clip(timeline_id);

-- ── Render ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS render_job (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES studio_project(id) ON DELETE CASCADE,
    workspace     TEXT NOT NULL DEFAULT 'default',
    status        TEXT NOT NULL DEFAULT 'queued',
    stage         TEXT NOT NULL DEFAULT '',
    stage_detail  TEXT NOT NULL DEFAULT '',
    progress_pct  REAL,
    settings      TEXT NOT NULL DEFAULT '{}',
    timeline_json TEXT NOT NULL DEFAULT '{}',
    output_key    TEXT NOT NULL DEFAULT '',
    error         TEXT NOT NULL DEFAULT '',
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    finished_at   REAL
);
CREATE INDEX IF NOT EXISTS idx_render_project ON render_job(project_id, created_at DESC);

-- ── Providers, cost, references, QC ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS provider_configuration (
    id            TEXT PRIMARY KEY,
    workspace     TEXT NOT NULL DEFAULT 'default',
    kind          TEXT NOT NULL,                        -- image|video|voice|music|storage
    provider      TEXT NOT NULL,
    enabled       INTEGER NOT NULL DEFAULT 1,
    default_model TEXT NOT NULL DEFAULT '',
    settings      TEXT NOT NULL DEFAULT '{}',
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_provcfg ON provider_configuration(workspace, kind, provider);

CREATE TABLE IF NOT EXISTS usage_record (
    id            TEXT PRIMARY KEY,
    workspace     TEXT NOT NULL DEFAULT 'default',
    project_id    TEXT,
    job_id        TEXT,
    provider      TEXT NOT NULL DEFAULT '',
    model         TEXT NOT NULL DEFAULT '',
    asset_type    TEXT NOT NULL DEFAULT '',
    units         REAL NOT NULL DEFAULT 1,
    unit_label    TEXT NOT NULL DEFAULT '',
    estimated_cost REAL,
    actual_cost   REAL,
    currency      TEXT NOT NULL DEFAULT 'USD',
    ts            REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_ws ON usage_record(workspace, ts DESC);
CREATE INDEX IF NOT EXISTS idx_usage_project ON usage_record(project_id, ts DESC);

CREATE TABLE IF NOT EXISTS studio_budget (
    workspace     TEXT NOT NULL,
    month         TEXT NOT NULL,                        -- YYYY-MM
    limit_amount  REAL NOT NULL DEFAULT 0,
    currency      TEXT NOT NULL DEFAULT 'USD',
    updated_at    REAL NOT NULL,
    PRIMARY KEY (workspace, month)
);

CREATE TABLE IF NOT EXISTS visual_reference (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES studio_project(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL DEFAULT 'character',    -- character|location|style
    name          TEXT NOT NULL DEFAULT '',
    description   TEXT NOT NULL DEFAULT '',
    attributes    TEXT NOT NULL DEFAULT '{}',
    reference_asset_ids TEXT NOT NULL DEFAULT '[]',
    -- User attests they hold rights to any uploaded likeness reference.
    rights_attested INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_visref_project ON visual_reference(project_id, kind);

CREATE TABLE IF NOT EXISTS quality_check (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES studio_project(id) ON DELETE CASCADE,
    passed        INTEGER NOT NULL DEFAULT 0,
    blocking_count INTEGER NOT NULL DEFAULT 0,
    warning_count INTEGER NOT NULL DEFAULT 0,
    findings      TEXT NOT NULL DEFAULT '[]',
    created_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_qc_project ON quality_check(project_id, created_at DESC);

-- ── Missions (pipeline runs) ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS studio_mission (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES studio_project(id) ON DELETE CASCADE,
    workspace     TEXT NOT NULL DEFAULT 'default',
    mode          TEXT NOT NULL DEFAULT 'assisted',
    stop_after    TEXT NOT NULL DEFAULT 'storyboard',
    status        TEXT NOT NULL DEFAULT 'queued',
    current_stage TEXT NOT NULL DEFAULT '',
    stages        TEXT NOT NULL DEFAULT '[]',
    awaiting      TEXT NOT NULL DEFAULT '',
    error         TEXT NOT NULL DEFAULT '',
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mission_project ON studio_mission(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mission_status ON studio_mission(status, created_at);
"""


def init_db() -> None:
    """Create the schema once per process. Safe to call from any thread."""
    global _INITIALISED
    if _INITIALISED:
        return
    with _INIT_LOCK:
        if _INITIALISED:
            return
        conn = _connect()
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()
        _INITIALISED = True


# =============================================================================
# GENERIC HELPERS
# =============================================================================

def insert(table: str, data: dict) -> str:
    """Insert a row. `data` must already contain the id."""
    cols = list(data.keys())
    with _conn() as c:
        c.execute(
            f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            [data[col] for col in cols],
        )
    return data.get("id", "")


def update(table: str, row_id: str, patch: dict, id_col: str = "id") -> bool:
    """Patch a row by id. Silently touches `updated_at` when the column exists."""
    if not patch:
        return False
    patch = dict(patch)
    with _conn() as c:
        cols = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
        if "updated_at" in cols:
            patch.setdefault("updated_at", now())
        patch = {k: v for k, v in patch.items() if k in cols and k != id_col}
        if not patch:
            return False
        sets = ",".join(f"{k}=?" for k in patch)
        cur = c.execute(
            f"UPDATE {table} SET {sets} WHERE {id_col}=?",
            list(patch.values()) + [row_id],
        )
        return cur.rowcount > 0


def fetch_one(sql: str, params: tuple = (), json_fields: Iterable[str] = ()) -> Optional[dict]:
    with _conn() as c:
        return row_to_dict(c.execute(sql, params).fetchone(), json_fields)


def fetch_all(sql: str, params: tuple = (), json_fields: Iterable[str] = ()) -> list[dict]:
    with _conn() as c:
        return [row_to_dict(r, json_fields) for r in c.execute(sql, params).fetchall()]


def execute(sql: str, params: tuple = ()) -> int:
    with _conn() as c:
        return c.execute(sql, params).rowcount


# =============================================================================
# OWNERSHIP
# =============================================================================

class NotFound(Exception):
    """Raised when a row does not exist, or exists in another workspace.

    Deliberately the *same* exception for both cases so callers cannot use
    the error to probe for the existence of other workspaces' projects.
    """


def assert_project(project_id: str, workspace: str) -> dict:
    """The single ownership chokepoint. Every route resolves the project
    through here before touching any child row."""
    row = fetch_one(
        "SELECT * FROM studio_project WHERE id=? AND workspace=?",
        (project_id, workspace),
    )
    if not row:
        raise NotFound(f"project {project_id} not found in workspace {workspace}")
    return row


def touch_project(project_id: str, **patch) -> None:
    patch["updated_at"] = now()
    update("studio_project", project_id, patch)


# =============================================================================
# JOB LOGGING (append-only)
# =============================================================================

def log_job(job_id: str, message: str, level: str = "info") -> None:
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO job_log (job_id, ts, level, message) VALUES (?,?,?,?)",
                (job_id, now(), level, str(message)[:2000]),
            )
    except Exception:
        # Logging must never break the job it is describing.
        pass


def job_logs(job_id: str, limit: int = 200) -> list[dict]:
    return fetch_all(
        "SELECT ts, level, message FROM job_log WHERE job_id=? ORDER BY id DESC LIMIT ?",
        (job_id, limit),
    )


__all__ = [
    "init_db", "new_id", "now", "insert", "update", "fetch_one", "fetch_all",
    "execute", "assert_project", "touch_project", "log_job", "job_logs",
    "NotFound", "row_to_dict", "STUDIO_DB_FILE",
]
