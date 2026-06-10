"""Phase 3c improvement suggester — pure pattern detection over ActionEvents.

Given a list of recent `ActionEvent`s, returns zero or more `Suggestion`s
describing repetitive workflows that could be automated.

Detectors implemented:
  * batch_rename: N+ FILE_RENAME events in the window.
  * morning_routine: M+ identical APP_LAUNCH events inside a short window.

Pure logic — no I/O, no integrations. Callers pass in a snapshot from
`action_log.recent(...)`.
"""
from typing import Iterable, List

from action_types import ActionEvent, ActionKind
from improvement_types import Suggestion


BATCH_RENAME_THRESHOLD = 5
MORNING_ROUTINE_WINDOW_SECONDS = 30
MORNING_ROUTINE_MIN_LAUNCHES = 3


def _detect_batch_rename(events: List[ActionEvent]) -> List[Suggestion]:
    renames = [e for e in events if e.kind == ActionKind.FILE_RENAME]
    if len(renames) < BATCH_RENAME_THRESHOLD:
        return []
    confidence = min(1.0, 0.5 + 0.1 * (len(renames) - BATCH_RENAME_THRESHOLD + 1))
    return [Suggestion(
        kind="batch_rename",
        summary=(
            f"Sir, you've renamed {len(renames)} files in a row. "
            "May I write a batch-rename script for this?"
        ),
        template="batch_rename_script",
        supporting_events=list(renames),
        confidence=confidence,
    )]


def _detect_morning_routine(events: List[ActionEvent]) -> List[Suggestion]:
    launches = [e for e in events if e.kind == ActionKind.APP_LAUNCH]
    if len(launches) < MORNING_ROUTINE_MIN_LAUNCHES:
        return []

    by_app: dict[str, List[ActionEvent]] = {}
    for ev in launches:
        by_app.setdefault(ev.target, []).append(ev)

    suggestions: List[Suggestion] = []
    for app, evs in by_app.items():
        if len(evs) < MORNING_ROUTINE_MIN_LAUNCHES:
            continue
        evs_sorted = sorted(evs, key=lambda e: e.ts)
        for start in range(len(evs_sorted) - MORNING_ROUTINE_MIN_LAUNCHES + 1):
            window = evs_sorted[start:start + MORNING_ROUTINE_MIN_LAUNCHES]
            if window[-1].ts - window[0].ts <= MORNING_ROUTINE_WINDOW_SECONDS:
                suggestions.append(Suggestion(
                    kind="morning_routine",
                    summary=(
                        f"Sir, you launched {app} {len(window)} times in "
                        f"{int(window[-1].ts - window[0].ts)}s. "
                        "Shall I bind it to a single shortcut?"
                    ),
                    template="morning_routine_script",
                    supporting_events=list(window),
                    confidence=0.6,
                ))
                break  # one suggestion per app
    return suggestions


def analyze(events: Iterable[ActionEvent]) -> List[Suggestion]:
    """Scan events for repetition patterns and return suggestions."""
    evs = list(events)
    if not evs:
        return []

    suggestions: List[Suggestion] = []
    suggestions.extend(_detect_batch_rename(evs))
    suggestions.extend(_detect_morning_routine(evs))
    return suggestions
