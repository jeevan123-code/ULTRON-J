"""
studio/captions.py — Caption engine.

Cues are built from the best timing evidence available, and the track records
which that was:

    timing_source='voice'   real measured voiceover durations. Accurate.
    timing_source='script'  planned script segment timings. Approximate —
                            correct only if narration matches the plan.
    timing_source='alignment' word-level forced alignment (only when an
                            aligner is actually installed).

That distinction is stored and surfaced, because captions timed off a plan
that the narration later diverged from will drift, and the user needs to know
which kind they are looking at before burning them into a render.

Long segments are split into readable cues on sentence and clause boundaries,
respecting the ~42-characters-per-line, two-line convention that keeps
subtitles readable, and a minimum on-screen time so a cue never flashes past
faster than it can be read.
"""

from __future__ import annotations

import re
from typing import Optional

from . import db

MAX_CHARS_PER_LINE = 42
MAX_LINES = 2
MAX_CUE_CHARS = MAX_CHARS_PER_LINE * MAX_LINES
MIN_CUE_S = 1.0
MAX_CUE_S = 6.0
#: Reading speed used to apportion time within a split segment.
CHARS_PER_SECOND = 17.0


CAPTION_STYLES = {
    "minimal": {
        "label": "Minimal",
        "font": "Inter, Helvetica, sans-serif", "font_size": 42,
        "color": "#FFFFFF", "background": "rgba(0,0,0,0.55)",
        "position": "bottom", "weight": 500, "outline": 0,
        "uppercase": False, "highlight": False,
    },
    "bold": {
        "label": "Bold",
        "font": "Inter, Helvetica, sans-serif", "font_size": 56,
        "color": "#FFFFFF", "background": "transparent",
        "position": "bottom", "weight": 800, "outline": 4,
        "outline_color": "#000000", "uppercase": False, "highlight": False,
    },
    "social": {
        "label": "Social Media",
        "font": "Inter, Helvetica, sans-serif", "font_size": 64,
        "color": "#FFFFFF", "background": "transparent",
        "position": "center", "weight": 900, "outline": 6,
        "outline_color": "#000000", "uppercase": True, "highlight": True,
        "highlight_color": "#FFE24A",
    },
    "documentary": {
        "label": "Documentary",
        "font": "Georgia, serif", "font_size": 38,
        "color": "#F2F2F2", "background": "rgba(0,0,0,0.4)",
        "position": "bottom", "weight": 400, "outline": 0,
        "uppercase": False, "highlight": False,
    },
}


# =============================================================================
# CUE BUILDING
# =============================================================================

def _split_text(text: str) -> list[str]:
    """Break a long line into readable cue-sized chunks.

    Prefers sentence ends, then clause boundaries, then word boundaries —
    breaking mid-clause is what makes machine captions hard to read.
    """
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return []
    if len(text) <= MAX_CUE_CHARS:
        return [text]

    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []

    for sentence in sentences:
        if len(sentence) <= MAX_CUE_CHARS:
            if chunks and len(chunks[-1]) + len(sentence) + 1 <= MAX_CUE_CHARS:
                chunks[-1] = f"{chunks[-1]} {sentence}"
            else:
                chunks.append(sentence)
            continue

        # Too long even alone: split on clause punctuation, then words.
        parts = re.split(r"(?<=[,;:—])\s+", sentence)
        buffer = ""
        for part in parts:
            while len(part) > MAX_CUE_CHARS:
                cut = part.rfind(" ", 0, MAX_CUE_CHARS)
                cut = cut if cut > 0 else MAX_CUE_CHARS
                if buffer:
                    chunks.append(buffer)
                    buffer = ""
                chunks.append(part[:cut].strip())
                part = part[cut:].strip()
            if len(buffer) + len(part) + 1 <= MAX_CUE_CHARS:
                buffer = f"{buffer} {part}".strip()
            else:
                if buffer:
                    chunks.append(buffer)
                buffer = part
        if buffer:
            chunks.append(buffer)

    return [c.strip() for c in chunks if c.strip()]


def _cues_for_span(text: str, start_s: float, end_s: float) -> list[dict]:
    """Distribute one narration span across cues, weighted by length."""
    chunks = _split_text(text)
    if not chunks:
        return []

    span = max(0.1, end_s - start_s)
    total_chars = sum(len(c) for c in chunks) or 1

    cues, cursor = [], start_s
    for i, chunk in enumerate(chunks):
        share = span * (len(chunk) / total_chars)
        # Keep a cue on screen long enough to actually read.
        share = max(MIN_CUE_S, min(MAX_CUE_S, share))
        cue_end = end_s if i == len(chunks) - 1 else min(cursor + share, end_s)
        if cue_end <= cursor:
            cue_end = min(cursor + MIN_CUE_S, end_s)
        cues.append({"start_s": round(cursor, 3), "end_s": round(cue_end, 3),
                     "text": chunk})
        cursor = cue_end
        if cursor >= end_s:
            break
    return cues


def build_cues(project_id: str) -> dict:
    """Build the cue list from the strongest timing evidence available."""
    voiceovers = db.fetch_all(
        "SELECT scene_id, text, duration_s FROM voiceover "
        "WHERE project_id=? AND scene_id IS NOT NULL AND duration_s IS NOT NULL",
        (project_id,))

    scenes = db.fetch_all(
        """SELECT s.* FROM scene s JOIN storyboard b ON b.id = s.storyboard_id
           WHERE s.project_id=? AND b.is_current=1 ORDER BY s.idx""",
        (project_id,))

    # Preferred path: real measured narration durations, laid end to end.
    if voiceovers and scenes:
        by_scene = {v["scene_id"]: v for v in voiceovers}
        if all(s["id"] in by_scene for s in scenes):
            cues, cursor = [], 0.0
            for scene in scenes:
                voiceover = by_scene[scene["id"]]
                duration = float(voiceover["duration_s"])
                cues.extend(_cues_for_span(
                    voiceover["text"] or scene["narration"], cursor, cursor + duration))
                cursor += duration
            return {"cues": cues, "timing_source": "voice",
                    "note": "Timed from measured voiceover durations."}

    # Fallback: scene plan timings.
    if scenes:
        cues = []
        for scene in scenes:
            if not scene["narration"].strip():
                continue
            cues.extend(_cues_for_span(
                scene["narration"], float(scene["start_s"]),
                float(scene["start_s"]) + float(scene["duration_s"])))
        return {"cues": cues, "timing_source": "script",
                "note": ("Timed from the planned script, not from generated audio. "
                         "These will drift if the narration runs to a different "
                         "length — regenerate after voice generation.")}

    # Last resort: raw script segments.
    script = db.fetch_one(
        "SELECT id FROM video_script WHERE project_id=? AND is_current=1 "
        "ORDER BY version DESC LIMIT 1", (project_id,))
    if script:
        segments = db.fetch_all(
            "SELECT * FROM script_segment WHERE script_id=? ORDER BY idx",
            (script["id"],))
        cues = []
        for seg in segments:
            cues.extend(_cues_for_span(seg["text"], seg["start_s"], seg["end_s"]))
        return {"cues": cues, "timing_source": "script",
                "note": "Timed from planned script segments; not yet aligned to audio."}

    return {"cues": [], "timing_source": "script", "note": "nothing to caption"}


def save_track(project_id: str, *, style: str = "minimal",
               language: str = "en", cues: Optional[list] = None,
               timing_source: str = "script",
               style_config: Optional[dict] = None) -> str:
    if cues is None:
        built = build_cues(project_id)
        cues, timing_source = built["cues"], built["timing_source"]

    existing = db.fetch_one(
        "SELECT id FROM caption_track WHERE project_id=? AND language=?",
        (project_id, language))

    payload = {
        "style": style if style in CAPTION_STYLES else "minimal",
        "style_config": db._dumps(style_config or CAPTION_STYLES.get(style, {})),
        "cues": db._dumps(cues),
        "timing_source": timing_source,
    }

    if existing:
        db.update("caption_track", existing["id"], payload)
        return existing["id"]

    track_id = db.new_id("cap")
    payload.update({"id": track_id, "project_id": project_id, "language": language,
                    "burned_in": 0, "created_at": db.now(), "updated_at": db.now()})
    db.insert("caption_track", payload)
    return track_id


def get_track(project_id: str, language: str = "en") -> Optional[dict]:
    return db.fetch_one(
        "SELECT * FROM caption_track WHERE project_id=? AND language=?",
        (project_id, language), json_fields=("cues", "style_config"))


# =============================================================================
# EXPORT FORMATS
# =============================================================================

def _timestamp(seconds: float, *, comma: bool = True) -> str:
    seconds = max(0.0, float(seconds))
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis == 1000:  # rounding carried into the next second
        secs, millis = secs + 1, 0
    sep = "," if comma else "."
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{sep}{millis:03d}"


def to_srt(cues: list[dict]) -> str:
    blocks = []
    for i, cue in enumerate(cues, start=1):
        blocks.append(
            f"{i}\n"
            f"{_timestamp(cue['start_s'])} --> {_timestamp(cue['end_s'])}\n"
            f"{_wrap(cue['text'])}\n"
        )
    return "\n".join(blocks)


def to_vtt(cues: list[dict]) -> str:
    lines = ["WEBVTT", ""]
    for i, cue in enumerate(cues, start=1):
        lines.append(str(i))
        lines.append(f"{_timestamp(cue['start_s'], comma=False)} --> "
                     f"{_timestamp(cue['end_s'], comma=False)}")
        lines.append(_wrap(cue["text"]))
        lines.append("")
    return "\n".join(lines)


def _wrap(text: str) -> str:
    """Wrap to at most two balanced lines."""
    text = text.strip()
    if len(text) <= MAX_CHARS_PER_LINE:
        return text
    words, lines, current = text.split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 <= MAX_CHARS_PER_LINE:
            current = f"{current} {word}".strip()
        else:
            lines.append(current)
            current = word
        if len(lines) == MAX_LINES - 1 and len(current) > MAX_CHARS_PER_LINE:
            break
    if current:
        lines.append(current)
    return "\n".join(lines[:MAX_LINES])


def find_gaps(cues: list[dict], total_duration: float,
              threshold_s: float = 3.0) -> list[dict]:
    """Stretches of video with no caption — a QC signal, not an error.

    A gap is legitimate when there is genuinely no narration there, so these
    are reported for review rather than treated as failures.
    """
    if not cues:
        return ([{"start_s": 0, "end_s": total_duration, "duration_s": total_duration}]
                if total_duration > threshold_s else [])

    ordered = sorted(cues, key=lambda c: c["start_s"])
    gaps, cursor = [], 0.0
    for cue in ordered:
        if cue["start_s"] - cursor > threshold_s:
            gaps.append({"start_s": round(cursor, 2),
                         "end_s": round(cue["start_s"], 2),
                         "duration_s": round(cue["start_s"] - cursor, 2)})
        cursor = max(cursor, cue["end_s"])
    if total_duration - cursor > threshold_s:
        gaps.append({"start_s": round(cursor, 2), "end_s": round(total_duration, 2),
                     "duration_s": round(total_duration - cursor, 2)})
    return gaps


def list_styles() -> list[dict]:
    return [{"id": key, **val} for key, val in CAPTION_STYLES.items()]
