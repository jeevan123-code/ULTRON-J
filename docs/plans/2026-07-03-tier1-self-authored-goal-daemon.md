# Tier 1 — Self-Authored Goal Daemon (Phase 14)

**Status:** DRAFT / awaiting user review (author away at write time — open questions flagged inline).
**Goal:** The JARVIS→Ultron jump. Today the autonomous loop only *executes* goals it is given (user via `agent_routes`, templates, `proactive_planner`). Nothing *originates* a goal from what Ultron observes. This phase adds a component that watches the observation/event stream, detects recurring or significant patterns, and **proposes its own goals** — behind a safety + human-approval gate.

---

## 1. Where this plugs into the existing machine

The heartbeat is `autonomous_loop._continuous_loop()` (autonomous_loop.py:682):

```
observe_environment()  ->  make_decision()  ->  plan_for_decision()  ->  act_on_plan()  ->  evaluate_result()  ->  maybe_reflect()
```

`observe_environment()` (autonomous_loop.py:230) already emits a rich dict:
`ram_pct/ram_critical`, `disk_critical`, `desktop_count/desktop_files`,
`pending_goals/active_goals/completed_today/failed_today`, `knowledge_entries`,
`ollama_models`, `perception_context`, `current_mood`,
`computer_control_available`, `email_available`, plus `phase7_summary` (from
`mind_tick.tick()` via `_phase7_unified_tick`).

**Existing scaffolding we reuse (do NOT rebuild):**
- `decision_engine.create_goal(title, description, priority, source, tags, depends_on, success_criteria, estimated_steps)` — goal factory (decision_engine.py:205), already supports a `source` tag, `_flag_conflicts` (:346), urgency decay (:320), `get_next_goal` (:280).
- `decision_engine.build_plan(goal)` (:497) + `act_on_plan`/`execute_goal_step` — execution path already exists.
- `confirm_gate.is_destructive` / `dry_run_preview` + `decision_engine.safety_check` — the Tier-4 safety primitives.
- `action_log` (recent events), `worldfeed_store` (world events), `improvement_suggester` — existing observation sources already unified in `mind_tick`.

**The gap:** no module converts *observed patterns* into *new goals*. That is this phase.

---

## 2. New component: `goal_author.py`

Pure-logic-first, side-effect-at-the-edge, mirroring project conventions
(`_now()`, `_reset_for_test()`, flag-gated hook, try/except-isolated stages).

### 2.1 Data types (`goal_author_types.py`)
```python
@dataclass
class GoalProposal:
    title: str
    description: str
    rationale: str            # WHY Ultron thinks this is worth doing
    trigger: str              # which detector fired (e.g. "repeated_failure")
    priority: str             # Priority.* 
    confidence: float         # 0..1
    requires_approval: bool   # True unless the action is "green" (see §4)
    dedup_key: str            # stable key to avoid re-proposing the same thing
```

### 2.2 Detectors (pure functions: observation/history -> list[GoalProposal])
Each detector is small, independently testable, and returns 0..n proposals.
Initial set (start minimal, expand later):

| Detector | Fires when | Example self-authored goal |
|---|---|---|
| `repeated_failure` | same action/goal failed ≥N times in `action_log` / `failed_today` up | "Investigate why <X> keeps failing" |
| `recurring_manual_task` | `improvement_suggester` surfaces a repeated manual sequence | "Offer to automate <sequence>" (ties into existing Phase 3c takeover) |
| `knowledge_gap` | a topic recurs in conversation/world feed with no KB entry | "Research <topic> and add to knowledge base" |
| `housekeeping` | `desktop_count` or a **real writable** disk mount trends high over K cycles | "Propose desktop/disk cleanup" (propose only — never auto-delete) |
| `stale_goal` | a goal sits PENDING past a threshold with rising urgency | "Re-plan or drop stale goal <id>" |

**Open question (user):** which detectors to ship in v1? Recommend starting with
`repeated_failure` + `knowledge_gap` (highest value, lowest risk) and adding the
rest behind sub-flags.

### 2.3 Dedup + rate limiting
- `goal_author` keeps a small persisted set of recent `dedup_key`s (JSON, gitignored) with timestamps; a proposal whose key was seen within a cooldown window is dropped.
- Hard cap: at most `MAX_SELF_GOALS_PER_DAY` (default small, e.g. 5) created автоnomously; the rest are queued as suggestions only.
- Never propose if `pending_goals`/`active_goals` already over a ceiling (avoid pile-up — the loop should finish work before inventing more).

### 2.4 Public API
```python
def propose(observation: dict, *, history=None) -> list[GoalProposal]   # pure
def author(observation: dict) -> dict                                    # side-effecting: dedup+gate+create
```

---

## 3. Wiring into the loop (flag-gated, default OFF)

New flag: `ULTRON_PHASE14_ENABLED`.

In `_continuous_loop`, after `obs = observe_environment()` and the Phase 7 tick,
add a Phase 14 stage (mirroring `_phase7_unified_tick`):

```python
def _phase14_author_goals(obs: dict) -> None:
    import os
    if os.environ.get("ULTRON_PHASE14_ENABLED", "0") != "1":
        return
    try:
        import goal_author
        obs["phase14_summary"] = goal_author.author(obs)
    except Exception as e:
        _safe_log(f"phase14 goal author failed: {e!r}")
```

Green proposals (`requires_approval=False`) → `create_goal(..., source="self_authored")` directly, entering the normal execution path.
Amber/red proposals (`requires_approval=True`) → parked via the **existing** `proactive_offer` surface so the user is asked before anything runs (reuse, don't reinvent — this is how Phase 3c already asks consent).

---

## 4. Safety model (Tier-4 seed — MANDATORY, ships WITH this phase)

A self-authoring, self-executing loop is exactly where autonomy gets risky, so
the capability tiering is not deferred — a minimal version ships here:

- **GREEN** (auto-allowed): read-only / additive research, knowledge-base writes, notifications, proposing (not performing) cleanup. `requires_approval=False`.
- **AMBER** (ask first): file moves, app control, anything touching the user's data or external services. Parked via `proactive_offer`; only runs on explicit consent.
- **RED** (forbidden to self-author): deletes, `run_python`/shell, self-modification, sends (email/telegram) to third parties, spending. `goal_author` must never emit a proposal whose plan contains these; enforced by running each proposal's would-be plan through `decision_engine.safety_check` + `confirm_gate.is_destructive` at proposal time and dropping/downgrading accordingly.

**Invariant to test:** no `source="self_authored"` goal can reach `act_on_plan` with a destructive step without an approval record.

---

## 5. TDD task breakdown (each: failing test → confirm FAIL → implement → PASS → commit)

1. `goal_author_types.py` + `test_goal_author_types.py` — GoalProposal dataclass, dedup_key stability.
2. `goal_author.propose()` pure detectors, one test file per detector (`test_goal_author_detectors.py`) driven by synthetic observation dicts. No I/O.
3. Dedup + rate-limit layer (`test_goal_author_dedup.py`) — same proposal twice within cooldown → one create; daily cap respected.
4. Safety gate (`test_goal_author_safety.py`) — a proposal implying a destructive plan is dropped/downgraded to AMBER; green stays green. Assert the §4 invariant.
5. `goal_author.author()` side-effecting entry (`test_goal_author_author.py`) — green → `create_goal` called with `source="self_authored"`; amber → parked via a stubbed `proactive_offer`; registry/goal store pointed at tmp.
6. Loop wiring (`test_phase14_wiring.py`) — with flag ON, `_phase14_author_goals(obs)` runs and populates `obs["phase14_summary"]`; with flag OFF it is a no-op and touches nothing.
7. `PHASE14_README.md` + update `PERFECTION_SCORECARD.md` current-state section + memory.

**Style (non-negotiable, per project):** `.venv/bin/python`; explicit `git add` paths; `_now()`/`_reset_for_test()` seams; flag-gated try/except hooks; surgical edits; commit msgs `feat(phase14): …` / `test(…)`.

---

## 6. Open questions for the user (resolve before task 2)

1. **Detector set for v1?** (recommend `repeated_failure` + `knowledge_gap` first.)
2. **Autonomy dial:** should GREEN goals truly auto-create+execute, or should *everything* (even green) start as a parked suggestion until you trust it for a while? (Recommend: everything parked for the first N days, then promote green to auto via a config flag.)
3. **Daily cap** for self-authored goals? (Recommend 5.)
4. **Persistence location** for dedup state (new gitignored JSON — confirm naming).
5. Anything you explicitly never want it to self-author, beyond the RED list in §4?

---

## 7. Non-goals (explicitly out of scope for Phase 14)
- Continuous vision / duplex voice (Tier 2).
- Multi-agent sub-mind delegation (Tier 3).
- Full self-modification-merge autonomy (Tier 1 item, separate phase — this phase only *authors goals*, it does not let Ultron rewrite its own code).
```
