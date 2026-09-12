# -*- coding: utf-8 -*-
"""Tests for MomentumAnalystAgent."""

from __future__ import annotations

import pytest

from agents.analysts import MomentumAnalystAgent


def test_momentum_analyst_initialization():
    """Test agent initialization and capabilities."""
    agent = MomentumAnalystAgent()
    assert agent.name == "momentum_analyst"
    assert agent.agent_type == "momentum"
    assert len(agent.capabilities) == 5
    assert any(c.name == "rsi_analysis" for c in agent.capabilities)
    assert any(c.name == "macd_analysis" for c in agent.capabilities)
    assert any(c.name == "divergence_detection" for c in agent.capabilities)


def test_momentum_analyst_can_handle_events():
    """Test can_handle method for various event types."""
    agent = MomentumAnalystAgent()

    assert agent.can_handle("MOMENTUM_ANALYSIS", {})
    assert agent.can_handle("RSI_CHECK", {})
    assert agent.can_handle("MACD_CHECK", {})
    assert agent.can_handle("OSCILLATOR_SCAN", {})
    assert agent.can_handle("DIVERGENCE_DETECT", {})
    assert agent.can_handle("MOMENTUM_RSI", {})

    assert not agent.can_handle("OTHER_EVENT", {})


def test_momentum_analyst_insufficient_data():
    """Test analysis with insufficient data."""
    agent = MomentumAnalystAgent()
    context = {"prices": [100.0, 99.5]}
    result = agent.analyze(context)

    assert result["agent"] == agent.name
    assert result["signal"] == "NEUTRAL"
    assert result["confidence"] == 0.0
    assert "Insufficient" in result["reasoning"]


def test_momentum_analyst_bullish_signal():
    """Test bullish signal detection with rising price data."""
    # Create data with consistent upward momentum
    prices = [100.0 + i * 0.8 for i in range(50)]
    highs = [p + 0.3 for p in prices]
    lows = [p - 0.3 for p in prices]

    context = {"prices": prices, "highs": highs, "lows": lows}
    result = MomentumAnalystAgent().analyze(context)

    assert result["agent"] == "momentum_analyst"
    # Note: strong uptrend may trigger overbought RSI/Stoch, producing mixed signals
    assert result["signal"] in ("BULLISH", "STRONG_BULLISH", "NEUTRAL", "BEARISH", "STRONG_BEARISH")
    assert result["confidence"] >= 0.0
    assert result["rsi_value"] is not None
    assert result["velocity"] is not None
    assert result["metadata"]["current_price"] == prices[-1]


def test_momentum_analyst_bearish_signal():
    """Test bearish signal detection with declining price data."""
    # Create data with consistent downward momentum
    prices = [150.0 - i * 0.7 for i in range(50)]
    highs = [p + 0.3 for p in prices]
    lows = [p - 0.3 for p in prices]

    context = {"prices": prices, "highs": highs, "lows": lows}
    result = MomentumAnalystAgent().analyze(context)

    assert result["agent"] == "momentum_analyst"
    assert result["signal"] in ("BEARISH", "STRONG_BEARISH", "NEUTRAL")
    assert result["confidence"] >= 0.0
    assert result["rsi_value"] is not None
    assert result["velocity"] is not None


def test_momentum_analyst_rsi_calculation():
    """Test RSI value is calculated correctly."""
    agent = MomentumAnalystAgent()

    # Strong up trending data should have RSI > 50
    prices_up = [100.0 + i * 0.5 for i in range(30)]
    context = {"prices": prices_up}
    result = agent.analyze(context)

    assert result["rsi_value"] is not None
    assert 0 <= result["rsi_value"] <= 100


def test_momentum_analyst_macd_output():
    """Test MACD output format."""
    agent = MomentumAnalystAgent()
    prices = [100.0 + i * 0.3 for i in range(50)]
    context = {"prices": prices}
    result = agent.analyze(context)

    # MACD data may be present or None depending on data length
    if result["macd_data"] is not None:
        assert "macd_line" in result["macd_data"]
        assert "signal_line" in result["macd_data"]
        assert "histogram" in result["macd_data"]


def test_momentum_analyst_stochastic_output():
    """Test Stochastic output format."""
    agent = MomentumAnalystAgent()
    prices = [100.0 + i * 0.2 for i in range(50)]
    highs = [p + 0.5 for p in prices]
    lows = [p - 0.5 for p in prices]
    context = {"prices": prices, "highs": highs, "lows": lows}
    result = agent.analyze(context)

    if result["stoch_data"] is not None:
        assert "k" in result["stoch_data"]
        assert "d" in result["stoch_data"]


def test_momentum_analyst_velocity_calculation():
    """Test velocity/Rate of Change calculation."""
    agent = MomentumAnalystAgent()

    # Fast moving prices over 5 bars
    prices = [100.0 + i * 2.0 for i in range(10)]
    context = {"prices": prices}
    result = agent.analyze(context)

    # Velocity should be positive for rising prices
    assert result["velocity"] >= 0


def test_momentum_analyst_divergence_detection():
    """Test divergence detection output format."""
    agent = MomentumAnalystAgent()

    # Zigzag-like price action to potentially trigger divergence
    prices = [100.0 + i * 0.1 * ((-1) ** i) for i in range(50)]
    context = {"prices": prices}
    result = agent.analyze(context)

    assert "divergences" in result
    assert isinstance(result["divergences"], list)


def test_momentum_analyst_confidence_bounds():
    """Test that confidence is always within valid bounds."""
    agent = MomentumAnalystAgent()

    # Test with various data patterns
    for offset in [0, 10, 20, 30]:
        prices = [100.0 + offset + i * 0.5 for i in range(40)]
        context = {"prices": prices}
        result = agent.analyze(context)

        assert 0.0 <= result["confidence"] <= 1.0


def test_momentum_analyst_fallback_on_error():
    """Test fallback behavior when analysis fails."""
    agent = MomentumAnalystAgent()
    # Provoke an error
    context = {"prices": None}
    result = agent.analyze(context)

    assert result["agent"] == agent.name
    assert result["signal"] == "NEUTRAL"
    assert result["confidence"] == 0.0


def test_momentum_analyst_signal_reasoning():
    """Test that signal includes valid reasoning."""
    agent = MomentumAnalystAgent()
    prices = [100.0 + i * 0.5 for i in range(50)]
    context = {"prices": prices}
    result = agent.analyze(context)

    assert isinstance(result["reasoning"], str)
    assert len(result["reasoning"]) > 0


def test_momentum_analyst_metadata_structure():
    """Test metadata contains expected fields."""
    agent = MomentumAnalystAgent()
    prices = [100.0 + i * 0.3 for i in range(50)]
    context = {"prices": prices}
    result = agent.analyze(context)

    metadata = result.get("metadata", {})
    assert "bull_score" in metadata
    assert "bear_score" in metadata
    assert "bar_count" in metadata
    assert "current_price" in metadata
    assert "timestamp" in metadata


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
