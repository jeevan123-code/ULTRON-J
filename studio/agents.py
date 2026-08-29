"""
studio/agents.py — The LEBENX STUDIO agent team.

Each agent is a focused prompt plus strict output parsing on top of the
project's existing `llm_engine`. They produce *editable project data*, never
final artefacts: everything an agent writes lands in a table the user can
edit, regenerate, or override.

    🧠 RESEARCHER   facts, angles, misconceptions, hook, uncertainties
    ✍️  WRITER       title, hook, timed script body, call to action
    🎬 DIRECTOR     scene division, pacing, camera, asset-type decisions
    🎨 VISUAL       delegates to prompts.py (the prompt engine)
    ✂️  EDITOR       pacing analysis, repetition detection, B-roll suggestions
    🔍 CRITIC       reviews research/script/storyboard BEFORE money is spent
    ✅ QC           pre-render inspection of real project state

Two rules run through all of them:

1. **No fabricated sources.** The Researcher is instructed never to invent a
   citation. When no research tool is connected, the report is marked
   `evidence_mode='model_only'` and any URL the model emits anyway is
   stripped by `_sanitise_sources()` — a plausible-looking fake citation is
   worse than none.

2. **Structured output, defensively parsed.** LLMs return imperfect JSON, so
   `_json_call()` tolerates fences and prose, and every agent degrades to a
   usable result rather than throwing.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from . import db, prompts

try:
    from llm_engine import call_llm_batch
    LLM_AVAILABLE = True
except ImportError:  # pragma: no cover
    LLM_AVAILABLE = False

    def call_llm_batch(prompt: str, system: str = "", provider: str = None) -> str:
        raise RuntimeError("llm_engine is unavailable")


class AgentError(Exception):
    pass


# =============================================================================
# LLM PLUMBING
# =============================================================================

def _json_call(system: str, user: str, *, expect: str = "object") -> object:
    """Call the LLM and coerce the reply to JSON.

    Models wrap JSON in prose or fences no matter how firmly asked not to, so
    we extract the outermost balanced structure rather than trusting the whole
    reply to parse.
    """
    if not LLM_AVAILABLE:
        raise AgentError("no LLM provider is configured for this installation")

    system = system + (
        "\n\nRespond with valid JSON only. No markdown fences, no commentary "
        "before or after the JSON."
    )
    raw = call_llm_batch(user, system=system) or ""
    if not raw.strip():
        raise AgentError("the model returned an empty response")

    parsed = _extract_json(raw, expect)
    if parsed is None:
        raise AgentError("the model did not return parseable JSON")
    return parsed


def _extract_json(raw: str, expect: str = "object"):
    text = raw.strip()

    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass

    # Fall back to the outermost balanced object/array in the reply.
    open_ch, close_ch = ("[", "]") if expect == "array" else ("{", "}")
    start = text.find(open_ch)
    if start == -1:
        return None
    depth, in_str, escaped = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except (ValueError, TypeError):
                    return None
    return None


def _str_list(value, limit: int = 40) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out = []
    for item in value[:limit]:
        if isinstance(item, dict):
            item = item.get("text") or item.get("point") or item.get("fact") or ""
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


# =============================================================================
# 🧠 RESEARCHER
# =============================================================================

RESEARCH_SYSTEM = """You are the RESEARCH AGENT for a video production studio.

Your job is to prepare an accurate research brief for a video script.

ABSOLUTE RULES:
- NEVER invent a citation, URL, study name, author, or publication date.
- If you are drawing on general knowledge rather than a retrieved document,
  put the claim under "key_points" or "facts" and leave "sources" EMPTY.
- Put anything you are not confident about under "uncertainties", with a note
  on what would need to be checked.
- Prefer specific, checkable statements over vague generalities.
- Distinguish established findings from contested or preliminary ones.

Return JSON with exactly these keys:
{
  "key_points": [string],
  "facts": [string],
  "statistics": [string],
  "misconceptions": [string],
  "hook": string,
  "sources": [{"title": string, "url": string, "note": string}],
  "uncertainties": [string]
}"""


def _sanitise_sources(sources, evidence_mode: str) -> list[dict]:
    """Drop fabricated citations.

    When no research tool ran, the model has no retrieved document to cite,
    so any URL it produces is a guess. We keep the title as an unverified
    lead and discard the URL rather than presenting it as a source.
    """
    if not isinstance(sources, list):
        return []

    cleaned = []
    for src in sources[:20]:
        if isinstance(src, str):
            src = {"title": src, "url": "", "note": ""}
        if not isinstance(src, dict):
            continue
        title = str(src.get("title", "")).strip()
        url = str(src.get("url", "")).strip()
        if not title and not url:
            continue

        if evidence_mode != "search":
            cleaned.append({
                "title": title or url,
                "url": "",
                "note": "unverified lead — model recollection, not a retrieved "
                        "source. Confirm before citing.",
                "verified": False,
            })
        else:
            cleaned.append({"title": title or url, "url": url,
                            "note": str(src.get("note", "")).strip(),
                            "verified": bool(url)})
    return cleaned


def _run_search(topic: str) -> tuple[list[dict], str]:
    """Use the project's research tooling when it is actually available.

    Returns (sources, evidence_mode). We only claim 'search' when a tool ran
    and returned something.
    """
    try:
        from research_engine import deep_research  # type: ignore
    except ImportError:
        try:
            from action_engine import web_search  # type: ignore
        except ImportError:
            return [], "model_only"
        try:
            results = web_search(topic) or []
        except Exception:  # noqa: BLE001
            return [], "model_only"
        sources = [
            {"title": r.get("title", ""), "url": r.get("href") or r.get("url", ""),
             "note": (r.get("body") or "")[:300]}
            for r in results[:8] if isinstance(r, dict)
        ]
        return ([s for s in sources if s["url"]], "search" if sources else "model_only")

    try:
        report = deep_research(topic) or {}
    except Exception:  # noqa: BLE001
        return [], "model_only"
    sources = report.get("sources") or []
    return (sources, "search" if sources else "model_only")


def research(project_id: str, topic: str, *, audience: str = "",
             use_search: bool = True) -> dict:
    """Produce the research report and persist it."""
    sources, evidence_mode = ([], "model_only")
    if use_search:
        sources, evidence_mode = _run_search(topic)

    context = ""
    if evidence_mode == "search" and sources:
        context = "\n\nRetrieved sources you MAY cite (cite only these):\n" + "\n".join(
            f"- {s.get('title','')} — {s.get('url','')}" for s in sources[:8])
    else:
        context = ("\n\nNo research tool is connected, so you have NO retrieved "
                   "documents. Leave \"sources\" as an empty array.")

    user = (f"Topic: {topic}\n"
            f"Target audience: {audience or 'general audience'}"
            f"{context}")

    data = _json_call(RESEARCH_SYSTEM, user)
    if not isinstance(data, dict):
        raise AgentError("research agent returned an unexpected shape")

    model_sources = _sanitise_sources(data.get("sources"), evidence_mode)
    if evidence_mode == "search":
        # Prefer the actually-retrieved list over anything the model echoed.
        model_sources = _sanitise_sources(sources, "search")

    report = {
        "key_points": _str_list(data.get("key_points")),
        "facts": _str_list(data.get("facts")),
        "statistics": _str_list(data.get("statistics")),
        "misconceptions": _str_list(data.get("misconceptions")),
        "hook": str(data.get("hook", "")).strip(),
        "sources": model_sources,
        "uncertainties": _str_list(data.get("uncertainties")),
        "evidence_mode": evidence_mode,
    }

    if evidence_mode != "search":
        report["uncertainties"].insert(
            0, "No research tool was connected for this report — every claim "
               "comes from model recollection and none of it is source-backed.")

    _save_research(project_id, report)
    return report


def _save_research(project_id: str, report: dict) -> None:
    existing = db.fetch_one("SELECT id FROM research_report WHERE project_id=?",
                            (project_id,))
    payload = {
        "key_points": db._dumps(report["key_points"]),
        "facts": db._dumps(report["facts"]),
        "statistics": db._dumps(report["statistics"]),
        "misconceptions": db._dumps(report["misconceptions"]),
        "hook": report["hook"],
        "sources": db._dumps(report["sources"]),
        "uncertainties": db._dumps(report["uncertainties"]),
        "evidence_mode": report["evidence_mode"],
        "status": "ready",
    }
    if existing:
        db.update("research_report", existing["id"], payload)
    else:
        payload.update({"id": db.new_id("res"), "project_id": project_id,
                        "created_at": db.now(), "updated_at": db.now()})
        db.insert("research_report", payload)


def get_research(project_id: str) -> Optional[dict]:
    return db.fetch_one(
        "SELECT * FROM research_report WHERE project_id=?", (project_id,),
        json_fields=("key_points", "facts", "statistics", "misconceptions",
                     "sources", "uncertainties"))


# =============================================================================
# ✍️ WRITER
# =============================================================================

WRITER_SYSTEM = """You are the WRITER AGENT for a video production studio.

Write a narration script that a voice actor will read aloud. It must be
spoken language, not prose: short sentences, concrete images, no bullet
points, no stage directions inside the narration text.

PACING: assume about 2.5 spoken words per second. Hit the requested duration.

RULES:
- Open with a hook that earns the next ten seconds.
- One idea per segment. Segments run 6-15 seconds.
- Do not state statistics the research brief did not supply.
- Do not invent sources or attribute claims to named studies.

Return JSON:
{
  "title": string,
  "hook": string,
  "segments": [{"start_s": number, "end_s": number, "text": string}],
  "call_to_action": string
}
Segments must be contiguous: each start_s equals the previous end_s, the
first starts at 0, and the last end_s equals the target duration."""


def write_script(project_id: str, *, brief: dict,
                 research_report: Optional[dict] = None,
                 instruction: str = "") -> dict:
    duration = int(brief.get("duration_s") or 300)
    target_words = int(duration * 2.5)

    context = ""
    if research_report:
        def _block(label, items):
            return f"\n{label}:\n" + "\n".join(f"- {i}" for i in items[:10]) if items else ""
        context = (
            _block("Key points", research_report.get("key_points") or [])
            + _block("Facts", research_report.get("facts") or [])
            + _block("Statistics you may use", research_report.get("statistics") or [])
            + _block("Misconceptions to address", research_report.get("misconceptions") or [])
        )
        if research_report.get("evidence_mode") != "search":
            context += ("\n\nNOTE: this research is model recollection, not "
                        "source-backed. Do not present any of it as a cited finding.")

    user = (
        f"Topic: {brief.get('topic', '')}\n"
        f"Video type: {brief.get('video_type', 'youtube_video')}\n"
        f"Platform: {brief.get('platform', 'youtube')}\n"
        f"Audience: {brief.get('audience', 'general')}\n"
        f"Tone: {brief.get('tone', 'engaging and clear')}\n"
        f"Language: {brief.get('language', 'en')}\n"
        f"Target duration: {duration} seconds (~{target_words} words)\n"
        f"{context}"
        f"{chr(10) + 'Additional instruction: ' + instruction if instruction else ''}"
    )

    data = _json_call(WRITER_SYSTEM, user)
    if not isinstance(data, dict):
        raise AgentError("writer agent returned an unexpected shape")

    segments = _normalise_segments(data.get("segments"), duration)
    if not segments:
        raise AgentError("writer agent returned no usable script segments")

    return {
        "title": str(data.get("title", "")).strip() or brief.get("topic", "Untitled"),
        "hook": str(data.get("hook", "")).strip(),
        "call_to_action": str(data.get("call_to_action", "")).strip(),
        "segments": segments,
        "body": "\n\n".join(s["text"] for s in segments),
        "word_count": sum(len(s["text"].split()) for s in segments),
    }


def _normalise_segments(raw, duration: int) -> list[dict]:
    """Repair the timing the model returned.

    Models routinely emit overlapping or gapped ranges. Rather than reject the
    whole script we rebuild a contiguous timeline from the segment texts,
    weighting each by word count so timings stay proportional to what is
    actually said.
    """
    if not isinstance(raw, list):
        return []

    texts = []
    for seg in raw:
        if isinstance(seg, str):
            text = seg
        elif isinstance(seg, dict):
            text = str(seg.get("text", ""))
        else:
            continue
        text = text.strip()
        if text:
            texts.append(text)

    if not texts:
        return []

    words = [max(1, len(t.split())) for t in texts]
    total_words = sum(words)

    segments, cursor = [], 0.0
    for i, (text, count) in enumerate(zip(texts, words)):
        span = duration * (count / total_words)
        end = duration if i == len(texts) - 1 else round(cursor + span, 2)
        segments.append({"idx": i, "start_s": round(cursor, 2),
                         "end_s": round(end, 2), "text": text})
        cursor = end
    return segments


def save_script(project_id: str, script: dict, *, source: str = "ai") -> str:
    """Persist a script as a new version, superseding the previous current one."""
    db.execute("UPDATE video_script SET is_current=0 WHERE project_id=?", (project_id,))
    prev = db.fetch_one(
        "SELECT MAX(version) AS v FROM video_script WHERE project_id=?", (project_id,))
    version = int((prev or {}).get("v") or 0) + 1

    script_id = db.new_id("scr")
    db.insert("video_script", {
        "id": script_id, "project_id": project_id, "version": version,
        "is_current": 1, "title": script.get("title", ""),
        "hook": script.get("hook", ""), "body": script.get("body", ""),
        "call_to_action": script.get("call_to_action", ""),
        "word_count": script.get("word_count", 0), "source": source,
        "created_at": db.now(), "updated_at": db.now(),
    })

    for seg in script.get("segments", []):
        db.insert("script_segment", {
            "id": db.new_id("seg"), "script_id": script_id,
            "project_id": project_id, "idx": seg["idx"],
            "start_s": seg["start_s"], "end_s": seg["end_s"],
            "text": seg["text"], "created_at": db.now(),
        })
    return script_id


def get_script(project_id: str) -> Optional[dict]:
    script = db.fetch_one(
        "SELECT * FROM video_script WHERE project_id=? AND is_current=1 "
        "ORDER BY version DESC LIMIT 1", (project_id,))
    if not script:
        return None
    script["segments"] = db.fetch_all(
        "SELECT * FROM script_segment WHERE script_id=? ORDER BY idx",
        (script["id"],))
    return script


REWRITE_MODES = {
    "shorter": "Cut it to roughly 70% of its length. Keep every substantive point.",
    "longer": "Expand to roughly 130%. Add concrete detail and examples, not filler.",
    "humanize": "Rewrite so it sounds like a person talking, not an essay read aloud. "
                "Contractions, varied sentence length, no corporate register.",
    "punchier": "Tighten every sentence. Cut hedging. Lead with the strongest image.",
    "simpler": "Rewrite for a reader with no background in the subject. Plain words.",
    "stronger_hook": "Rewrite the opening so the first sentence creates an open loop "
                     "the viewer needs closed.",
}


def rewrite_script(project_id: str, *, brief: dict, script: dict,
                   mode: str = "", instruction: str = "",
                   section: str = "") -> dict:
    """Regenerate a script or one section of it under a transformation."""
    directive = REWRITE_MODES.get(mode, "") or instruction
    if not directive:
        raise AgentError("no rewrite mode or instruction supplied")

    target = script.get("body", "")
    if section == "hook":
        target = script.get("hook", "")
    elif section == "cta":
        target = script.get("call_to_action", "")

    user = (
        f"Rewrite this {section or 'script'} for a "
        f"{brief.get('duration_s', 300)}-second {brief.get('video_type', 'video')}.\n\n"
        f"Transformation: {directive}\n\n"
        f"Current text:\n{target}"
    )
    return write_script(project_id, brief=brief, instruction=user)


# =============================================================================
# 🎬 DIRECTOR
# =============================================================================

DIRECTOR_SYSTEM = """You are the DIRECTOR AGENT for a video production studio.

Break a narration script into shot-by-shot scenes.

For each scene decide:
- visual: what is literally on screen. Concrete and filmable — a specific
  subject, setting, light and framing. Never abstract ("the concept of time").
- camera: one movement (static, slow push-in, pull-back, pan left, tilt up,
  tracking, handheld drift).
- asset_type: "ai_video" ONLY when motion carries the meaning (a gesture, a
  process unfolding). "ai_image" when a strong still works — it is far cheaper
  and more reliable. "text_animation" for pure data or quotes. Prefer
  ai_image: aim for at most a third of scenes as ai_video.
- transition: cut, fade, dissolve, or slide. Default to cut.

Keep visual continuity: recurring subjects must be described identically
every time they appear.

Return JSON:
{
  "style": string,
  "pacing": string,
  "scenes": [{
     "narration": string, "visual": string, "camera": string,
     "asset_type": "ai_video"|"ai_image"|"text_animation"|"stock",
     "transition": "cut"|"fade"|"dissolve"|"slide",
     "duration_s": number, "characters": [string]
  }]
}"""


def direct(project_id: str, *, brief: dict, script: dict) -> dict:
    segments = script.get("segments", [])
    if not segments:
        raise AgentError("cannot build a storyboard without script segments")

    refs = prompts.load_references(project_id)
    ref_block = ""
    if refs:
        ref_block = "\n\nVisual Bible — describe these consistently:\n" + "\n".join(
            f"- {r['name']} ({r['kind']}): {r['description']}" for r in refs[:12])

    script_text = "\n".join(
        f"[{s['start_s']:.1f}-{s['end_s']:.1f}] {s['text']}" for s in segments)

    user = (
        f"Video type: {brief.get('video_type', 'youtube_video')}\n"
        f"Visual style: {brief.get('visual_style', 'cinematic')}\n"
        f"Aspect ratio: {brief.get('aspect_ratio', '16:9')}\n"
        f"Total duration: {brief.get('duration_s', 300)} seconds\n"
        f"{ref_block}\n\nScript:\n{script_text}"
    )

    data = _json_call(DIRECTOR_SYSTEM, user)
    if not isinstance(data, dict):
        raise AgentError("director agent returned an unexpected shape")

    raw_scenes = data.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise AgentError("director agent returned no scenes")

    total = float(brief.get("duration_s") or 300)
    scenes = _normalise_scenes(raw_scenes, total)

    return {
        "style": str(data.get("style", brief.get("visual_style", "cinematic"))),
        "pacing": str(data.get("pacing", "")),
        "scenes": scenes,
    }


_VALID_ASSET_TYPES = {"ai_video", "ai_image", "text_animation", "stock",
                      "user_upload", "screen_recording"}
_VALID_TRANSITIONS = {"cut", "fade", "dissolve", "slide"}


def _normalise_scenes(raw_scenes: list, total_duration: float) -> list[dict]:
    """Clamp the director's output to a contiguous, valid timeline."""
    scenes = []
    for item in raw_scenes:
        if not isinstance(item, dict):
            continue
        asset_type = str(item.get("asset_type", "ai_image")).lower().strip()
        transition = str(item.get("transition", "cut")).lower().strip()
        try:
            duration = float(item.get("duration_s") or 0)
        except (TypeError, ValueError):
            duration = 0.0

        scenes.append({
            "narration": str(item.get("narration", "")).strip(),
            "visual_description": str(item.get("visual") or
                                      item.get("visual_description", "")).strip(),
            "camera": str(item.get("camera", "static")).strip(),
            "asset_type": asset_type if asset_type in _VALID_ASSET_TYPES else "ai_image",
            "transition": transition if transition in _VALID_TRANSITIONS else "cut",
            "duration_s": duration,
            "characters": _str_list(item.get("characters"), limit=8),
        })

    if not scenes:
        return []

    # Scale durations to fill exactly the target runtime.
    stated = sum(s["duration_s"] for s in scenes)
    if stated <= 0:
        for scene in scenes:
            scene["duration_s"] = total_duration / len(scenes)
    else:
        factor = total_duration / stated
        for scene in scenes:
            scene["duration_s"] = round(max(0.5, scene["duration_s"] * factor), 2)

    cursor = 0.0
    for i, scene in enumerate(scenes):
        scene["idx"] = i
        scene["start_s"] = round(cursor, 2)
        cursor += scene["duration_s"]
    return scenes


def save_storyboard(project_id: str, board: dict, *, brief: dict,
                    workspace: str = "default") -> str:
    """Persist a storyboard, generating each scene's provider-tuned prompt."""
    from .providers import registry

    db.execute("UPDATE storyboard SET is_current=0 WHERE project_id=?", (project_id,))
    prev = db.fetch_one("SELECT MAX(version) AS v FROM storyboard WHERE project_id=?",
                        (project_id,))
    version = int((prev or {}).get("v") or 0) + 1

    board_id = db.new_id("sbd")
    db.insert("storyboard", {
        "id": board_id, "project_id": project_id, "version": version,
        "is_current": 1, "style": board.get("style", ""),
        "pacing": board.get("pacing", ""), "notes": "",
        "created_at": db.now(), "updated_at": db.now(),
    })

    style = brief.get("visual_style", "cinematic")
    aspect = brief.get("aspect_ratio", "16:9")

    for scene in board["scenes"]:
        kind = "video" if scene["asset_type"] == "ai_video" else "image"
        # Format for whichever provider would actually run this scene. If
        # none is connected we still build a prompt (planning must work
        # without providers) using the neutral default formatter.
        try:
            provider_name = registry.resolve(kind, workspace).name
        except registry.NoProviderAvailable:
            provider_name = ""

        built = prompts.build_prompt(
            description=scene["visual_description"], style=style,
            camera=scene["camera"], provider=provider_name, kind=kind,
            project_id=project_id, character_refs=scene.get("characters"),
            aspect_ratio=aspect,
        )

        db.insert("scene", {
            "id": db.new_id("scn"), "storyboard_id": board_id,
            "project_id": project_id, "idx": scene["idx"],
            "start_s": scene["start_s"], "duration_s": scene["duration_s"],
            "narration": scene["narration"],
            "visual_description": scene["visual_description"],
            "camera": scene["camera"], "transition": scene["transition"],
            "transition_duration": 0.5, "asset_type": scene["asset_type"],
            "generation_prompt": built["prompt"],
            "negative_prompt": built["negative_prompt"],
            "status": "pending",
            "character_refs": db._dumps(scene.get("characters", [])),
            "created_at": db.now(), "updated_at": db.now(),
        })
    return board_id


def get_storyboard(project_id: str) -> Optional[dict]:
    board = db.fetch_one(
        "SELECT * FROM storyboard WHERE project_id=? AND is_current=1 "
        "ORDER BY version DESC LIMIT 1", (project_id,))
    if not board:
        return None
    board["scenes"] = db.fetch_all(
        "SELECT * FROM scene WHERE storyboard_id=? ORDER BY idx",
        (board["id"],), json_fields=("character_refs",))
    return board


# =============================================================================
# 🔍 CRITIC
# =============================================================================

CRITIC_SYSTEM = """You are the CRITIC AGENT. You review work BEFORE expensive
asset generation begins, when fixing a problem is still cheap.

Be specific and actionable. "The hook is weak" is useless; "the hook states a
fact instead of opening a question — try leading with the phone-unlock
statistic" is useful.

Flag especially:
- factual claims presented with unearned confidence
- statistics with no stated basis
- a hook that does not create curiosity
- scenes whose visual does not match its narration
- repetitive or redundant scenes
- pacing that will bore the viewer

Return JSON:
{
  "verdict": "approve"|"revise",
  "score": number (0-10),
  "findings": [{"severity":"blocking"|"warning"|"note", "target": string,
                "issue": string, "recommendation": string}]
}"""


def critique(*, research_report: Optional[dict] = None,
             script: Optional[dict] = None,
             storyboard: Optional[dict] = None) -> dict:
    """Review whichever artefacts exist before money is spent."""
    parts = []
    if research_report:
        parts.append("RESEARCH:\n" + json.dumps({
            "key_points": research_report.get("key_points", [])[:10],
            "statistics": research_report.get("statistics", [])[:10],
            "evidence_mode": research_report.get("evidence_mode"),
            "sources": len(research_report.get("sources") or []),
        }, indent=2))
    if script:
        parts.append(f"SCRIPT:\nTitle: {script.get('title')}\n"
                     f"Hook: {script.get('hook')}\n\n{script.get('body', '')[:4000]}")
    if storyboard:
        scene_lines = [
            f"{s['idx']}. [{s['duration_s']}s, {s['asset_type']}] "
            f"{s['visual_description'][:160]}"
            for s in storyboard.get("scenes", [])[:40]
        ]
        parts.append("STORYBOARD:\n" + "\n".join(scene_lines))

    if not parts:
        raise AgentError("nothing to critique")

    data = _json_call(CRITIC_SYSTEM, "\n\n---\n\n".join(parts))
    if not isinstance(data, dict):
        raise AgentError("critic agent returned an unexpected shape")

    findings = []
    for item in (data.get("findings") or [])[:30]:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity", "note")).lower()
        findings.append({
            "severity": severity if severity in ("blocking", "warning", "note") else "note",
            "target": str(item.get("target", "")),
            "issue": str(item.get("issue", "")),
            "recommendation": str(item.get("recommendation", "")),
        })

    return {
        "verdict": "revise" if str(data.get("verdict")) == "revise" else "approve",
        "score": _safe_number(data.get("score")),
        "findings": findings,
        "blocking": sum(1 for f in findings if f["severity"] == "blocking"),
    }


def _safe_number(value, default: float = 0.0) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return default


# =============================================================================
# ✂️ EDITOR
# =============================================================================

def editor_insights(project_id: str) -> dict:
    """Analyse the storyboard for pacing and repetition problems.

    Deliberately computed from real project data rather than asked of an LLM:
    scene lengths and text similarity are measurable, and a measured finding
    is one the user can trust and act on.
    """
    board = get_storyboard(project_id)
    if not board or not board.get("scenes"):
        return {"insights": [], "note": "no storyboard to analyse"}

    scenes = board["scenes"]
    insights = []
    durations = [s["duration_s"] for s in scenes]
    mean = sum(durations) / len(durations)

    for scene in scenes:
        if scene["duration_s"] > mean * 2.2 and scene["duration_s"] > 12:
            insights.append({
                "type": "pacing", "severity": "warning", "scene": scene["idx"],
                "insight": f"Scene {scene['idx'] + 1} runs {scene['duration_s']:.1f}s "
                           f"against a {mean:.1f}s average.",
                "recommendation": "Split it, or cut away to a second visual "
                                  "partway through to keep the eye moving.",
            })
        if scene["duration_s"] < 1.2:
            insights.append({
                "type": "pacing", "severity": "warning", "scene": scene["idx"],
                "insight": f"Scene {scene['idx'] + 1} is only {scene['duration_s']:.1f}s.",
                "recommendation": "Merge it with a neighbour — below about 1.2s "
                                  "a shot reads as a glitch.",
            })

    # Adjacent-scene similarity, on visual description word overlap.
    for i in range(1, len(scenes)):
        prev, curr = scenes[i - 1], scenes[i]
        similarity = _jaccard(prev["visual_description"], curr["visual_description"])
        if similarity > 0.6:
            insights.append({
                "type": "repetition", "severity": "warning", "scene": curr["idx"],
                "insight": f"Scene {curr['idx'] + 1} is visually {similarity:.0%} "
                           f"similar to Scene {prev['idx'] + 1}.",
                "recommendation": "Change the framing — if the previous shot was "
                                  "wide, make this one a close-up.",
            })

    video_scenes = [s for s in scenes if s["asset_type"] == "ai_video"]
    if len(video_scenes) > len(scenes) * 0.4:
        insights.append({
            "type": "cost", "severity": "note", "scene": None,
            "insight": f"{len(video_scenes)} of {len(scenes)} scenes are AI video, "
                       f"which is the most expensive and least predictable asset type.",
            "recommendation": "Convert static-subject scenes to AI image with a "
                              "slow push-in applied at render time.",
        })

    runs = _consecutive_runs([s["transition"] for s in scenes])
    if runs and runs[0][1] >= 6 and runs[0][0] == "cut":
        insights.append({
            "type": "transition", "severity": "note", "scene": None,
            "insight": f"{runs[0][1]} consecutive hard cuts.",
            "recommendation": "A dissolve at a topic change signals a shift in "
                              "argument to the viewer.",
        })

    return {
        "insights": insights,
        "scene_count": len(scenes),
        "mean_duration_s": round(mean, 2),
        "video_scene_count": len(video_scenes),
        "note": "Recommendations only — no change is applied without your approval.",
    }


def _jaccard(a: str, b: str) -> float:
    stop = {"a", "an", "the", "of", "in", "on", "at", "to", "and", "with", "is"}
    set_a = {w for w in re.findall(r"[a-z]{3,}", a.lower())} - stop
    set_b = {w for w in re.findall(r"[a-z]{3,}", b.lower())} - stop
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _consecutive_runs(values: list) -> list[tuple]:
    if not values:
        return []
    runs, current, count = [], values[0], 1
    for value in values[1:]:
        if value == current:
            count += 1
        else:
            runs.append((current, count))
            current, count = value, 1
    runs.append((current, count))
    return sorted(runs, key=lambda r: -r[1])


# =============================================================================
# 🎨 THUMBNAIL LAB
# =============================================================================

THUMBNAIL_SYSTEM = """You are a YouTube thumbnail strategist.

Produce three distinct concepts. Each must be a single readable image at
phone size: one clear subject, high contrast, at most four words of text.

Return JSON:
{"concepts": [{
   "name": string, "composition": string, "subject": string,
   "background": string, "text": string, "emotion": string,
   "curiosity_factor": string, "generation_prompt": string
}]}"""


def thumbnail_concepts(*, title: str, topic: str, style: str = "cinematic") -> list[dict]:
    data = _json_call(THUMBNAIL_SYSTEM,
                      f"Video title: {title}\nTopic: {topic}\nVisual style: {style}")
    concepts = data.get("concepts") if isinstance(data, dict) else None
    if not isinstance(concepts, list):
        raise AgentError("thumbnail agent returned an unexpected shape")

    out = []
    for i, concept in enumerate(concepts[:5]):
        if not isinstance(concept, dict):
            continue
        out.append({
            "id": chr(65 + i),
            "name": str(concept.get("name", f"Concept {chr(65 + i)}")),
            "composition": str(concept.get("composition", "")),
            "subject": str(concept.get("subject", "")),
            "background": str(concept.get("background", "")),
            "text": str(concept.get("text", ""))[:60],
            "emotion": str(concept.get("emotion", "")),
            "curiosity_factor": str(concept.get("curiosity_factor", "")),
            "generation_prompt": str(concept.get("generation_prompt", "")),
        })
    return out


# =============================================================================
# 📺 YOUTUBE METADATA
# =============================================================================

YOUTUBE_SYSTEM = """You are a YouTube packaging strategist.

Return JSON:
{
  "titles": [string],            // 5 options, under 60 characters each
  "description": string,         // 2-3 paragraphs, first line is the hook
  "tags": [string],              // 12-15, specific over generic
  "chapters": [{"time_s": number, "label": string}]
}
Do not promise content the script does not contain. Chapter times must fall
within the video's duration."""


def youtube_package(*, script: dict, brief: dict) -> dict:
    segments = script.get("segments", [])
    outline = "\n".join(f"[{s['start_s']:.0f}s] {s['text'][:120]}"
                        for s in segments[:40])
    data = _json_call(YOUTUBE_SYSTEM,
                      f"Title: {script.get('title')}\n"
                      f"Duration: {brief.get('duration_s')}s\n"
                      f"Audience: {brief.get('audience')}\n\nScript outline:\n{outline}")
    if not isinstance(data, dict):
        raise AgentError("youtube agent returned an unexpected shape")

    duration = float(brief.get("duration_s") or 0)
    chapters = []
    for chapter in (data.get("chapters") or [])[:20]:
        if not isinstance(chapter, dict):
            continue
        time_s = _safe_number(chapter.get("time_s"), -1)
        if 0 <= time_s <= duration:
            chapters.append({"time_s": time_s, "label": str(chapter.get("label", ""))})

    return {
        "titles": _str_list(data.get("titles"), limit=8),
        "description": str(data.get("description", "")),
        "tags": _str_list(data.get("tags"), limit=20),
        "chapters": sorted(chapters, key=lambda c: c["time_s"]),
    }
