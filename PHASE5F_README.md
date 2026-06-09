# Phase 5f — Shortcut Live Wiring

Status: SHIPPED on branch `phase5f-shortcut-live-wiring`.

## What Phase 5f Builds

Phase 5e was a library. Phase 5f makes it live by wiring it into the Phase 1
conversation pipeline.

```
voice_engine receives an utterance
        |
        v
phase1_pipeline.process_user_utterance(raw, context, last_action)
        |
        +-- Phase 5f hook (flag-gated):
        |      context = phase5f_shortcut_hook.apply(raw, context)
        |      # parses teach utterances + persists them
        |      # resolves known shortcuts into context["shortcuts"]
        |
        v
parse(raw) -> ParsedUtterance
        |
        v
conversation_intelligence.enrich(parsed, context)  <-- sees context["shortcuts"]
        |
        v
reasoning_layer.plan(enriched, last_action)
        |
        v
ExecutionPlan
```

Net effect: when you say `"by 'the wheat thing' I mean wheat-3d-explorer"`,
the mapping is persisted on the spot. Next time you say
`"look up the wheat thing"`, the resolved canonical name flows through the
pipeline as `context["shortcuts"]`.

## Modules

| File | Purpose |
|---|---|
| `phase5f_shortcut_hook.py` | NEW — `apply(raw, context) -> Dict` pure helper |
| `phase1_pipeline.py` | MODIFIED — top of `process_user_utterance` runs `phase5f_shortcut_hook.apply` when ULTRON_PHASE5F_ENABLED=1 |

## How to enable

```bash
export ULTRON_PHASE5F_ENABLED=1
```

Default OFF means zero behavioral change. The hook is wrapped in
try/except so any failure silently falls back to the original `context`.

## How to test

```bash
.venv/bin/python -m pytest \
    tests/test_phase5f_shortcut_hook.py \
    tests/test_phase5f_integration.py -v
```

Phase 5f ships with 11 tests. Full ULTRON suite = **883 tests passing**,
zero regression on the original 481.

## Context schema

The hook adds (or overwrites) a single key in `context`:

```python
context["shortcuts"] = {
    "the wheat thing": "wheat-3d-explorer",
    "wt": "wheat-3d-explorer",
}
```

Downstream consumers (`conversation_intelligence.enrich`,
`reasoning_layer.plan`) can use this to fill in references like
*"look up the wheat thing"*.

Note: a freshly-taught term in the SAME utterance is excluded from
`context["shortcuts"]` to avoid noise — teach sentences are
meta-conversation, not usage.

## What's next

- **Phase 5g** — implicit shortcut learning via n-gram correlator over
  `conversation_listener` buffer (no explicit teach utterance needed).
- **Phase 3c** — improvement_suggester + true keyboard/mouse takeover.
- **Phase 4** — Multi-Device Coordination (House Party Protocol).
