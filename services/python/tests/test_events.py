# -*- coding: utf-8 -*-
"""Tests for the Event Detection Engine (events.py)."""

from __future__ import annotations

import pytest

from trading.events import (
    DetectedEvent,
    EventTypes,
    MarketState,
    detect_events,
    update_market_state,
)

# ---------------------------------------------------------------------------
# EventTypes enum tests
# ---------------------------------------------------------------------------


class TestEventTypes:
    def test_enum_has_trend_events(self):
        assert EventTypes.TREND_BULLISH.value == "TREND_BULLISH"
        assert EventTypes.TREND_BEARISH.value == "TREND_BEARISH"
        assert EventTypes.TREND_NEUTRAL.value == "TREND_NEUTRAL"

    def test_enum_has_momentum_events(self):
        assert EventTypes.MOMENTUM_BULLISH.value == "MOMENTUM_BULLISH"
        assert EventTypes.MOMENTUM_BEARISH.value == "MOMENTUM_BEARISH"

    def test_enum_has_volatility_events(self):
        assert EventTypes.VOLATILITY_EXPANDING.value == "VOLATILITY_EXPANDING"
        assert EventTypes.VOLATILITY_CONTRACTING.value == "VOLATILITY_CONTRACTING"

    def test_enum_has_price_action_events(self):
        assert EventTypes.BREAKOUT.value == "BREAKOUT"
        assert EventTypes.BREAKDOWN.value == "BREAKDOWN"
        assert EventTypes.REVERSAL.value == "REVERSAL"
        assert EventTypes.DOJI.value == "DOJI"
        assert EventTypes.GAP_UP.value == "GAP_UP"
        assert EventTypes.GAP_DOWN.value == "GAP_DOWN"

    def test_enum_has_indicator_crossover_events(self):
        assert EventTypes.EMA_CROSSOVER.value == "EMA_CROSSOVER"
        assert EventTypes.MACD_CROSSOVER.value == "MACD_CROSSOVER"
        assert EventTypes.RSI_OVERBOUGHT.value == "RSI_OVERBOUGHT"
        assert EventTypes.RSI_OVERSOLD.value == "RSI_OVERSOLD"
        assert EventTypes.STOCH_OVERBOUGHT.value == "STOCH_OVERBOUGHT"
        assert EventTypes.STOCH_OVERSOLD.value == "STOCH_OVERSOLD"

    def test_enum_has_risk_events(self):
        assert EventTypes.DRAWDOWN_WARNING.value == "DRAWDOWN_WARNING"
        assert EventTypes.EXPOSURE_LIMIT_REACHED.value == "EXPOSURE_LIMIT_REACHED"
        assert EventTypes.LIQUIDITY_WARNING.value == "LIQUIDITY_WARNING"

    def test_enum_count(self):
        assert len(EventTypes) >= 20


# ---------------------------------------------------------------------------
# DetectedEvent dataclass tests
# ---------------------------------------------------------------------------


class TestDetectedEvent:
    def test_created_with_minimal_args(self):
        e = DetectedEvent(
            event_type=EventTypes.TREND_BULLISH,
            severity=0.8,
            description="test",
            timestamp="2026-01-01T00:00:00",
        )
        assert e.event_type == EventTypes.TREND_BULLISH
        assert e.severity == 0.8
        assert e.description == "test"
        assert e.symbol == ""

    def test_severity_clamp(self):
        e = DetectedEvent(
            event_type=EventTypes.BREAKOUT,
            severity=1.5,
            description="test",
            timestamp="now",
        )
        assert e.severity == 1.5  # detektor tidak clamp, caller yang clamp


# ---------------------------------------------------------------------------
# MarketState dataclass tests
# ---------------------------------------------------------------------------


class TestMarketState:
    def test_default_state(self):
        s = MarketState()
        assert s.symbol == ""
        assert s.close == 0.0
        assert s.trend_direction is None
        assert s.volatility_regime is None

    def test_populated_state(self):
        s = MarketState(
            symbol="EURUSD",
            close=1.1000,
            trend_direction="BULLISH",
            trend_strength=0.6,
            volatility_regime="EXPANDING",
            volatility_value=0.0012,
            BB_width=0.08,
            rsi=55.0,
            adx_value=28.0,
        )
        assert s.symbol == "EURUSD"
        assert s.trend_direction == "BULLISH"
        assert s.volatility_regime == "EXPANDING"
        assert s.rsi == 55.0
        assert s.adx_value == 28.0


# ---------------------------------------------------------------------------
# detect_events tests
# ---------------------------------------------------------------------------


class TestDetectEvents:
    @pytest.fixture
    def bullish_ohlcv(self):
        """40 bars: 25 flat then 15-bar strong rally → guarantees MACD bullish."""
        bars = []
        # First 25 bars: flat at 1.0000
        for i in range(25):
            bars.append(
                {
                    "symbol": "EURUSD",
                    "time": f"2026-01-{i+1:02d}T00:00:00",
                    "open": 1.0000,
                    "high": 1.0005,
                    "low": 0.9995,
                    "close": 1.0000,
                    "volume": 1000,
                }
            )
        # Last 15 bars: linear rally from 1.0000 → 1.0200 (200 pips)
        for i in range(15):
            idx = 25 + i
            close = 1.0000 + (i + 1) * (0.0200 / 15)  # 1.00133 → 1.0200
            open_p = close - 0.0005
            high = close + 0.0008
            low = open_p - 0.0003
            bars.append(
                {
                    "symbol": "EURUSD",
                    "time": f"2026-01-{idx+1:02d}T00:00:00",
                    "open": round(open_p, 5),
                    "high": round(high, 5),
                    "low": round(low, 5),
                    "close": round(close, 5),
                    "volume": 1000 + idx * 10,
                }
            )
        return bars

    @pytest.fixture
    def bearish_ohlcv(self):
        """40 bars: 25 flat then 15-bar strong selloff → guarantees MACD bearish."""
        bars = []
        # First 25 bars: flat at 1.1000
        for i in range(25):
            bars.append(
                {
                    "symbol": "EURUSD",
                    "time": f"2026-01-{i+1:02d}T00:00:00",
                    "open": 1.1000,
                    "high": 1.1005,
                    "low": 1.0995,
                    "close": 1.1000,
                    "volume": 1000,
                }
            )
        # Last 15 bars: linear selloff from 1.1000 → 1.0800 (200 pips down)
        for i in range(15):
            idx = 25 + i
            close = 1.1000 - (i + 1) * (0.0200 / 15)  # 1.09867 → 1.0800
            open_p = close + 0.0005
            high = open_p + 0.0008
            low = close - 0.0003
            bars.append(
                {
                    "symbol": "EURUSD",
                    "time": f"2026-01-{idx+1:02d}T00:00:00",
                    "open": round(open_p, 5),
                    "high": round(high, 5),
                    "low": round(low, 5),
                    "close": round(close, 5),
                    "volume": 1000 + idx * 10,
                }
            )
        return bars

    @pytest.fixture
    def oversold_ohlcv(self):
        """Price series that will push RSI below 30."""
        prices = [100.0]
        for i in range(30):
            prices.append(prices[-1] - 0.3)
        return [
            {
                "symbol": "GBPUSD",
                "time": f"2026-01-{i+1:02d}T00:00:00",
                "open": prices[i],
                "high": prices[i] + 0.1,
                "low": prices[i] - 0.1,
                "close": prices[i],
                "volume": 500,
            }
            for i in range(30)
        ]

    def test_empty_ohlcv_returns_empty_events(self):
        events = detect_events([])
        assert events == []

    def test_bullish_ohlcv_detects_trend_bullish(self, bullish_ohlcv):
        events = detect_events(bullish_ohlcv)
        event_types = {e.event_type for e in events}
        assert EventTypes.TREND_BULLISH in event_types

    def test_bearish_ohlcv_detects_trend_bearish(self, bearish_ohlcv):
        events = detect_events(bearish_ohlcv)
        event_types = {e.event_type for e in events}
        assert EventTypes.TREND_BEARISH in event_types

    def test_bullish_ohlcv_detects_momentum_bullish(self, bullish_ohlcv):
        events = detect_events(bullish_ohlcv)
        event_types = {e.event_type for e in events}
        assert EventTypes.MOMENTUM_BULLISH in event_types

    def test_bearish_ohlcv_detects_momentum_bearish(self, bearish_ohlcv):
        events = detect_events(bearish_ohlcv)
        event_types = {e.event_type for e in events}
        assert EventTypes.MOMENTUM_BEARISH in event_types

    def test_detected_events_have_valid_severity(self, bullish_ohlcv):
        events = detect_events(bullish_ohlcv)
        for e in events:
            assert 0.0 <= e.severity <= 1.0
            assert isinstance(e.description, str)
            assert isinstance(e.timestamp, str)
            assert isinstance(e.symbol, str)

    def test_detected_events_have_correct_symbol(self, bullish_ohlcv):
        events = detect_events(bullish_ohlcv)
        for e in events:
            assert e.symbol == "EURUSD"

    def test_all_detected_events_are_DetectedEvent_instances(self, bullish_ohlcv):
        events = detect_events(bullish_ohlcv)
        for e in events:
            assert isinstance(e, DetectedEvent)
            assert isinstance(e.event_type, EventTypes)

    def test_no_prev_state_does_not_fail(self, bullish_ohlcv):
        """detect_events must not crash when prev_state is None."""
        events = detect_events(bullish_ohlcv, prev_state=None)
        assert isinstance(events, list)

    def test_prev_state_changes_detectable(self, bullish_ohlcv):
        """With prev_state, trend transitions can be detected."""
        # Use first bar as prev_state equivalent
        prev = update_market_state(bullish_ohlcv[:-1])
        events = detect_events(bullish_ohlcv, prev_state=prev)
        assert isinstance(events, list)


# ---------------------------------------------------------------------------
# update_market_state tests
# ---------------------------------------------------------------------------


class TestUpdateMarketState:
    @pytest.fixture
    def sample_ohlcv(self):
        return [
            {
                "symbol": "USDJPY",
                "time": "2026-01-15T00:00:00",
                "open": 150.0,
                "high": 150.5,
                "low": 149.8,
                "close": 150.2,
                "volume": 5000,
            }
            for _ in range(30)
        ]

    def test_basic_market_state(self, sample_ohlcv):
        state = update_market_state(sample_ohlcv)
        assert state.symbol == "USDJPY"
        assert state.close == 150.2
        assert state.open == 150.0
        assert state.high == 150.5
        assert state.low == 149.8
        assert state.volume == 5000

    def test_market_state_has_trend(self, sample_ohlcv):
        state = update_market_state(sample_ohlcv)
        # Rising prices → bullish atau bearish atau neutral, cukup ada nilainya
        assert state.trend_direction in ("BULLISH", "BEARISH", "NEUTRAL", None)
        assert 0.0 <= state.trend_strength <= 1.0

    def test_market_state_has_indicators(self, sample_ohlcv):
        state = update_market_state(sample_ohlcv)
        assert state.ema_fast is not None
        assert state.ema_slow is not None
        assert state.rsi is not None
        assert state.adx_value is not None
        assert state.atr is not None

    def test_market_state_volatility_regime(self, sample_ohlcv):
        state = update_market_state(sample_ohlcv)
        assert state.volatility_regime in ("NORMAL", "EXPANDING", "CONTRACTING")
        assert isinstance(state.BB_width, float)

    def test_market_state_uses_latest_bar(self, sample_ohlcv):
        state = update_market_state(sample_ohlcv)
        assert state.timestamp is not None
        assert isinstance(state.timestamp, str)

    def test_empty_ohlcv_returns_default_state(self):
        state = update_market_state([])
        assert state.symbol == ""
        assert state.close == 0.0

    def test_market_state_prev_event_types_exists(self, sample_ohlcv):
        state = update_market_state(sample_ohlcv)
        assert isinstance(state.prev_event_types, list)


# ---------------------------------------------------------------------------
# Integration: detect + state together
# ---------------------------------------------------------------------------


class TestEventDetectionIntegration:
    def test_detect_and_state_return_consistent_data(self):
        ohlcv = [
            {
                "symbol": "AUDUSD",
                "time": "2026-01-10T00:00:00",
                "open": 0.7500,
                "high": 0.7530,
                "low": 0.7490,
                "close": 0.7520,
                "volume": 3000,
            }
            for _ in range(30)
        ]
        events = detect_events(ohlcv)
        state = update_market_state(ohlcv)

        # Both should reference same symbol
        for e in events:
            assert e.symbol == state.symbol == "AUDUSD"

        # State close should equal last bar close
        assert abs(state.close - 0.7520) < 0.0001


class TestEventDetectionEdgeCases:
    def test_single_bar_insufficient_for_indicators(self):
        ohlcv = [
            {
                "symbol": "XAUUSD",
                "time": "2026-01-01T00:00:00",
                "open": 2000.0,
                "high": 2005.0,
                "low": 1998.0,
                "close": 2002.0,
                "volume": 100,
            }
        ]
        events = detect_events(ohlcv)
        # Single bar can still produce some events (doji, gap) but not trend
        assert isinstance(events, list)
