"""Phase 5g hook — wires the implicit shortcut learner into the live system.

The pure-logic learner in `implicit_learner.py` was previously unreachable:
nothing observed utterances into it and nothing acted on its proposals. This
hook closes that gap.

  observe(text)  — accumulate an utterance into a bounded rolling buffer
                   (called per-utterance from phase1_pipeline).
  tick(...)      — run co-occurrence analysis over the buffer and auto-register
                   high-confidence proposals as (implicit) shortcuts, WITHOUT
                   ever overwriting a shortcut the user taught explicitly
                   (called periodically from the mind loop).

Pure-ish: the only side effect is writing new shortcuts through
`shortcut_registry`. Flag-gated by callers (ULTRON_PHASE5G_ENABLED); this
module itself is import-safe and does nothing until observe()/tick() run.
"""
import threading
import time
from collections import deque
from typing import List

import shortcut_registry
from shortcut_types import Shortcut
from implicit_learner import propose_shortcuts


# Rolling window of observed utterances. Larger than the 32-slot conversation
# buffer so co-occurrences (which need >=3 sightings) actually accumulate.
_MAX_UTTERANCES = 200

_lock = threading.RLock()
_utterances: deque = deque(maxlen=_MAX_UTTERANCES)


def _now() -> float:
    return time.time()


def _reset_for_test() -> None:
    with _lock:
        _utterances.clear()


def observe(text: str) -> None:
    """Record an utterance for later co-occurrence analysis. No-op on empty."""
    if not text or not text.strip():
        return
    with _lock:
        _utterances.append(text.strip())


def tick(min_cooccurrence: int = 3, min_confidence: float = 0.6) -> List[Shortcut]:
    """Analyse the buffer and register newly-confident implicit shortcuts.

    Returns the list of Shortcut records newly written this tick. A proposal is
    skipped if the term is already known — an explicitly-taught mapping is never
    downgraded or overwritten by an inferred one.
    """
    with _lock:
        utterances = list(_utterances)

    proposals = propose_shortcuts(utterances, min_cooccurrence=min_cooccurrence)
    written: List[Shortcut] = []
    for p in proposals:
        if p.confidence < min_confidence:
            continue
        # Never clobber an existing shortcut (esp. one taught explicitly).
        if shortcut_registry.get(p.slang) is not None:
            continue
        sc = Shortcut(
            term=p.slang,
            canonical=p.canonical,
            confidence=p.confidence,
            created_at=_now(),
            taught_explicitly=False,
        )
        try:
            shortcut_registry.teach(sc)
            written.append(sc)
        except Exception:
            pass
    return written
