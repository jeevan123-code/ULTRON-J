# Phase 16 — Durable Belief / Preference Memory (long-horizon consolidation)

The `memory_distiller` already extracts flat lessons every few hours. Phase 16
adds what was missing: a **durable model of the user that deepens over weeks** —
beliefs that strengthen with repeated evidence and decay when stale/contradicted.

## Modules
- `belief_store.py` — pure, deterministic core (no LLM). `Belief` dataclass;
  `consolidate(evidence)` (reinforce / add / detect contradiction),
  `apply_decay(now)`, `top_beliefs()`, `get_beliefs_block()`.
  Confidence = `evidence_count / (evidence_count + 2)` → deepens with sightings.
- `belief_consolidation.py` — bridge: feeds NEW personal facts (via an ISO
  watermark so loop frequency can't inflate confidence) into `belief_store`.

## Wiring (flag-gated: `ULTRON_PHASE16_ENABLED`, default OFF)
- `mind_tick._stage_beliefs` runs consolidation each cycle (watermarked).
- `intelligence_core` injects `get_beliefs_block()` (high-confidence beliefs
  only) into the prompt context so answers reflect the deepened model.

## Safety / correctness
- Watermark prevents re-counting the same fact.
- Contradictions (same content tokens, opposite polarity) weaken the prior
  belief rather than silently stacking.
- Stale beliefs decay and drop below a floor. State in `beliefs.json`
  (gitignored).

## Tests (13)
`tests/test_belief_store.py` (8) + `tests/test_belief_consolidation.py` (5).
