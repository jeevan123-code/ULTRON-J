# Phase 2b — Autonomous Research Triggers

Status: SHIPPED on branch `phase2b-auto-research`.

## What Phase 2b Builds

ULTRON now researches topics it overhears in your conversation — without being asked.

```
voice transcript -> conversation_listener.record(text)
                            |
                            v
       auto_research_loop._tick_detect()  (every 30s)
                            |
        +--- topic_detector.detect_topics(utts) ---+
        |   (LLM filter: people, events,           |
        |    technical concepts worth knowing)     |
        +-------------------+----------------------+
                            v
                  research_queue.enqueue(topic, priority)
                            |
                            v
       auto_research_loop._tick_execute()  (every 60s)
                            |
       if proactive_planner.should_deliver_research_now():
                            |
                            v
       phase2_executor.execute(ExecutionPlan{research, topic})
                            |
                            v
   voice brief speaks + visual card + verified-fact storage
```

## Modules

| File | Purpose |
|---|---|
| `conversation_listener.py` | Thread-safe rolling buffer (cap 32). `record`, `drain_unprocessed`, `snapshot` |
| `topic_detector.py` | LLM filter -> at most 3 topics with priority 1..5 |
| `research_queue.py` | Priority + dedupe (1h TTL) + JSON persistence at `research_queue.json` |
| `proactive_planner.py` (+ extension) | `should_deliver_research_now(quiet_seconds=60)` quietness gate |
| `auto_research_loop.py` | Background thread: `_tick_detect` (30s) + `_tick_execute` (60s) |

## Reuses (untouched)

- Phase 1: `intent_types.ExecutionPlan`
- Phase 2a: `phase2_executor.execute(plan)`, `research_engine.research()`
- `llm_engine.py`, `voice_engine.py`, `vector_store.py`

## How to enable

```bash
export ULTRON_PHASE1_ENABLED=1
export ULTRON_PHASE2A_ENABLED=1
export ULTRON_PHASE2B_ENABLED=1
```

Then call `auto_research_loop.start()` once at process startup (e.g., from `app.py`'s init path).

## How to test

```bash
.venv/bin/python -m pytest \
    tests/test_research_queue.py \
    tests/test_conversation_listener.py \
    tests/test_topic_detector.py \
    tests/test_proactive_quietness.py \
    tests/test_auto_research_loop.py \
    tests/test_phase2b_integration.py -v
```

Phase 2b ships with 29 tests. Combined with Phase 1 + Phase 2a, the new suite is
139 tests. Full ULTRON suite = **620 tests passing** with zero regression on the
original 481 capability tests.

## What's next — Phase 3

Screen Co-Pilot: passive screen watching + struggle detection + polite help offers.
