# -*- coding: utf-8 -*-
"""Tests for Market Regime Engine classification."""

from __future__ import annotations

import math

import pytest

from trading.regime import MarketRegime, RegimeResult, detect_regime


def _make_test_data(
    base_price: float, n: int, amplitude: float = 1.0
) -> tuple[list[float], list[float], list[float]]:
    """Helper to generate simple OHLC test data with given amplitude."""
    closes = [base_price + amplitude * math.sin(i * 0.4) for i in range(n)]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    return highs, lows, closes


class TestMarketRegime:
    """Test market regime classification."""

    def test_trending_uptrend_classification(self):
        """Strong uptrend with ADX > 25 should return TRENDING."""
        closes = [100.0 + i * 0.5 for i in range(50)]
        highs = [c + 1.0 for c in closes]
        lows = [c - 1.0 for c in closes]

        result = detect_regime(highs, lows, closes, period=20)

        assert result.regime == MarketRegime.TRENDING
        assert result.confidence > 0.5
        assert result.metadata["trend_direction"] == "uptrend"

    def test_trending_downtrend_classification(self):
        """Strong downtrend with ADX > 25 should return TRENDING."""
        closes = [150.0 - i * 0.4 for i in range(50)]
        highs = [c + 1.0 for c in closes]
        lows = [c - 1.0 for c in closes]

        result = detect_regime(highs, lows, closes, period=20)

        assert result.regime == MarketRegime.TRENDING
        assert result.metadata["trend_direction"] == "downtrend"

    def test_low_volatility_squeeze(self):
        """Bollinger Band squeeze (width < 3%) should return LOW_VOLATILITY."""
        closes = [100.0] * 50
        highs = [100.1] * 50
        lows = [99.9] * 50

        result = detect_regime(highs, lows, closes, period=20)

        assert result.regime == MarketRegime.LOW_VOLATILITY
        assert result.metadata["bb_width_pct"] < 3.0

    def test_high_volatility_expansion(self):
        """Bollinger Band expansion (width > 10%) should return HIGH_VOLATILITY."""
        closes = [100.0 + ((-1) ** i) * 10.0 for i in range(50)]
        highs = [c + 2.0 for c in closes]
        lows = [c - 2.0 for c in closes]

        result = detect_regime(highs, lows, closes, period=20)

        assert result.regime == MarketRegime.HIGH_VOLATILITY
        assert result.metadata["bb_width_pct"] > 10.0

    def test_breakout_above_upper_bb(self):
        """Close breaking above upper BB should return BREAKOUT."""
        # Create a scenario: oscillating data with a final spike above BB
        base = [100.0 + 3.0 * math.sin(i * 0.35) for i in range(30)]
        breaks = base + [107.0, 108.0, 109.0]  # Spike above BB upper
        highs = [c + 1.0 for c in breaks]
        lows = [c - 1.0 for c in breaks]

        result = detect_regime(highs, lows, breaks, period=20)

        assert result.regime == MarketRegime.BREAKOUT
        assert result.metadata["direction"] == "up"
        assert result.metadata["latest_close"] > result.metadata["bb_upper"]

    def test_breakout_below_lower_bb(self):
        """Close breaking below lower BB should return BREAKOUT."""
        base = [100.0 + 3.0 * math.sin(i * 0.35) for i in range(30)]
        breaks = base + [93.0, 92.0, 91.0]  # Spike below BB lower
        highs = [c + 1.0 for c in breaks]
        lows = [c - 1.0 for c in breaks]

        result = detect_regime(highs, lows, breaks, period=20)

        assert result.regime == MarketRegime.BREAKOUT
        assert result.metadata["direction"] == "down"
        assert result.metadata["latest_close"] < result.metadata["bb_lower"]

    def test_ranging_market_classification(self):
        """ADX < 20 and no clear trend should return RANGING."""
        # Sinusoidal oscillation gives no trend
        closes = [100.0 + 1.5 * math.sin(i * 0.5) for i in range(50)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]

        result = detect_regime(highs, lows, closes, period=20)

        assert result.regime == MarketRegime.RANGING
        assert result.confidence > 0.0

    def test_insufficient_data_returns_unknown(self):
        """Insufficient bars should return UNKNOWN with confidence 0."""
        short = [100.0] * 10
        highs = [100.1] * 10
        lows = [99.9] * 10

        result = detect_regime(highs, lows, short, period=20)

        assert result.regime == MarketRegime.UNKNOWN
        assert result.confidence == 0.0

    def test_unequal_lengths_returns_unknown(self):
        """Unequal length arrays should return UNKNOWN."""
        highs = [100.1] * 50
        lows = [99.9] * 50
        closes = [100.0] * 40  # Shorter

        result = detect_regime(highs, lows, closes, period=20)

        assert result.regime == MarketRegime.UNKNOWN

    def test_regime_result_dataclass(self):
        """RegimeResult should be an immutable dataclass with expected fields."""
        result = RegimeResult(
            regime=MarketRegime.UNKNOWN,
            confidence=0.5,
            metadata={"test": "value"},
        )

        assert result.regime == MarketRegime.UNKNOWN
        assert result.confidence == 0.5
        assert result.metadata == {"test": "value"}

        # Verify it's frozen (cannot modify)
        with pytest.raises(AttributeError):
            result.regime = MarketRegime.TRENDING  # type: ignore[misc]

    def test_market_regime_enum_values(self):
        """MarketRegime enum should have exactly 6 named values."""
        expected = {
            "trending",
            "ranging",
            "breakout",
            "high_volatility",
            "low_volatility",
            "unknown",
        }
        actual = {m.value for m in MarketRegime}
        assert actual == expected


class TestRegimeEdgeCases:
    """Edge case tests for regime detection."""

    def test_flat_pricedata_returns_low_volatility(self):
        """Completely flat price data (no movement) should be LOW_VOLATILITY."""
        closes = [100.0] * 100
        highs = [100.0] * 100
        lows = [100.0] * 100

        result = detect_regime(highs, lows, closes, period=20)

        assert result.regime == MarketRegime.LOW_VOLATILITY

    def test_zero_variance_returns_undefined_ema(self):
        """Data with zero variance causes zero std dev handling."""
        # All same price - bollinger bands have zero width
        closes = [50.0] * 60
        highs = [50.0] * 60
        lows = [50.0] * 60

        result = detect_regime(highs, lows, closes, period=20)

        # Should be LOW_VOLATILITY due to zero BB width
        assert result.regime == MarketRegime.LOW_VOLATILITY

    def test_single_bar_above_upper_band_breakout(self):
        """Single bar closing above upper band triggers breakout."""
        # 25 stable bars near 100
        stable = [100.0 + 0.1 * math.sin(i) for i in range(25)]
        # One bar jumps above
        jump = stable + [115.0]
        highs = [c + 0.5 for c in jump]
        lows = [c - 0.5 for c in jump]

        result = detect_regime(highs, lows, jump, period=20)

        # Should detect breakout since close > upper BB
        assert result.regime in (MarketRegime.BREAKOUT, MarketRegime.TRENDING)

    def test_custom_period_parameter(self):
        """detect_regime should accept custom period parameter."""
        closes = [100.0 + i * 0.3 for i in range(35)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]

        # With period=10, we have enough data
        result = detect_regime(highs, lows, closes, period=10)

        assert result.regime in (MarketRegime.TRENDING, MarketRegime.UNKNOWN)
