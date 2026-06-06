# Phase 2a — Agentic Deep Research Pipeline (Core)

Status: SHIPPED on branch `phase2a-research`.

## What Phase 2a Builds

Phase 1 turned utterances into structured `ExecutionPlan`s. Phase 2a EXECUTES
research plans end to end — wiring Phase 1 to ULTRON's existing 578-line
`research_engine.py` and adding voice + visual delivery and verified-fact
storage on top.

```
ExecutionPlan{action: research, args: {topic: X}}
    |
    v
phase2_executor.execute(plan)
    |
    +-- research_engine.research(X, depth)        <-- existing pipeline (decompose -> search -> fetch -> extract -> cross-reference -> synthesise)
    +-- report_from_research_dict(d)              <-- typed report + tier-weighted facts
    +-- research_facts.store_verified_facts(...)  <-- cross-session ChromaDB memory
    +-- delivery_manager.deliver(envelope)        <-- voice brief (TTS) + visual card
    |
    v
{executed: True, delivery: {spoken, card}, facts_stored: N, ms: ...}
```

## Modules

| File | Purpose |
|---|---|
| `research_types.py` | `SourceTier` enum (value=label, weight=trust int), `CitedFact`, `ResearchReport`, `DeliveryEnvelope`, plus `report_from_research_dict` |
| `source_credibility.py` | `tier_for_url(url) -> SourceTier`, `consensus_confidence(tiers) -> float` |
| `delivery_manager.py` | `deliver(envelope)` voice + card routing; `build_card_payload(report)` |
| `research_facts.py` | `store_verified_facts(report, min_confidence)`, `recall_facts(topic, k)` using `vector_store.remember/recall` |
| `phase2_executor.py` | `execute(plan) -> dict` — the public entry point |

## Reuses (untouched)

- `research_engine.py` (578 lines) — full agentic research pipeline
- `vector_store.py` — ChromaDB-backed semantic memory (`remember`/`recall`)
- `voice_engine.py` — TTS stack (ElevenLabs → OpenAI → Edge → Piper → Kokoro), only a surgical hook extension in `parse_voice_command`
- `llm_engine.py` — Groq → Gemini → OpenRouter

## How to enable

```bash
export ULTRON_PHASE1_ENABLED=1
export ULTRON_PHASE2A_ENABLED=1
```

Both flags must be ON. Default OFF means zero behavioral change to existing ULTRON.

## How to test (mocked, fast)

```bash
.venv/bin/python -m pytest \
    tests/test_research_types.py \
    tests/test_source_credibility.py \
    tests/test_research_audit.py \
    tests/test_report_builder.py \
    tests/test_delivery_manager.py \
    tests/test_research_facts.py \
    tests/test_phase2_executor.py -v
```

Phase 2a ships with 41 tests. Combined with Phase 1's 69 tests, the new suite is
110 tests. Full ULTRON suite (baseline + Phase 1 + Phase 2a) = **591 tests passing**
with zero regression on the original 481 capability tests.

## Live smoke (uses real LLM + ChromaDB)

```bash
ULTRON_PHASE1_ENABLED=1 ULTRON_PHASE2A_ENABLED=1 .venv/bin/python -c "
from phase2_executor import execute
from intent_types import ExecutionPlan
plan = ExecutionPlan(
    steps=[{'action': 'research', 'args': {'topic': 'Puccinia triticina lifecycle'}}],
    pre_checks=[],
    rationale='live smoke',
)
result = execute(plan)
print('executed:', result['executed'])
print('ms:', result.get('ms'))
print('facts_stored:', result.get('facts_stored'))
print('bullets[0]:', result['delivery']['card']['bullets'][0] if result.get('delivery') else None)
"
```

Expected: `executed=True`, ms in tens of thousands, at least one bullet, voice
speaks the brief through your speakers.

## What's next — Phase 2b

- `conversation_listener.py` + `topic_detector.py` — auto-research on conversation mentions
- `research_queue.py` — dedupe + scheduled morning briefings
- `proactive_planner.py` extension — deliver research at quiet moments, not interrupt focus
- Hook into `brain_orchestrator.py` so any DAG step can request research as a sub-step
