"""
Phase 3.3 — prove the autonomous loop can complete a real goal end-to-end.

Pre-Phase-3 state: tool_stats.json + reflection_log.json showed
`total_goals_ever = 0` and `avg_execution_score = 0.0`. The loop was
healthy but idle — `decide_next_action` returned `observe` forever
because goals.json was empty AND `disk_critical` was firing on
squashfs snap mounts every cycle.

This test seeds ONE concrete goal — "fetch Hyderabad weather → write
to a note" — with pre-populated tasks carrying tool-specific params,
then drives the observe→decide→plan→act→evaluate cycle by hand until
the goal reaches COMPLETED. Asserts the reflection metrics show a
non-zero success rate.

Run:  venv/bin/python -m pytest tests/test_autonomous_goal.py -v --timeout=30
"""

import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import autonomous_loop as al                        # noqa: E402
import decision_engine as de                        # noqa: E402
from action_engine import execute_action            # noqa: E402
import reflection                                    # noqa: E402


GOALS_FILE     = ROOT / "goals.json"
EXEC_LOG_FILE  = ROOT / "execution_log.json"


# ─── Fixture: isolate goals + execution log from any user state ───────────────

@pytest.fixture()
def clean_goal_state():
    """Back up goals.json and execution_log.json (if any), run with a
    clean slate, restore at teardown so real user state isn't polluted."""
    backups = {}
    for f in (GOALS_FILE, EXEC_LOG_FILE):
        if f.exists():
            backups[f] = f.read_bytes()
            f.unlink()
    yield
    for f, content in backups.items():
        f.write_bytes(content)
    # Tear down any test artifact still present
    for f in (GOALS_FILE, EXEC_LOG_FILE):
        if f.exists() and f not in backups:
            f.unlink()


# ─── The acceptance test ──────────────────────────────────────────────────────

def test_one_real_goal_completes_end_to_end(clean_goal_state):
    """Seed → start → execute every task → evaluate → COMPLETED. Then
    confirm reflection metrics show a non-zero success rate and a
    completed_today count of >=1."""

    # ── seed ──────────────────────────────────────────────────────────────────
    goal = de.create_goal(
        title="Phase 3 demo — Hyderabad weather snapshot",
        description="Fetch the current Hyderabad weather and save a note.",
        priority=de.Priority.HIGH,
        source="phase3_test",
        tags=["test", "phase3"],
    )
    goal_id = goal["id"]

    # Pre-populate tasks with concrete tool + params, then mark PLANNING.
    # build_plan would otherwise auto-generate generic ask_llm steps that
    # don't carry tool-specific args.
    tasks = [
        {
            "id":          "step_0",
            "description": "Fetch current Hyderabad weather",
            "status":      de.TaskStatus.PENDING,
            "result":      None,
            "tool":        "weather_fetch",
            "params":      {"location": "Hyderabad"},
            "attempts":    0,
            "depends_on":  [],
        },
        {
            "id":          "step_1",
            "description": "Save a note marking this run",
            "status":      de.TaskStatus.PENDING,
            "result":      None,
            "tool":        "note_create",
            "params": {
                "title":    "Phase 3 demo: Hyderabad weather",
                "content":  "Autonomous-loop test fired weather_fetch + note_create end-to-end.",
                "category": "test",
                "tags":     ["phase3", "demo"],
            },
            "attempts":   0,
            "depends_on": ["step_0"],
        },
    ]
    de.update_goal(goal_id, tasks=tasks, status=de.GoalStatus.PENDING)

    # ── drive the loop by hand ─────────────────────────────────────────────────
    # The real loop sleeps HEARTBEAT_INTERVAL between iterations; we
    # don't sleep — we just call the same five-phase pipeline a fixed
    # number of times. Generous upper bound (15 iterations) so the test
    # doesn't hang if something deadlocks.

    completed = False
    for _ in range(15):
        obs      = al.observe_environment()
        decision = al.make_decision(obs)
        plan     = al.plan_for_decision(decision)
        if plan.get("planned") and plan.get("action") != "observe":
            al.act_on_plan(plan)

        # Stop as soon as our specific goal is COMPLETED.
        cur = de.get_goal(goal_id)
        if cur and cur.get("status") == de.GoalStatus.COMPLETED:
            completed = True
            break

    cur = de.get_goal(goal_id)
    assert completed, (
        f"goal did not complete in 15 iterations — final status="
        f"{cur and cur.get('status')!r}, tasks="
        f"{[(t['id'], t.get('status')) for t in (cur or {}).get('tasks', [])]}"
    )
    assert cur["status"] == de.GoalStatus.COMPLETED
    assert cur.get("execution_score", 0) > 0, (
        f"execution_score={cur.get('execution_score')} — must be >0 for acceptance"
    )
    assert cur.get("progress_pct", 0) >= 80

    # ── reflection metrics ─────────────────────────────────────────────────────
    metrics = reflection.analyze_performance()
    assert metrics["completed_today"] >= 1, metrics
    assert metrics["success_rate_pct"] > 0, metrics
    assert metrics["avg_execution_score"] > 0, metrics

    # ── per-task verification (catches "goal marked completed but tasks
    # actually failed silently" mode) ─────────────────────────────────────────
    for t in cur["tasks"]:
        assert t["status"] == de.TaskStatus.SUCCESS, (
            f"task {t['id']} status={t['status']!r}, result={t.get('result')!r}"
        )
