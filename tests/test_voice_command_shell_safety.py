"""Voice commands must never build a shell command line from spoken text.

The 2026-07-03 hardening batch removed shell=True from intent_router for exactly
this reason, but the same pattern survived in voice_commands_upgrade — which
voice_routes imports — on the Windows branches:

    subprocess.Popen(f'explorer "{path}"', shell=True)   # path <- speech
    subprocess.Popen(app, shell=True)                    # app  <- speech

The parser is regex-bounded and these are Windows-only, so this was latent
rather than live. It is still the same class of bug, so it gets the same fix:
list-form argv, no shell, on every platform.
"""
import subprocess

import pytest

import voice_commands_upgrade as vcu


@pytest.fixture
def popen_spy(monkeypatch):
    calls = []

    class _FakeProc:
        pass

    def _spy(args, **kw):
        calls.append({"args": args, "kw": kw})
        return _FakeProc()

    monkeypatch.setattr(subprocess, "Popen", _spy)
    monkeypatch.setattr(vcu.subprocess, "Popen", _spy)
    return calls


def _assert_no_shell(calls):
    for c in calls:
        assert c["kw"].get("shell") is not True, f"shell=True used: {c}"
        assert isinstance(c["args"], (list, tuple)), (
            f"argv must be a list, not a shell string: {c['args']!r}")


# ── the helpers ─────────────────────────────────────────────────────────────
def test_open_path_never_uses_a_shell(monkeypatch, popen_spy):
    monkeypatch.setattr(vcu.platform, "system", lambda: "Linux")
    vcu._open_path("/home/user/Desktop")
    _assert_no_shell(popen_spy)


def test_open_path_with_metacharacters_stays_a_single_argv_entry(
        monkeypatch, popen_spy):
    monkeypatch.setattr(vcu.platform, "system", lambda: "Linux")
    nasty = '/home/user/x" & touch /tmp/pwned & echo "'
    vcu._open_path(nasty)
    _assert_no_shell(popen_spy)
    assert popen_spy[0]["args"][-1] == nasty, "path must survive as one argument"


def test_launch_app_never_uses_a_shell(monkeypatch, popen_spy):
    monkeypatch.setattr(vcu.platform, "system", lambda: "Linux")
    vcu._launch_app("firefox")
    _assert_no_shell(popen_spy)
    assert popen_spy[0]["args"] == ["firefox"]


def test_launch_app_with_injection_payload_is_not_split_into_a_command(
        monkeypatch, popen_spy):
    monkeypatch.setattr(vcu.platform, "system", lambda: "Windows")
    payload = 'calc & del /f /q C:\\important'
    vcu._launch_app(payload)
    _assert_no_shell(popen_spy)
    assert popen_spy[0]["args"] == [payload], (
        "the whole string must be treated as one executable name, never parsed "
        "by a shell")


def test_helpers_report_failure_instead_of_raising(monkeypatch):
    def _boom(*a, **k):
        raise OSError("no such binary")

    monkeypatch.setattr(vcu.subprocess, "Popen", _boom)
    monkeypatch.setattr(vcu.platform, "system", lambda: "Linux")
    assert vcu._open_path("/nope") is False
    assert vcu._launch_app("nope") is False


# ── the call sites that used to interpolate ─────────────────────────────────
def test_open_system_folder_command_uses_no_shell(monkeypatch, popen_spy):
    monkeypatch.setattr(vcu.platform, "system", lambda: "Linux")
    vcu.execute_upgraded_voice_command('OPEN_SYSTEM_FOLDER:desktop')
    _assert_no_shell(popen_spy)


def test_open_app_command_uses_no_shell(monkeypatch, popen_spy):
    monkeypatch.setattr(vcu.platform, "system", lambda: "Windows")
    vcu.execute_upgraded_voice_command('OPEN_APP:notepad" & calc & "')
    _assert_no_shell(popen_spy)


def test_no_shell_true_remains_with_interpolated_values():
    """Guard the file itself: no interpolated value may reach a shell.

    AST-based rather than text-based so that documentation quoting the old
    broken form does not trip it.
    """
    import ast
    src = open(vcu.__file__, encoding="utf-8").read()
    offenders = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        shell_on = any(kw.arg == "shell" and
                       isinstance(kw.value, ast.Constant) and
                       kw.value.value is True
                       for kw in node.keywords)
        if not shell_on:
            continue
        # An f-string or any non-literal first argument means the command line
        # is being built at runtime from a value we do not control.
        for arg in node.args[:1]:
            if isinstance(arg, ast.JoinedStr) or not isinstance(arg, (ast.Constant, ast.List)):
                offenders.append(f"line {node.lineno}")
    assert offenders == [], f"interpolated shell command lines at: {offenders}"
