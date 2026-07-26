"""Tests for capability_policy — the Tier-4 authority engine."""
import json

import pytest

import capability_policy as cp
from capability_policy import Tier, evaluate, enforce


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(cp, "_POLICY_FILE", str(tmp_path / "policy.json"))
    cp._reset_for_test()
    yield
    cp._reset_for_test()


# ── evaluate: table tiers ──────────────────────────────────────────────────
def test_read_only_is_green():
    assert evaluate("file_read").tier == Tier.GREEN


def test_mutating_is_amber():
    assert evaluate("file_write", {"path": "/tmp/x", "content": "y"}).tier == Tier.AMBER


def test_destructive_is_red():
    assert evaluate("delete_file", {"path": "/tmp/x"}).tier == Tier.RED
    assert evaluate("run_python", {"code": "print(1)"}).tier == Tier.RED


def test_unknown_action_denied_by_default():
    # Deny-by-default: an action the safety whitelist doesn't recognise is RED.
    d = evaluate("some_new_tool")
    assert d.tier == Tier.RED
    assert "safety_check" in d.reason


# ── evaluate: escalation via safety_check ──────────────────────────────────
def test_dangerous_code_escalates_to_red_even_if_table_says_otherwise():
    # Force the table to call it green, but the payload is dangerous.
    cp.set_policy_override({"run_python": Tier.GREEN})
    d = evaluate("run_python", {"code": "import os; os.system('rm -rf /')"})
    assert d.tier == Tier.RED
    assert "safety_check" in d.reason


# ── enforce: allow / deny / approval gate ──────────────────────────────────
def test_enforce_green_allowed():
    r = enforce("file_read")
    assert r["allowed"] is True and r["needs_approval"] is False


def test_enforce_amber_needs_approval():
    r = enforce("file_write", {"path": "/tmp/x", "content": "y"})
    assert r["allowed"] is False and r["needs_approval"] is True
    r2 = enforce("file_write", {"path": "/tmp/x", "content": "y"}, approved=True)
    assert r2["allowed"] is True


def test_enforce_red_never_allowed_even_if_approved():
    r = enforce("delete_folder", {"path": "/tmp/x"}, approved=True)
    assert r["allowed"] is False
    assert r["tier"] == "red"


# ── config override from disk (no hardcoding) ──────────────────────────────
def test_disk_override_changes_tier(monkeypatch, tmp_path):
    pf = tmp_path / "policy.json"
    pf.write_text(json.dumps({"open_url": "green"}))
    monkeypatch.setattr(cp, "_POLICY_FILE", str(pf))
    assert evaluate("open_url", {"url": "http://x"}).tier == Tier.GREEN


# ── FAIL-CLOSED: a broken escalation layer must never widen authority ───────
# A safety control whose failure mode is "allow" is not a safety control. If a
# layer cannot render a verdict we assume the worst verdict it could have given.
def test_safety_check_raising_fails_closed_to_red(monkeypatch):
    import decision_engine

    def _boom(*a, **k):
        raise RuntimeError("simulated safety_check failure")

    monkeypatch.setattr(decision_engine, "safety_check", _boom)
    d = evaluate("some_unknown_tool")
    assert d.tier == Tier.RED, "unknown action must not degrade RED->AMBER"
    assert "unavailable" in d.reason


def test_safety_check_raising_denies_even_when_approved(monkeypatch):
    import decision_engine

    monkeypatch.setattr(
        decision_engine, "safety_check",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    assert enforce("some_unknown_tool", {}, approved=True)["allowed"] is False


def test_safety_check_import_failure_fails_closed(monkeypatch):
    # Simulate decision_engine being entirely unimportable.
    import builtins
    real_import = builtins.__import__

    def _blocked(name, *a, **k):
        if name == "decision_engine":
            raise ImportError("simulated missing module")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    assert evaluate("file_read").tier == Tier.RED


def test_confirm_gate_raising_escalates_to_amber_minimum(monkeypatch):
    # confirm_gate can only ever raise the floor to AMBER; if it breaks we
    # cannot rule out "destructive", so a GREEN action must not stay GREEN.
    import confirm_gate

    monkeypatch.setattr(
        confirm_gate, "is_destructive",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    d = evaluate("file_read")
    assert d.tier != Tier.GREEN
    assert "unavailable" in d.reason


def test_healthy_path_is_unchanged():
    # Regression guard: the fail-closed logic must not alter normal operation.
    assert evaluate("file_read").tier == Tier.GREEN
    assert evaluate("file_write", {"path": "/tmp/x", "content": "y"}).tier == Tier.AMBER
    assert evaluate("delete_file", {"path": "/tmp/x"}).tier == Tier.RED
