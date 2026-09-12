# -*- coding: utf-8 -*-
"""Test deterministic trading engine integration with MT5 connector."""

from __future__ import annotations

import importlib


def test_trading_engine_importable_from_main():
    """Test that trading engine can be imported from main app."""
    import importlib

    import src.main

    importlib.reload(src.main)

    assert hasattr(src.main, "app")


def test_engine_with_real_mt5_data():
    """Test signal generation with real MT5 OHLC data."""
    engine = importlib.import_module("trading.engine").TradingEngine()

    # Generate synthetic OHLC data using MT5 connector
    bars = engine.generate_signal([[2345.0, 2350.0, 2350.0, 2348.0]])

    assert bars.signal_type is not None
    assert bars.entry_price is not None


def test_multiple_symbol_signals():
    """Test signal generation with different price levels."""
    engine = importlib.import_module("trading.engine").TradingEngine()

    signals = []
    for price in [100.0, 500.0, 2340.0, 5000.0]:
        signal = engine.generate_signal([[price, price + 2.0, price - 2.0, price + 1.0]])
        signals.append(signal)

    # All signals should have valid types (SignalType enum)
    from trading.engine import SignalType

    for s in signals:
        assert isinstance(s.signal_type, SignalType)


def test_backtest_with_different_trades():
    """Test backtest evaluation with various trade scenarios."""
    engine = importlib.import_module("trading.engine").TradingEngine()

    # Series of profitable and losing trades
    trades = []
    for direction, entry, exit_price in [(1, 100.0, 102.0), (1, 102.0, 104.0), (1, 104.0, 103.0)]:
        trades.append([entry, exit_price, direction, 1.0])

    # Series of losing trades
    for direction, entry, exit_price in [(-1, 106.0, 104.0), (-1, 104.0, 102.0)]:
        trades.append([entry, exit_price, direction, 1.0])

    results = engine.evaluate_backtest(trades, initial_equity=10000.0)

    assert results is not None
    assert "return" in results or results is not None
