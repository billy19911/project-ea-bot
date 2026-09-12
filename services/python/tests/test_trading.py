# -*- coding: utf-8 -*-
"""Tests for the deterministic trading engine."""

from __future__ import annotations

import pytest

from trading.engine import SignalType, TradingEngine, TradingSignal
from trading.indicators import adx, atr, bollinger_bands, ema, macd, rsi, sma
from trading.position_sizing import atr_position_size
from trading.risk import max_drawdown

# ---------------------------------------------------------------------------
# SMA tests
# ---------------------------------------------------------------------------


class TestSMA:
    def test_basic_sma(self):
        """Test basic SMA calculation."""
        prices = [101.0, 102.0, 103.0, 104.0, 105.0]
        result = sma(prices, period=3)
        assert result is not None
        # SMA of last 3: (103 + 104 + 105) / 3 = 104.0
        assert abs(result - 104.0) < 0.001

    def test_sma_insufficient_data(self):
        """Test SMA with insufficient data."""
        prices = [100.0, 101.0]
        result = sma(prices, period=3)
        assert result is None

    def test_sma_single_data_point(self):
        """Test SMA with single data point."""
        prices = [100.0]
        result = sma(prices, period=1)
        assert result == 100.0


# ---------------------------------------------------------------------------
# EMA tests
# ---------------------------------------------------------------------------


class TestEMA:
    def test_basic_ema(self):
        """Test basic EMA calculation (returns latest value as float)."""
        prices = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0]
        result = ema(prices, period=5)
        assert result is not None
        assert result > 100.0
        assert result < 106.0

    def test_ema_insufficient_data(self):
        """Test EMA with insufficient data."""
        prices = [100.0, 101.0]
        result = ema(prices, period=5)
        assert result is None

    def test_ema_returns_float(self):
        """Test that ema() returns a float, not a list."""
        prices = [100.0, 101.0, 102.0, 103.0, 104.0]
        result = ema(prices, period=3)
        assert isinstance(result, float)
        assert result > 0.0


# ---------------------------------------------------------------------------
# RSI tests
# ---------------------------------------------------------------------------


class TestRSI:
    def test_rsi_bullish_momentum(self):
        """Test RSI with bullish momentum."""
        prices = [100.0, 102.0, 101.0, 103.0, 102.0, 104.0, 103.0, 105.0]
        result = rsi(prices, period=5)
        assert result is not None
        assert result > 50.0  # Bullish momentum

    def test_rsi_bearish_momentum(self):
        """Test RSI with bearish momentum."""
        prices = [100.0, 98.0, 99.0, 97.0, 98.0, 96.0, 97.0, 95.0]
        result = rsi(prices, period=5)
        assert result is not None
        assert result < 50.0

    def test_rsi_value_range(self):
        """Test that RSI is always between 0 and 100."""
        prices = [100.0, 99.0, 101.0, 98.0, 102.0, 97.0, 103.0, 96.0, 104.0, 95.0]
        result = rsi(prices, period=5)
        assert result is not None
        assert 0 <= result <= 100

    def test_rsi_returns_float(self):
        """RSI returns Optional[float], not a list."""
        prices = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
        result = rsi(prices, period=3)
        assert result is None or isinstance(result, float)


# ---------------------------------------------------------------------------
# MACD tests
# ---------------------------------------------------------------------------


class TestMACD:
    def test_macd_basic(self):
        """Test basic MACD calculation — returns MACDResult dataclass."""
        prices = [100.0] * 50
        prices[0:10] = [110.0, 109.0, 108.0, 109.0, 110.0, 111.0, 110.0, 109.0, 110.0, 111.0]
        result = macd(prices, fast_period=8, slow_period=17, signal_period=9)
        assert result is not None
        # MACDResult has macd_line, signal_line, histogram attributes
        assert hasattr(result, "macd_line")
        assert hasattr(result, "signal_line")
        assert hasattr(result, "histogram")

    def test_macd_insufficient_data(self):
        """Test MACD with insufficient data."""
        prices = [100.0] * 20
        result = macd(prices, fast_period=8, slow_period=17, signal_period=9)
        assert result is None


# ---------------------------------------------------------------------------
# ATR tests
# ---------------------------------------------------------------------------


class TestATR:
    def test_atr_basic(self):
        """Test basic ATR calculation."""
        highs = [101.0, 102.0, 103.0, 104.0, 105.0]
        lows = [100.0, 101.0, 102.0, 103.0, 104.0]
        closes = [100.5, 101.5, 102.5, 103.5, 104.5]
        result = atr(highs, lows, closes, period=3)
        assert result is not None
        assert result > 0

    def test_atr_insufficient_data(self):
        """Test ATR with insufficient data."""
        highs = [100.0]
        lows = [99.0]
        closes = [99.5]
        result = atr(highs, lows, closes, period=3)
        assert result is None


# ---------------------------------------------------------------------------
# ADX tests
# ---------------------------------------------------------------------------


class TestADX:
    def test_adx_basic(self):
        """Test basic ADX calculation."""
        highs = [
            101.0,
            102.0,
            103.0,
            104.0,
            105.0,
            106.0,
            107.0,
            108.0,
            109.0,
            110.0,
            111.0,
            112.0,
            113.0,
            114.0,
            115.0,
            116.0,
        ]
        lows = [
            100.0,
            101.0,
            102.0,
            103.0,
            104.0,
            105.0,
            106.0,
            107.0,
            108.0,
            109.0,
            110.0,
            111.0,
            112.0,
            113.0,
            114.0,
            115.0,
        ]
        closes = [
            100.5,
            101.5,
            102.5,
            103.5,
            104.5,
            105.5,
            106.5,
            107.5,
            108.5,
            109.5,
            110.5,
            111.5,
            112.5,
            113.5,
            114.5,
            115.5,
        ]
        result = adx(highs, lows, closes, period=3)
        assert result is not None
        assert result >= 0.0
        assert result <= 100.0

    def test_adx_insufficient_data(self):
        """Test ADX with insufficient data."""
        highs = [100.0]
        lows = [99.0]
        closes = [99.5]
        result = adx(highs, lows, closes, period=3)
        assert result is None

    def test_adx_no_trend(self):
        """Test ADX in ranging market (lower values)."""
        highs = [100.0] * 30
        lows = [99.0] * 30
        closes = [99.5] * 30
        result = adx(highs, lows, closes, period=5)
        assert result is not None
        assert result < 20

    def test_adx_constant_prices(self):
        """Test ADX with constant prices — returns None (undefined for flat markets)."""
        highs = [100.0] * 30
        lows = [100.0] * 30
        closes = [100.0] * 30
        result = adx(highs, lows, closes, period=14)
        # ADX is undefined when there's no price movement (all TR = 0)
        assert result is None


# ---------------------------------------------------------------------------
# Bollinger & Stochastic tests
# ---------------------------------------------------------------------------


class TestBollinger:
    def test_bollinger_bands(self):
        """Test Bollinger Bands calculation."""
        prices = [
            100.0,
            101.0,
            102.0,
            103.0,
            104.0,
            105.0,
            106.0,
            107.0,
            108.0,
            109.0,
            110.0,
            111.0,
            112.0,
            113.0,
            114.0,
            115.0,
            116.0,
            117.0,
            118.0,
            119.0,
            120.0,
            121.0,
            122.0,
            123.0,
            124.0,
        ]
        result = bollinger_bands(prices, period=20, num_std=2.0)
        assert result is not None
        assert result.upper > result.middle > result.lower


# ---------------------------------------------------------------------------
# Trading engine tests
# ---------------------------------------------------------------------------


class TestTradingEngine:
    def test_engine_initialization(self):
        """Test engine initialization."""
        engine = TradingEngine()
        assert engine.config is not None
        assert "fast_ema_period" in engine.config

    def test_signal_generation_with_30_bars(self):
        """Test engine.generate_signal with 30 OHLC bars.

        Must not error and return TradingSignal.
        """
        engine = TradingEngine()
        # Generate 30 bars of synthetic OHLC data (list of dicts)
        ohlc_data = [
            {
                "open": 100.0 + i * 0.5,
                "high": 101.0 + i * 0.5,
                "low": 99.0 + i * 0.5,
                "close": 100.5 + i * 0.5,
            }
            for i in range(30)
        ]
        signal = engine.generate_signal(ohlc_data, account_equity=10000.0)
        assert isinstance(signal, TradingSignal)
        assert signal.signal_type in (SignalType.BUY, SignalType.SELL, SignalType.HOLD)

    def test_signal_generation_with_float_list(self):
        """Test signal with list of floats (close prices only)."""
        engine = TradingEngine()
        prices = [100.0 + i * 0.3 for i in range(30)]
        signal = engine.generate_signal(prices, account_equity=10000.0)
        assert isinstance(signal, TradingSignal)

    def test_signal_hold_when_insufficient_data(self):
        """Test HOLD when not enough bars."""
        engine = TradingEngine()
        prices = [100.0, 101.0, 102.0]  # Too few for default config
        signal = engine.generate_signal(prices, account_equity=10000.0)
        assert signal.signal_type == SignalType.HOLD
        assert signal.confidence == 0.0

    def test_signal_with_ohlc_dict(self):
        """Test signal generation with OHLC as list of dicts."""
        engine = TradingEngine()
        ohlc_data = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5},
        ]
        signal = engine.generate_signal(ohlc_data, account_equity=10000.0)
        assert isinstance(signal, TradingSignal)

    def test_signal_with_ohlc_tuple_list(self):
        """Test signal generation with OHLC as list of tuples."""
        engine = TradingEngine()
        ohlc_data = [
            [100.0, 101.0, 99.0, 100.5],
        ]
        signal = engine.generate_signal(ohlc_data, account_equity=10000.0)
        assert isinstance(signal, TradingSignal)

    def test_empty_ohlc_raises(self):
        """Test that empty OHLC data raises ValueError."""
        engine = TradingEngine()
        with pytest.raises(ValueError):
            engine.generate_signal([])

    def test_backtest_evaluation(self):
        """Test backtest evaluation."""
        engine = TradingEngine()
        trades = [
            [100.0, 102.0, 1, 1.0],  # Long profit
            [103.0, 105.0, 1, 1.0],  # Long profit
            [104.0, 103.0, -1, 1.0],  # Short profit
        ]
        results = engine.evaluate_backtest(trades, initial_equity=10000.0)
        assert results is not None
        assert "return" in results
        assert "profit_factor" in results


# ---------------------------------------------------------------------------
# Position sizing tests
# ---------------------------------------------------------------------------


class TestPositionSizing:
    def test_atr_position_size_valid(self):
        """Test atr_position_size with valid inputs."""
        size = atr_position_size(
            account_equity=10000.0,
            risk_percent=2.0,
            atr_value=1.5,
            atr_multiplier=2.0,
        )
        assert size is not None
        assert size > 0
        # Expected: 10000 * 0.02 / (1.5 * 2.0) = 200 / 3.0 = 66.666...
        expected = 10000.0 * 0.02 / (1.5 * 2.0)
        assert abs(size - expected) < 0.01

    def test_atr_position_size_zero_atr(self):
        """Test atr_position_size with zero ATR returns None."""
        size = atr_position_size(
            account_equity=10000.0,
            risk_percent=2.0,
            atr_value=0.0,
            atr_multiplier=2.0,
        )
        assert size is None

    def test_atr_position_size_zero_equity(self):
        """Test atr_position_size with zero equity returns None."""
        size = atr_position_size(
            account_equity=0.0,
            risk_percent=2.0,
            atr_value=1.5,
            atr_multiplier=2.0,
        )
        assert size is None

    def test_atr_position_size_negative_risk(self):
        """Test atr_position_size with negative risk returns None."""
        size = atr_position_size(
            account_equity=10000.0,
            risk_percent=-1.0,
            atr_value=1.5,
            atr_multiplier=2.0,
        )
        assert size is None


# ---------------------------------------------------------------------------
# Risk metrics tests
# ---------------------------------------------------------------------------


class TestRiskMetrics:
    def test_max_drawdown_basic(self):
        """Test max_drawdown with a simple equity curve."""
        curve = [10000.0, 10500.0, 10200.0, 11000.0, 10800.0, 11500.0]
        dd = max_drawdown(curve)
        assert dd >= 0.0
        assert dd <= 100.0
        # Peak 11500, trough after peak: 10800 → drawdown = (11500-10800)/11500 = 6.09%
        # But actually: peak at 10500, trough 10200 → (10500-10200)/10500 = 2.86%
        # Then peak 11000, trough 10800 → (11000-10800)/11000 = 1.82%
        # Max DD = 2.86%
        assert abs(dd - 2.857) < 0.1

    def test_max_drawdown_empty(self):
        """Test max_drawdown with empty curve returns 0.0."""
        assert max_drawdown([]) == 0.0

    def test_max_drawdown_single_element(self):
        """Test max_drawdown with single element returns 0.0."""
        assert max_drawdown([10000.0]) == 0.0

    def test_max_drawdown_steady_decline(self):
        """Test max_drawdown with steady decline."""
        curve = [10000.0, 9000.0, 8000.0, 7000.0]
        dd = max_drawdown(curve)
        # Peak 10000, final 7000 → (10000-7000)/10000 = 30%
        assert abs(dd - 30.0) < 0.1

    def test_max_drawdown_gain_only(self):
        """Test max_drawdown with only gains returns 0.0."""
        curve = [10000.0, 11000.0, 12000.0, 13000.0]
        dd = max_drawdown(curve)
        assert dd == 0.0
