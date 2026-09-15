# -*- coding: utf-8 -*-
"""Tests for PRD_V2 §15 event priority levels and scheduler backpressure."""

from __future__ import annotations

from typing import Any

from trading.event_engine import PRIORITY_ORDER, EventPriority, EventQueue, get_priority
from trading.events import DetectedEvent, EventTypes
from trading.scheduler import AutonomousScheduler

# ---------------------------------------------------------------------------
# §15 priority ladder
# ---------------------------------------------------------------------------


def test_priority_members_present():
    names = {p.name for p in EventPriority}
    assert {"CRITICAL", "HIGH", "NORMAL", "MEDIUM", "LOW", "BACKGROUND"} <= names


def test_priority_order_is_ascending():
    values = [p.value for p in PRIORITY_ORDER]
    assert values == sorted(values)
    assert PRIORITY_ORDER[0] is EventPriority.BACKGROUND
    assert PRIORITY_ORDER[-1] is EventPriority.CRITICAL


def test_priority_comparison_by_value():
    assert EventPriority.BACKGROUND.value < EventPriority.LOW.value
    assert EventPriority.LOW.value < EventPriority.NORMAL.value
    assert EventPriority.NORMAL.value < EventPriority.HIGH.value
    assert EventPriority.HIGH.value < EventPriority.CRITICAL.value


def test_get_priority_default_is_normal():
    # An event type not explicitly mapped falls back to NORMAL.
    class _Fake:
        pass

    assert get_priority(_Fake()) is EventPriority.NORMAL  # type: ignore[arg-type]


def test_background_event_mapped():
    assert get_priority(EventTypes.DOJI) is EventPriority.BACKGROUND


# ---------------------------------------------------------------------------
# Backpressure behaviour
# ---------------------------------------------------------------------------


class _StubPipeline:
    def __init__(self) -> None:
        self.seen: list[Any] = []

    def run(self, event: Any, context: dict[str, Any]) -> Any:
        self.seen.append(event)
        return type("R", (), {"status": "OK", "decision": "", "error": None})()


def _event(event_type: EventTypes) -> DetectedEvent:
    return DetectedEvent(event_type=event_type, severity=0.5, description="x", timestamp="now")


def test_scheduler_skips_background_under_backpressure():
    q = EventQueue(max_size=10)
    q.enqueue(_event(EventTypes.DOJI))  # BACKGROUND
    q.enqueue(_event(EventTypes.BREAKOUT))  # HIGH
    pipe = _StubPipeline()
    sched = AutonomousScheduler(q, pipe, backpressure=True)

    processed = sched.process_available()

    assert processed == 1
    assert [e.event_type for e in pipe.seen] == [EventTypes.BREAKOUT]
    assert sched.stats()["events_skipped"] == 1
    assert sched.stats()["backpressure"] is True


def test_scheduler_processes_background_without_backpressure():
    q = EventQueue(max_size=10)
    q.enqueue(_event(EventTypes.DOJI))  # BACKGROUND
    q.enqueue(_event(EventTypes.BREAKOUT))  # HIGH
    pipe = _StubPipeline()
    sched = AutonomousScheduler(q, pipe, backpressure=False)

    processed = sched.process_available()

    assert processed == 2
    assert sched.stats()["events_skipped"] == 0


def test_scheduler_default_no_backpressure():
    q = EventQueue(max_size=10)
    pipe = _StubPipeline()
    sched = AutonomousScheduler(q, pipe)
    assert sched.backpressure is False
