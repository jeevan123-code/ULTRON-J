"""End-to-end Phase 5f: phase1_pipeline learns + resolves shortcuts live."""
from unittest.mock import patch
import pytest

import phase1_pipeline as p1
import conversation_intelligence as ci
import shortcut_registry as reg
from shortcut_types import Shortcut


@pytest.fixture(autouse=True)
def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_REGISTRY_PATH", str(tmp_path / "shortcuts.json"))
    reg._reset_for_test()
    monkeypatch.setenv("ULTRON_PHASE5F_ENABLED", "1")
    yield
    reg._reset_for_test()


def _fake_enrich(parsed, context):
    """Skip LLM calls during enrichment; expose context.shortcuts on parsed."""
    parsed.references = dict(context.get("shortcuts", {}))
    return parsed


def test_teach_utterance_persists_via_pipeline():
    """A teach utterance routed through process_user_utterance hits the registry."""
    with patch.object(ci, "enrich", _fake_enrich):
        p1.process_user_utterance("by 'wt' I mean wheat-3d-explorer")
    s = reg.get("wt")
    assert s is not None
    assert s.canonical == "wheat-3d-explorer"
    assert s.taught_explicitly is True


def test_known_shortcut_appears_in_enrichment_context():
    """A previously-taught shortcut shows up in the enriched references."""
    reg.teach(Shortcut(term="wt", canonical="wheat-3d-explorer", confidence=1.0,
                       created_at=100.0, taught_explicitly=True))
    with patch.object(ci, "enrich", _fake_enrich):
        plan = p1.process_user_utterance("look up wt now")
    assert plan is not None
    assert plan.rationale != ""


def test_flag_off_leaves_pipeline_unchanged(monkeypatch):
    """When ULTRON_PHASE5F_ENABLED=0, no learning or resolution happens."""
    monkeypatch.setenv("ULTRON_PHASE5F_ENABLED", "0")
    with patch.object(ci, "enrich", _fake_enrich):
        p1.process_user_utterance("by 'wt' I mean wheat-3d-explorer")
    assert reg.get("wt") is None


def test_unrelated_chat_leaves_registry_alone():
    with patch.object(ci, "enrich", _fake_enrich):
        p1.process_user_utterance("what is the weather today")
    assert reg.list_all() == []
