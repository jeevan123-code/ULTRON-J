# Phase 17 — Capability Policy Engine (Tier-4 safety foundation)

Generalises the Phase 14 green/amber/red seed into one config-driven authority
model usable anywhere an action is about to run. This is the safety floor the
wider-autonomy tiers (self-code-modify, agent swarm) stand on.

## `capability_policy.py`
- `Tier` = GREEN (read-only/additive) / AMBER (mutating, needs approval) /
  RED (destructive/code-exec/self-modify/send/spend, never autonomous).
- `evaluate(action_type, params)` → `PolicyDecision(tier, reason)`. Starts from
  a policy TABLE, then **escalates** using `confirm_gate.is_destructive` and
  `decision_engine.safety_check`, returning the strictest tier.
- **Deny-by-default:** an action the safety whitelist doesn't recognise → RED.
- `enforce(action_type, params, approved)` → allow/deny with an AMBER approval
  gate.
- **No hardcoding:** the table is overridable at runtime via
  `capability_policy.json` (`{"open_url": "green", ...}`) and
  `set_policy_override()`.

## Wiring (flag-gated: `ULTRON_PHASE17_ENABLED`, default OFF)
`action_engine.execute_goal_step` — the autonomous execution boundary — now
runs every goal step through `enforce()`: RED refused; AMBER requires
`task["human_confirmed"]=True`; GREEN runs freely. Generalises the older
Phase 7.5 code-only guard to all actions. Off = unchanged behaviour.

## Tests (14)
`tests/test_capability_policy.py` (9) + `tests/test_phase17_policy_gate.py` (5).
