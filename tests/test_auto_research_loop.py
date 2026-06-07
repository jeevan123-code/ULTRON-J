"""Tests for auto_research_loop — single-tick worker without real threads."""
from unittest.mock import patch, MagicMock

import auto_research_loop as arl
import conversation_listener as cl
import research_queue as rq


def setup_function():
    cl._reset_for_test()
    rq._reset_for_test()


def test_tick_drains_listener_and_enqueues_detected_topics():
    cl.record("I'm meeting Elon Musk tomorrow")
    with patch.object(arl, "_detect_topics", return_value=[
        {"name": "Elon Musk", "priority": 4, "reason": "person"}
    ]):
        arl._tick_detect()
    snap = rq.snapshot()
    assert len(snap) == 1
    assert snap[0]["topic"] == "Elon Musk"
    assert snap[0]["priority"] == 4


def test_tick_skips_executor_when_user_not_idle():
    rq.enqueue("Elon Musk", priority=4)
    fake_exec = MagicMock()
    with patch.object(arl, "_should_deliver", return_value=False), \
         patch.object(arl, "_execute_plan", new=fake_exec):
        arl._tick_execute()
    assert len(rq.snapshot()) == 1
    fake_exec.assert_not_called()


def test_tick_executes_one_job_when_user_idle():
    rq.enqueue("Elon Musk", priority=4)
    fake_exec = MagicMock(return_value={"executed": True})
    with patch.object(arl, "_should_deliver", return_value=True), \
         patch.object(arl, "_execute_plan", new=fake_exec):
        arl._tick_execute()
    assert rq.snapshot() == []
    fake_exec.assert_called_once()
    plan_arg = fake_exec.call_args[0][0]
    assert plan_arg.steps[0]["action"] == "research"
    assert plan_arg.steps[0]["args"]["topic"] == "Elon Musk"


def test_tick_marks_done_after_execution():
    rq.enqueue("topic")
    with patch.object(arl, "_should_deliver", return_value=True), \
         patch.object(arl, "_execute_plan", return_value={"executed": True}):
        arl._tick_execute()
    assert rq.snapshot() == []
