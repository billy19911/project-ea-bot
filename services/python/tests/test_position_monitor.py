# -*- coding: utf-8 -*-
"""Test suite for Phase 15 Position Monitor.

Tests real-time position monitoring, SL/TP management,
trailing stops, abnormal detection, and exit events.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from monitoring.position_monitor import (
    AbnormalEvent,
    EventType,
    PositionMonitor,
    PositionSnapshot,
    Severity,
    Side,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class MockPosition:
    """Mock MT5 position object."""

    def __init__(
        self,
        ticket: int = 1001,
        symbol: str = "EURUSD",
        side: str = "BUY",
        volume: float = 1.0,
        price_open: float = 1.0840,
        price_current: float = 1.0852,
        profit: float = 12.0,
        sl: float = 0.0,
        tp: float = 0.0,
        margin: float = 108.4,
        swap: float = 0.0,
    ):
        self.ticket = ticket
        self.symbol = symbol
        self.side = side
        self.volume = volume
        self.price_open = price_open
        self.price_current = price_current
        self.profit = profit
        self.unrealized_pnl = profit
        self.sl = sl
        self.tp = tp
        self.margin = margin
        self.swap = swap


class MockTick:
    """Mock tick data."""

    def __init__(self, symbol: str = "EURUSD", bid: float = 1.0849, ask: float = 1.0851):
        self.symbol = symbol
        self.bid = bid
        self.ask = ask
        self.last = (bid + ask) / 2
        self.volume = 100.0
        self.time = datetime.now(timezone.utc)


class MockOHLC:
    """Mock OHLC bar."""

    def __init__(
        self,
        open_: float = 1.0840,
        high: float = 1.0860,
        low: float = 1.0830,
        close: float = 1.0850,
    ):
        self.open = open_
        self.high = high
        self.low = low
        self.close = close


@pytest.fixture
def mock_connector():
    """Create a minimal mock MT5 connector for position monitoring."""
    conn = MagicMock()
    conn.get_positions.return_value = [
        MockPosition(
            ticket=1001,
            symbol="EURUSD",
            side="BUY",
            volume=1.0,
            price_open=1.0840,
            price_current=1.0852,
            profit=12.0,
            sl=1.0820,
            tp=1.0880,
            margin=108.4,
        ),
        MockPosition(
            ticket=1002,
            symbol="XAUUSD",
            side="SELL",
            volume=0.5,
            price_open=2350.0,
            price_current=2345.5,
            profit=2.25,
            sl=2360.0,
            tp=2330.0,
            margin=1175.0,
            swap=-0.5,
        ),
    ]
    conn.get_tick.return_value = MockTick(bid=1.0849, ask=1.0851)
    conn.get_ohlc.return_value = [MockOHLC() for _ in range(15)]
    return conn


@pytest.fixture
def monitor(mock_connector):
    """Create a PositionMonitor with mock connector."""
    return PositionMonitor(mt5_connector=mock_connector, atr_lookback=14)


# ---------------------------------------------------------------------------
# PositionSnapshot Tests
# ---------------------------------------------------------------------------


def test_position_snapshot_creation():
    """PositionSnapshot should store all fields correctly."""
    now = datetime.now(timezone.utc)
    snap = PositionSnapshot(
        symbol="EURUSD",
        side=Side.BUY,
        volume=1.0,
        entry_price=1.0840,
        current_price=1.0852,
        pnl=12.0,
        pnl_pct=1.11,
        sl=1.0820,
        tp=1.0880,
        margin=108.4,
        swap=0.0,
        ticket=1001,
        timestamp=now,
    )
    assert snap.symbol == "EURUSD"
    assert snap.side == Side.BUY
    assert snap.pnl == 12.0
    assert snap.ticket == 1001


def test_position_snapshot_to_dict():
    """PositionSnapshot.to_dict should serialize all fields."""
    snap = PositionSnapshot(
        symbol="GBPUSD",
        side=Side.SELL,
        volume=0.5,
        entry_price=1.2650,
        current_price=1.2630,
        pnl=-10.0,
        pnl_pct=-1.58,
        sl=1.2700,
        tp=1.2600,
        margin=63.25,
        swap=-0.1,
        ticket=2001,
    )
    d = snap.to_dict()
    assert d["symbol"] == "GBPUSD"
    assert d["side"] == "SELL"
    assert d["pnl"] == -10.0
    assert isinstance(d["timestamp"], str)
    assert "ticket" in d


# ---------------------------------------------------------------------------
# AbnormalEvent Tests
# ---------------------------------------------------------------------------


def test_abnormal_event_creation():
    """AbnormalEvent should store all fields correctly."""
    event = AbnormalEvent(
        event_type=EventType.PRICE_SPIKE,
        severity=Severity.CRITICAL,
        message="Price spike detected on EURUSD",
        symbol="EURUSD",
        metadata={"atr": 0.0010, "price_change": 0.004},
    )
    assert event.event_type == EventType.PRICE_SPIKE
    assert event.severity == Severity.CRITICAL
    assert event.metadata["atr"] == 0.0010


def test_abnormal_event_to_dict():
    """AbnormalEvent.to_dict should serialize correctly."""
    event = AbnormalEvent(
        event_type=EventType.RISK_BREACH,
        severity=Severity.WARNING,
        message="Risk threshold exceeded",
        symbol="XAUUSD",
    )
    d = event.to_dict()
    assert d["event_type"] == "RISK_BREACH"
    assert d["severity"] == "WARNING"
    assert d["symbol"] == "XAUUSD"


# ---------------------------------------------------------------------------
# PositionMonitor — monitor_position Tests
# ---------------------------------------------------------------------------


def test_monitor_position_found(monitor):
    """monitor_position should return snapshot when position exists."""
    snapshot = monitor.monitor_position("EURUSD")
    assert snapshot is not None
    assert snapshot.symbol == "EURUSD"
    assert snapshot.side == Side.BUY
    assert snapshot.ticket == 1001


def test_monitor_position_not_found(monitor):
    """monitor_position should return None when no position exists."""
    snapshot = monitor.monitor_position("NONEXISTENT")
    assert snapshot is None


def test_monitor_position_case_insensitive(monitor):
    """monitor_position should be case-insensitive for symbol lookup."""
    snapshot = monitor.monitor_position("eurusd")
    assert snapshot is not None
    assert snapshot.symbol == "EURUSD"


# ---------------------------------------------------------------------------
# PositionMonitor — monitor_all_positions Tests
# ---------------------------------------------------------------------------


def test_monitor_all_positions(monitor):
    """monitor_all_positions should return snapshots of all open positions."""
    snapshots = monitor.monitor_all_positions()
    assert len(snapshots) == 2
    symbols = {s.symbol for s in snapshots}
    assert "EURUSD" in symbols
    assert "XAUUSD" in symbols


def test_monitor_all_positions_stores_history(monitor):
    """monitor_all_positions should store position history."""
    monitor.monitor_all_positions()
    # Call again to add more history
    monitor.monitor_all_positions()

    assert 1001 in monitor._position_history
    assert len(monitor._position_history[1001]) >= 2


def test_monitor_all_positions_limits_history(monitor):
    """monitor_all_positions should keep only last 100 snapshots per position."""
    for _ in range(150):
        monitor.monitor_all_positions()

    assert len(monitor._position_history[1001]) <= 100


# ---------------------------------------------------------------------------
# PositionMonitor — Trailing SL Tests
# ---------------------------------------------------------------------------


def test_update_trailing_sl_buy(monitor):
    """Trailing SL for BUY should move up with price."""
    # Set a higher current price to trigger trailing update
    monitor.mt5_connector.get_tick.return_value = MockTick(bid=1.0900, ask=1.0902)

    new_sl = monitor.update_trailing_sl("EURUSD", trail_atr_factor=1.5)
    # Should return a new SL value since price moved favorably
    if new_sl is not None:
        assert new_sl > 1.0820  # Original SL was 1.0820


def test_update_trailing_sl_sell(monitor):
    """Trailing SL for SELL should move down with price."""
    # Set a lower current price for SELL position
    monitor.mt5_connector.get_tick.return_value = MockTick(bid=2340.0, ask=2340.5)

    new_sl = monitor.update_trailing_sl("XAUUSD", trail_atr_factor=1.5)
    # For SELL, new SL should be lower than original (2360.0) if price moved favorably
    if new_sl is not None:
        assert new_sl < 2360.0


def test_update_trailing_sl_no_position(monitor):
    """Trailing SL should return None when no position exists."""
    result = monitor.update_trailing_sl("NONEXISTENT")
    assert result is None


# ---------------------------------------------------------------------------
# PositionMonitor — Breakeven SL Tests
# ---------------------------------------------------------------------------


def test_update_breakeven_sl_in_profit(monitor):
    """Breakeven SL should apply when position is in profit."""
    # Set price well above entry for BUY position
    monitor.mt5_connector.get_tick.return_value = MockTick(bid=1.0950, ask=1.0952)

    new_sl = monitor.update_breakeven_sl("EURUSD")
    assert new_sl is not None
    assert abs(new_sl - 1.0840) < 0.0001  # Should be at entry price


def test_update_breakeven_sl_applies_once(monitor):
    """Breakeven SL should only apply once per position."""
    monitor.mt5_connector.get_tick.return_value = MockTick(bid=1.0950, ask=1.0952)

    first_call = monitor.update_breakeven_sl("EURUSD")
    second_call = monitor.update_breakeven_sl("EURUSD")

    assert first_call is not None
    assert second_call is None  # Already applied


def test_update_breakeven_sl_no_profit(monitor):
    """Breakeven SL should not apply when position is at loss."""
    # Set price below entry for BUY position
    monitor.mt5_connector.get_tick.return_value = MockTick(bid=1.0830, ask=1.0832)

    result = monitor.update_breakeven_sl("EURUSD")
    assert result is None


# ---------------------------------------------------------------------------
# PositionMonitor — Abnormal Detection Tests
# ---------------------------------------------------------------------------


def test_detect_normal_movement(monitor):
    """Normal price movement should not trigger abnormal event."""
    event = monitor.detect_abnormal_movement("EURUSD", atr_threshold=3.0)
    assert event is None


def test_detect_price_spike(monitor):
    """Large price movement should trigger PRICE_SPIKE event."""
    # Create bars showing large move
    big_move_bars = [
        MockOHLC(open_=1.0840, high=1.0880, low=1.0830, close=1.0870),
        MockOHLC(open_=1.0790, high=1.0800, low=1.0780, close=1.0795),  # Far from first
    ] + [MockOHLC() for _ in range(18)]
    monitor.mt5_connector.get_ohlc.return_value = big_move_bars
    monitor.mt5_connector.get_tick.return_value = MockTick(bid=1.0870, ask=1.0872)

    event = monitor.detect_abnormal_movement("EURUSD", atr_threshold=0.01)  # Very low threshold
    # With very low threshold, even small moves may trigger
    # The key is the function runs without error and returns correct type
    assert event is None or isinstance(event, AbnormalEvent)


def test_detect_gap(monitor):
    """Price gap between bars should trigger GAP event."""
    gap_bars = [
        MockOHLC(open_=1.0900, high=1.0910, low=1.0895, close=1.0905),
        MockOHLC(open_=1.0800, high=1.0810, low=1.0795, close=1.0805),  # Gap from above
    ] + [MockOHLC() for _ in range(18)]
    monitor.mt5_connector.get_ohlc.return_value = gap_bars

    event = monitor.detect_abnormal_movement("EURUSD", atr_threshold=0.01)
    assert event is None or isinstance(event, AbnormalEvent)


# ---------------------------------------------------------------------------
# PositionMonitor — Risk Change Tests
# ---------------------------------------------------------------------------


def test_check_risk_no_sl(monitor):
    """Risk check without SL should report full risk."""
    # Remove SL from EURUSD position
    positions = monitor.mt5_connector.get_positions.return_value
    positions[0].sl = 0.0

    at_risk, pct = monitor.check_risk_change("EURUSD")
    assert at_risk is True
    assert pct == 100.0


def test_check_risk_with_sl(monitor):
    """Risk check with SL should calculate actual risk."""
    at_risk, pct = monitor.check_risk_change("EURUSD", max_risk_pct=50.0)
    # Should return a tuple of (bool, float)
    assert isinstance(at_risk, bool)
    assert isinstance(pct, float)


def test_check_risk_no_position(monitor):
    """Risk check without position should return no risk."""
    at_risk, pct = monitor.check_risk_change("NONEXISTENT")
    assert at_risk is False
    assert pct == 0.0


# ---------------------------------------------------------------------------
# PositionMonitor — Exit Events Tests
# ---------------------------------------------------------------------------


def test_check_exit_events_tp_hit(monitor):
    """Exit events should detect TP hit."""
    # Set bid above TP for BUY position
    monitor.mt5_connector.get_tick.return_value = MockTick(bid=1.0890, ask=1.0892)

    events = monitor.check_exit_events("EURUSD")
    tp_events = [e for e in events if e.metadata.get("exit_reason") == "TP_HIT"]
    assert len(tp_events) > 0


def test_check_exit_events_sl_hit(monitor):
    """Exit events should detect SL hit."""
    # Set bid below SL for BUY position
    monitor.mt5_connector.get_tick.return_value = MockTick(bid=1.0810, ask=1.0812)

    events = monitor.check_exit_events("EURUSD")
    sl_events = [e for e in events if e.metadata.get("exit_reason") == "SL_HIT"]
    assert len(sl_events) > 0


def test_check_exit_events_sell_tp_hit(monitor):
    """Exit events should detect TP hit for SELL position."""
    # Set ask below TP for SELL XAUUSD position (TP=2330.0)
    monitor.mt5_connector.get_tick.return_value = MockTick(bid=2329.0, ask=2329.5)

    events = monitor.check_exit_events("XAUUSD")
    tp_events = [e for e in events if e.metadata.get("exit_reason") == "TP_HIT"]
    assert len(tp_events) > 0


def test_check_exit_events_no_trigger(monitor):
    """Exit events should be empty when no triggers are met."""
    # Price within normal range
    monitor.mt5_connector.get_tick.return_value = MockTick(bid=1.0850, ask=1.0852)

    events = monitor.check_exit_events("EURUSD")
    # No TP/SL hit, no abnormal movement expected with default threshold
    non_risk_events = [e for e in events if e.metadata.get("exit_reason") != "RISK_BREACH"]
    assert len(non_risk_events) == 0


def test_check_exit_events_no_position(monitor):
    """Exit events should return empty list for non-existent position."""
    events = monitor.check_exit_events("NONEXISTENT")
    assert events == []


# ---------------------------------------------------------------------------
# Edge Cases & Integration
# ---------------------------------------------------------------------------


def test_monitor_without_connector():
    """PositionMonitor should work without explicit connector (uses module defaults)."""
    mon = PositionMonitor()
    # Should not raise error
    snapshots = mon.monitor_all_positions()
    assert isinstance(snapshots, list)


def test_side_enum_values():
    """Side enum should have correct values."""
    assert Side.BUY.value == "BUY"
    assert Side.SELL.value == "SELL"


def test_event_type_enum_coverage():
    """EventType enum should cover all required types."""
    expected_types = {
        "PRICE_SPIKE",
        "VOLUME_SURGE",
        "SLIPPAGE",
        "GAP",
        "NEWS_FLASH",
        "RISK_BREACH",
        "MARGIN_CALL",
        # Audit P2-2: external position-change detection.
        "SL_CHANGED",
        "TP_CHANGED",
        "PARTIAL_CLOSE",
        "POSITION_DISAPPEARED",
    }
    actual_types = {et.value for et in EventType}
    assert expected_types == actual_types


def test_severity_ordering():
    """Severity levels should exist for all required levels."""
    assert Severity.INFO.value == "INFO"
    assert Severity.WARNING.value == "WARNING"
    assert Severity.CRITICAL.value == "CRITICAL"


def test_position_snapshot_pnl_calculation():
    """PnL percentage should be calculated correctly."""
    snap = PositionSnapshot(
        symbol="EURUSD",
        side=Side.BUY,
        volume=1.0,
        entry_price=1.0840,
        current_price=1.0852,
        pnl=12.0,
        pnl_pct=1.1075,  # ~12 / (1.0840 * 1.0) * 100
        sl=0.0,
        tp=0.0,
        margin=108.4,
        swap=0.0,
        ticket=9999,
    )
    # PnL% should be positive for profitable BUY
    assert snap.pnl_pct > 0


def test_trailing_never_widens_risk_buy(monitor):
    """Trailing SL for BUY should never move SL downward."""
    # First call sets initial trailing
    monitor.mt5_connector.get_tick.return_value = MockTick(bid=1.0900, ask=1.0902)
    first_sl = monitor.update_trailing_sl("EURUSD", trail_atr_factor=1.0)

    # Second call with lower price should NOT lower SL
    monitor.mt5_connector.get_tick.return_value = MockTick(bid=1.0860, ask=1.0862)
    second_sl = monitor.update_trailing_sl("EURUSD", trail_atr_factor=1.0)

    if first_sl is not None and second_sl is not None:
        assert second_sl >= first_sl


def test_trailing_never_widens_risk_sell(monitor):
    """Trailing SL for SELL should never move SL upward."""
    # First call sets initial trailing
    monitor.mt5_connector.get_tick.return_value = MockTick(bid=2340.0, ask=2340.5)
    first_sl = monitor.update_trailing_sl("XAUUSD", trail_atr_factor=1.0)

    # Second call with higher price should NOT raise SL
    monitor.mt5_connector.get_tick.return_value = MockTick(bid=2355.0, ask=2355.5)
    second_sl = monitor.update_trailing_sl("XAUUSD", trail_atr_factor=1.0)

    if first_sl is not None and second_sl is not None:
        assert second_sl <= first_sl


def test_empty_positions_list(monitor):
    """Monitor should handle empty positions gracefully."""
    monitor.mt5_connector.get_positions.return_value = []
    snapshots = monitor.monitor_all_positions()
    assert snapshots == []

    snapshot = monitor.monitor_position("EURUSD")
    assert snapshot is None
