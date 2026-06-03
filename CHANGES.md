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

---

## Phase 1 — SECURITY LOCKDOWN

The single most important phase. Before this, `app.py` had `CORS(app)`
(all origins), `host="0.0.0.0"` (all interfaces), and **zero auth on
~200 endpoints**. `config.ULTRON_API_KEYS` existed but was never
checked. Anything reachable on Wi-Fi could call `/self_upgrade/run`
(which rewrites code), `/computer/action` (which moves the mouse),
`/phone/tap` (which controls the phone), etc.

### 1.1 Auth gate (new file `auth.py`)
- `install_auth(app)` registers a `before_request` hook that runs
  before any blueprint route.
- Keys configured → require `X-API-Key` header (or `?api_key=` query
  param) match → otherwise 401.
- Keys not configured → "dev mode": loopback (`127.0.0.1` / `::1`)
  passes; remote callers get **403** with a hint pointing at `.env`.
- Bypass list: `OPTIONS` preflight (CORS handles it), `/`, `/health`,
  anything under `/static/`, plus anything in `ULTRON_PUBLIC_PATHS`
  env var. The voice UI at `/voice` is NOT public by default; if the
  user wants it open, set `ULTRON_PUBLIC_PATHS=/voice`.

### 1.2 CORS lockdown (`app.py`)
- Replaced `CORS(app)` with origins read from `ULTRON_ALLOWED_ORIGINS`
  (defaults to `http://localhost:5000,http://127.0.0.1:5000`).
- `supports_credentials=True` so the UI can still send the API-key
  header alongside the request.

### 1.3 Explicit network bind (`app.py`)
- Default `app.run(host=...)` flipped from `0.0.0.0` to `127.0.0.1`.
- `ULTRON_HOST` and `ULTRON_PORT` override.
- **Hard refuse-to-bind**: if `ULTRON_HOST=0.0.0.0` is set without
  `ULTRON_API_KEYS`, the app prints a warning and `sys.exit(2)`.
  That combination was the original hole — we won't let it recur
  silently.

### 1.4 Confirm-token gate (new file `confirm_gate.py`)
- Second layer beyond auth. Auth proves you're allowed to call ANY
  endpoint; this proves you MEAN to call THIS endpoint.
- Contract: caller must include
  `{"confirm": "I CONFIRM <action_name>"}` in the JSON body or the
  route returns **428 Precondition Required** with a self-describing
  payload (action, required field, expected value).
- Wired into 6 routes that rewrite code or run the upgrade:
  | Route                             | Action name           |
  |-----------------------------------|-----------------------|
  | `POST /self_upgrade/run`          | `self_upgrade_run`    |
  | `POST /self_modify/improve`       | `self_modify_improve` |
  | `POST /self_modify/patch`         | `self_modify_patch`   |
  | `POST /self_modify/rollback`      | `self_modify_rollback`|
  | `POST /self_modify/apply/<id>`    | `self_modify_apply`   |
  | `POST /self_modify/rollback/<id>` | `self_modify_rollback`|
- `/self_modify/propose` and `/self_modify/proposals` are read-only
  / queue-only — gated by auth only.
- Phase 7.3 will consolidate this with the destructive-shell guards
  in `task_orchestrator` and `intent_router`, and switch from the
  literal-string token to a real signed challenge + dry-run preview.

### 1.5 Phone + click input validation (`app.py`, `computer_control.py`)
- `/phone/tap`: `x,y` coerced to int in `[0,4096]` or 400.
- `/phone/key`: `keycode` coerced to int in `[0,300]` or 400.
- `/phone/volume`: `action` restricted to allow-list `{up,down,mute}`
  or 400.
- `execute_computer_action("click", ...)`: `x,y` in `[0,4096]`,
  `clicks` in `[1,10]` (prevents a typo'd `clicks=1_000_000` from
  hammering the desktop for minutes).

### Phase 1 acceptance — `tests/test_auth.py`
33 tests covering all four properties from the plan:
- No keys + remote → 403 (+ loopback dev-mode passes)
- Keys + missing/wrong header → 401; correct header or `?api_key=` → passes
- Public-path + `OPTIONS` preflight bypass
- `/self_upgrade/run` + all 5 `/self_modify/*` write routes require
  the confirm token; near-miss values (`"yes"`) still rejected
- `/phone/tap`, `/phone/key`, `/phone/volume` reject non-int / out-of-
  range / unknown-action inputs; valid inputs pass; float coords
  coerce to int (acceptable behavior)

Verified end-to-end:
- `pytest tests/` → **146 passed** (113 capabilities + 33 auth, no regressions)
- `import app` still boots cleanly (210 routes, 1 `before_request` hook)
- Smoke: `/self_upgrade/run` with the right confirm actually kicks off
  the upgrade pipeline (gate doesn't false-positive on legitimate intent)

To use this from a phone or another device on the LAN:
1. Add `ULTRON_API_KEYS=mySecret123` (and any others, comma-separated)
   to `.env`.
2. Add `ULTRON_HOST=0.0.0.0`.
3. Add `ULTRON_ALLOWED_ORIGINS=http://<your-ip>:5000` if calling from
   a browser at that origin.
4. Send the key with every request:
   `curl -H "X-API-Key: mySecret123" http://<your-ip>:5000/health`.
The app will refuse to bind `0.0.0.0` if step 1 is missing.

---

## Phase 2 — Make the core tools provably perfect

### 2.1 `/home/user` normalization — verified, not blind-rewritten
Per the plan's rule #5 ("verify first"). Ran the real code path:
```
_resolve_path('/home/user/Desktop')           -> '/home/jeevan/Desktop'
_resolve_path('/home/user/Desktop/hello.txt') -> '/home/jeevan/Desktop/hello.txt'
file_list  /home/user/Desktop                 -> 5 folders, 23 files
file_read  /home/user/Desktop/hello.txt       -> Ultron-J Claude Code Plan content
```
The May-21 failures in `tool_stats.json` are stale — the
normalization at `action_engine.py:117-119` already fixed them.
Regression locked by `test_capabilities.py::test_home_user_path_normalization`.

### 2.2 Poisoned `tool_stats.json` reset
Moved root `tool_stats.json` (contained stale `file_list 7/11`,
`file_read 6/9` from May 21) to `_archive/tool_stats.poisoned-2026-06-03.json`.
The reflection engine no longer reads stale 0%/partial data;
`load_tool_stats()` returns `{}` when the file is absent (verified)
and the next real action call rebuilds it clean.

(`tool_stats.json` itself is in `.gitignore` — the archived copy is
preserved locally for forensics but isn't tracked. The move is
documented here so the absence isn't mistaken for a deletion.)

### 2.3 Full 81-pattern intent audit
New `tests/test_intent_audit.py`: 81 sample phrases + 1 count assertion.
For every regex in `intent_router._PATTERNS`, a representative phrase
is fed through `detect_intent` and asserted to dispatch to the
expected `action_type`. Catches three bug classes at once:
  - broken regex (typo / forgotten alternative)
  - shadowing (earlier broad pattern eats a later specific phrase)
  - missing handler (already covered by `test_capabilities.py` but
    re-confirmed at dispatch level)

Where multiple patterns share a type (e.g. read_file has three
phrasings: `read X`, `show X`, `cat X`), each pattern gets its own
phrase using syntax only it matches.

Findings:
  - **No shadowing bugs.** All 81 patterns dispatch correctly when
    given their intended phrasing.
  - **One UX gap noted (deferred to Phase 8):** pattern 23
    (`what's in / show me <qualifier> <path>`) only matches when the
    folder/directory/files qualifier appears BEFORE the path
    (`"what's in folder downloads"`). The more natural English
    `"what's in downloads"` or `"what's in downloads folder"` falls
    through to the LLM. The pattern is doing what it was written to
    do; broadening it would shadow `"show me the time"` and other
    `show me <something>` phrasings — needs a more careful redesign
    in Phase 8.

### Bonus: flaky-test fix in `test_capabilities.py`
The `HAS_NET` probe was computed once at module import time with a
1.5s timeout. A cold DNS lookup on the first run would set
`HAS_NET=False` for the entire pytest session, silently skipping
weather_fetch + web_scrape even when network was up. Symptom: 2
skipped in the full suite, 0 skipped when run in isolation.
Fix: probe per-test at 3s timeout. Each test now decides for itself.

### Phase 2 acceptance
Full test suite after Phase 2:
```
pytest tests/ --timeout=20 -q
228 passed in 4.07s         (was 146 + 82 new audit tests)
```
- file + intent + calculate + note + sandbox tools: **100% PASS**
- network-dependent tools (weather_fetch, web_scrape): **PASS** (no
  skips when network is up)
- 81-pattern intent dispatch audit: **all green** (no shadowing)

---

## Phase 3 — One autonomous goal completes end-to-end

The reflection log had been flat-zero for weeks: `total_goals_ever=0`,
`success_rate_pct=0`, `avg_execution_score=0`. The loop was healthy
but idle. Phase 3 traced the lifecycle, found and fixed two real
blockers, and drove one real goal through the full pipeline.

### 3.1 Goal-lifecycle trace + disk-critical bug fix
Live trace before any edit (per master-prompt rule #5):
```
load_goals()          -> [] (file doesn't exist)
get_active_goals()    -> 0
get_next_goal()       -> None
3 decision cycles     -> {'action':'alert','msg':'Disk critical — cleanup needed'} x 3
```
Two root causes for the flat-zero metrics:
1. **No goals exist** — `goals.json` was empty and no module
   auto-creates one. The loop sits on `observe`/`self_evaluate` forever.
2. **`disk_critical` false-positive bug** — `autonomous_loop.observe_environment`
   was running `any(percent > 92 for d in get_disk_usage().values())`,
   but `psutil.disk_partitions()` on this Linux box reports squashfs
   snap mounts (`/snap/core22`, `/snap/ngrok`, `/snap/snapd`) at
   **100.0% — by design** (they're read-only loop devices). The check
   fired every cycle and short-circuited `decide_next_action` into
   alert-spam, blocking the goal path even when goals did exist.
   Fix: exclude `/snap/`, `/var/lib/docker/`, `/proc/`, `/sys/`, `/dev/`
   mount-point prefixes from the disk_critical check. After the fix,
   `disk_critical = False`, decisions flow to observe/self_evaluate
   then start_goal once goals exist.

### 3.2 Web-search dependency fix
Reflection log flagged "Web search not being used — verify SearXNG
and DDG integrations." Live probe before edit:
```
DDGS_AVAILABLE          False  (module 'ddgs' not installed)
SEARXNG_URL probe       Connection refused (no local SearXNG server)
import bs4              ModuleNotFoundError
```
Actioned proposal #0 from `proposals.json`:
- Installed `ddgs==9.14.4` + `beautifulsoup4==4.14.3` plus transitive
  deps (`brotli`, `lxml`, `soupsieve`, `primp`, `fake-useragent`,
  `h2`, `hpack`, `hyperframe`, `socksio`) — 11 new packages total.
- After install: `DDGS_AVAILABLE=True`, DDG returned 3 results for
  "hyderabad weather", `web_scrape("https://example.com")` succeeded.
- `requirements.txt` updated (now 154 lines). Header note added: bs4,
  ddgs, lxml are now required, not optional.
- `proposals.json` proposal #0 marked `status: applied`, with
  applied_at + applied_by + notes. SearXNG remains optional (it's a
  self-hosted server, beyond a pip install).

### 3.3 Pre-populated-task fix + tests/test_autonomous_goal.py
**Design gap discovered:** `action_engine.execute_goal_step` was
building params as `{"content": desc, "prompt": desc}` and IGNORING
any `task["params"]`. So a goal that wanted `weather_fetch` (needs
`params.location`) or `note_create` (needs `title` + `content`) could
never actually complete. Fix: merge `task.get("params") or {}` on top
of the desc-based defaults — backward compatible with old ask_llm
tasks.

`tests/test_autonomous_goal.py` (NEW): seeds the demo goal
"fetch Hyderabad weather → save a note" with two pre-populated tasks
(weather_fetch + note_create), drives the observe→decide→plan→act→
evaluate cycle in-process for ≤15 iterations, then asserts:
- goal reaches `COMPLETED`
- `execution_score > 0` and `progress_pct >= 80`
- every task ended in `SUCCESS` (catches "goal marked complete but a
  silent task failure" mode)
- `reflection.analyze_performance()`:
  - `completed_today >= 1`
  - `success_rate_pct > 0`
  - `avg_execution_score > 0`

Backs up + restores `goals.json` / `execution_log.json` so the test
doesn't pollute user state.

### Phase 3 acceptance — live demonstration
Ran the same flow OUTSIDE the test (no state restore) to leave a
real completed goal on disk:
```
goal completed in 3 iterations

=== final goal state ===
status:           completed
progress_pct:     100
execution_score:  10
result_summary:   Completed 2/2 tasks
tasks:
  [SUCCESS] step_0  weather_fetch   'Hyderabad: Sunny, 35°C ...'
  [SUCCESS] step_1  note_create     "Note created: 'Phase 3 live demo...'"

=== reflection.analyze_performance() ===
  total_goals_ever          1
  completed_ever            1
  completed_today           1
  success_rate_pct          100.0
  total_actions_logged      2
  avg_execution_score       10.0
```
Acceptance gate met: success rate **>0%** (actually 100%), at least
one genuinely-completed goal logged.

Suite after Phase 3: **229 passed in 8.63s** (was 228; +1 from the
new autonomous-goal test). No regressions.

---

## Phase 4 — Background loops: throttle + gate (health_score 17 → 98)

The plan's diagnosis: ~17 always-on daemons + full-file JSON rewrites
were keeping memory at 80-95% and pinning `health_score` to 17. Phase
4 added a central loop registry, memory backpressure, and a
sqlite-first hot-memory path — and along the way, found the disk
false-positive ALSO lived in `get_system_health_score()`, which
explained the entire 17 score.

### 4.0 Survey
13 boot-time daemons mapped: system_monitor (×2), perception (×2),
autonomous_loop, activity_tracker, code_indexer, screen_monitor,
plugin_watcher, distiller, evolution, proactive, predictive,
skill_learner. Double-storage of episodes confirmed: 459 rows in
`ultron.db` ~= 461 in `episodic_memory.json` (189KB rewritten on
every store).

### 4.1 Central LOOPS registry + loop_supervisor.py
- `config.LOOPS` is the single source of truth — `{enabled, interval_s}`
  per loop, plus `MEM_BACKPRESSURE_PCT` (default 70).
- Default OFF: `evolution`, `proactive`, `skill_learner`,
  `screen_monitor`. They were running on empty input or pulling
  heavy resources (screen_monitor screenshots every 3s) for no payoff
  until Phases 3/8 produce real signal.
- Default ON, retuned: `predictive` 60s → **300s** (the dominant
  source of mem_rising anomalies — was rewriting predictive_metrics.json
  every minute).
- Env override per loop: `LOOPS_<NAME>_ENABLED=0|1`,
  `LOOPS_<NAME>_INTERVAL_S=<n>`.
- `loop_supervisor.py` exposes 3 primitives — `loop_enabled(name)`,
  `loop_interval_s(name, default)`, `should_skip_heavy_tick()` —
  each `start_*` function calls them in a 5-line guard at the top.
  No architectural rewrite required.
- `loop_supervisor.snapshot()` reports configured + effective state +
  live mem_pct; future `/loop/status` endpoint can use it (Phase 8.1).

### 4.2 Memory backpressure
`should_skip_heavy_tick()` returns True when `psutil.virtual_memory().percent`
exceeds `MEM_BACKPRESSURE_PCT`. Heavy loops consult it at the top of
each tick: `predictive_monitor._loop`, `code_indexer._run`,
`screen_engine._loop`. Lightweight loops (heartbeat, plugin_watcher)
intentionally don't — backpressure is the heavy loops' problem.

### 4.3 sqlite-first hot memory
The old `store_episode` did `load_episodes()` (full JSON read) →
append → `save_episodes()` (full 189KB rewrite) → `INSERT INTO
episodes` on every call. With ~460 episodes that's O(n) write
amplification on every conversation turn.
- New path: write one SQLite row → bump in-process counter →
  `_flush_episodes_to_json()` only every `EPISODE_EXPORT_EVERY=50`
  stores or when consolidation actually fires.
- `load_episodes()` reads from SQLite (source of truth); falls back
  to JSON only on cold-start (fresh clone, no DB).
- One-time migration on import: any episode in JSON but not in SQLite
  is `INSERT OR IGNORE`-imported. Safe to repeat across boots.
- Added `consolidated` column to `episodes` table via idempotent
  ALTER TABLE.
- Fixed a long-standing pre-existing bug: the old consolidation
  check was firing on every store (`unconsolidated >= 200` was true
  forever once the threshold was crossed). New: consolidation check
  happens only inside the periodic flush, not per-store.

**Verified hot-path zero-write:**
```
mtime BEFORE 3 store_episode calls:  1780474386
mtime AFTER  3 store_episode calls:  1780474386  (delta +0s)
JSON size 186690 bytes — unchanged
SQLite went from 462 -> 465 episodes
```

### Phase 4 acceptance — health_score
`get_system_health_score()` had the **same disk false-positive** as
the Phase 3 fix in `autonomous_loop`: it penalized -10 per mount
>80% and -15 per mount >90%. On this Linux box there are 4 snap
squashfs mounts at 100% (read-only loop devices, full by design) =
−100 points alone. That was the entire health_score=17 explanation.

Same fix applied: exclude `/snap/`, `/var/lib/docker/`, `/proc/`,
`/sys/`, `/dev/` mount prefixes. Live result:
```
Pre-fix:   health_score = 17/100   (heartbeat.json snapshot)
Post-fix:  health_score = 98/100   (computed inline; +81 points)
```

Boot verification (port 5099, idle, real loops respecting registry):
```
[distiller] loop started — interval=6.0h
[evolution] loop disabled by config.LOOPS — not starting
[proactive] loop disabled by config.LOOPS — not starting
[predictive] monitor started — interval=300.0s
[skill_learner] loop disabled by config.LOOPS — not starting
```
4 heavy daemons skipped vs the old boot. predictive interval 5x
slower.

Suite after Phase 4: **229 passed in 10.96s** — no regressions vs
Phase 3 baseline.

---

## Phase 5 — Consolidate the over-wired brain

The plan's diagnosis: too many overlapping reasoning engines
(`intelligence_core`, `react_engine`, `brain_orchestrator`,
`decision_engine`, `task_orchestrator`, `autonomous_loop`,
`evolution_loop`, `proactive_planner`), and `react_engine` /
`brain_orchestrator` only reachable via `intelligence_core`. Phase 5
documented the real graph, gated the optional engines, confirmed the
proposal-writing path is already single-source, and added a
route-smoke regression test.

### 5.1 Real call graph + `ARCHITECTURE.md`
Static AST scan + manual dynamic-import sweep computed fan-in per
module. Top 12 are the canonical spine (config 35, llm_engine 23,
memory 22, computer_control 14, loop_supervisor 12, decision_engine
12, system_monitor 11, personality 11, action_engine 7, vector_store
7, screen_engine 6, perception 6). `task_orchestrator` and
`decision_engine` stay canonical for autonomous-flow; `intelligence_core`
stays canonical for interactive `/ask` flow.

`ARCHITECTURE.md` (new) documents:
  - The TWO independent primary flows (interactive `/ask` vs
    autonomous goal loop) — they're often confused for one engine
  - Full background loop table (Phase 4.1 registry effective state)
  - Single-writer proposal flow (Phase 5.3)
  - Runtime file ownership (who writes / reads `ultron.db`,
    `goals.json`, `proposals.json`, etc.)
  - The "orphan"-looking modules that are actually wired via
    `ultimate_routes._safe_import` — and the 8 genuine orphans
    (test scripts) staged for Phase 7 archive

### 5.2 One primary decision path
`intelligence_core.think_and_stream` no longer routes COMPLEX
questions through `react_engine` by default. Both opt-in engines now
share a single environment-variable gate, `INTELLIGENCE_MODE`:

|        | `INTELLIGENCE_MODE` value | What it does                  |
|--------|---------------------------|-------------------------------|
| (none) | unset / empty             | Default — prompt-based path   |
| react  | `react`                   | Enable `react_engine.reason`  |
| plan   | `plan`                    | Enable `brain_orchestrator`   |

Legacy `USE_BRAIN_ORCHESTRATOR=1` and the `"plan this"` /
`"kartha plan"` natural-language triggers still work. Neither
`react_engine` nor `brain_orchestrator` was deleted — both still
import cleanly, just no longer wire themselves in by default.

The default COMPLEX path now goes through the same
`_stream_with_intelligence_prompt` as MEDIUM but with the long
model — one route through the file instead of three.

### 5.3 Single-writer proposal flow
Audit found `system_monitor.add_proposal` is ALREADY the only writer
of `proposals.json` (verified by grep — `smart_home.py` writes to a
separate `code_proposals.json`, different domain). Four generators
funnel through it: `reflection`, `evolution_loop`,
`predictive_monitor`, `proactive_planner`. Title-dedup prevents
generators from spamming the file with duplicate suggestions.

Improvement: added a `source` field to every proposal so the UI can
show which generator produced each one. `reflection`, `evolution_loop`,
`predictive_monitor` now pass their `source` tag through; legacy
proposals get `"unspecified"`.

### Phase 5 acceptance — route smoke + green tests
New `tests/test_route_smoke.py`: parametrize over EVERY registered
Flask route (across all 7 blueprints), send a GET or POST with empty
body, assert the response is NOT a server crash (200-499 OK; 503
accepted as the documented "feature not installed" mode).

Bug caught + fixed during this work:
  - `POST /verify/screenshot` was returning **500** (uncaught
    exception) when `gnome-screenshot` binary wasn't installed.
    Wrapped `take_labeled_screenshot` in try/except, returns 503
    with a precise hint about what's missing.

Locked baselines:
  - Suite: **436 passed in 58.48s** (was 229; +207 route-smoke tests).
  - Route count check: 200 ≤ N ≤ 250 (currently 210).
  - Capability suite + autonomous-goal test: still all green, no
    regressions from the engine-gating.
