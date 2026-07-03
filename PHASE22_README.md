# Phase 22 — Predictive Intervention (Tier 3)

`predictive_monitor` forecasts trouble (memory climbing, disk filling, provider
failures rising) and ALERTS. Phase 22 upgrades alerting to ACTING: each
predicted anomaly becomes a parked remediation GOAL via `goal_author`, so Ultron
proposes to fix a problem before it lands rather than only warning.

## `predictive_intervention.py`
- `remediation_for(anomaly)` — PURE: maps `{key, severity, summary, action}`
  to a `GoalProposal` (trigger `predictive`, research category).
- `intervene(anomalies)` — routes proposals through `goal_author.submit_proposals`
  (the same dedup / safety / cap / park pipeline as author()).
- `run(n)` — reads recent anomalies from `predictive_monitor.get_anomaly_log`.

## Wiring
`mind_tick._stage_predictive` (gated `ULTRON_PHASE22_ENABLED`) runs it each
cycle. A standing anomaly is deduped by goal_author's 24h cooldown per
`trigger:subject`, so it won't spam proposals. Remediation goals are research
category; any destructive execution step is still gated by the Phase 17
capability policy.

## goal_author refactor
`author()`'s per-proposal loop was extracted into `_process_proposals`, and a
new `submit_proposals()` lets any producer feed the gate. (7 goal_author tests
still green.)

## Tests (8)
`tests/test_predictive_intervention.py`.
