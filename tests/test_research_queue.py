"""Tests for research_queue — priority + dedupe + JSON persistence."""
import json
import os
import time
import pytest
import research_queue as rq


@pytest.fixture(autouse=True)
def _tmp_queue(tmp_path, monkeypatch):
    """Redirect persistence to a tmp file per test."""
    path = tmp_path / "queue.json"
    monkeypatch.setattr(rq, "_QUEUE_PATH", str(path))
    rq._reset_for_test()
    yield
    rq._reset_for_test()


def test_enqueue_and_peek():
    rq.enqueue("wheat leaf rust", priority=2)
    job = rq.peek()
    assert job is not None
    assert job["topic"] == "wheat leaf rust"
    assert job["priority"] == 2


def test_dedupe_within_window_drops_duplicate():
    assert rq.enqueue("Elon Musk") is True
    assert rq.enqueue("elon musk") is False
    assert len(rq.snapshot()) == 1


def test_dedupe_window_allows_reenqueue_after_ttl(monkeypatch):
    rq.enqueue("topic A", dedupe_ttl_seconds=0)
    assert rq.enqueue("topic A", dedupe_ttl_seconds=0) is True


def test_priority_ordering():
    rq.enqueue("low", priority=1)
    rq.enqueue("high", priority=5)
    rq.enqueue("medium", priority=3)
    topics = [rq.pop()["topic"] for _ in range(3)]
    assert topics == ["high", "medium", "low"]


def test_pop_empty_returns_none():
    assert rq.pop() is None


def test_persistence_roundtrip():
    rq.enqueue("persisted topic", priority=2)
    rq._reset_in_memory_for_test()
    rq._load_from_disk()
    job = rq.pop()
    assert job is not None
    assert job["topic"] == "persisted topic"


def test_done_removes_job():
    rq.enqueue("x")
    job = rq.pop()
    rq.done(job["id"])
    assert rq.peek() is None


def test_snapshot_returns_pending_jobs_only():
    rq.enqueue("a")
    rq.enqueue("b")
    rq.pop()
    assert len(rq.snapshot()) == 1
