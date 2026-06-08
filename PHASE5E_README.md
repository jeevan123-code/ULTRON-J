# Phase 5e — Shortcut Inferrer

Status: SHIPPED on branch `phase5e-shortcut-inferrer`.

## What Phase 5e Builds

ULTRON learns Jeevan's slang and shortcuts.

```
"by 'the wheat thing' I mean wheat-3d-explorer"
                |
                v
shortcut_inferrer.parse_teach_utterance(text)
                |
                v
("the wheat thing", "wheat-3d-explorer")
                |
                v
shortcut_registry.teach(Shortcut(...))
                |
                v
shortcuts/shortcuts.json   (persistent)

                ... later, in any conversation ...

"hey ULTRON look up the wheat thing"
                |
                v
shortcut_inferrer.resolve_in_text(text)
                |
                v
{"the wheat thing": "wheat-3d-explorer"}
```

## Modules

| File | Purpose |
|---|---|
| `shortcut_types.py` | `Shortcut` dataclass: term, canonical, confidence, created_at, taught_explicitly |
| `shortcut_registry.py` | JSON-backed CRUD at `shortcuts/shortcuts.json`: `teach`, `get`, `list_all`, `forget`, `iter_terms` |
| `shortcut_inferrer.py` | `parse_teach_utterance(text)` (regex teach parsing) + `resolve_in_text(text)` (whole-word resolver) |

## Reuses (untouched)

- No prior phase code is touched.

## Teach utterance patterns recognised

| Pattern | Example |
|---|---|
| `by "X" I mean Y` | `by "the wheat thing" I mean wheat-3d-explorer` |
| `by 'X' I mean Y` | `by 'wt' I mean wheat-3d-explorer` |
| `by X I mean Y` (unquoted) | `by the wheat thing I mean wheat-3d-explorer` |
| `when I say "X", I mean Y` | `when I say "the project", I mean wheat-3d-explorer` |
| `"X" means Y` | `"the wheat thing" means wheat-3d-explorer` |

`canonical` is required to be a single token (`[A-Za-z0-9_-]+`); trailing
sentence punctuation is stripped.

## Resolution rules

- `resolve_in_text(text)` returns `{normalised_term: canonical}` for every
  known shortcut whose normalised (lowercase) term appears as a whole word
  in `text`, regardless of case.
- Whole-word matching uses `(?<![\w])TERM(?![\w])` so `pep` does NOT match
  `pepper`.

## Public API

```python
from shortcut_inferrer import parse_teach_utterance, resolve_in_text
from shortcut_registry import teach
from shortcut_types import Shortcut
import time

# Teach
parsed = parse_teach_utterance("by 'the wheat thing' I mean wheat-3d-explorer")
if parsed:
    term, canonical = parsed
    teach(Shortcut(
        term=term, canonical=canonical, confidence=1.0,
        created_at=time.time(), taught_explicitly=True,
    ))

# Resolve
shortcuts = resolve_in_text("look up the wheat thing")
# -> {"the wheat thing": "wheat-3d-explorer"}
```

## How to test

```bash
.venv/bin/python -m pytest \
    tests/test_shortcut_types.py \
    tests/test_shortcut_registry.py \
    tests/test_shortcut_inferrer.py \
    tests/test_phase5e_integration.py -v
```

Phase 5e ships with 39 tests. Full ULTRON suite (baseline + Phase 1 + 2a
+ 2b + 3a + 3b + 5a + 5b + 5c + 5d + 5e) = **872 tests passing**, zero
regression on the original 481.

## Integration (deferred to Phase 5f)

Phase 5e keeps `voice_engine.py` / `conversation_intelligence.py` untouched.
To wire shortcut resolution into the live conversation path, a future hook
in `phase1_pipeline.process_user_utterance` would call:

```python
from shortcut_inferrer import parse_teach_utterance, resolve_in_text
from shortcut_registry import teach
from shortcut_types import Shortcut
import time

# 1) intercept teach utterances
parsed = parse_teach_utterance(raw)
if parsed:
    term, canonical = parsed
    teach(Shortcut(term=term, canonical=canonical, confidence=1.0,
                   created_at=time.time(), taught_explicitly=True))

# 2) enrich context with known shortcuts found in the utterance
known = resolve_in_text(raw)
context = {**context, "shortcuts": known}
```

That hook is deferred so the new code stays a pure, easy-to-test library.

## What's next

- **Phase 5f** — wire shortcut_inferrer into phase1_pipeline; add implicit
  shortcut learning (n-gram correlator over conversation_listener buffer).
- **Phase 3c** — improvement_suggester + true keyboard/mouse takeover.
- **Phase 4** — Multi-Device Coordination (House Party Protocol).
