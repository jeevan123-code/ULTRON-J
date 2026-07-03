# Phase 20 — Proactive Device Orchestration (Tier 2 embodiment)

`multi_device_coordinator` is reactive (voice trigger → scenario). Phase 20 adds
PROACTIVE orchestration: Ultron runs device scenarios from CONTEXT/EVENTS
("nobody home + it's late → lock up + drop the thermostat").

## `proactive_orchestrator.py`
- `ContextRule(name, predicate, actions, cooldown_seconds)` — a rule that fires
  when `predicate(context)` is true.
- `evaluate(context)` — PURE: which rules match (a throwing predicate is skipped).
- `orchestrate(context, approved)` — fires matching rules, respecting per-rule
  cooldown (persisted, so a standing condition doesn't re-fire every cycle).

## Safety posture (Tier-4)
Device actions touch the physical world, so they are **AMBER by default**: a
fired rule is PARKED for approval and the user is notified, unless
`approved=True` or `ULTRON_PHASE20_AUTO=1`. The device dispatch is a mockable
seam (`_dispatch` → `smart_home`).

## Tests (6)
`tests/test_proactive_orchestrator.py` — evaluation, park-by-default, approved/
auto run, cooldown suppression.
