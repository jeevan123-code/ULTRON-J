"""End-to-end Phase 2b: utterance heard -> detected -> queued -> executed."""
from unittest.mock import patch, MagicMock
import json
import pytest

import conversation_listener as cl
import research_queue as rq
import auto_research_loop as arl
from tests.fixtures.research_responses import wheat_rust_report


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    monkeypatch.setattr(rq, "_QUEUE_PATH", str(tmp_path / "q.json"))
    cl._reset_for_test()
    rq._reset_for_test()
    yield
    cl._reset_for_test()
    rq._reset_for_test()


def test_full_autonomous_flow():
    # 1. Voice transcript arrives -> listener records
    cl.record("I'm meeting Elon Musk tomorrow at the SpaceX event")

    # 2. Detection tick — LLM returns the topic
    with patch.object(arl, "_detect_topics", return_value=[
        {"name": "Elon Musk SpaceX event", "priority": 5, "reason": "imminent meeting"}
    ]):
        arl._tick_detect()

    assert len(rq.snapshot()) == 1
    assert rq.peek()["topic"] == "Elon Musk SpaceX event"

    # 3. Execute tick — user is idle, executor runs the plan
    fake_speak = MagicMock()
    with patch.object(arl, "_should_deliver", return_value=True), \
         patch("phase2_executor._research", return_value=wheat_rust_report()), \
         patch("delivery_manager._speak", new=fake_speak), \
         patch("research_facts._get_vector_store", return_value=MagicMock()):
        arl._tick_execute()

    # 4. Queue is empty, voice was spoken
    assert rq.snapshot() == []
    fake_speak.assert_called_once()


def test_quietness_gate_blocks_execution():
    cl.record("urgent stuff happening now")
    rq.enqueue("urgent stuff", priority=4)

    fake_speak = MagicMock()
    with patch.object(arl, "_should_deliver", return_value=False), \
         patch("delivery_manager._speak", new=fake_speak):
        arl._tick_execute()

    # Queue still has the job; voice not spoken
    assert len(rq.snapshot()) == 1
    fake_speak.assert_not_called()
