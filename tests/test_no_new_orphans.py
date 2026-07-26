"""THE WIRING GATE.

A phase is not shipped until production can reach it. Twice now a batch of
modules was built, tested and recorded as "shipped" while nothing outside its
own test file imported it — Phases 5b/5g, then Phases 18/19/20/21/23. The audit
tool caught both; nobody ran it. This test makes the suite run it.

If this fails: either wire the module from a production caller, or retire it,
or (last resort, with a written reason) add it to orphan_guard.ALLOWED_ORPHANS.
"""
import orphan_guard


def test_no_unexpected_orphans():
    orphans = orphan_guard.unexpected_orphans()
    assert orphans == [], (
        "These modules are unreachable from production — only their own tests "
        f"import them: {orphans}. Wire them from a real caller, retire them, or "
        "add them to orphan_guard.ALLOWED_ORPHANS with a reason."
    )


def test_allowlist_has_no_stale_entries():
    # Once a module is wired, its allowlist entry must go — otherwise the
    # allowlist silently accumulates and stops meaning anything.
    stale = orphan_guard.stale_allowlist_entries()
    assert stale == [], (
        f"These are no longer orphans and must be removed from "
        f"orphan_guard.ALLOWED_ORPHANS: {stale}"
    )


def test_every_allowlist_entry_has_a_reason():
    blank = [m for m, why in orphan_guard.ALLOWED_ORPHANS.items() if not why.strip()]
    assert blank == [], f"allowlist entries without a documented reason: {blank}"
