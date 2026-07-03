# Phase 23 — Self-Modification Autonomy (approval-gated + rollback ledger)

Ultron rewriting its own code is the highest-risk autonomy, so this is the
SAFEST possible design: a patch is STAGED and compile-checked but **never
auto-applied**. A human must `approve()` it; only then is it written (via
`self_modify.patch_file_direct`, which takes its own backup). Every
proposal/approval/apply/rollback is recorded in an append-only ledger, and any
applied patch can be rolled back.

## `self_modify_proposals.py`
- `propose(filename, new_code, request, rationale)` — validates target is in
  `self_modify.ALLOWED_FILES` and (for .py) compiles; stores as pending. Does
  NOT apply.
- `approve(id)` — the human gate: applies via `patch_file_direct`, records the
  backup path in the ledger.
- `reject(id)`, `rollback(id)` (restore backup), `get_ledger()`, `list_pending()`.

## Safety property
There is intentionally **no flag that makes this auto-apply** — approval is
always manual. Compile-check on propose + backup on apply + ledger + rollback
give defence in depth. This is the "self-modification-merge with a safety
ledger" item from the Tier-1 roadmap; Ultron proposes code changes, but a human
always merges them.

## Tests (8)
`tests/test_self_modify_proposals.py` — propose-doesn't-apply, disallowed file,
syntax rejection, approve→apply→ledger, reject blocks apply, rollback, apply-
failure recording.
