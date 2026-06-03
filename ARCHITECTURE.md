# ARCHITECTURE — Ultron-J (Phase 5.1)

> The "real" call graph as it stands on the `hardening` branch.
> Computed from a static AST scan of every project `.py` plus a manual
> sweep of `_safe_import` / dynamic `__import__` paths in
> `ultimate_routes.py`. Updated alongside Phase 5 work.

## Fan-in spine (top 12)

These are the modules everything else leans on. The hardening branch
preserves them as the canonical spine; new code should import from
here, not duplicate.

| fan-in | module                | role                                                     |
|-------:|------------------------|----------------------------------------------------------|
|     35 | `config`               | Constants, env-var resolution, the **`LOOPS` registry**  |
|     23 | `llm_engine`           | Provider dispatch (Groq / Gemini / OpenRouter) + retries |
|     22 | `memory`               | SQLite-first episodes, conversations, facts (Phase 4.3)  |
|     14 | `computer_control`     | pyautogui wrappers, sandboxed click/type/screenshot      |
|     12 | `loop_supervisor`      | Phase 4.1 gate — `loop_enabled / interval_s / backpressure` |
|     12 | `decision_engine`      | Goal lifecycle, `safety_check`, `make_decision`          |
|     11 | `system_monitor`       | Health score, heartbeat, **canonical `add_proposal`**    |
|     11 | `personality`          | Mood state + transitions                                 |
|      7 | `action_engine`        | Central tool dispatcher (`execute_action`)               |
|      7 | `vector_store`         | Sentence-Transformer embeddings + chroma/sqlite fallback |
|      6 | `screen_engine`        | Window + screenshot + OCR                                |
|      6 | `perception`           | FS watcher + clipboard monitor                           |
|      6 | `model_selector`       | Pick model by task type                                  |
|      5 | `task_orchestrator`    | Multi-step task execution + destructive-shell guard      |

## Two primary control flows

The codebase has TWO independent loops, not one. Confusing them is
the most common source of "but I thought engine X did Y" bugs.

### Flow A — Interactive `/ask` (a user sent a message)

```
HTTP /ask
   |
   v
app.py route
   |
   v
intelligence_core.think_and_stream(question, history, ...)
   |
   |--- complexity classification (cheap LLM call) ---> SIMPLE / MEDIUM / COMPLEX
   |
   |--- SIMPLE -------> _stream_with_intelligence_prompt (fast model, no CoT)
   |
   |--- MEDIUM -------> _stream_with_intelligence_prompt (CoT system block,
   |                                                      world_state context,
   |                                                      fast model)
   |
   |--- COMPLEX ------> default: same as MEDIUM but with the long model
   |                    INTELLIGENCE_MODE=react: react_engine.reason
   |                                            (ReAct tool loop)
   |                    INTELLIGENCE_MODE=plan:  brain_orchestrator.orchestrate
   |                                            (DAG planner)
   |
   v
LLM token stream  ->  Server-Sent Events to the browser
```

`react_engine` and `brain_orchestrator` are both **opt-in** as of Phase
5.2. The default route is the single prompt-based path through
`_stream_with_intelligence_prompt`. If you want either, set:

```
INTELLIGENCE_MODE=react   # ReAct tool-using loop for COMPLEX
INTELLIGENCE_MODE=plan    # DAG planner for COMPLEX
```

(or the older `USE_BRAIN_ORCHESTRATOR=1` / `"plan this"` phrase still
works as a backward-compatible alias.)

### Flow B — Autonomous goal loop (background daemon)

```
autonomous_loop._continuous_loop
   |
   |--- HEARTBEAT_INTERVAL=300s (config.py)
   |
   v
observe_environment()
   |
   |--- mem / disk / battery / desktop / pending_goals / mood / perception
   |
   v
decision_engine.make_decision(obs)
   |
   |--- ram_critical / disk_critical (pseudo-fs aware, Phases 3+4)  ->  push_alert
   |--- has active goals?  ->  execute_task / evaluate_goal
   |--- pending goal?      ->  start_goal
   |--- nothing?           ->  observe / self_evaluate
   |
   v
plan_for_decision(decision)
   |
   v
act_on_plan(plan)
   |
   |--- execute_goal_step (action_engine, honors task["params"] per Phase 3.3)
   |--- finish_goal_evaluation -> COMPLETED / FAILED / PENDING (retry)
   |
   v
reflection.maybe_reflect()   # periodic — writes reflection_log.json
```

Goal source: external for now. `create_goal(...)` must be called by
something — user via HTTP, voice intent, or one of the planner modules.
Phase 3 demonstrated a real goal completes end-to-end; auto-goal-
creation by `proactive_planner` is a Phase 8 follow-up.

## Background loop landscape (Phase 4.1 registry)

Every daemon now consults `config.LOOPS` via `loop_supervisor`. The
table below is the effective default state on this branch.

| Loop              | Default state | Interval | Notes                          |
|-------------------|--------------:|---------:|--------------------------------|
| `autonomous`      | ON  | 30s    | Flow B above (heartbeat is separate, 300s) |
| `perception`      | ON  | 15s    | FS watcher + clipboard         |
| `system_monitor`  | ON  | 30s    | Heartbeat + change monitor     |
| `voice_listener`  | ON  | event  | Picovoice wake; no periodic tick |
| `distiller`       | ON  | 6h     | `memory_distiller`             |
| `predictive`      | ON  | **300s** (was 60s) | `predictive_monitor` |
| `code_indexer`    | ON  | 1h     | `code_index` rebuilds          |
| `plugin_watcher`  | ON  | 5s     | Lightweight                    |
| `activity_tracker`| ON  | 60s    | pynput listeners               |
| `evolution`       | OFF | 12h    | Runs on empty input until Phase 8 |
| `proactive`       | OFF | 30min  | Same                           |
| `skill_learner`   | OFF | 6h     | Same                           |
| `screen_monitor`  | OFF | 3s     | Screenshots+OCR every 3s — only enable when you need it |

Override at runtime: `LOOPS_<NAME>_ENABLED=0|1`,
`LOOPS_<NAME>_INTERVAL_S=<n>`. Memory backpressure auto-skips heavy
ticks above `ULTRON_MEM_BACKPRESSURE_PCT=70`.

## Proposal flow (Phase 5.3 — single writer)

```
reflection.generate_proposals(metrics)   ----+
predictive_monitor anomaly detection      ----+
evolution_loop._loop                      ----+----> system_monitor.add_proposal()
                                                              |
                                                              v
                                                       proposals.json
                                                       (dedup by title)
```

`system_monitor.add_proposal(title, description, code_snippet="",
target_file="")` is the **only writer** of `proposals.json`. It does
exact-title deduplication so multiple sources can independently
propose the same improvement without spamming the file. Other
modules import this function rather than touching the file directly:

- `reflection.py` (auto-reflection's improvement suggestions)
- `evolution_loop.py` (meta-learning improvements)
- `predictive_monitor.py` (anomaly-triggered alerts)
- `proactive_planner.py` (user-pattern-driven suggestions)

`smart_home.py` writes to a SEPARATE `code_proposals.json` for its
self-modification workflow — different file, different domain, not
unified intentionally (those proposals carry full code diffs).

## "Orphaned"-looking but actually wired

The static AST scan reports zero importers for these — they're wired
via `ultimate_routes._safe_import(name)` which uses `__import__()`
(string-based, invisible to AST scanning):

- `evolution_loop`
- `predictive_monitor`
- `proactive_planner`
- `skill_learner`
- `tweak_engine`
- `brain_orchestrator`
- `research_engine`
- `task_graph`
- `human_interface`

Their idleness (when running) was the Phase 3+4 problem, not the
plumbing.

## Genuine orphans (Phase 5.1 audit — candidates for archive)

Static scan + manual check confirms zero importers AND zero dynamic
loads:

- `test.py`, `test_groq.py`, `test_play.py`, `test_stream.py`,
  `test_t17.py`, `test_youtube.py`, `ultron_test.py`,
  `wiring_audit.py` — old probe scripts. Candidates for Phase 7's
  archive pass (Phase 0 already moved similar leftovers).

## File-system state (runtime)

These are written at runtime and gitignored. ARCHITECTURE.md and
CHANGES.md document their shape so a fresh clone can understand them:

| File                          | Writer                               | Reader                          |
|-------------------------------|--------------------------------------|---------------------------------|
| `ultron.db`                   | `memory.py` (SQLite source of truth) | `memory.load_episodes`, etc.   |
| `episodic_memory.json`        | `memory._flush_episodes_to_json` (every 50 stores) | tooling, dashboards |
| `goals.json`                  | `decision_engine.update_goal`        | `decision_engine.load_goals`    |
| `execution_log.json`          | `decision_engine.log_execution`      | `reflection.analyze_performance`|
| `proposals.json`              | `system_monitor.add_proposal` (one writer) | `system_routes`, UI       |
| `tool_stats.json`             | `action_engine.record_tool_result`   | `reflection`                    |
| `heartbeat.json`              | `system_monitor._heartbeat_loop`     | `agent_routes`, dashboard       |
| `loop_status.json`            | `autonomous_loop.save_loop_status`   | UI                              |
| `anomaly_log.json`            | `predictive_monitor.run_check`       | `reflection`                    |
| `predictive_metrics.json`     | `predictive_monitor.run_check`       | UI                              |
| `reflection_log.json`         | `reflection.add_reflection`          | dashboard, scorecard            |
