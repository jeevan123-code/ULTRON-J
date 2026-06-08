"""Privacy Circle — derive a single mode label from who's in the room.

Modes (priority high -> low):
    stranger_present  — an unknown voice / unregistered name was heard
    professional      — at least one PROFESSIONAL person present
    friends           — at least one FRIEND present (no professional, no stranger)
    family            — at least one FAMILY person (in addition to SELF)
    private           — only SELF, or no one heard recently

Other modules query `current_mode()` to gate behavior (e.g., voice_engine
might suppress speaking secrets in `professional` or `stranger_present`).
"""
from typing import Optional

import person_registry
import room_awareness


_STRANGER_SENTINEL = "_stranger"


def _resolve_relation_for(name: str):
    """Return the Relation for a registered name, or None if unregistered."""
    from person_types import Relation
    if name == _STRANGER_SENTINEL:
        return None
    p = person_registry.get(name)
    return p.relation if p else None


def current_mode(now: Optional[float] = None,
                 within_seconds: int = 300) -> str:
    """Return the highest-precedence privacy mode for the current room."""
    from person_types import Relation
    names = room_awareness.who_is_in_the_room(now=now, within_seconds=within_seconds)
    if not names:
        return "private"

    has_stranger = False
    has_professional = False
    has_friend = False
    has_family = False

    for n in names:
        if n == _STRANGER_SENTINEL:
            has_stranger = True
            continue
        rel = _resolve_relation_for(n)
        if rel is None:
            has_stranger = True
            continue
        if rel == Relation.PROFESSIONAL:
            has_professional = True
        elif rel == Relation.FRIEND:
            has_friend = True
        elif rel == Relation.FAMILY:
            has_family = True
        elif rel == Relation.SELF:
            pass
        else:
            has_stranger = True

    if has_stranger:
        return "stranger_present"
    if has_professional:
        return "professional"
    if has_friend:
        return "friends"
    if has_family:
        return "family"
    return "private"
