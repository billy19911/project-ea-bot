# -*- coding: utf-8 -*-
"""Tests for external position-change detection (audit P2-2).

PositionMonitor must detect changes the system did not make itself: external
SL/TP modification, partial close, and unexpected disappearance.
"""

from __future__ import annotations

from monitoring.position_monitor import EventType, PositionMonitor


class _Connector:
    def __init__(self) -> None:
        self.positions: list[dict] = []

    def get_positions(self):
        return list(self.positions)

    def get_tick(self, symbol):
        return None

    def get_ohlc(self, symbol, timeframe, count):
        return []


def _pos(ticket=1, symbol="EURUSD", sl=1.0, tp=2.0, volume=0.1):
    return {
        "ticket": ticket,
        "symbol": symbol,
        "side": "BUY",
        "volume": volume,
        "price_open": 1.5,
        "price_current": 1.5,
        "profit": 0.0,
        "sl": sl,
        "tp": tp,
    }


def test_no_change_emits_nothing() -> None:
    conn = _Connector()
    monitor = PositionMonitor(mt5_connector=conn)
    conn.positions = [_pos()]
    assert monitor.detect_position_changes() == []
    assert monitor.detect_position_changes() == []


def test_external_sl_change_detected() -> None:
    conn = _Connector()
    monitor = PositionMonitor(mt5_connector=conn)
    conn.positions = [_pos(sl=1.0)]
    monitor.detect_position_changes()
    conn.positions = [_pos(sl=1.2)]  # external change
    events = monitor.detect_position_changes()
    assert any(e.event_type is EventType.SL_CHANGED for e in events)
    sl_event = next(e for e in events if e.event_type is EventType.SL_CHANGED)
    assert sl_event.metadata["old_sl"] == 1.0
    assert sl_event.metadata["new_sl"] == 1.2


def test_external_tp_change_detected() -> None:
    conn = _Connector()
    monitor = PositionMonitor(mt5_connector=conn)
    conn.positions = [_pos(tp=2.0)]
    monitor.detect_position_changes()
    conn.positions = [_pos(tp=2.5)]
    events = monitor.detect_position_changes()
    assert any(e.event_type is EventType.TP_CHANGED for e in events)


def test_partial_close_detected() -> None:
    conn = _Connector()
    monitor = PositionMonitor(mt5_connector=conn)
    conn.positions = [_pos(volume=0.5)]
    monitor.detect_position_changes()
    conn.positions = [_pos(volume=0.2)]  # partial close
    events = monitor.detect_position_changes()
    assert any(e.event_type is EventType.PARTIAL_CLOSE for e in events)
    pc = next(e for e in events if e.event_type is EventType.PARTIAL_CLOSE)
    assert pc.metadata["old_volume"] == 0.5
    assert pc.metadata["new_volume"] == 0.2


def test_disappearance_detected() -> None:
    conn = _Connector()
    monitor = PositionMonitor(mt5_connector=conn)
    conn.positions = [_pos(ticket=9)]
    monitor.detect_position_changes()
    conn.positions = []  # gone
    events = monitor.detect_position_changes()
    assert any(e.event_type is EventType.POSITION_DISAPPEARED for e in events)


def test_changes_reported_once() -> None:
    conn = _Connector()
    monitor = PositionMonitor(mt5_connector=conn)
    conn.positions = [_pos(sl=1.0)]
    monitor.detect_position_changes()
    conn.positions = [_pos(sl=1.3)]
    first = monitor.detect_position_changes()
    second = monitor.detect_position_changes()  # no further change
    assert any(e.event_type is EventType.SL_CHANGED for e in first)
    assert second == []


def test_detect_does_not_double_fire_close_detector() -> None:
    """detect_position_changes must not also feed the P1-6 close detector."""

    class _SpyDetector:
        def __init__(self) -> None:
            self.calls = 0

        def observe(self, positions):
            self.calls += 1
            return []

    spy = _SpyDetector()
    conn = _Connector()
    monitor = PositionMonitor(mt5_connector=conn, close_detector=spy)
    conn.positions = [_pos()]
    monitor.detect_position_changes()
    assert spy.calls == 0  # snapshot helper does not observe


if __name__ == "__main__":  # pragma: no cover
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
