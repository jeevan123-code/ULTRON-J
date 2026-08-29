"""
Studio acceptance tests.

The theme running through these: the Studio must be *honest*. The tests that
matter most are the ones asserting it refuses to fake things — no synthetic
assets when no provider is connected, no invented citations, no fabricated
progress percentages, no silent timing distortion.

Run: .testvenv/bin/python -m pytest tests/test_studio.py -v
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Point the Studio at throwaway storage before anything imports config.
_TMP = tempfile.mkdtemp(prefix="studio-test-")
os.environ["STUDIO_MEDIA_DIR"] = os.path.join(_TMP, "media")

import studio.db as db                                    # noqa: E402
from studio import captions, cost, jobs, prompts, quality  # noqa: E402
from studio import render, timeline as tl                  # noqa: E402
from studio.providers import registry                      # noqa: E402
from studio.providers.base import (                        # noqa: E402
    Capabilities, GenerationRequest, JobState, NotConnected, ProviderStatus,
)
from studio.storage import LocalStorageProvider, StorageError, sanitize_key  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch, tmp_path):
    """Each test gets its own database file, and no live worker pool.

    Workers must be stopped: importing `app` elsewhere in the suite calls
    `init_studio()`, which starts real daemon workers. Those poll whatever
    `db.STUDIO_DB_FILE` currently points at — including this test's database —
    and would race to claim the jobs these tests drive inline. Stopping them
    makes the handler tests deterministic rather than order-dependent.
    """
    jobs.stop_workers()
    monkeypatch.setattr(db, "STUDIO_DB_FILE", str(tmp_path / "studio.db"))
    monkeypatch.setattr(db, "_INITIALISED", False)
    db.init_db()
    yield


def _project(workspace="w1", **kw):
    pid = db.new_id("proj")
    db.insert("studio_project", {
        "id": pid, "workspace": workspace, "owner": "u", "title": "T",
        "idea": "an idea", "created_at": db.now(), "updated_at": db.now(), **kw,
    })
    db.insert("video_brief", {
        "id": db.new_id("brf"), "project_id": pid, "topic": "t",
        "duration_s": 30, "aspect_ratio": "16:9",
        "created_at": db.now(), "updated_at": db.now(),
    })
    return pid


# =============================================================================
# OWNERSHIP
# =============================================================================

def test_project_is_scoped_to_its_workspace():
    pid = _project("w1")
    assert db.assert_project(pid, "w1")["id"] == pid
    with pytest.raises(db.NotFound):
        db.assert_project(pid, "w2")


def test_missing_and_foreign_projects_are_indistinguishable():
    """Same exception either way, so the error cannot be used to probe for
    the existence of another workspace's projects."""
    pid = _project("w1")
    with pytest.raises(db.NotFound):
        db.assert_project(pid, "w2")
    with pytest.raises(db.NotFound):
        db.assert_project("proj_doesnotexist", "w1")


# =============================================================================
# PROVIDER HONESTY
# =============================================================================

def test_provider_states_are_distinct_not_boolean():
    described = registry.describe_all("w1")
    statuses = {p["status"] for kind in ("image", "video", "voice")
                for p in described[kind]}
    # Whatever this host has, states must come from the real vocabulary.
    assert statuses <= {s.value for s in ProviderStatus}


def test_unconnected_provider_is_never_dispatchable(monkeypatch):
    """The core guarantee: no connected provider means a refusal, not a fake."""
    monkeypatch.setattr(registry, "dispatchable", lambda kind, ws="default": [])
    with pytest.raises(registry.NoProviderAvailable) as exc:
        registry.resolve("video", "w1")
    assert "no connected video provider" in exc.value.message
    # The refusal explains itself per provider so the UI can act on it.
    assert exc.value.candidates
    assert all("status" in c for c in exc.value.candidates)


def test_refusal_names_the_missing_credential():
    try:
        registry.resolve("video", "w1")
    except registry.NoProviderAvailable as exc:
        replicate = [c for c in exc.candidates if c["provider"] == "replicate"]
        if replicate:  # only when it is genuinely unconfigured on this host
            assert replicate[0]["credential_env"] == ["REPLICATE_API_TOKEN"]


def test_unknown_provider_status_maps_to_failed_not_completed():
    """An unrecognised remote state is never optimistically treated as done."""
    from studio.providers.video import ReplicateVideoProvider
    provider = ReplicateVideoProvider()
    assert provider.map_status("succeeded", provider.STATUS_MAP) == JobState.COMPLETED
    assert provider.map_status("who-knows", provider.STATUS_MAP) == JobState.FAILED
    assert provider.map_status("", provider.STATUS_MAP) == JobState.FAILED


def test_capabilities_default_to_unsupported():
    caps = Capabilities()
    assert caps.image_to_video is False
    assert caps.character_reference is False
    assert caps.reports_progress is False


def test_generating_without_credentials_raises_not_connected():
    from studio.providers.image import OpenAIImageProvider
    provider = OpenAIImageProvider()
    if provider.is_connected():
        pytest.skip("a real OPENAI_API_KEY is present in this environment")
    with pytest.raises(NotConnected) as exc:
        provider.generate_image(GenerationRequest(prompt="x"))
    assert "OPENAI_API_KEY" in str(exc.value)
    assert exc.value.retryable is False   # a retry cannot conjure a key


def test_api_keys_are_redacted_on_read():
    registry.set_config("w1", "image", "openai", settings={"api_key": "sk-secret-value"})
    described = registry.describe_all("w1")
    openai = next(p for p in described["image"] if p["name"] == "openai")
    assert "sk-secret-value" not in str(described)
    assert openai["settings"]["api_key"] == "***set***"


def test_unverified_providers_are_labelled_as_claims():
    described = registry.describe_all("w1")
    for p in described["image"]:
        if not p["verified_ok"]:
            assert p["capability_confidence"] == "declared_unverified"


# =============================================================================
# STORAGE
# =============================================================================

def test_storage_key_traversal_is_blocked(tmp_path):
    storage = LocalStorageProvider(str(tmp_path / "media"))
    with pytest.raises(StorageError):
        storage.upload("../../etc/passwd", b"x")
    with pytest.raises(StorageError):
        storage._resolve("../../../etc/shadow")


def test_sanitize_key_strips_traversal():
    assert ".." not in sanitize_key("../..", "x")
    assert sanitize_key("proj1", "image", "a.png") == "proj1/image/a.png"


def test_storage_roundtrip(tmp_path):
    storage = LocalStorageProvider(str(tmp_path / "media"))
    info = storage.upload("p/image/a.png", b"bytes-here", mime="image/png")
    assert info["bytes"] == 10
    assert storage.get_metadata("p/image/a.png")["bytes"] == 10
    assert storage.local_path("p/image/a.png")
    assert storage.delete("p/image/a.png") is True
    assert storage.get_metadata("p/image/a.png") is None


# =============================================================================
# COST HONESTY
# =============================================================================

def test_unknown_cost_is_none_not_zero():
    """$0.00 reads as 'free'. Unknown must stay unknown."""
    from studio.providers.video import ReplicateVideoProvider
    est = ReplicateVideoProvider().estimate_cost(GenerationRequest(prompt="x"))
    assert est.amount is None
    assert est.confidence == "unknown"
    assert "not predictable" in est.basis


def test_estimates_and_actuals_stay_separate():
    pid = _project()
    cost.record_usage(workspace="w1", project_id=pid, provider="p",
                      estimated_cost=1.0, actual_cost=None)
    cost.record_usage(workspace="w1", project_id=pid, provider="p",
                      estimated_cost=2.0, actual_cost=3.0)
    spend = cost.month_spend("w1")
    assert spend["confirmed"] == 3.0        # only the provider-reported one
    assert spend["estimated_only"] == 1.0   # not folded into 'confirmed'


def test_unset_budget_is_reported_as_unset_not_unlimited():
    budget = cost.get_budget("w-fresh")
    assert budget["configured"] is False
    assert budget["limit"] is None
    assert "not capped" in budget["note"]


def test_budget_blocks_when_projected_spend_exceeds_limit():
    cost.set_budget("w1", 10.0)
    cost.record_usage(workspace="w1", provider="p", actual_cost=9.0)
    decision = cost.check_budget("w1", 5.0)
    assert decision["allowed"] is False
    assert "exceed" in decision["reason"]


def test_unknown_cost_does_not_block_but_is_flagged():
    cost.set_budget("w1", 10.0)
    cost.record_usage(workspace="w1", provider="p", actual_cost=9.5)
    decision = cost.check_budget("w1", None)
    assert decision["allowed"] is True         # unpriced providers stay usable
    assert decision["requires_approval"] is True   # ...but a human is asked


def test_project_estimate_reports_unknowns_rather_than_understating():
    pid = _project()
    board_id = db.new_id("sbd")
    db.insert("storyboard", {"id": board_id, "project_id": pid, "version": 1,
                             "is_current": 1, "created_at": db.now(),
                             "updated_at": db.now()})
    db.insert("scene", {"id": db.new_id("scn"), "storyboard_id": board_id,
                        "project_id": pid, "idx": 0, "duration_s": 5,
                        "asset_type": "ai_video", "created_at": db.now(),
                        "updated_at": db.now()})
    est = cost.estimate_project(pid, "w1")
    if est["unknown_count"]:
        assert est["is_complete"] is False
        assert "at least" in est["label"]


# =============================================================================
# JOBS
# =============================================================================

def test_idempotency_key_prevents_duplicate_jobs():
    pid = _project()
    a = jobs.enqueue(project_id=pid, workspace="w1", job_type="image",
                     prompt="p", idempotency_key="k1")
    b = jobs.enqueue(project_id=pid, workspace="w1", job_type="image",
                     prompt="p", idempotency_key="k1")
    assert a["id"] == b["id"]


def test_progress_stays_null_until_a_provider_reports_one():
    pid = _project()
    job = jobs.enqueue(project_id=pid, workspace="w1", job_type="image", prompt="p")
    assert job["progress_pct"] is None

    jobs.update_progress(job["id"], stage="generating", progress_pct=None)
    assert jobs.get_job(job["id"])["progress_pct"] is None   # stage only

    jobs.update_progress(job["id"], progress_pct=42.0)
    assert jobs.get_job(job["id"])["progress_pct"] == 42.0


def test_cancel_says_whether_remote_work_actually_stopped():
    pid = _project()
    job = jobs.enqueue(project_id=pid, workspace="w1", job_type="image", prompt="p")
    result = jobs.cancel_job(job["id"])
    assert result["ok"] is True
    assert result["stopped_remote"] is True     # never dispatched
    assert jobs.get_job(job["id"])["status"] == JobState.CANCELLED.value


def test_orphaned_jobs_are_requeued_after_a_restart():
    pid = _project()
    job = jobs.enqueue(project_id=pid, workspace="w1", job_type="image", prompt="p")
    db.update("generation_job", job["id"], {"status": JobState.GENERATING.value})
    assert jobs.recover_orphans() == 1
    assert jobs.get_job(job["id"])["status"] == JobState.QUEUED.value


def test_job_without_a_handler_fails_with_a_clear_reason():
    pid = _project()
    job = jobs.enqueue(project_id=pid, workspace="w1", job_type="nonexistent",
                       prompt="p")
    jobs._run_job(jobs.get_job(job["id"]))
    finished = jobs.get_job(job["id"])
    assert finished["status"] == JobState.FAILED.value
    assert "no handler registered" in finished["error"]


def test_scene_failure_is_isolated_to_that_scene():
    """One bad scene must never fail the whole project."""
    pid = _project()
    board_id = db.new_id("sbd")
    db.insert("storyboard", {"id": board_id, "project_id": pid, "version": 1,
                             "is_current": 1, "created_at": db.now(),
                             "updated_at": db.now()})
    scenes = []
    for i in range(3):
        sid = db.new_id("scn")
        db.insert("scene", {"id": sid, "storyboard_id": board_id, "project_id": pid,
                            "idx": i, "duration_s": 5, "created_at": db.now(),
                            "updated_at": db.now()})
        scenes.append(sid)

    job = jobs.enqueue(project_id=pid, workspace="w1", job_type="image",
                       scene_id=scenes[1], prompt="p")
    jobs._handle_failure(dict(job, attempts=3), "provider exploded", retryable=False)

    states = {s["id"]: s["status"] for s in
              db.fetch_all("SELECT id, status FROM scene WHERE project_id=?", (pid,))}
    assert states[scenes[1]] == "failed"
    assert states[scenes[0]] == "pending"     # untouched
    assert states[scenes[2]] == "pending"
    assert db.fetch_one("SELECT status FROM studio_project WHERE id=?",
                        (pid,))["status"] != "failed"


# =============================================================================
# VOICE TIMING
# =============================================================================

def _scene_with_voice(pid, planned, actual):
    board_id = db.fetch_one("SELECT id FROM storyboard WHERE project_id=?", (pid,))
    if not board_id:
        board_id = db.new_id("sbd")
        db.insert("storyboard", {"id": board_id, "project_id": pid, "version": 1,
                                 "is_current": 1, "created_at": db.now(),
                                 "updated_at": db.now()})
    else:
        board_id = board_id["id"]

    sid = db.new_id("scn")
    db.insert("scene", {"id": sid, "storyboard_id": board_id, "project_id": pid,
                        "idx": 0, "duration_s": planned, "narration": "hello",
                        "created_at": db.now(), "updated_at": db.now()})
    if actual is not None:
        db.insert("voiceover", {"id": db.new_id("vo"), "project_id": pid,
                                "scene_id": sid, "duration_s": actual,
                                "text": "hello", "created_at": db.now(),
                                "updated_at": db.now()})
    return sid


def test_timing_mismatch_is_reported_not_silently_fixed():
    """The spec's example: 8s planned, 10.4s narration."""
    pid = _project()
    sid = _scene_with_voice(pid, planned=8.0, actual=10.4)

    result = tl.analyse_timing(pid)
    assert len(result["conflicts"]) == 1

    conflict = result["conflicts"][0]
    assert conflict["planned_s"] == 8.0
    assert conflict["narration_s"] == 10.4
    assert conflict["delta_s"] == 2.4
    assert conflict["kind"] == "narration_longer"
    assert {o["action"] for o in conflict["options"]} == {
        "extend_visual", "shorten_narration", "speed_up_voice", "manual"}

    # Nothing changed on disk — the scene keeps its planned duration.
    assert db.fetch_one("SELECT duration_s FROM scene WHERE id=?",
                        (sid,))["duration_s"] == 8.0


def test_unmeasured_narration_is_unknown_not_assumed_fine():
    pid = _project()
    _scene_with_voice(pid, planned=8.0, actual=None)
    result = tl.analyse_timing(pid)
    assert not result["conflicts"]
    assert not result["ok"]                       # not claimed as in sync
    assert len(result["unknown"]) == 1
    assert "no voiceover generated" in result["unknown"][0]["reason"]


def test_timing_resolution_applies_only_when_chosen():
    pid = _project()
    sid = _scene_with_voice(pid, planned=8.0, actual=10.4)
    result = tl.apply_timing_resolution(pid, sid, "extend_visual")
    assert result["ok"] is True
    assert result["new_duration_s"] == 10.4
    assert db.fetch_one("SELECT duration_s FROM scene WHERE id=?",
                        (sid,))["duration_s"] == 10.4


def test_absurd_speed_up_is_refused():
    """Rather than distort the voice into unintelligibility."""
    pid = _project()
    sid = _scene_with_voice(pid, planned=2.0, actual=10.0)   # would need 5x
    result = tl.apply_timing_resolution(pid, sid, "speed_up_voice")
    assert result["ok"] is False
    assert "unintelligible" in result["error"]


def test_small_differences_are_tolerated():
    pid = _project()
    _scene_with_voice(pid, planned=8.0, actual=8.2)
    result = tl.analyse_timing(pid)
    assert not result["conflicts"]
    assert len(result["ok"]) == 1


# =============================================================================
# TIMELINE
# =============================================================================

def test_auto_assemble_leaves_gaps_rather_than_substituting():
    """A scene with no asset must produce a visible hole, not a stand-in."""
    pid = _project()
    board_id = db.new_id("sbd")
    db.insert("storyboard", {"id": board_id, "project_id": pid, "version": 1,
                             "is_current": 1, "created_at": db.now(),
                             "updated_at": db.now()})
    for i in range(2):
        db.insert("scene", {"id": db.new_id("scn"), "storyboard_id": board_id,
                            "project_id": pid, "idx": i, "start_s": i * 5,
                            "duration_s": 5, "created_at": db.now(),
                            "updated_at": db.now()})

    result = tl.auto_assemble(pid, brief={"aspect_ratio": "16:9"})
    assert result["scenes_placed"] == 0
    assert result["scenes_skipped"] == 2
    assert result["is_draft"] is True
    assert all("no generated asset" in s["reason"] for s in result["skipped"])


def test_split_refuses_at_a_clip_boundary():
    pid = _project()
    timeline = tl.get_or_create(pid)
    clip_id = tl.add_clip(timeline_id=timeline["id"], project_id=pid,
                          kind="video", start_s=0, duration_s=10)
    assert tl.split_clip(clip_id, 0.05) is None    # would make a zero-length clip
    assert tl.split_clip(clip_id, 5.0) is not None


def test_timeline_dimensions_follow_aspect_ratio():
    assert tl._dimensions("16:9", "1080p") == (1920, 1080)
    assert tl._dimensions("9:16", "1080p") == (606, 1080)
    assert tl._dimensions("1:1", "720p") == (720, 720)


# =============================================================================
# CAPTIONS
# =============================================================================

def test_caption_timing_source_is_recorded():
    pid = _project()
    _scene_with_voice(pid, planned=8.0, actual=10.4)
    built = captions.build_cues(pid)
    assert built["timing_source"] == "voice"     # real measured audio

    pid2 = _project()
    _scene_with_voice(pid2, planned=8.0, actual=None)
    built2 = captions.build_cues(pid2)
    assert built2["timing_source"] == "script"   # planned only
    assert "drift" in built2["note"]


def test_srt_and_vtt_timestamps_are_well_formed():
    cues = [{"start_s": 0, "end_s": 2.5, "text": "First line"},
            {"start_s": 2.5, "end_s": 5.0, "text": "Second line"}]
    srt = captions.to_srt(cues)
    assert "00:00:00,000 --> 00:00:02,500" in srt
    vtt = captions.to_vtt(cues)
    assert vtt.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:02.500" in vtt


def test_long_text_splits_into_readable_cues():
    text = ("This is a long narration segment that exceeds the readable cue length "
            "and therefore must be split across multiple cues so a viewer can "
            "actually read it before it disappears from the screen.")
    cues = captions._cues_for_span(text, 0, 12)
    assert len(cues) > 1
    assert all(len(c["text"]) <= captions.MAX_CUE_CHARS for c in cues)
    assert cues[0]["start_s"] == 0


def test_caption_gaps_are_detected():
    cues = [{"start_s": 0, "end_s": 2, "text": "a"},
            {"start_s": 10, "end_s": 12, "text": "b"}]
    gaps = captions.find_gaps(cues, 14)
    assert len(gaps) == 1
    assert gaps[0]["duration_s"] == 8


# =============================================================================
# PROMPT ENGINE
# =============================================================================

def test_prompt_format_differs_per_provider():
    """Prompts must not be hardcoded for one model."""
    args = dict(description="A person alone at night", style="cinematic")
    natural = prompts.build_prompt(provider="openai", kind="image", **args)
    tags = prompts.build_prompt(provider="together", kind="image", **args)
    motion = prompts.build_prompt(provider="replicate", kind="video", **args)

    assert natural["provider_format"] == "natural"
    assert tags["provider_format"] == "tags"
    assert motion["provider_format"] == "motion"
    assert len({natural["prompt"], tags["prompt"], motion["prompt"]}) == 3


def test_visual_bible_descriptions_are_applied():
    pid = _project()
    db.insert("visual_reference", {
        "id": db.new_id("vref"), "project_id": pid, "kind": "character",
        "name": "Maya", "description": "a woman in her twenties",
        "attributes": db._dumps({"clothing": "grey hoodie"}),
        "created_at": db.now(), "updated_at": db.now(),
    })
    built = prompts.build_prompt(description="She checks her phone",
                                 project_id=pid, character_refs=["Maya"])
    assert "Maya" in built["prompt"]
    assert "grey hoodie" in built["prompt"]


def test_consistency_warning_never_promises_identity_match():
    class NoRef:
        def supports(self, cap): return False

    class WithRef:
        def supports(self, cap): return cap == "character_reference"

    without = prompts.consistency_warning("x", NoRef())
    assert "not guaranteed" in without

    with_ref = prompts.consistency_warning("y", WithRef())
    assert "does not guarantee" in with_ref
    assert "improves" in with_ref


# =============================================================================
# RESEARCH HONESTY
# =============================================================================

def test_citations_are_stripped_when_no_search_tool_ran():
    """The model may hallucinate a URL; we must not present it as a source."""
    from studio.agents import _sanitise_sources

    fabricated = [{"title": "Nature 2019", "url": "https://nature.com/fake-study"}]
    cleaned = _sanitise_sources(fabricated, "model_only")
    assert cleaned[0]["url"] == ""            # URL discarded
    assert cleaned[0]["verified"] is False
    assert "unverified lead" in cleaned[0]["note"]


def test_real_search_results_keep_their_urls():
    from studio.agents import _sanitise_sources

    retrieved = [{"title": "Real page", "url": "https://example.com/x", "note": ""}]
    cleaned = _sanitise_sources(retrieved, "search")
    assert cleaned[0]["url"] == "https://example.com/x"
    assert cleaned[0]["verified"] is True


def test_script_segments_are_made_contiguous():
    """Models emit overlapping ranges; we rebuild a valid timeline."""
    from studio.agents import _normalise_segments

    raw = [{"text": "one two three"}, {"text": "four five"}, {"text": "six"}]
    segments = _normalise_segments(raw, duration=30)
    assert segments[0]["start_s"] == 0
    assert segments[-1]["end_s"] == 30
    for a, b in zip(segments, segments[1:]):
        assert a["end_s"] == b["start_s"]     # no gaps, no overlaps


def test_json_extraction_survives_fences_and_prose():
    from studio.agents import _extract_json

    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json('Sure! Here you go: {"a": 2} Hope that helps.') == {"a": 2}
    assert _extract_json('not json at all') is None


def test_director_output_is_clamped_to_valid_values():
    from studio.agents import _normalise_scenes

    scenes = _normalise_scenes([
        {"visual": "a", "asset_type": "hologram", "transition": "explode",
         "duration_s": 5},
        {"visual": "b", "asset_type": "ai_video", "transition": "fade",
         "duration_s": 5},
    ], total_duration=20)
    assert scenes[0]["asset_type"] == "ai_image"   # invalid type -> safe default
    assert scenes[0]["transition"] == "cut"
    assert scenes[1]["asset_type"] == "ai_video"   # valid type preserved
    assert sum(s["duration_s"] for s in scenes) == pytest.approx(20, abs=0.1)


# =============================================================================
# QUALITY CONTROL
# =============================================================================

def test_quality_check_blocks_an_empty_project():
    pid = _project()
    report = quality.run(pid, "w1")
    assert report["passed"] is False
    codes = {f["code"] for f in report["findings"]}
    assert "no_storyboard" in codes


def test_quality_check_reports_the_timing_mismatch():
    pid = _project()
    _scene_with_voice(pid, planned=5.0, actual=9.0)
    report = quality.run(pid, "w1")
    mismatches = [f for f in report["findings"] if f["code"] == "duration_mismatch"]
    assert mismatches
    assert "4.0s over" in mismatches[0]["message"]


def test_quality_check_is_persisted_for_audit():
    pid = _project()
    quality.run(pid, "w1")
    assert quality.latest(pid) is not None


# =============================================================================
# RENDER
# =============================================================================

def test_render_probe_is_honest_about_ffmpeg():
    capability = render.probe()
    if capability["available"]:
        assert capability["ffmpeg"]
        assert capability["formats"]
    else:
        # Missing ffmpeg must come with the fix and the blast radius.
        assert "ffmpeg" in capability["reason"]
        assert "install" in capability["remedy"].lower()
        assert "without it" in capability["impact"]


def test_render_refuses_rather_than_pretending_when_unavailable():
    pid = _project()
    result = render.create_job(pid, "w1")
    assert result["ok"] is False
    assert result.get("error")
    # No render job row is created for work that cannot happen.
    assert not db.fetch_all("SELECT id FROM render_job WHERE project_id=?", (pid,))


def test_export_settings_mirror_real_capability():
    settings = render.export_settings()
    if not settings["available"]:
        assert settings["remedy"]
    else:
        assert set(settings.keys()) >= {"resolutions", "frame_rates", "formats"}


# =============================================================================
# END-TO-END GENERATION
# =============================================================================
#
# These use a stub adapter registered through the public `register_provider`
# API. That is deliberate: it exercises the full worker → provider → storage →
# asset → usage path without a network call, and simultaneously proves the
# extensibility claim — a provider defined outside the package works with no
# change to jobs, storage, or the storyboard.

from studio.providers.base import (  # noqa: E402
    GenerationHandle, GenerationStatus, ImageGenerationProvider,
)

_ONE_PX_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080200000090"
    "7753de0000000c4944415408d763f8cfc00000030101003e2a5c1b0000000049454e44ae426082")


class _StubImageProvider(ImageGenerationProvider):
    """Deterministic in-memory adapter. `fail_with` drives the failure tests."""

    name = "stub"
    label = "Stub Image Provider"
    credential_env = ()
    fail_with = None

    def is_connected(self):
        return True

    def capabilities(self):
        return Capabilities(models=["stub-1"], aspect_ratios=["16:9"],
                            text_to_image=True, cancellation=True)

    def generate_image(self, request):
        handle = GenerationHandle(external_id="stub-job-1", state=JobState.COMPLETED)
        if type(self).fail_with:
            handle.raw["_r"] = GenerationStatus(state=JobState.FAILED,
                                                error=type(self).fail_with)
        else:
            handle.raw["_r"] = GenerationStatus(
                state=JobState.COMPLETED, output_bytes=_ONE_PX_PNG,
                mime="image/png", width=1, height=1, actual_cost=0.02)
        return handle

    def get_generation_status(self, handle):
        return handle.raw["_r"]


@pytest.fixture
def stub_provider():
    registry.register_provider(_StubImageProvider)
    _StubImageProvider.fail_with = None
    yield _StubImageProvider
    registry._CLASSES["image"].pop("stub", None)
    _StubImageProvider.fail_with = None


def _scene_for_generation(pid):
    board_id = db.new_id("sbd")
    db.insert("storyboard", {"id": board_id, "project_id": pid, "version": 1,
                             "is_current": 1, "created_at": db.now(),
                             "updated_at": db.now()})
    sid = db.new_id("scn")
    db.insert("scene", {"id": sid, "storyboard_id": board_id, "project_id": pid,
                        "idx": 0, "duration_s": 8, "asset_type": "ai_image",
                        "generation_prompt": "a cinematic close-up",
                        "created_at": db.now(), "updated_at": db.now()})
    return sid


def test_successful_generation_stores_a_real_asset(stub_provider, monkeypatch, tmp_path):
    """The full happy path: job → provider → storage → asset → scene → usage."""
    from studio import handlers, storage as storage_mod

    monkeypatch.setattr(storage_mod, "_ACTIVE",
                        storage_mod.LocalStorageProvider(str(tmp_path / "media")))
    handlers.register_all()

    pid = _project()
    sid = _scene_for_generation(pid)
    job = jobs.enqueue(project_id=pid, workspace="w1", job_type="image",
                       scene_id=sid, prompt="a cinematic close-up",
                       provider="stub", settings={"aspect_ratio": "16:9"})

    # Run the handler inline so the test is deterministic (no worker timing).
    jobs._run_job(dict(jobs.get_job(job["id"]), attempts=1))

    finished = jobs.get_job(job["id"])
    assert finished["status"] == JobState.COMPLETED.value
    assert finished["result_asset_id"]

    asset = db.fetch_one("SELECT * FROM media_asset WHERE id=?",
                         (finished["result_asset_id"],))
    assert asset["bytes"] == len(_ONE_PX_PNG)
    assert asset["provider"] == "stub"
    assert storage_mod.get_storage().local_path(asset["storage_key"])

    scene = db.fetch_one("SELECT * FROM scene WHERE id=?", (sid,))
    assert scene["status"] == "completed"
    assert scene["selected_asset_id"] == asset["id"]

    usage = db.fetch_all("SELECT * FROM usage_record WHERE job_id=?", (job["id"],))
    assert len(usage) == 1
    assert usage[0]["actual_cost"] == 0.02   # provider-reported, so it is 'confirmed'


def test_failed_generation_stores_no_asset(stub_provider, monkeypatch, tmp_path):
    """A failure must leave nothing behind that looks like a result."""
    from studio import handlers, storage as storage_mod

    monkeypatch.setattr(storage_mod, "_ACTIVE",
                        storage_mod.LocalStorageProvider(str(tmp_path / "media")))
    handlers.register_all()
    stub_provider.fail_with = "the model refused this prompt"

    pid = _project()
    sid = _scene_for_generation(pid)
    job = jobs.enqueue(project_id=pid, workspace="w1", job_type="image",
                       scene_id=sid, prompt="p", provider="stub")
    jobs._run_job(dict(jobs.get_job(job["id"]), attempts=3))

    assert jobs.get_job(job["id"])["status"] == JobState.FAILED.value
    assert not db.fetch_all("SELECT id FROM media_asset WHERE project_id=?", (pid,))

    scene = db.fetch_one("SELECT * FROM scene WHERE id=?", (sid,))
    assert scene["status"] == "failed"
    assert scene["selected_asset_id"] is None
    assert "refused this prompt" in scene["error"]


def test_assembled_timeline_uses_measured_narration_over_the_plan(
        stub_provider, monkeypatch, tmp_path):
    """When real audio is longer than planned, the timeline follows the audio."""
    from studio import handlers, storage as storage_mod

    monkeypatch.setattr(storage_mod, "_ACTIVE",
                        storage_mod.LocalStorageProvider(str(tmp_path / "media")))
    handlers.register_all()

    pid = _project()
    sid = _scene_for_generation(pid)
    job = jobs.enqueue(project_id=pid, workspace="w1", job_type="image",
                       scene_id=sid, prompt="p", provider="stub")
    jobs._run_job(dict(jobs.get_job(job["id"]), attempts=1))

    # Scene planned at 8s; narration actually measured at 10.4s.
    db.insert("voiceover", {"id": db.new_id("vo"), "project_id": pid,
                            "scene_id": sid, "duration_s": 10.4, "text": "hello",
                            "asset_id": jobs.get_job(job["id"])["result_asset_id"],
                            "created_at": db.now(), "updated_at": db.now()})

    result = tl.auto_assemble(pid, brief={"aspect_ratio": "16:9"})
    assert result["scenes_placed"] == 1
    assert result["duration_s"] == pytest.approx(10.4, abs=0.01)

    loaded = tl.load(pid)
    video = next(t for t in loaded["tracks"] if t["kind"] == "video")
    assert video["clips"][0]["duration_s"] == pytest.approx(10.4, abs=0.01)


def test_externally_registered_provider_becomes_dispatchable(stub_provider):
    """The extensibility claim: register a class, and the registry uses it."""
    names = [p.name for p in registry.dispatchable("image", "w1")]
    assert "stub" in names
    assert registry.resolve("image", "w1", preferred="stub").name == "stub"


def test_capability_requirement_filters_dispatch(stub_provider):
    """A provider that does not declare a capability never receives that work."""
    assert not _StubImageProvider().supports("image_to_video")
    with pytest.raises(registry.NoProviderAvailable) as exc:
        registry.resolve("image", "w1", require="image_to_video")
    stub = [c for c in exc.value.candidates if c["provider"] == "stub"]
    assert "does not support image_to_video" in stub[0]["status"]
