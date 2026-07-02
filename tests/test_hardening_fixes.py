"""Regression tests for the security/hardening batch shipped on
`phase13-strict-validation` (2026-07-02).

Each of these fixes previously went in WITHOUT a test, against the project's
TDD-first convention. These lock the behaviour so a future refactor can't
silently reintroduce the gap.

Covers:
  1. decision_engine.safety_check  — scans params["code"] (run_python bypass)
  2. action_engine.safe_calculate  — exponentiation DoS cap
  3. self_modify.patch_file        — compile()-check rejects broken patches pre-write
  4. intent_router run_script      — no shell=True for .sh (injection surface)
  5. autonomous_loop.observe_environment — disk_critical ignores pseudo/read-only mounts
"""
import os
import subprocess

import pytest


# ──────────────────────────────────────────────────────────────────────────
# 1. decision_engine.safety_check — code-param dangerous-pattern scan
# ──────────────────────────────────────────────────────────────────────────
def test_safety_check_blocks_dangerous_pattern_in_code_param():
    """`run_python` carries its payload in params['code']; the scanner must
    inspect it, or the whole dangerous-pattern layer is a no-op for the normal
    code-execution path."""
    import decision_engine as de
    ok, reason = de.safety_check(
        {"type": "run_python", "params": {"code": "import os; os.system('rm -rf /')"}}
    )
    assert ok is False
    assert "rm -rf" in reason.lower() or "dangerous" in reason.lower()


def test_safety_check_allows_safe_code():
    import decision_engine as de
    ok, reason = de.safety_check(
        {"type": "run_python", "params": {"code": "print(sum(range(10)))"}}
    )
    assert ok is True


def test_safety_check_still_scans_command_and_content():
    import decision_engine as de
    for field in ("command", "content"):
        ok, _ = de.safety_check({"type": "run_code", "params": {field: "sudo rm stuff"}})
        assert ok is False, f"pattern in params[{field!r}] should be blocked"


# ──────────────────────────────────────────────────────────────────────────
# 2. action_engine.safe_calculate — exponentiation DoS cap
# ──────────────────────────────────────────────────────────────────────────
def test_calculate_rejects_chained_exponentiation():
    """9**9**9 right-associates to 9**387420489 → memory exhaustion."""
    from action_engine import safe_calculate
    r = safe_calculate("9**9**9")
    assert r["success"] is False
    assert "exponent" in r["error"].lower()


def test_calculate_rejects_oversized_exponent():
    from action_engine import safe_calculate
    r = safe_calculate("2**5000")
    assert r["success"] is False
    assert "exponent" in r["error"].lower()


def test_calculate_allows_normal_power_and_arithmetic():
    from action_engine import safe_calculate
    assert safe_calculate("2**10")["result"] == 1024
    assert safe_calculate("2 + 2 * 5")["result"] == 12


# ──────────────────────────────────────────────────────────────────────────
# 3. self_modify.patch_file — compile()-check before writing
# ──────────────────────────────────────────────────────────────────────────
def test_patch_file_rejects_syntax_error_without_writing(tmp_path, monkeypatch):
    """A broken patch to a .py file must be rejected BEFORE the original is
    overwritten, otherwise Ultron can't re-import itself to self-heal."""
    import self_modify as sm

    target = tmp_path / "victim.py"
    original = "def ok():\n    return 1\n"
    target.write_text(original)

    monkeypatch.setattr(sm, "ALLOWED_FILES", {"victim.py": str(target)})
    monkeypatch.setattr(sm, "_patches_this_session", 0, raising=False)

    broken = "def ok(:\n    return 1\n"          # invalid syntax
    res = sm.patch_file_direct("victim.py", broken)

    assert res["success"] is False
    assert "syntax" in res["error"].lower() or "reject" in res["error"].lower()
    # Original file must be untouched.
    assert target.read_text() == original


def test_patch_file_accepts_valid_python(tmp_path, monkeypatch):
    import self_modify as sm

    target = tmp_path / "victim2.py"
    target.write_text("x = 1\n")
    monkeypatch.setattr(sm, "ALLOWED_FILES", {"victim2.py": str(target)})
    monkeypatch.setattr(sm, "_patches_this_session", 0, raising=False)

    res = sm.patch_file_direct("victim2.py", "x = 2\ny = 3\n")
    assert res["success"] is True
    assert "y = 3" in target.read_text()


# ──────────────────────────────────────────────────────────────────────────
# 4. intent_router run_script — no shell=True for .sh
# ──────────────────────────────────────────────────────────────────────────
def test_run_script_executes_sh_without_shell_true(tmp_path, monkeypatch):
    """A .sh file must run via ["bash", path] (list argv), never shell=True —
    otherwise a filename with shell metacharacters is an injection surface."""
    import intent_router as ir

    script = tmp_path / "harmless.sh"
    script.write_text("#!/bin/bash\necho hi\n")

    monkeypatch.setattr(ir, "_find", lambda *_a, **_k: str(script))

    captured = {}

    class _FakeProc:
        stdout, stderr, returncode = "hi\n", "", 0

    def _fake_run(args, **kwargs):
        captured["args"] = args
        captured["shell"] = kwargs.get("shell", False)
        return _FakeProc()

    monkeypatch.setattr(subprocess, "run", _fake_run)

    ir.execute_intent({"type": "run_script", "groups": [str(script)]})

    assert captured["shell"] is not True
    assert isinstance(captured["args"], list)
    assert captured["args"][0] == "bash"
    assert captured["args"][1] == str(script)


# ──────────────────────────────────────────────────────────────────────────
# 5. autonomous_loop.observe_environment — disk_critical ignores pseudo mounts
# ──────────────────────────────────────────────────────────────────────────
def test_disk_critical_ignores_snap_pseudo_mount(tmp_path, monkeypatch):
    """A 100%-full /snap squashfs (read-only by design) must NOT trip
    disk_critical and short-circuit the goal loop into alert-spam."""
    import autonomous_loop as al

    monkeypatch.setattr(
        al, "get_disk_usage",
        lambda: {"/snap/core": {"percent": 100.0}},
        raising=False,
    )
    obs = al.observe_environment()
    assert obs["disk_critical"] is False


def test_disk_critical_fires_on_real_writable_mount(tmp_path, monkeypatch):
    """A genuinely writable disk over threshold must still trip disk_critical."""
    import autonomous_loop as al

    monkeypatch.setattr(
        al, "get_disk_usage",
        lambda: {str(tmp_path): {"percent": 95.0}},   # real, writable
        raising=False,
    )
    obs = al.observe_environment()
    assert obs["disk_critical"] is True
