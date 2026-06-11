# Phase 7 — Unified Mind

Status: SHIPPED on branch `phase7-unified-mind`.

## What Phase 7 Builds

Until now, every phase shipped in isolation:

- Phase 6 polled the world.
- Phase 6 also scheduled briefings.
- Phase 3c watched action patterns and built improvement suggestions.
- Phase 4 matched scenarios for multi-device fan-out.
- Phase 3b parked stuck-on-error offers.

`autonomous_loop.observe_environment()` saw none of these new surfaces.
The cycle remained: RAM, disk, goals, mood — same eight things it always
saw. Adding capabilities did not make the loop smarter.

**Phase 7 closes that gap with a single new function — `mind_tick.tick()`.**

It runs once per cycle (immediately after OBSERVE) and connects every
isolated subsystem into one coherent thinking step:

```
mind_tick.tick(now)
   │
   ├── briefing_scheduler.tick(now)             ──→ dispatches due cron briefings
   │                                                via briefing_builder + briefing_delivery
   │
   ├── worldfeed_store.recent(top_n=5)          ──→ alerts very-high-score events
   │                                                (score ≥ 0.85) via mobile_bridge.alert
   │                                                (deduped across ticks)
   │
   └── action_log.recent → improvement_suggester ──→ parks a takeover suggestion
                                                     via proactive_offer when no
                                                     other offer is pending — a
                                                     HANDS_ON reply later runs
                                                     takeover_executor
```

Each stage is wrapped in try/except. One stage failing never aborts the
next. The tick returns a summary dict; the autonomous_loop stamps it
into `obs["phase7_summary"]` so `make_decision` can react if it wants.

## Why this matters for "ULTRON > JARVIS"

JARVIS feels alive in the films because every input stream feeds into
one consciousness. Phase 7 is the smallest, surgical change that gives
ULTRON the same property:

- A worldfeed event with score 0.95 is now an alert on your phone within
  one cycle — no manual poll, no user prompt required.
- A morning cron schedule fires through the same cycle that watches
  errors and listens to your voice — every input is now considered together.
- A repetitive workflow (five renames in a row) becomes a parked offer
  ULTRON can act on as soon as you say "yes, do it" — even if you weren't
  thinking about automation.

## Modules

| File | Tests | Purpose |
|---|---:|---|
| `mind_tick.py` | 7 | Single unified `tick(now)` over briefings + worldfeed + improvements |
| `autonomous_loop.py` (modified) | 3 | `_phase7_unified_tick(obs)` flag-gated hook in the cycle |

**10 new tests**, zero regression on the 1045-test Phase 6 baseline.

## How to enable

```bash
export ULTRON_PHASE7_ENABLED=1
```

That's all. The existing autonomous_loop now invokes `mind_tick.tick()`
every iteration. No new threads, no new state files — Phase 7 reuses
every existing store.

## How to test

```bash
.venv/bin/python -m pytest \
    tests/test_mind_tick.py \
    tests/test_phase7_autonomous_hook.py -v
```

## Defensive design

- The mind tick must never crash the autonomous loop. Every stage is
  wrapped in try/except; failures are recorded in the summary dict and
  logged to `ultron_log.txt` but never re-raised.
- World alerts deduplicate on title across ticks — a high-score event
  alerts once, not on every cycle.
- Improvement offers are parked only when no other offer is pending —
  no double-park, no overlapping HANDS_ON ambiguity.

## What's next

- Teach `make_decision` to use `obs["phase7_summary"]` for priority bumps
  (e.g., suppress low-priority desktop alerts when an improvement offer
  is pending so the user has cognitive space to respond).
- Extend `mind_tick` with a "thought generator" registry — pluggable
  observers that can write into the summary without modifying mind_tick.
- A real `proactive_offer.speak("Sir, ...")` voice prompt when an
  improvement is parked, so the user hears the offer instead of having
  to check a UI.
