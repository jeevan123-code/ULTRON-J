"""Tests for self_modify_proposals — approval-gated self-modification + ledger."""
import pytest

import self_modify_proposals as smp


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(smp, "_PROPOSALS_PATH", str(tmp_path / "proposals.json"))
    monkeypatch.setattr(smp, "_LEDGER_PATH", str(tmp_path / "ledger.json"))
    # Pretend one file is patchable; capture apply/rollback via seams.
    monkeypatch.setattr(smp, "_allowed_files", lambda: {"index.html": "/x/index.html"})
    applied = {}
    monkeypatch.setattr(smp, "_apply",
                        lambda fn, code: applied.update({"fn": fn, "code": code}) or
                        {"success": True, "backup": "/x/index.html.bak"})
    monkeypatch.setattr(smp, "_rollback", lambda fn: {"success": True})
    smp._reset_for_test()
    yield applied
    smp._reset_for_test()


def test_propose_does_not_apply(_isolate):
    r = smp.propose("index.html", "<h1>hi</h1>", request="tweak")
    assert r["ok"] is True
    assert _isolate == {}                       # _apply NOT called on propose
    assert len(smp.list_pending()) == 1


def test_propose_rejects_disallowed_file():
    r = smp.propose("secrets.py", "x=1")
    assert r["ok"] is False
    assert "not an allowed" in r["error"]


def test_propose_rejects_python_syntax_error(monkeypatch, _isolate):
    monkeypatch.setattr(smp, "_allowed_files", lambda: {"app.py": "/x/app.py"})
    r = smp.propose("app.py", "def broken(:\n  pass")
    assert r["ok"] is False
    assert "SyntaxError" in r["error"]


def test_approve_applies_and_ledgers(_isolate):
    pid = smp.propose("index.html", "<h1>hi</h1>")["id"]
    r = smp.approve(pid)
    assert r["ok"] is True and r["status"] == "applied"
    assert _isolate["fn"] == "index.html"       # _apply was called
    assert smp.get(pid)["status"] == "applied"
    events = [e["event"] for e in smp.get_ledger()]
    assert "applied" in events and "proposed" in events


def test_reject_prevents_apply(_isolate):
    pid = smp.propose("index.html", "<h1>hi</h1>")["id"]
    assert smp.reject(pid) is True
    assert smp.approve(pid)["ok"] is False       # can't approve a rejected one
    assert _isolate == {}                        # never applied


def test_rollback_after_apply(_isolate):
    pid = smp.propose("index.html", "<h1>hi</h1>")["id"]
    smp.approve(pid)
    r = smp.rollback(pid)
    assert r["ok"] is True
    assert smp.get(pid)["status"] == "rolled_back"
    assert "rolled_back" in [e["event"] for e in smp.get_ledger()]


def test_cannot_rollback_unapplied(_isolate):
    pid = smp.propose("index.html", "<h1>hi</h1>")["id"]
    assert smp.rollback(pid)["ok"] is False


def test_apply_failure_recorded(monkeypatch, _isolate):
    monkeypatch.setattr(smp, "_apply", lambda fn, code: {"success": False, "error": "boom"})
    pid = smp.propose("index.html", "<h1>hi</h1>")["id"]
    r = smp.approve(pid)
    assert r["ok"] is False
    assert smp.get(pid)["status"] == "failed"
    assert "apply_failed" in [e["event"] for e in smp.get_ledger()]
