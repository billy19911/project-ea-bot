# -*- coding: utf-8 -*-
"""FIX A test: position-close detection emits a TRADE_CLOSE event to the queue.

The supervisor only routes to ReviewLead when a TRADE_CLOSE event reaches the
EventQueue. This test verifies that the runtime's _build_position_monitor wiring
enqueues such an event (and wakes the scheduler) when a ticket disappears,
mirroring the MarketFeedLoop ``on_emit`` pattern.
"""

from __future__ import annotations

from typing import Any


class _FakeQueue:
    """Minimal EventQueue stub recording enqueued payloads."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def enqueue(self, event: dict[str, Any]) -> None:
        self.events.append(event)


class _FakeScheduler:
    """Minimal scheduler stub counting wake() calls."""

    def __init__(self) -> None:
        self.wake_count = 0

    def wake(self) -> None:
        self.wake_count += 1


def _position(ticket: int) -> dict:
    return {
        "ticket": ticket,
        "symbol": "EURUSD",
        "side": "BUY",
        "price_open": 1.1,
        "profit": 10.0,
    }


def test_position_close_emits_trade_close_event(monkeypatch: Any) -> None:
    """A disappeared ticket triggers a TRADE_CLOSE event + scheduler wake.

    We monkeypatch ``review.auto_trigger.on_position_closed`` so the review path
    does not need a live MT5 connection, then drive the detector directly.
    """
    from orchestration.runtime import _build_position_monitor

    queue = _FakeQueue()
    scheduler = _FakeScheduler()

    # Stub the review path so the TRADE_CLOSE emit is the only thing tested.
    import review.auto_trigger as at_mod

    monkeypatch.setattr(at_mod, "on_position_closed", lambda _tr: None)

    monitor = _build_position_monitor(event_queue=queue, scheduler=scheduler)
    if monitor is None:
        import pytest

        pytest.skip("PositionMonitor not available (optional dependency missing)")

    detector = monitor.close_detector
    assert detector is not None, "Detector should be wired"

    # First observation: position 42 is open.
    detector.observe([_position(42)])
    assert len(queue.events) == 0, "No close yet"
    assert scheduler.wake_count == 0, "Scheduler not woken"

    # Second observation: position 42 disappeared (closed).
    detector.observe([])

    # Verify: TRADE_CLOSE event was enqueued and scheduler woke.
    assert len(queue.events) == 1, "TRADE_CLOSE event should be enqueued"
    event = queue.events[0]
    assert event["event_type"] == "TRADE_CLOSE", f"Wrong event: {event}"
    assert "trade_result" in event, "Event should have trade_result payload"
    assert event["trade_result"]["ticket"] == 42, "trade_result ticket mismatch"
    assert scheduler.wake_count == 1, "Scheduler should wake after event"


def test_trade_close_event_skipped_when_queue_none(monkeypatch: Any) -> None:
    """No queue supplied (legacy wiring) — close still runs, no event emitted."""
    import review.auto_trigger as at_mod
    from orchestration.runtime import _build_position_monitor

    monkeypatch.setattr(at_mod, "on_position_closed", lambda _tr: None)

    monitor = _build_position_monitor(event_queue=None, scheduler=None)
    if monitor is None:
        import pytest

        pytest.skip("PositionMonitor not available (optional dependency missing)")

    # Should not raise even without a queue/scheduler.
    monitor.close_detector.observe([_position(99)])
    monitor.close_detector.observe([])


if __name__ == "__main__":  # pragma: no cover
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
