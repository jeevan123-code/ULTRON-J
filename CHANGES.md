# CHANGES — Ultron-J Hardening Branch

Per-task log of moves, deletions, and notable behavior changes on the
`hardening` branch. The branch's job is to make Ultron-J's CURRENT
abilities provably solid and secure before extending it. See
`hello.txt` (the Claude Code Execution Plan v2) for the full phase
order and acceptance gates.

The rule from the master prompt: **never delete a file** — move it to
`_archive/` and log it here.

---

## Phase 0 — Safety net & ground truth

### 0.1 Compile baseline
- Branch `hardening` created off `master` (master HEAD at the time:
  `49deb11` "Voice stack: single male voice, terse TTS mode, snap-wake detector").
- All 97 project `.py` files compile under `venv/bin/python -m py_compile`.
  Re-run after every task; today still 85 `.py` (post-archive) all PASS.

### 0.2 Pin dependencies
- New `requirements.txt` (119 packages pinned to the exact versions in
  `venv/`, cross-checked against `system_snapshot.json`).
- New `requirements-dev.txt` (`pytest==9.0.3`, `pytest-timeout==2.4.0`).
- `.gitignore` amended: global `*.txt` rule was hiding the new files;
  added explicit negations for `requirements.txt`, `requirements-dev.txt`,
  and `BASELINE_CAPABILITIES.txt`.
- Optional ML/voice/Windows-only deps (torch, whisper, mem0, langchain,
  pywin32, pycaw, …) are intentionally NOT pinned — they're already
  imported via `try/except` and installed on demand per feature.

### 0.3 Capability self-test harness
- New `tests/test_capabilities.py` — covers file roundtrip, calculate,
  sandbox, note_create, file_list, append, delete_file, git_status, the
  `/home/user` path-normalization regression, weather_fetch + web_scrape
  (network-gated), pattern-count lock at 81, parametrized
  "every-pattern-has-a-handler" check, and 19 curated phrase→type
  dispatch checks.
- First-run snapshot saved to `BASELINE_CAPABILITIES.txt`:
  **114 PASS, 0 FAIL, 0 SKIP**. This is the regression target every
  later phase must not drop below.
- Initial handler-scan regex was too narrow and false-flagged 6
  patterns (`repeat_last`, `help_me_now`, `edit_file`) that ARE handled
  but via `t in (…)` shared branches or route-layer `_intent["type"] ==
  "…"` checks in `app.py`. Broadened the scan to union all five
  dispatch forms found in the codebase.

### 0.4 Archive clutter (no deletions)
Moved to `_archive/` — kept in git so history is preserved:
| Path now                                | Why                          |
|-----------------------------------------|------------------------------|
| `_archive/run_phase_b.py`               | one-off phase-B runner       |
| `_archive/run_phase_b_recheck.py`       | one-off phase-B recheck      |
| `_archive/run_phase_c.py`               | one-off phase-C runner       |
| `_archive/run_phase_d.py`               | one-off phase-D runner       |
| `_archive/run_klmj.py`                  | one-off K-L-M-J runner       |
| `_archive/phase_m_timing.py`            | one-off phase-M timing probe |
| `_archive/phase_n.py`                   | one-off phase-N runner       |
| `_archive/trace_upgrade.py`             | one-off upgrade tracer       |
| `_archive/append_session_to_ok.py`      | one-off session logger       |
| `_archive/append_session_closeout.py`   | one-off session logger       |
| `_archive/remaining_tests.py`           | one-off test runner          |
| `_archive/unit_test_self_upgrade.py`    | one-off self-upgrade test    |
| `_archive/run_open_any_app.py`          | one-off probe                |
| `_archive/crypto_price.root.py`         | duplicate of `plugins/crypto_price.py`; root copy verified unused by `grep -rn "import crypto_price"` (only the plugins version is referenced) |
| `_archive/.tmp_iz20b5j0.json`           | stray temp file              |
| `_archive/.tmp_wdka8n1u.json`           | stray temp file              |

Acceptance verified:
- 85 `.py` still compile clean.
- `import app` succeeds and registers all 210 routes / 7 blueprints.
- `pytest tests/test_capabilities.py` still **113 passed** (one record
  is parametrized so 113 tests = 114 records).
