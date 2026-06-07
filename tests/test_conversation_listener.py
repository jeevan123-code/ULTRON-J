"""Tests for conversation_listener — rolling buffer of recent utterances."""
import pytest
import conversation_listener as cl


@pytest.fixture(autouse=True)
def _reset():
    cl._reset_for_test()
    yield
    cl._reset_for_test()


def test_record_adds_utterance():
    cl.record("hello there")
    snap = cl.snapshot()
    assert len(snap) == 1
    assert snap[0]["text"] == "hello there"
    assert snap[0]["processed"] is False


def test_buffer_caps_at_max_size():
    for i in range(50):
        cl.record(f"msg {i}")
    assert len(cl.snapshot()) <= cl.MAX_BUFFER


def test_drain_unprocessed_returns_only_new():
    cl.record("a")
    cl.record("b")
    new = cl.drain_unprocessed()
    assert [u["text"] for u in new] == ["a", "b"]
    assert cl.drain_unprocessed() == []


def test_drain_after_record_returns_only_new_ones():
    cl.record("old")
    cl.drain_unprocessed()
    cl.record("new")
    new = cl.drain_unprocessed()
    assert [u["text"] for u in new] == ["new"]


def test_empty_string_is_ignored():
    cl.record("")
    cl.record("   ")
    assert cl.snapshot() == []


def test_record_thread_safe(monkeypatch):
    import threading
    def worker():
        for i in range(20):
            cl.record(f"t-{i}")
    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert len(cl.snapshot()) <= cl.MAX_BUFFER
