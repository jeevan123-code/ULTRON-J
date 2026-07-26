"""Phase 23 wiring — the self-modification approval gate needs a human surface.

An approval-gated feature with no way for a human to see or act on the queue is
not a safety feature, it is dead code. These routes are that surface.

Safety invariant under test: NOTHING here applies a patch except an explicit
POST to .../approve. Listing, reading and the ledger are all read-only.
"""
import flask
import pytest

import agent_routes
import self_modify_proposals as smp


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(smp, "_PROPOSALS_PATH", str(tmp_path / "p.json"))
    monkeypatch.setattr(smp, "_LEDGER_PATH", str(tmp_path / "l.json"))
    smp._reset_for_test()
    app = flask.Flask(__name__)
    app.register_blueprint(agent_routes.agent_bp)
    return app.test_client()


@pytest.fixture
def applied(monkeypatch):
    """Record every real patch application so we can assert it never happens."""
    calls = []
    monkeypatch.setattr(smp, "_apply",
                        lambda fn, code: calls.append(fn) or
                        {"success": True, "backup": "b.bak"})
    monkeypatch.setattr(smp, "_allowed_files", lambda: {"demo.py": "/tmp/demo.py"})
    return calls


def _stage(client, filename="demo.py", code="x = 1\n"):
    return smp.propose(filename, code, request="r", rationale="why")


# ── the surface exists ──────────────────────────────────────────────────────
def test_pending_proposals_are_listable(client, applied):
    _stage(client)
    r = client.get("/agent/self_modify/proposals")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["total"] == 1
    assert body["proposals"][0]["filename"] == "demo.py"


def test_listing_never_applies_anything(client, applied):
    _stage(client)
    client.get("/agent/self_modify/proposals")
    client.get("/agent/self_modify/ledger")
    assert applied == [], "a read-only route applied a patch"


def test_ledger_is_readable(client, applied):
    _stage(client)
    r = client.get("/agent/self_modify/ledger")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True


# ── approval / rejection ────────────────────────────────────────────────────
def test_approve_applies_only_on_explicit_post(client, applied):
    pid = _stage(client)["id"]
    assert applied == []
    r = client.post(f"/agent/self_modify/proposals/{pid}/approve")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert applied == ["demo.py"]


def test_reject_never_applies(client, applied):
    pid = _stage(client)["id"]
    r = client.post(f"/agent/self_modify/proposals/{pid}/reject")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert applied == []
    assert smp.list_pending() == []


def test_unknown_proposal_is_a_clean_404(client, applied):
    r = client.post("/agent/self_modify/proposals/nope/approve")
    assert r.status_code == 404
    assert applied == []


def test_rollback_route_exists(client, applied, monkeypatch):
    monkeypatch.setattr(smp, "_rollback", lambda fn: {"success": True})
    pid = _stage(client)["id"]
    client.post(f"/agent/self_modify/proposals/{pid}/approve")
    r = client.post(f"/agent/self_modify/proposals/{pid}/rollback")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True


def test_no_route_can_create_and_apply_in_one_call(client, applied):
    """A proposal must be stageable without ever auto-applying."""
    r = client.post("/agent/self_modify/proposals",
                    json={"filename": "demo.py", "new_code": "y = 2\n",
                          "request": "r", "rationale": "why"})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert applied == [], "staging a proposal applied it immediately"
    assert len(smp.list_pending()) == 1
