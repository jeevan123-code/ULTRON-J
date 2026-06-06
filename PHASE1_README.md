# Phase 1 — Conversation Intelligence Foundation

Status: SHIPPED on branch `phase1-foundation`.

## What Phase 1 Builds

The "prefrontal cortex" of ULTRON: every raw human utterance is parsed into a
structured `ExecutionPlan` before any action runs. This is the foundation that
later phases (research pipeline, screen co-pilot, voice ID, etc.) will plug into.

```
raw text  -->  compound_intent_parser.parse(text)        ParsedUtterance
                          |
                          v
              conversation_intelligence.enrich(parsed, context)
                          |
                          v
              reasoning_layer.plan(enriched, last_action)
                          |
                          v
                  ExecutionPlan
          (steps + pre_checks + rationale)
```

Phase 1 PRODUCES and LOGS plans. It does NOT yet execute them — that's Phase 2.

## Modules

| File | Purpose |
|---|---|
| `intent_types.py` | Shared dataclasses: `Intent`, `Modifier`, `ParsedUtterance`, `ExecutionPlan`, plus `IntentKind` and `ModifierKind` enums |
| `compound_intent_parser.py` | Pure-regex parser: affirm/deny/defer detection + modifier extraction (ADD / EXCLUDE / PRE_CHECK / PRIORITY / SWITCH_TO) |
| `conversation_intelligence.py` | LLM-backed: tone detection, reference resolution, free-form intent classification + `enrich()` public API |
| `reasoning_layer.py` | Pure-logic chain-of-thought planner that applies modifiers and pre-checks to a `last_action` |
| `phase1_pipeline.py` | Single-call wrapper: `process_user_utterance(raw, context, last_action) -> ExecutionPlan` |

## How to enable

```bash
export ULTRON_PHASE1_ENABLED=1
```

When ON, every utterance routed through `voice_engine.parse_voice_command()`
is also processed by Phase 1 and the resulting plan is logged to
`ultron_log.txt`. Execution of the plan is deferred to Phase 2.

When OFF (default), there is zero behavioral change to existing ULTRON.

## How to test

```bash
.venv/bin/python -m pytest tests/test_intent_types.py \
    tests/test_compound_intent_parser.py \
    tests/test_conversation_intelligence.py \
    tests/test_reasoning_layer.py \
    tests/test_phase1_integration.py \
    tests/test_phase1_pipeline.py -v
```

Phase 1 ships with 69 tests. The full ULTRON suite (550 tests total)
passes with zero regressions on the existing 481 capability tests.

## What's Next

Phase 2 will wire `ExecutionPlan` into actual execution by:
- Extending `brain_orchestrator.py` to consume the plan
- Building the agentic deep research pipeline (8 new modules + 3 extended)
- Adding `conversation_listener.py`, `topic_detector.py`, `research_queue.py`
- Adding `research_orchestrator.py`, `source_fetcher.py`, `cross_checker.py`
- Adding `summariser.py`, `delivery_manager.py`
- Hooking into `vector_store.py` so verified facts are reusable across sessions
