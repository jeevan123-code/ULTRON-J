# PERFECTION SCORECARD — Ultron-J

The definition of "top-level / perfect" the hardening branch is driving
toward. Updated at the end of each phase. Source of truth: `hello.txt`
Phase 9.

A row goes green only when its evidence (test, command output,
file) is committed on this branch and verifiable from a fresh checkout.

| # | Dimension          | Target                                                                     | Status |
|---|--------------------|----------------------------------------------------------------------------|--------|
| 1 | Security           | auth enforced; CORS locked; loopback default; dangerous ops gated          | 🟩 **green** — auth gate + CORS + loopback bind + confirm-token gate on 6 write-routes + phone/click input validation, all proved by 33 tests in `tests/test_auth.py` |
| 2 | Core tools         | 100% on capability suite, repeatable                                       | 🟩 **green** — 114/114 PASS, baseline locked in `BASELINE_CAPABILITIES.txt` |
| 3 | Autonomous loop    | >0 real goals completed; success rate trending up; no crashes              | ⬜ pending (Phase 3) |
| 4 | Resource health    | health_score consistently high; no `mem_rising` anomalies                  | ⬜ pending (Phase 4) |
| 5 | Voice              | TTS + STT round-trips pass; error rate ~0                                  | 🟨 likely already true (per plan) — no regression test yet |
| 6 | Architecture       | one documented primary path; no dead/duplicate code                        | ⬜ pending (Phase 5) |
| 7 | Error handling     | 0 naked excepts; core-path swallows logged                                 | ⬜ pending (Phase 7) |
| 8 | Reproducibility    | requirements.txt pinned; fresh clone boots clean; LF line endings          | 🟨 **partial** — requirements pinned (Phase 0.2 ✅); LF normalization pending (Phase 7.2) |
| 9 | Tests              | capabilities + intent(81) + auth + autonomous-goal + route-smoke green     | 🟨 **partial** — capabilities + intent(81) + auth green (146/146); autonomous-goal + route-smoke still owed |

Legend: 🟩 green · 🟨 partial · 🟥 red · ⬜ not started

Final acceptance (Phase 9): every row green; `BASELINE_CAPABILITIES.txt`
versus latest shows improvement (or unchanged at 100%); `git log` tells
a clean per-task story.
