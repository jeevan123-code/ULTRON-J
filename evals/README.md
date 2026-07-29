# Evals — fixed questions, known-correct answers

Run these against a **running** Ultron after any change that touches routing,
search, prompts or intents.

```bash
.venv/bin/python app.py &                       # Ultron must be up
.venv/bin/python evals/run_evals.py             # all cases
.venv/bin/python evals/run_evals.py --category arithmetic
.venv/bin/python evals/run_evals.py --report out.json
```

Exit code is non-zero when a case fails, so it works as a pre-commit gate.

## Why this exists and the unit suite does not replace it

On 2026-07-29 all 1516 unit tests passed while Ultron was answering "what is
the current price of gold" with a scraped HTML table and a stranger's byline,
and "what is 847 times 291" with 246,297.

Neither bug was in a unit. Both were in the **wiring between** components — an
action intercept returning raw text before the model was called, and a
calculator that could not parse the sentence it was handed. Only a real HTTP
request goes through the orchestrator, the intent router, the search stack and
the model in one pass.

The unit suite proves the parts work. This proves the assembled thing answers.

## Adding a case

Add a bug to `cases.yaml` the moment you find one, with a `why` recording what
went wrong. The goal is that no bug is ever found twice.

```yaml
- id: math-multiplication
  category: arithmetic
  why: "Answered 246,297 on 2026-07-29 — the calculator was unreachable."
  question: what is 847 times 291
  expect: {number: 246477, provider: calculate}
```

Checks are documented at the top of `cases.yaml` and implemented in
`checks.py`, which is unit-tested in `tests/test_eval_checks.py` against the
real answers from that day — the broken ones and their fixed replacements.

**Quote `yes`, `no`, `on` and `off`.** YAML reads them as booleans, which
killed two cases on the harness's first run.

## known_issue

A case marked `known_issue: true` reports as `KNOWN` and does not fail the
run. Use it for behaviour that is still an open decision rather than an agreed
bug — a permanently red run is a run nobody reads.

Currently one: `edge-injection-direct`. Ultron obeys "ignore all previous
instructions" 5 times in 6 across all three providers, so it is the system
prompt rather than any one model. It is left open because it is genuinely
ambiguous — Jeevan typed it, and Ultron is built to obey Jeevan. It stops
being ambiguous once retrieved page content reaches the model, which is where
the raw-dump fixes are heading, and Ultron can delete files and run code.
