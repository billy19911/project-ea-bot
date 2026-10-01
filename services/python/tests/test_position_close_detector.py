# -*- coding: utf-8 -*-
"""Tests for the position-close detector (audit P1-6).

The learning loop needs a close event to run review → lesson, but no production
path closed a position. The detector observes successive open-position snapshots
and, when a ticket disappears, emits a synthetic close record and fires the
review hook — observation only, no orders.
"""

from __future__ import annotations

from monitoring.position_monitor import PositionMonitor
from review.close_detector import PositionCloseDetector


def test_disappeared_ticket_is_detected_as_close() -> None:
    reviews: list[dict] = []
    detector = PositionCloseDetector(on_close=lambda rec: reviews.append(rec))

    # First snapshot: two positions.
    detector.observe(
        [
            {"ticket": 1, "symbol": "EURUSD", "side": "BUY", "price_open": 1.1, "profit": 5.0},
            {"ticket": 2, "symbol": "XAUUSD", "side": "SELL", "price_open": 2000.0, "profit": -3.0},
        ]
    )
    assert reviews == []

    # Second snapshot: ticket 1 is gone → one close emitted.
    closed = detector.observe(
        [{"ticket": 2, "symbol": "XAUUSD", "side": "SELL", "price_open": 2000.0, "profit": -3.0}]
    )
    assert len(closed) == 1
    assert closed[0]["ticket"] == 1
    assert closed[0]["status"] == "CLOSED"
    assert len(reviews) == 1


def test_no_false_close_when_position_persists() -> None:
    reviews: list[dict] = []
    detector = PositionCloseDetector(on_close=lambda rec: reviews.append(rec))
    pos = [{"ticket": 7, "symbol": "EURUSD", "side": "BUY", "price_open": 1.1, "profit": 1.0}]
    detector.observe(pos)
    detector.observe(pos)
    detector.observe(pos)
    assert reviews == []


def test_hook_error_is_fail_safe() -> None:
    def boom(record):
        raise RuntimeError("review down")

    detector = PositionCloseDetector(on_close=boom)
    detector.observe([{"ticket": 1, "side": "BUY", "price_open": 1.0}])
    # Must not raise even though the hook does.
    closed = detector.observe([])
    assert len(closed) == 1


def test_monitor_feeds_close_detector() -> None:
    class _Connector:
        def __init__(self) -> None:
            self.positions = [{"ticket": 5, "symbol": "EURUSD", "side": "BUY", "price_open": 1.1}]

        def get_positions(self):
            return list(self.positions)

        def get_tick(self, symbol):
            return None

        def get_ohlc(self, symbol, timeframe, count):
            return []

    conn = _Connector()
    reviews: list[dict] = []
    detector = PositionCloseDetector(on_close=lambda rec: reviews.append(rec))
    monitor = PositionMonitor(mt5_connector=conn, close_detector=detector)

    monitor.monitor_all_positions()  # sees ticket 5
    conn.positions = []  # ticket 5 closed
    monitor.monitor_all_positions()  # detector fires

    assert len(reviews) == 1
    assert reviews[0]["ticket"] == 5


def test_monitor_without_detector_still_works() -> None:
    class _Connector:
        def get_positions(self):
            return []

        def get_tick(self, symbol):
            return None

        def get_ohlc(self, symbol, timeframe, count):
            return []

    monitor = PositionMonitor(mt5_connector=_Connector())
    assert monitor.monitor_all_positions() == []


def test_detector_fires_review_auto_trigger() -> None:
    """End-to-end: a disappeared ticket produces a ReviewRecord via the trigger."""
    from review.auto_trigger import ReviewAutoTrigger

    records: list = []
    trigger = ReviewAutoTrigger(on_review=lambda rec: records.append(rec))
    detector = PositionCloseDetector(on_close=trigger.on_position_closed)

    detector.observe(
        [{"ticket": 42, "symbol": "EURUSD", "side": "BUY", "price_open": 1.1, "profit": 10.0}]
    )
    detector.observe([])  # ticket 42 closed

    assert len(records) == 1
    assert records[0].trade_id == "42"


def test_close_record_carries_original_stop_loss() -> None:
    """The entry context's ORIGINAL stop-loss is bridged into the close record
    so the review can compute an honest R-multiple."""
    from review.auto_trigger import ReviewAutoTrigger
    from review.entry_context import clear_entry_contexts, remember_entry_context

    clear_entry_contexts()
    try:
        records: list = []
        trigger = ReviewAutoTrigger(on_review=lambda rec: records.append(rec))
        detector = PositionCloseDetector(on_close=trigger.on_position_closed)

        # Entry registers the original SL keyed by ticket.
        remember_entry_context(
            99,
            {
                "symbol": "XAUUSD",
                "entry_price": 2000.0,
                "stop_loss": 1990.0,
            },
        )
        detector.observe([{"ticket": 99, "symbol": "XAUUSD", "side": "BUY", "price_open": 2000.0}])
        closed = detector.observe([])

        assert closed[0]["stop_loss"] == 1990.0
        assert len(records) == 1
        # close_price falls back to price_open (2000) → exit == entry → 0R.
        assert records[0].r_multiple == 0.0
    finally:
        clear_entry_contexts()


def test_closed_at_is_true_utc_not_broker_wall() -> None:
    """`closed_at` must carry the TRUE UTC close instant (raw epoch − 3 h).

    The closing deal's ``time`` is a raw MT5 epoch — broker server wall clock
    rendered as UTC (measured +3 h vs true UTC). Rendering it with
    ``datetime.fromtimestamp(..., tz=utc)`` stamped the close 3 h in the
    future; the fix routes it through ``mt5.broker_time.from_broker_epoch``.
    """
    import importlib
    from datetime import datetime, timezone

    broker_time = importlib.import_module("mt5.broker_time")
    true_close = datetime(2026, 10, 1, 14, 30, 0, tzinfo=timezone.utc)
    raw = broker_time.to_broker_epoch(true_close)  # 17:30 broker wall

    def resolver(ticket):
        return {"price": 2001.5, "time": raw, "profit": 5.0, "ticket": 9001}

    detector = PositionCloseDetector(close_deal_resolver=resolver)
    detector.observe([{"ticket": 9001, "symbol": "XAUUSD", "side": "BUY", "price_open": 2000.0}])
    closed = detector.observe([])

    assert len(closed) == 1
    assert closed[0]["closed_at"] == true_close.isoformat()


if __name__ == "__main__":  # pragma: no cover
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
