"""Autonomous Research Loop.

Two cooperating ticks (called in alternation by a background thread):

  _tick_detect():
      drain conversation_listener -> topic_detector.detect_topics -> research_queue.enqueue

  _tick_execute():
      if proactive_planner.should_deliver_research_now():
          pop a job from research_queue -> phase2_executor.execute -> done

Both ticks are pure functions and individually testable. The full loop is
launched by start(), which sleeps between ticks.
"""
import threading
import time
from typing import Any, Dict, List, Optional

import conversation_listener
import research_queue
from intent_types import ExecutionPlan


def _detect_topics(utts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from topic_detector import detect_topics
    return detect_topics(utts)


def _execute_plan(plan: ExecutionPlan) -> Dict[str, Any]:
    from phase2_executor import execute
    return execute(plan)


def _should_deliver() -> bool:
    from proactive_planner import should_deliver_research_now
    return should_deliver_research_now()


def _tick_detect() -> None:
    """Move new utterances from listener into the queue."""
    fresh = conversation_listener.drain_unprocessed()
    if not fresh:
        return
    topics = _detect_topics(fresh)
    for t in topics:
        research_queue.enqueue(t["name"], priority=int(t.get("priority", 1)),
                               metadata={"reason": t.get("reason", "")})


def _tick_execute() -> None:
    """Pop one job, execute it, mark done — only if user is idle."""
    if not _should_deliver():
        return
    job = research_queue.pop()
    if not job:
        return
    plan = ExecutionPlan(
        steps=[{"action": "research", "args": {"topic": job["topic"]}}],
        pre_checks=[],
        rationale=f"auto-research from conversation (priority {job['priority']})",
    )
    try:
        _execute_plan(plan)
    finally:
        research_queue.done(job["id"])


_running = False
_thread: Optional[threading.Thread] = None
_DETECT_EVERY_SECONDS = 30
_EXECUTE_EVERY_SECONDS = 60


def _loop():
    global _running
    last_exec = 0.0
    while _running:
        try:
            _tick_detect()
            if time.time() - last_exec >= _EXECUTE_EVERY_SECONDS:
                _tick_execute()
                last_exec = time.time()
        except Exception as e:
            try:
                with open("ultron_log.txt", "a") as f:
                    f.write(f"[phase2b][loop_error] {e!r}\n")
            except Exception:
                pass
        time.sleep(_DETECT_EVERY_SECONDS)


def start() -> bool:
    global _running, _thread
    if _running:
        return False
    _running = True
    _thread = threading.Thread(target=_loop, daemon=True, name="auto_research_loop")
    _thread.start()
    return True


def stop() -> bool:
    global _running, _thread
    if not _running:
        return False
    _running = False
    _thread = None
    return True


def is_running() -> bool:
    return _running
