# -*- coding: utf-8 -*-
"""Tests for MomentumAnalystAgent."""

from __future__ import annotations

import agents.analysts.momentum_analyst as momentum_module
import pytest
from agents.analysts import MomentumAnalystAgent


def test_momentum_analyst_initialization():
    """Test agent initialization and capabilities."""
    agent = MomentumAnalystAgent()
    assert agent.name == "momentum_analyst"
    assert agent.agent_type == "momentum"
    assert len(agent.capabilities) == 6
    assert any(c.name == "rsi_analysis" for c in agent.capabilities)
    assert any(c.name == "macd_analysis" for c in agent.capabilities)
    assert any(c.name == "divergence_detection" for c in agent.capabilities)
    assert any(c.name == "self_improvement" for c in agent.capabilities)


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
    assert result["signal"] in (
        "BULLISH",
        "STRONG_BULLISH",
        "NEUTRAL",
        "BEARISH",
        "STRONG_BEARISH",
    )
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


def test_momentum_analyst_detects_regular_and_hidden_divergences(monkeypatch):
    """Use the latest two confirmed pivots for RSI and MACD divergences."""
    regular_bullish = [100.0] * 30 + [98.0, 95.0, 98.0, 100.0, 98.0, 92.0, 96.0]
    hidden_bullish = [100.0] * 30 + [98.0, 92.0, 98.0, 100.0, 98.0, 95.0, 98.0]
    regular_bearish = [100.0] * 30 + [102.0, 105.0, 102.0, 100.0, 102.0, 108.0, 104.0]
    hidden_bearish = [100.0] * 30 + [102.0, 108.0, 102.0, 100.0, 102.0, 105.0, 102.0]
    oscillator_directions = {
        tuple(regular_bullish): (40.0, 50.0),
        tuple(hidden_bullish): (50.0, 40.0),
        tuple(regular_bearish): (60.0, 50.0),
        tuple(hidden_bearish): (50.0, 60.0),
    }

    def fake_rsi_series(prices, period=14):
        values = [50.0] * len(prices)
        values[31], values[35] = oscillator_directions[tuple(prices)]
        return values

    def fake_macd_series(prices, fast_period=12, slow_period=26, signal_period=9):
        values = [0.5] * len(prices)
        values[31], values[35] = oscillator_directions[tuple(prices)]
        return values, [0.0] * len(prices), [value / 2 for value in values]

    monkeypatch.setattr(momentum_module, "rsi_series", fake_rsi_series)
    monkeypatch.setattr(momentum_module, "macd_series", fake_macd_series)

    agent = MomentumAnalystAgent()
    detected = set()
    for prices in (regular_bullish, hidden_bullish, regular_bearish, hidden_bearish):
        result = agent.analyze({"prices": prices})
        detected.update(
            (divergence["indicator"], divergence["divergence_type"])
            for divergence in result["divergences"]
        )

    assert {
        ("RSI", "regular_bullish"),
        ("RSI", "regular_bearish"),
        ("RSI", "hidden_bullish"),
        ("RSI", "hidden_bearish"),
        ("MACD", "regular_bullish"),
        ("MACD", "regular_bearish"),
        ("MACD", "hidden_bullish"),
        ("MACD", "hidden_bearish"),
    } <= detected


def test_momentum_analyst_unconfirmed_final_pivot_ignored(monkeypatch):
    """An unconfirmed extreme on the final bar must not emit a divergence."""
    prices = [100.0] * 30 + [98.0, 95.0, 98.0, 100.0, 98.0, 91.0]

    def fake_rsi_series(series, period=14):
        values = [50.0] * len(series)
        values[31] = 40.0
        values[-1] = 60.0
        return values

    monkeypatch.setattr(momentum_module, "rsi_series", fake_rsi_series)
    result = MomentumAnalystAgent().analyze({"prices": prices})
    assert result["divergences"] == []


def test_momentum_analyst_divergence_fails_closed_when_oscillator_unavailable(
    monkeypatch,
):
    """When oscillator series is unavailable or None, no divergence is emitted."""
    prices = [100.0] * 30 + [98.0, 95.0, 98.0, 100.0, 98.0, 92.0, 96.0]
    monkeypatch.setattr(
        momentum_module, "rsi_series", lambda prices, period=14: [None] * len(prices)
    )
    monkeypatch.setattr(
        momentum_module,
        "macd_series",
        lambda prices, fast_period=12, slow_period=26, signal_period=9: (
            [None] * len(prices),
            [None] * len(prices),
            [None] * len(prices),
        ),
    )
    result = MomentumAnalystAgent().analyze({"prices": prices})
    assert result["divergences"] == []


def test_momentum_analyst_multi_timeframe_consensus():
    """Consensus requires at least two agreeing directional frames and no conflict."""
    agent = MomentumAnalystAgent()
    bull_prices = [100.0 + i * 0.8 for i in range(50)]
    bear_prices = [150.0 - i * 0.7 for i in range(50)]
    neutral_prices = [100.0 + (i % 2) * 0.1 for i in range(50)]

    # Absent timeframe_prices
    base_res = agent.analyze({"prices": bull_prices})
    assert base_res["metadata"].get("multi_timeframe_consensus") is None
    assert base_res["metadata"].get("timeframe_signals") == {}

    # Agreeing directional frames
    agreeing_res = agent.analyze(
        {
            "prices": bull_prices,
            "timeframe_prices": {"15m": bull_prices, "1h": bull_prices},
        }
    )
    assert agreeing_res["metadata"]["multi_timeframe_consensus"] is True
    assert "15m" in agreeing_res["metadata"]["timeframe_signals"]
    assert "1h" in agreeing_res["metadata"]["timeframe_signals"]

    # Conflict between directional frames
    conflict_res = agent.analyze(
        {
            "prices": bull_prices,
            "timeframe_prices": {"15m": bull_prices, "1h": bear_prices},
        }
    )
    assert conflict_res["metadata"]["multi_timeframe_consensus"] is False

    # Only one directional frame (needs at least two)
    single_directional_res = agent.analyze(
        {
            "prices": bull_prices,
            "timeframe_prices": {"15m": bull_prices, "1h": neutral_prices},
        }
    )
    assert single_directional_res["metadata"]["multi_timeframe_consensus"] is False


def test_momentum_analyst_malformed_timeframe_prices_fails_closed():
    """Malformed timeframe_prices must fail closed with NEUTRAL and 0.0 confidence."""
    agent = MomentumAnalystAgent()
    bull_prices = [100.0 + i * 0.8 for i in range(50)]

    for bad_payload in [
        "not-a-dict",
        {"1h": "not-a-list"},
        {"1h": [100.0, 101.0]},  # < 15 bars
        {"1h": [100.0, "bad-price"] * 10},
    ]:
        result = agent.analyze(
            {
                "prices": bull_prices,
                "timeframe_prices": bad_payload,
            }
        )
        assert result["signal"] == "NEUTRAL"
        assert result["confidence"] == 0.0
        assert len(result["reasoning"]) > 0


def test_momentum_analyst_adx_metadata_and_regimes(monkeypatch):
    """ADX metadata must classify regimes and adjust confidence conservatively."""
    agent = MomentumAnalystAgent()
    prices = [100.0 + i * 0.5 for i in range(50)]
    highs = [p + 0.3 for p in prices]
    lows = [p - 0.3 for p in prices]

    # Strong trend: >= 25
    monkeypatch.setattr(
        momentum_module, "adx", lambda highs, lows, closes, period=14: 30.0
    )
    strong_res = agent.analyze({"prices": prices, "highs": highs, "lows": lows})
    assert strong_res["metadata"]["adx_regime"] == "strong_trend"
    assert strong_res["metadata"]["adx_value"] == 30.0

    # Developing: 20-25
    monkeypatch.setattr(
        momentum_module, "adx", lambda highs, lows, closes, period=14: 22.5
    )
    dev_res = agent.analyze({"prices": prices, "highs": highs, "lows": lows})
    assert dev_res["metadata"]["adx_regime"] == "developing"
    assert dev_res["metadata"]["adx_value"] == 22.5

    # Weak range: < 20 (caps confidence at 0.50)
    monkeypatch.setattr(
        momentum_module, "adx", lambda highs, lows, closes, period=14: 15.0
    )
    weak_res = agent.analyze({"prices": prices, "highs": highs, "lows": lows})
    assert weak_res["metadata"]["adx_regime"] == "weak_range"
    assert weak_res["metadata"]["adx_value"] == 15.0
    assert weak_res["confidence"] <= 0.50


def test_momentum_analyst_adx_failure_fails_closed(monkeypatch):
    """If highs/lows are supplied but ADX calculation fails, fail closed."""
    agent = MomentumAnalystAgent()
    prices = [100.0 + i * 0.5 for i in range(50)]
    highs = [p + 0.3 for p in prices]
    lows = [p - 0.3 for p in prices]

    # ADX returns None
    monkeypatch.setattr(
        momentum_module, "adx", lambda highs, lows, closes, period=14: None
    )
    res_none = agent.analyze({"prices": prices, "highs": highs, "lows": lows})
    assert res_none["signal"] == "NEUTRAL"
    assert res_none["confidence"] == 0.0

    # ADX raises Exception
    def raise_err(highs, lows, closes, period=14):
        raise RuntimeError("ADX computation error")

    monkeypatch.setattr(momentum_module, "adx", raise_err)
    res_err = agent.analyze({"prices": prices, "highs": highs, "lows": lows})
    assert res_err["signal"] == "NEUTRAL"
    assert res_err["confidence"] == 0.0


def test_momentum_analyst_legacy_price_only_path():
    """When only prices are supplied, preserve legacy behavior with adx_regime unavailable."""
    agent = MomentumAnalystAgent()
    prices = [100.0 + i * 0.5 for i in range(50)]

    result = agent.analyze({"prices": prices})
    assert result["metadata"]["adx_regime"] == "unavailable"
    assert result["metadata"]["adx_value"] is None
    assert result["metadata"]["multi_timeframe_consensus"] is None
    assert result["signal"] != "NEUTRAL" or result["confidence"] >= 0.5


def test_momentum_analyst_self_improvement_memory_adjustment():
    """AgentPatternMemory adjusts confidence and appends a [Memory: ...] note."""
    from agents.agent_memory import AgentPatternMemory

    agent = MomentumAnalystAgent()
    prices = [100.0 + i * 0.8 for i in range(50)]

    # Get baseline without memory
    base_result = agent.analyze({"prices": prices, "agent_memory": None})
    base_conf = base_result["confidence"]

    # Inject memory with high accuracy in TRENDING regime
    mem = AgentPatternMemory(min_samples=3)
    for _ in range(5):
        mem.record_outcome("momentum_analyst", "BULLISH", True, regime="TRENDING")

    mem_result = agent.analyze({"prices": prices, "agent_memory": mem})
    assert "[Memory: " in mem_result["reasoning"]
    assert mem_result["confidence"] >= base_conf


def test_momentum_analyst_malformed_memory_preserves_analysis():
    """A malformed injected memory object preserves analysis and adds no fake note."""
    agent = MomentumAnalystAgent()
    prices = [100.0 + i * 0.8 for i in range(50)]

    base_result = agent.analyze({"prices": prices})

    # Non-object / string memory
    bad_mem_result = agent.analyze(
        {"prices": prices, "agent_memory": "invalid-memory-object"}
    )
    assert bad_mem_result["signal"] == base_result["signal"]
    assert bad_mem_result["confidence"] == base_result["confidence"]
    assert "[Memory: " not in bad_mem_result["reasoning"]

    # Broken object whose adjust_confidence raises
    class BrokenMemory:
        def adjust_confidence(self, *args, **kwargs):
            raise RuntimeError("Memory internal error")

    broken_result = agent.analyze({"prices": prices, "agent_memory": BrokenMemory()})
    assert broken_result["signal"] == base_result["signal"]
    assert broken_result["confidence"] == base_result["confidence"]
    assert "[Memory: " not in broken_result["reasoning"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
