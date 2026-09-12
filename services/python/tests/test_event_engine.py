# -*- coding: utf-8 -*-
"""Test suite for Phase 5 EventEngine extensions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trading.event_engine import (
    EVENT_PRIORITY_MAP,
    EventDeduplicator,
    EventHistory,
    EventPriority,
    EventQueue,
)
from trading.events import DetectedEvent, EventDetector, EventTypes

# ---------------------------------------------------------------------------
# EventPriority enum tests
# ---------------------------------------------------------------------------


def test_event_priority_values():
    assert EventPriority.LOW.value == 1
    assert EventPriority.MEDIUM.value == 2
    assert EventPriority.HIGH.value == 3
    assert EventPriority.CRITICAL.value == 4


def test_event_priority_map_complete():
    # Ensure each EventTypes has a mapping entry.
    missing = [et for et in EventTypes if et not in EVENT_PRIORITY_MAP]
    assert missing == []


# ---------------------------------------------------------------------------
# EventQueue tests
# ---------------------------------------------------------------------------


def test_queue_enqueue_dequeue_priority_order():
    q = EventQueue(max_size=10)
    # Low‑priority event
    low = DetectedEvent(
        event_type=EventTypes.DOJI,
        severity=0.1,
        description="doji",
        timestamp="now",
    )
    # High‑priority event
    high = DetectedEvent(
        event_type=EventTypes.BREAKOUT,
        severity=0.9,
        description="breakout",
        timestamp="now",
    )
    q.enqueue(low)
    q.enqueue(high)
    # Dequeue should return high first
    first = q.dequeue()
    assert first.event_type == EventTypes.BREAKOUT
    second = q.dequeue()
    assert second.event_type == EventTypes.DOJI


def test_queue_max_size_eviction():
    q = EventQueue(max_size=2)
    e1 = DetectedEvent(EventTypes.DOJI, 0.1, "1", "t")
    e2 = DetectedEvent(EventTypes.BREAKOUT, 0.9, "2", "t")
    e3 = DetectedEvent(EventTypes.GAP_DOWN, 0.5, "3", "t")
    assert q.enqueue(e1)
    assert q.enqueue(e2)
    # Queue full, third enqueue returns False
    assert not q.enqueue(e3)
    # Dequeue two events, ensure they are the first two
    d1 = q.dequeue()
    d2 = q.dequeue()
    assert d1.event_type in (EventTypes.BREAKOUT, EventTypes.DOJI)
    assert d2.event_type in (EventTypes.DOJI, EventTypes.BREAKOUT)
    assert q.dequeue() is None


# ---------------------------------------------------------------------------
# EventHistory tests
# ---------------------------------------------------------------------------


def test_history_add_and_get_filters():
    h = EventHistory(max_size=5)
    base_time = datetime.now(timezone.utc)
    ev = DetectedEvent(EventTypes.DOJI, 0.1, "doji", base_time.isoformat(), "EURUSD")
    h.add(ev)
    # Retrieve by symbol
    res = h.get(symbol="EURUSD")
    assert len(res) == 1 and res[0].symbol == "EURUSD"
    # Retrieve by type
    res2 = h.get(event_type=EventTypes.DOJI)
    assert len(res2) == 1
    # Retrieve by time window
    later = base_time + timedelta(minutes=1)
    res3 = h.get(since=later)
    assert res3 == []


def test_history_eviction_and_counts():
    h = EventHistory(max_size=3)
    now = datetime.now(timezone.utc)
    types = [
        EventTypes.DOJI,
        EventTypes.BREAKOUT,
        EventTypes.GAP_UP,
        EventTypes.GAP_DOWN,
    ]
    for i, et in enumerate(types):
        e = DetectedEvent(et, 0.1, f"e{i}", (now + timedelta(seconds=i)).isoformat(), "SYMB")
        h.add(e)
    # Only last three should remain
    all_events = h.get(limit=10)
    assert len(all_events) == 3
    # Counts by type
    counts = h.get_counts_by_type()
    assert counts.get(EventTypes.DOJI, 0) == 0
    assert counts[EventTypes.BREAKOUT] == 1
    assert counts[EventTypes.GAP_UP] == 1
    assert counts[EventTypes.GAP_DOWN] == 1


# ---------------------------------------------------------------------------
# Deduplication tests
# ---------------------------------------------------------------------------


def test_deduplication_window_behaviour():
    dedup = EventDeduplicator(dedup_window=2)
    sym = "EURUSD"
    # First emission allowed
    assert dedup.should_emit(sym, EventTypes.DOJI, bar_index=0)
    # Same bar within window blocked
    assert not dedup.should_emit(sym, EventTypes.DOJI, bar_index=1)
    # Outside window allowed again
    assert dedup.should_emit(sym, EventTypes.DOJI, bar_index=3)


# ---------------------------------------------------------------------------
# Integration with EventDetector
# ---------------------------------------------------------------------------


def test_detector_routing_to_queue_and_history():
    dedup = EventDeduplicator(dedup_window=5)
    q = EventQueue(max_size=10)
    h = EventHistory(max_size=10)
    det = EventDetector(deduplicator=dedup, queue=q, history=h)
    # Minimal OHLCV to trigger at least one event
    ohlcv = [
        {
            "symbol": "EURUSD",
            "open": 1.0,
            "high": 1.1,
            "low": 0.9,
            "close": 1.0,
            "volume": 1000,
        }
    ]
    events = det.detect(ohlcv)
    assert isinstance(events, list) and len(events) >= 1
    # Queue should contain same events
    queued = q.peek()
    assert len(queued) == len(events)
    # History should contain same events
    hist = h.get()
    assert len(hist) == len(events)


# ---------------------------------------------------------------------------
# End of tests
# ---------------------------------------------------------------------------
