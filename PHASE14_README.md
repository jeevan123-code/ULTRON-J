# Phase 14 — Self-Authored Goal Daemon

The JARVIS→Ultron jump. Prior phases only *execute* goals they were given
(user via `agent_routes`, templates, `proactive_planner`). Phase 14 lets Ultron
**originate its own goals** by watching its observation stream — behind a
safety + human-approval gate.

## Modules

- `goal_author_types.py` — `GoalProposal` dataclass (+ stable `dedup_key`) and
  `SafetyTier` (GREEN / AMBER / RED).
- `goal_author.py` — pure detectors, safety classifier, and the `author()`
  orchestrator (dedup + daily cap + gate + create/park). Approval API.
- Wiring in `autonomous_loop.py`: `_phase14_author_goals(obs)` runs once per
  consciousness cycle, right after the Phase 7 tick.

## Detectors (v1)

| Detector | Fires when | Proposes |
|---|---|---|
| `repeated_failure` | a subject failed ≥3× (from FAILED goals, self-authored excluded) | "Investigate repeated failures of '<x>'" |
| `knowledge_gap` | a topic recurs ≥3× in conversation/world-feed with no KB entry | "Research '<topic>' and add to knowledge base" |

Detectors are pure `(observation) -> [GoalProposal]`; `author()` enriches the
observation (`failure_counts`, `recent_topics`, `known_topics`) from real
sources first. More detectors slot into `_DETECTORS`.

## Safety model (Tier-4 seed)

Every proposal is classified before it can act:

- **GREEN** — research / KB-write / notify. Auto-allowed *only if*
  `ULTRON_PHASE14_AUTO_GREEN=1`.
- **AMBER** — automate / cleanup. Always parked for approval.
- **RED** — any destructive / code-exec / self-modify / third-party-send /
  spend keyword anywhere in the proposal → **dropped**, never created or parked.

**Invariant:** no `source="self_authored"` goal reaches execution with a
destructive step without an explicit approval.

## Autonomy posture (default = cautious)

- `ULTRON_PHASE14_ENABLED` (default `0`): master flag. Off = total no-op.
- `ULTRON_PHASE14_AUTO_GREEN` (default `0`): **off = EVERYTHING is parked for
  approval**, including green. Turn on once you trust it and green goals
  auto-create.
- `MAX_SELF_GOALS_PER_DAY = 5`: hard cap on autonomous creations; overflow is
  parked, never dropped.
- `DEDUP_COOLDOWN_SECONDS = 24h`: the same proposal won't be re-raised within a
  day. State persisted in `goal_author_state.json` (gitignored).

## Approval API

`goal_author.list_pending()`, `approve(dedup_key)` (→ creates the goal),
`reject(dedup_key)`. Route/voice wiring for approve/reject is a deliberate
NEXT step (not in this phase) — same pattern as Phase 5b's deferred wiring.

## Tests (27, all green)

```
tests/test_goal_author_types.py       (6)  types + dedup key
tests/test_goal_author_detectors.py   (10) detectors + safety classifier
tests/test_goal_author_author.py      (7)  dedup, cap, RED-drop, park/approve
tests/test_phase14_wiring.py          (4)  loop flag-gating + enrichment
```

## Not in scope (later tiers/phases)

Continuous vision + duplex voice (Tier 2), multi-agent sub-minds (Tier 3),
self-code-modification autonomy (separate phase — Phase 14 authors *goals*, it
does not rewrite Ultron's own code).
