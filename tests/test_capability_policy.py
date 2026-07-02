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
