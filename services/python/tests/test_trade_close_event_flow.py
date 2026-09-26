# -*- coding: utf-8 -*-
"""Trade-close / risk event flow: dict payloads must survive the EventQueue.

Live bug (logs/python.err.log): ``TRADE_CLOSE event emit failed: 'dict' object
has no attribute 'event_type'``. The producers (position-close detector in
orchestration/runtime and the risk-monitor wiring in main) enqueue plain dicts
carrying an ``event_type`` string, while ``EventQueue`` only accepted
``DetectedEvent`` objects. These tests pin the fixed contract:

* EventQueue accepts a dict payload, keeps it intact, and dequeues it back.
* ``TRADE_CLOSE`` / ``RISK_*`` are first-class EventTypes with mapped
  priorities (RISK_* = CRITICAL, TRADE_CLOSE = NORMAL).
* The pipeline aliases a trade-close payload to ``closed_trade`` so the
  supervisor can route it to ReviewLead (which reads ``closed_trade``).
"""

from __future__ import annotations

from typing import Any

from trading.event_engine import EventPriority, EventQueue, get_priority
from trading.events import DetectedEvent, EventTypes


def test_event_queue_accepts_dict_payload() -> None:
    """A dict enqueued by the close/risk producers must not crash the queue."""
    queue = EventQueue()
    payload = {"event_type": "TRADE_CLOSE", "trade_result": {"ticket": 42}}

    assert queue.enqueue(payload) is True
    assert len(queue) == 1

    event = queue.dequeue()
    assert event == payload
    assert event["event_type"] == "TRADE_CLOSE"
    assert event["trade_result"]["ticket"] == 42


def test_event_queue_dict_priority_uses_event_type() -> None:
    """Dict payloads are prioritised by their event_type (RISK_* = CRITICAL)."""
    queue = EventQueue()
    queue.enqueue({"event_type": "TREND_BULLISH", "symbol": "EURUSD"})
    queue.enqueue({"event_type": "RISK_DRAWDOWN", "drawdown": 0.2})

    first = queue.dequeue()
    assert first["event_type"] == "RISK_DRAWDOWN"


def test_event_queue_still_accepts_detected_event() -> None:
    """Legacy DetectedEvent path is unchanged (regression guard)."""
    queue = EventQueue()
    event = DetectedEvent(
        event_type=EventTypes.DOJI,
        severity=0.1,
        description="doji",
        timestamp="2026-09-25T00:00:00+00:00",
    )
    assert queue.enqueue(event) is True
    assert queue.dequeue() is event


def test_trade_close_and_risk_types_are_mapped() -> None:
    """New EventTypes members must carry explicit priorities."""
    assert get_priority(EventTypes.TRADE_CLOSE) is EventPriority.NORMAL
    assert get_priority(EventTypes.RISK_DRAWDOWN) is EventPriority.CRITICAL
    assert get_priority(EventTypes.RISK_EXPOSURE) is EventPriority.CRITICAL
    assert get_priority(EventTypes.RISK_MARGIN) is EventPriority.CRITICAL


class _RecordingSupervisor:
    """Supervisor stub capturing the analysis context it receives."""

    def __init__(self) -> None:
        self.contexts: list[dict[str, Any]] = []

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        self.contexts.append(dict(context))
        return {"summary": "", "proposal": None, "overall_signal": "NEUTRAL"}


def test_pipeline_maps_trade_result_to_closed_trade() -> None:
    """Pipeline context must expose the closed trade as ``closed_trade``."""
    from orchestration.pipeline import TradingPipeline

    supervisor = _RecordingSupervisor()
    pipeline = TradingPipeline(supervisor=supervisor, risk_gate=object())

    event = {
        "event_type": "TRADE_CLOSE",
        "trade_result": {"ticket": 42, "symbol": "XAUUSD"},
    }
    pipeline.run(event, {})

    assert supervisor.contexts, "supervisor should have been called"
    context = supervisor.contexts[0]
    assert context["closed_trade"] == {"ticket": 42, "symbol": "XAUUSD"}
    assert context["event_type"] == "TRADE_CLOSE"


def test_runtime_producer_to_real_queue_no_crash(monkeypatch: Any) -> None:
    """The exact live-bug path: runtime producer -> REAL EventQueue.

    logs/python.err.log recorded ``TRADE_CLOSE event emit failed: 'dict' object
    has no attribute 'event_type'`` because test_runtime.py drives a dict-based
    stub queue. This test wires the production EventQueue instead.
    """
    import review.auto_trigger as at_mod
    from orchestration.runtime import _build_position_monitor

    monkeypatch.setattr(at_mod, "on_position_closed", lambda _tr: None)

    class _Scheduler:
        def __init__(self) -> None:
            self.wakes = 0

        def wake(self) -> None:
            self.wakes += 1

    queue = EventQueue()  # production queue
    scheduler = _Scheduler()

    monitor = _build_position_monitor(event_queue=queue, scheduler=scheduler)
    if monitor is None:
        import pytest

        pytest.skip("PositionMonitor not available (optional dependency missing)")

    detector = monitor.close_detector
    detector.observe(
        [{"ticket": 4242, "symbol": "XAUUSD", "side": "SELL", "price_open": 2400.0}]
    )
    assert len(queue) == 0

    detector.observe([])  # close -> producer enqueues dict into REAL queue

    assert len(queue) == 1, "TRADE_CLOSE must survive the production queue"
    event = queue.dequeue()
    assert isinstance(event, dict)
    assert event["event_type"] == "TRADE_CLOSE"
    assert event["trade_result"]["ticket"] == 4242
    assert scheduler.wakes == 1


if __name__ == "__main__":  # pragma: no cover
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
