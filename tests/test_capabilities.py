"""
Phase 0.3 capability self-test harness.

Goal: exercise every core tool path and every intent-pattern dispatch so that
regressions show up as a red row in the printed capability table instead of
silently rotting in tool_stats.json. Network-dependent calls are SKIPped with
a clear reason rather than failing.

Run:
    venv/bin/python -m pytest tests/test_capabilities.py -v -s --timeout=20

Saves a capability snapshot to BASELINE_CAPABILITIES.txt at the end.
"""

import os
import re
import sys
import json
import socket
from pathlib import Path

import pytest

# Project root on sys.path so `import action_engine` resolves
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import action_engine as ae  # noqa: E402
import intent_router as ir  # noqa: E402

# ─── Results table ─────────────────────────────────────────────────────────────

RESULTS: list[tuple[str, str, str]] = []   # (name, status, detail)


def _record(name: str, ok: bool, detail: str = "", *, skipped: bool = False) -> bool:
    status = "SKIP" if skipped else ("PASS" if ok else "FAIL")
    RESULTS.append((name, status, detail))
    return ok


def _has_network(host: str = "1.1.1.1", port: int = 53, timeout: float = 3.0) -> bool:
    """Probe DNS port on a public anycast IP. Called per-test so a cold
    one-off slow probe at import time doesn't pin the whole suite into
    skip-mode. A 3s timeout tolerates first-DNS lag on cold networks.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ─── action_engine: file roundtrip ─────────────────────────────────────────────

def test_create_and_read_file(tmp_path):
    target = tmp_path / "probe.txt"
    w = ae.execute_action("create_file", {"path": str(target), "content": "hi"})
    assert _record("create_file", w.get("success"), w.get("error", "") or w.get("result", "")[:60])
    r = ae.execute_action("file_read", {"path": str(target)})
    assert _record("file_read", r.get("success") and r.get("result") == "hi",
                   r.get("error", "") or f"got={r.get('result')!r}")


def test_file_write_alias(tmp_path):
    target = tmp_path / "alias.txt"
    w = ae.execute_action("file_write", {"path": str(target), "content": "alias"})
    _record("file_write", w.get("success"), w.get("error", ""))
    assert target.read_text() == "alias"


def test_append_file(tmp_path):
    target = tmp_path / "append.txt"
    target.write_text("one\n")
    a = ae.execute_action("append_file", {"path": str(target), "content": "two\n"})
    assert _record("append_file", a.get("success"), a.get("error", ""))
    assert target.read_text() == "one\ntwo\n"


def test_file_list(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "sub").mkdir()
    out = ae.execute_action("file_list", {"path": str(tmp_path)})
    ok = out.get("success") and "a.txt" in out.get("result", "") and "b.txt" in out.get("result", "")
    assert _record("file_list", ok, out.get("error", ""))


def test_delete_file(tmp_path):
    target = tmp_path / "kill.txt"
    target.write_text("x")
    out = ae.execute_action("delete_file", {"path": str(target)})
    assert _record("delete_file", out.get("success") and not target.exists(), out.get("error", ""))


# ─── action_engine: sandbox + calculate + note ────────────────────────────────

def test_calculate():
    out = ae.execute_action("calculate", {"expression": "2+2*5"})
    ok = out.get("success") and "12" in str(out.get("result", ""))
    assert _record("calculate", ok, f"result={out.get('result')!r}")


def test_run_python_sandbox():
    out = ae.execute_action("run_python", {"code": "print(sum(range(5)))"})
    ok = out.get("success") and "10" in str(out.get("result", ""))
    assert _record("run_python", ok, f"result={out.get('result')!r} err={out.get('error', '')}")


def test_note_create():
    out = ae.execute_action(
        "note_create",
        {"title": "Phase0 probe", "content": "capability harness", "category": "test"},
    )
    assert _record("note_create", out.get("success"), out.get("error", ""))


def test_git_status_self_repo():
    # ULTRON_WEB itself is a git repo — git_status on . should succeed
    out = ae.execute_action("git_status", {"path": str(ROOT)})
    assert _record("git_status", out.get("success"), out.get("error", ""))


# ─── action_engine: /home/user path normalization (Phase 2.1 regression) ──────

def test_home_user_path_normalization():
    real_home = os.path.expanduser("~")
    resolved = ae._resolve_path("/home/user/Desktop")
    ok = resolved.startswith(real_home)
    assert _record("path_normalize:/home/user", ok, f"resolved={resolved!r}")


# ─── Network-gated tools ──────────────────────────────────────────────────────

def test_weather_fetch():
    if not _has_network():
        _record("weather_fetch", True, "no network", skipped=True)
        pytest.skip("no network")
    out = ae.execute_action("weather_fetch", {"location": "Hyderabad"})
    # Don't fail on no-API-key; record SKIP if missing creds, PASS if success
    if not out.get("success"):
        _record("weather_fetch", True, f"skip: {out.get('error', '')[:80]}", skipped=True)
        pytest.skip(f"weather unavailable: {out.get('error', '')}")
    _record("weather_fetch", True, out.get("result", "")[:60])


def test_web_scrape():
    if not _has_network():
        _record("web_scrape", True, "no network", skipped=True)
        pytest.skip("no network")
    out = ae.execute_action("web_scrape", {"url": "https://example.com"})
    ok = out.get("success") and "Example Domain" in out.get("result", "")
    assert _record("web_scrape", ok, out.get("error", "") or "ok")


# ─── intent_router: every pattern must have a dispatch branch ─────────────────

def _intent_router_handled_types() -> set[str]:
    """A pattern's type is 'handled' if any code path dispatches on it.

    The dispatch can take several forms in this codebase:
      * `t == "X"`                       (intent_router.execute_intent)
      * `t in ("X", "Y")`                (intent_router shared branches)
      * `_intent["type"] == "X"`         (route-layer handling in app.py)
      * `action_type == "X"`             (action_engine.execute_action)
      * `action_type in ("X", "Y", ...)` (action_engine shared branches)

    Scan every project .py for any of those forms, union the result.
    """
    handled: set[str] = set()
    EQ_PATTERNS = [
        re.compile(r'\bt\s*==\s*"([^"]+)"'),
        re.compile(r'\[\s*["\']type["\']\s*\]\s*==\s*"([^"]+)"'),
        re.compile(r'\.get\(\s*["\']type["\']\s*\)\s*==\s*"([^"]+)"'),
        re.compile(r'\baction_type\s*==\s*"([^"]+)"'),
    ]
    IN_PATTERNS = [
        re.compile(r'\bt\s+in\s+\(([^)]+)\)'),
        re.compile(r'\baction_type\s+in\s+\(([^)]+)\)'),
        re.compile(r'\[\s*["\']type["\']\s*\]\s+in\s+\(([^)]+)\)'),
    ]
    STR_LIT = re.compile(r'"([^"]+)"')

    SKIP_DIRS = {"venv", ".venv", "_archive", "tests", "__pycache__",
                 "chroma_memory", "browser_cache", "voice_cache",
                 "screen_cache", "extracted_code", "visual_verify_cache",
                 "self_modify_backups", "config_backups", "workspace",
                 "task_graphs", "piper_voices", "logs"}

    for dirpath, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            src = (Path(dirpath) / fn).read_text(encoding="utf-8", errors="ignore")
            for pat in EQ_PATTERNS:
                handled.update(pat.findall(src))
            for pat in IN_PATTERNS:
                for tup in pat.findall(src):
                    handled.update(STR_LIT.findall(tup))
    return handled


HANDLED_TYPES = _intent_router_handled_types()


def test_pattern_count_unchanged():
    """Lock the pattern count so accidental deletions are caught."""
    assert _record("pattern_count==81", len(ir._PATTERNS) == 81, f"got={len(ir._PATTERNS)}")


@pytest.mark.parametrize(
    "pattern,action_type",
    ir._PATTERNS,
    ids=[f"{i:02d}:{p[1]}" for i, p in enumerate(ir._PATTERNS)],
)
def test_every_pattern_has_handler(pattern, action_type):
    """For every regex in _PATTERNS, the action_type it maps to must have a
    dispatch branch somewhere — either intent_router.execute_intent or
    action_engine.execute_action. Otherwise we silently drop the user's intent."""
    ok = action_type in HANDLED_TYPES
    _record(f"handler:{action_type}", ok, "" if ok else "no dispatch branch found")
    assert ok, f"intent type {action_type!r} from pattern {pattern!r} has no handler"


# ─── intent_router: curated phrases must detect to the right type ─────────────

CURATED_PHRASES: list[tuple[str, str]] = [
    ("open chrome",                          "open_app"),
    ("open my resume.pdf",                   "open_file"),
    ("read notes.txt",                       "read_file"),
    ("list files in downloads folder",       "list_dir"),
    ("what time is it",                      "get_time"),
    ("what's the date today",                "get_date"),
    ("take a screenshot",                    "take_screenshot"),
    ("volume up",                            "volume_up"),
    ("mute",                                 "volume_mute"),
    ("pause",                                "media_pause"),
    ("next track",                           "media_next"),
    ("scroll down",                          "scroll_down"),
    ("press enter",                          "press_enter"),
    ("press escape",                         "press_escape"),
    ("search the web for wheat diseases",    "search_web"),
    ("repeat",                               "repeat_last"),
    ("help me",                              "help_me_now"),
    ("lock screen",                          "lock_screen"),
    ("system info",                          "system_info"),
]


@pytest.mark.parametrize("phrase,expected_type", CURATED_PHRASES,
                         ids=[p[0][:40] for p in CURATED_PHRASES])
def test_curated_phrase_dispatch(phrase, expected_type):
    intent = ir.detect_intent(phrase)
    got = intent["type"] if intent else None
    ok = got == expected_type
    _record(f"phrase:{phrase[:30]}", ok, f"expected={expected_type} got={got}")
    assert ok, f"{phrase!r} -> {got!r} (wanted {expected_type!r})"


# ─── Snapshot writer ──────────────────────────────────────────────────────────

def _snapshot_lines(results):
    """Render the capability table.

    PASSing rows deliberately carry NO detail. They used to record whatever the
    check happened to output — pytest tmpdir ids, live weather readings — which
    made this tracked file differ on every run, so `git status` was never clean
    and real changes to it went unnoticed. The table's contract is which
    capabilities work; detail is kept where it is diagnostic, on FAIL and SKIP.
    """
    pass_n = sum(1 for _, s, _ in results if s == "PASS")
    fail_n = sum(1 for _, s, _ in results if s == "FAIL")
    skip_n = sum(1 for _, s, _ in results if s == "SKIP")
    lines = [
        "=== ULTRON-J CAPABILITY TABLE ===",
        f"PASS={pass_n}  FAIL={fail_n}  SKIP={skip_n}  TOTAL={len(results)}",
        "",
    ]
    for name, status, detail in results:
        shown = "" if status == "PASS" else (detail or "")
        lines.append(f"{status:4}  {name:50s}  {shown}".rstrip())
    return lines


def _write_snapshot():
    path = ROOT / "BASELINE_CAPABILITIES.txt"
    path.write_text("\n".join(_snapshot_lines(RESULTS)) + "\n", encoding="utf-8")


def teardown_module(_):
    print("\n=== CAPABILITY TABLE ===")
    for name, status, detail in RESULTS:
        print(f"{status:4}  {name:50s}  {detail}")
    _write_snapshot()
    print(f"\nSnapshot written to {ROOT / 'BASELINE_CAPABILITIES.txt'}")
