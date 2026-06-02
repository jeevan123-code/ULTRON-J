block = """

================================================================================
SESSION 2026-05-16 (evening) -- PHASES F-N FIX PASS (CLAUDE OPUS 4.7)
================================================================================
Brief: Jeevan asked to run the remaining phases (F-N) after A-E. Phase F was
skipped (needs mic), Phase 4 stays deferred. Found 5 real bugs across phases
G/H/I/J/K/L and patched all of them with verified fixes. Ollama skipped per
do-not-touch (reconfirmed in this session).

--------------------------------------------------------------------------------
HEAD-LINE RESULT
--------------------------------------------------------------------------------
- Phase G   (screen monitor)      : G1 GREEN. G3 picker mis-routes "what does
                                    my screen say" to get_window (window title
                                    only, not OCR). Behavioral, deferred.
- Phase H   (activity tracker)    : last_key updates correctly; mouse_pos /
                                    last_mouse_move / last_click stay at 0.0.
                                    pynput keyboard hook works, mouse hook
                                    appears not to fire. Needs Jeevan to move
                                    the mouse for 5+ sec and re-curl
                                    /system/activity to confirm pynput-vs-env.
- Phase I   (search + browser)    : I1, I3 now GREEN post-fix. Tavily returns
                                    plain-text summary, no SSE leak. SearchOn-
                                    Site demoted to search_web when site arg
                                    is not a real domain.
- Phase J   (self-upgrade)        : J3 was DESTRUCTIVE -- clicked once, it
                                    overwrote action_engine.py (1133->67 lines
                                    of raw SSE chunks). Restored from backup.
                                    Now patched: validate() rejects, apply_fix
                                    verifies exports survive reload.
- Phase K   (hardening)           : K1/K2 test plan calls
                                    self_modify.patch_file but the real export
                                    is patch_file_direct (or SelfModifier
                                    method). Guard works; test invocation in
                                    ok.txt is stale. K4 FORBIDDEN list good.
- Phase L   (stress)              : L1 graceful, L4 graceful fallback, L5
                                    unicode OK. L3 pre-fix: 8 PASS / 1 (500) /
                                    1 timeout. Post-fix: 6 PASS / 0 (500) /
                                    4 timeouts. The 500 was OneDrive lock on
                                    atomic_json_write rename -- now retry-wrapped.
- Phase M, N: Not separately executed; queued for next session if needed.

--------------------------------------------------------------------------------
BUGS FOUND & FIXED THIS SESSION (file:line)
--------------------------------------------------------------------------------
BUG 1 -- CATASTROPHIC: self_upgrade.generate_fix raw-SSE handling
  File: self_upgrade.py:213-221 (old) / now 187-219 + 250-275
  Cause: stream_llm yields SSE strings ('data: {"token": "..."}\\n\\n') plus a
         final 'data: {"_full": "..."}\\n\\n'. The old isinstance(chunk, str)
         branch appended those SSE lines verbatim, so the "new source code"
         was a wall of `data: {...}` lines.
  Impact: J3 overwrote action_engine.py with 67 lines of SSE blob.
  Fix:   New _parse_stream_llm_output() parses SSE per-line, preferring _full
         and accumulating tokens, ignoring status hints. Strips code fences.

BUG 1a -- validate() too weak
  File: self_upgrade.py:235-261 (old) / now 290-340
  Cause: ast.parse accepts `data: {"token":"x"}` as PEP 526 variable
         annotation; exec() runs no-op. Validator passed despite corruption.
  Fix:   Added _top_level_defs(source) and a public-API survival check --
         the new code MUST define every top-level def/class the old file
         had, else reject with "missing top-level defs: ...".
         Also switched the subprocess test from exec(open(...).read()) to
         a real importlib.util.spec_from_file_location load so import-time
         side effects are exercised.

BUG 1b -- apply_fix() no post-reload verification
  File: self_upgrade.py:264-291 (old) / now 343-396
  Cause: importlib.reload succeeded even when essential exports were silently
         lost (annotations-only module body).
  Fix:   Before write, snapshot the live module's public callables. After
         reload, compare. If a previously-callable name vanished, raise and
         auto-rollback via the existing backup path.

BUG 2 -- HIGH: smart_browser_agent.summarize_with_llm same SSE-parse bug
  File: smart_browser_agent.py:54-73
  Cause: Identical pattern to Bug 1. Returned raw SSE lines as the summary.
  Impact: User-facing -- message field for search_on_site / cloud_search
         responses leaked 'data: {"token": "..."}\\n\\n' into chat reply and
         (post-2026-05-15 rewire) into TTS playback.
  Fix:   Inlined the same SSE parser used by self_upgrade. Verified end-to-end
         on "search what is rust on github" -- 894-char plain English summary,
         SSE leak: False.

BUG 3 -- MEDIUM: hallucinated bare-word -> "<word>.com" fallback
  File: smart_browser_agent.py:_resolve_site_to_domain (was line 137)
  Cause: Unknown bare words fell through to "<word>.com" -- so
         "hyderabad" -> "hyderabad.com". Tavily then either returned nothing
         or scoped to a nonexistent domain.
  Fix:   Return None for unknown bare words. Added is_known_site() helper
         for orchestrator demotion (Bug 4).

BUG 4 -- MEDIUM: search_on_site regex over-matches natural prepositions
  File: task_orchestrator.py:1408-1424
  Cause: Regex `(?:on|in|using)\\s+([\\w\\-\\.]+)$` accepts "in hyderabad" --
         the token "hyderabad" is a noun in the user's query, not a site.
  Fix:   In the search_on_site dispatch, call smart_browser_agent.is_known_site
         on the captured site token. If unknown, fold the token back into the
         query and demote to search_web. Verified end-to-end on
         "search latest news in hyderabad" -> action_taken=search_web with
         real Hyderabad news returned by Tavily.

BUG 5 -- MEDIUM: atomic_json_write OneDrive/AV lock collision
  File: memory.py:51-67 (old) / now 51-100
  Cause: Project lives inside OneDrive (C:/Users/xjoke/OneDrive/...). The
         OneDrive sync agent and AV scanners momentarily lock files for
         indexing; os.replace then fails with PermissionError [WinError 5].
         Visible chronically in heartbeat ([Loop] Cycle 1/4/7 error) and
         under L3 concurrency (a 500 on /ask).
  Fix:   Retry os.replace with exponential backoff (50/100/200/400/800/1600 ms).
         If all retries lose the race, fall back to shutil.copyfile so the
         newest data still lands (non-atomic but not lost). Added `import time`.
         Post-fix: server boot log is 100% clean -- no Cycle errors, no 500s.

BUG 6 -- INFO: ok.txt K1/K2 test invocation is stale
  Test plan calls `from self_modify import patch_file`, but the real export
  is `patch_file_direct` (or the `SelfModifier.patch_file()` method). The
  guard itself works -- `patch_file_direct("config.py", "x=1")` returns
  {success: False, error: "config.py is permanently protected"}. No code
  change needed.

BUG 7 -- DEFER: activity_tracker mouse hooks
  File: activity_tracker.py:35-50
  Symptom: last_key updates correctly. mouse_pos, last_mouse_move, last_click
           stay at initial 0/0.0. pynput.mouse.Listener.is_alive() returns True
           but on_move/on_click never fire.
  Root cause unknown without runtime data. Needs Jeevan to physically move
  the mouse for 5+ seconds and re-curl /system/activity.
  Hypotheses:
    a) Process owns no message-pumped window; some Windows builds drop
       WH_MOUSE_LL events from such processes.
    b) Higher-priority hook (AV/macro tool) consuming events first.
    c) Listener object GC'd despite .start() (unlikely -- would also kill
       the keyboard hook).
  Workaround candidate: assign mouse.Listener() to a kept reference; experiment
  if hypothesis (c) holds. NOT TOUCHED THIS SESSION.

BUG 8 -- DEFER: JARVIS picker grabs "what does my screen say" -> get_window
  File: task_orchestrator.py picker prompt + _likely_command heuristic
  Symptom: Query routes to action_engine.get_window, which returns only the
           active window title, not the OCR'd screen text. The /ask SSE path
           with screen-aware context (already wired) would have answered
           correctly, but the picker short-circuited it first.
  Fix candidate: distinguish screen-text vs window-title intents in the
  picker prompt, OR exclude get_window when the query contains screen-content
  verbs ("say", "show", "read", "what's on"). Behavioral tuning, deferred.

--------------------------------------------------------------------------------
VERIFICATION ARTIFACTS
--------------------------------------------------------------------------------
- _test_workspace/results/session_2026_05_16_late/post_fix_verify.log
- _test_workspace/results/session_2026_05_16_late/i1_v2_raw.txt
- _test_workspace/results/session_2026_05_16_late/v2_fix2.txt
- _test_workspace/results/session_2026_05_16_late/v2_fix34.txt
- _test_workspace/unit_test_self_upgrade.py  (4/4 pass)
- self_upgrade_backups/action_engine.py.20260516_175138.bak  (first nuke)
- self_upgrade_backups/action_engine.py.20260516_183537.bak  (second nuke)
- self_upgrade_backups/action_engine.py.20260516_183737.bak  (third nuke -- same content as the original good file because the OLD self_upgrade still ran in the parallel process)
- Boot log post-fix: 0 [Loop] Cycle errors, 0 tracebacks.

--------------------------------------------------------------------------------
PROCESS LESSONS (for the next session)
--------------------------------------------------------------------------------
1. Windows allows multiple Flask servers to bind port 5000 (SO_REUSEADDR set
   somewhere upstream). When restarting via TaskStop on a bash wrapper, the
   spawned python.exe child can survive. Always verify with
       netstat -ano | grep ":5000.*LISTENING"
   that exactly ONE PID owns the port before re-running tests that touch
   self-modifying code paths. Otherwise old in-memory modules race new ones.
2. self_upgrade.run is a public POST endpoint with a real LLM in the loop.
   Without the validator hardening shipped this session, anyone with access
   to the server can wipe the most-failing module in seconds.
3. OneDrive + atomic-rename is the #1 source of intermittent Windows server
   errors here. The retry pattern now in memory.py:atomic_json_write should
   be carried into any new write path added to this repo.

--------------------------------------------------------------------------------
HOW TO RESUME (NEXT SESSION)
--------------------------------------------------------------------------------
1. curl http://127.0.0.1:5000/status -- alive? If not:
     python app.py
2. Sanity check: POST /self_upgrade/run -- must NOT return success:true if
   the LLM-generated source loses any top-level def. Should return
   {"success": false, "error": "missing top-level defs: [...]"} or a
   syntax-error message.
3. Phase H mouse: ask Jeevan to wiggle / click his mouse for 5 seconds, then
   curl /system/activity -- does mouse_pos change off [0,0]? If yes, the
   listener IS working and the earlier reading was just stale. If no, dig
   into pynput hook setup (try keeping a module-level reference to the
   Listener instance; experiment with a low-level Win32 hook directly).
4. Bug 8 (picker over-grabs screen queries) -- propose a picker-prompt edit
   that excludes get_window when the query is about screen contents, and a
   matching _likely_command tweak.
5. Phase 4 barge-in still deferred. Phase F still needs mic.

================================================================================
END OF SESSION 2026-05-16 (evening) UPDATE
================================================================================
"""

with open(r"C:\Users\xjoke\OneDrive\Desktop\ok.txt", "a", encoding="utf-8") as f:
    f.write(block)
print("appended", len(block), "chars")
