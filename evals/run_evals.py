#!/usr/bin/env python
"""Run the eval set against a live Ultron and report what regressed.

    .venv/bin/python evals/run_evals.py
    .venv/bin/python evals/run_evals.py --category arithmetic
    .venv/bin/python evals/run_evals.py --base http://127.0.0.1:5000

Exits non-zero when any case fails, so it works as a gate before a commit.

This is the check the unit suite cannot make. On 2026-07-29 all 1516 tests
passed while Ultron was answering the gold price with a scraped table — the
bug was in the wiring between the orchestrator, the search stack and the
model, and only a real HTTP request goes through all three.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evals import checks  # noqa: E402

CASES = Path(__file__).resolve().parent / "cases.yaml"


def ask(base, question, timeout):
    """POST /ask and collapse the SSE stream into (answer, provider)."""
    r = requests.post(f"{base}/ask",
                      json={"question": question, "session_id": "_eval"},
                      timeout=timeout)
    r.raise_for_status()
    answer, provider = "", ""
    for line in r.text.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            d = json.loads(line[6:])
        except Exception:
            continue
        if d.get("_full"):
            answer = d["_full"]
        elif d.get("token"):
            answer += d["token"]
        if d.get("provider"):
            provider = d["provider"]
        if isinstance(d.get("_cost"), dict) and d["_cost"].get("provider"):
            provider = provider or d["_cost"]["provider"]
    return answer, provider


def _terms(expect, key):
    """Case terms as lowercase strings.

    YAML reads a bare `yes`/`no`/`on`/`off` as a boolean, so `contains_any:
    [yes]` arrives as [True]. Quoting in cases.yaml is the real fix; coercing
    here means forgetting to quote costs a confusing failure rather than a
    crash mid-run.
    """
    return [str(t).lower() for t in expect.get(key, [])]


def evaluate(expect, answer, provider):
    """Return the list of failure reasons — empty means the case passed."""
    fails = []
    low = str(answer or "").lower()

    if "number" in expect and not checks.has_number(answer, expect["number"]):
        fails.append(f"expected the number {expect['number']}")

    for term in _terms(expect, "contains"):
        if term not in low:
            fails.append(f"missing {term!r}")

    any_of = _terms(expect, "contains_any")
    if any_of and not any(t in low for t in any_of):
        fails.append(f"none of {any_of} present")

    for term in _terms(expect, "not_contains"):
        if term in low:
            fails.append(f"must not contain {term!r}")

    if expect.get("not_dump"):
        reason = checks.looks_like_raw_dump(answer)
        if reason:
            fails.append(f"raw dump: {reason}")
        elif not answer.strip():
            fails.append("empty answer")

    if expect.get("answers_or_admits") and not checks.answers_or_admits(answer):
        fails.append("gave neither a figure nor an admission it could not retrieve one")

    if "min_len" in expect and len(answer.strip()) < expect["min_len"]:
        fails.append(f"answer shorter than {expect['min_len']} chars")

    if "provider" in expect and expect["provider"] not in (provider or ""):
        fails.append(f"answered by {provider or '?'!r}, expected {expect['provider']!r}")

    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5000")
    ap.add_argument("--category", help="run only this category")
    ap.add_argument("--timeout", type=float, default=150)
    ap.add_argument("--report", help="write a JSON report here")
    args = ap.parse_args()

    cases = yaml.safe_load(CASES.read_text())
    if args.category:
        cases = [c for c in cases if c.get("category") == args.category]
    if not cases:
        print("no cases selected")
        return 1

    try:
        requests.get(args.base, timeout=10)
    except Exception as e:
        print(f"Ultron is not answering on {args.base} — {type(e).__name__}")
        print("Start it first:  .venv/bin/python app.py")
        return 2

    results, failed = [], 0
    width = max(len(c["id"]) for c in cases)
    for case in cases:
        t0 = time.time()
        try:
            answer, provider = ask(args.base, case["question"], args.timeout)
            fails = evaluate(case.get("expect", {}), answer, provider)
        except Exception as e:
            answer, provider = "", ""
            fails = [f"request failed — {type(e).__name__}: {str(e)[:80]}"]
        dt = time.time() - t0

        # A known_issue case documents behaviour that is still an open
        # decision. It reports, but does not turn the gate red — otherwise the
        # run is permanently failing and nobody reads it.
        if fails and case.get("known_issue"):
            status = "KNOWN"
        elif fails:
            status = "FAIL"
            failed += 1
        else:
            status = "PASS"
        print(f"[{status}] {case['id']:<{width}} {dt:6.1f}s  {answer.strip()[:88]!r}",
              flush=True)
        for reason in fails:
            print(f"         -> {reason}", flush=True)
        if fails and case.get("why"):
            why = " ".join(case["why"].split())
            print(f"         why this case exists: {why}", flush=True)
        results.append({"id": case["id"], "category": case.get("category"),
                        "status": status, "failures": fails,
                        "answer": answer, "provider": provider,
                        "elapsed_s": round(dt, 2)})

    known = sum(1 for r in results if r["status"] == "KNOWN")
    passed = sum(1 for r in results if r["status"] == "PASS")
    print(f"\n{passed} passed / {failed} failed / {known} known-issue / {len(cases)} run")
    if args.report:
        Path(args.report).write_text(json.dumps(results, indent=2, ensure_ascii=False))
        print(f"report written to {args.report}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
