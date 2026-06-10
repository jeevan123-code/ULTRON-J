# Phase 5g — Implicit Shortcut Learner

Status: SHIPPED on branch `phase5g-implicit-learner`.

## What Phase 5g Builds

ULTRON discovers shortcut mappings **without explicit teach utterances** by
observing co-occurrence of slang phrases and canonical identifiers across
many conversation turns.

```
conversation_listener buffer (last N utterances)
        |
        v
implicit_learner.propose_shortcuts(utterances, min_cooccurrence=3)
        |
        +-- extract_slang_candidates(text)      "the wheat thing"  / "that wheat project"
        +-- extract_canonical_candidates(text)  "wheat-3d-explorer" (hyphenated identifiers)
        +-- count (slang, canonical) co-occurrences
        |
        v
List[ProposedShortcut(slang, canonical, cooccurrences, confidence)]
```

When a `(slang, canonical)` pair co-occurs in `min_cooccurrence` or more
utterances, it's surfaced as a proposal. Callers can review and call
`shortcut_registry.teach(...)` to accept.

## Module

| File | Purpose |
|---|---|
| `implicit_learner.py` | `propose_shortcuts(utterances, min_cooccurrence)`, `extract_slang_candidates`, `extract_canonical_candidates`, `ProposedShortcut` dataclass |

## How it works

- **Canonical candidates**: tokens matching `[a-zA-Z0-9]+(-[a-zA-Z0-9]+)+` —
  hyphenated identifiers like `wheat-3d-explorer`.
- **Slang candidates**: `"the X"` or `"that X"` where X is 1-3 lowercase words.
  A stop-word list (`in`, `on`, `for`, `today`, `now`, `needs`, …) prevents
  the regex from absorbing prepositions, adverbs, or auxiliary verbs.
- **Confidence**: `count / (count + 2)`, so 3 co-occurrences → 0.6, 10 → 0.83.

## Reuses (untouched)

No prior phase modules. Pure logic.

## Tests

15 tests — `tests/test_implicit_learner.py` — cover slang extraction,
canonical extraction, threshold filtering, confidence scaling, and
ProposedShortcut serialization.

## What's next

- **Phase 5h** (future) — hook `propose_shortcuts` into `conversation_listener`
  drain loop; surface proposals via a `proactive_offer`-style voice prompt:
  "Sir, I've noticed you call wheat-3d-explorer 'the wheat thing'. Shall I remember?"
- **Phase 3c** — improvement_suggester + computer_control takeover (handoff doc)
- **Phase 4** — Multi-Device Coordination / House Party Protocol (handoff doc)
