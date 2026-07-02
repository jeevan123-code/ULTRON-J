"""Phase 15 — approve/reject self-authored proposals via route + voice."""
import pytest

import goal_author as ga
from goal_author_types import GoalProposal


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ga, "_STATE_PATH", str(tmp_path / "state.json"))
    created = []
    monkeypatch.setattr(ga, "_create_goal",
                        lambda p: created.append(p) or {"id": "g1", "title": p.title})
    monkeypatch.setattr(ga, "_notify", lambda m: None)
    ga._reset_for_test()
    yield created
    ga._reset_for_test()


def _park_one(subject="graphql"):
    monkey_obs = {"recent_topics": [subject] * ga.KNOWLEDGE_GAP_THRESHOLD, "known_topics": []}
    # AUTO_GREEN off -> parks
    ga.author(monkey_obs)


# ── pure NLU ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,expected", [
    ("approve that", "approve"),
    ("approve the proposal", "approve"),
    ("go ahead with that goal", "approve"),
    ("reject that", "reject"),
    ("dismiss the suggestion", "reject"),
    ("what's the weather", None),
    ("tell me about python", None),
    ("", None),
])
def test_match_proposal_command(text, expected):
    assert ga.match_proposal_command(text) == expected


# ── voice handler ──────────────────────────────────────────────────────────
def test_handle_voice_decision_approve(_isolate):
    _park_one()
    res = ga.handle_voice_decision("approve that")
    assert res["decision"] == "approved"
    assert len(_isolate) == 1
    assert ga.list_pending() == []


def test_handle_voice_decision_reject(_isolate):
    _park_one()
    res = ga.handle_voice_decision("reject that proposal")
    assert res["decision"] == "rejected"
    assert _isolate == []
    assert ga.list_pending() == []


def test_handle_voice_decision_none_when_no_pending(_isolate):
    assert ga.handle_voice_decision("approve that") is None


def test_handle_voice_decision_ignores_unrelated(_isolate):
    _park_one()
    assert ga.handle_voice_decision("what is kubernetes") is None
    assert len(ga.list_pending()) == 1     # untouched


# ── Flask routes ───────────────────────────────────────────────────────────
def test_proposal_routes(monkeypatch, _isolate):
    from app import app as flask_app
    _park_one()
    key = ga.list_pending()[0]["dedup_key"]
    client = flask_app.test_client()

    r = client.get("/agent/proposals")
    assert r.status_code == 200
    assert r.get_json()["total"] == 1

    r = client.post(f"/agent/proposals/{key}/approve")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert len(_isolate) == 1
    assert ga.list_pending() == []

    # rejecting a now-missing key -> ok False
    r = client.post(f"/agent/proposals/{key}/reject")
    assert r.get_json()["ok"] is False
