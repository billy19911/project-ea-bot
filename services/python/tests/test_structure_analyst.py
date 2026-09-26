# -*- coding: utf-8 -*-
"""Tests for StructureAnalystAgent."""

from __future__ import annotations

import pytest
from agents.analysts import StructureAnalystAgent


def test_structure_analyst_initialization():
    """Test agent initialization and capabilities."""
    agent = StructureAnalystAgent()
    assert agent.name == "structure_analyst"
    assert agent.agent_type == "structural"
    assert len(agent.capabilities) >= 4
    assert any(c.name == "support_resistance" for c in agent.capabilities)


def test_structure_analyst_can_handle_events():
    """Test can_handle method for various event types."""
    agent = StructureAnalystAgent()

    assert agent.can_handle("STRUCTURE_ANALYSIS", {})
    assert agent.can_handle("PRICE_ACTION", {})
    assert agent.can_handle("TREND_DETECT", {})
    assert agent.can_handle("LEVEL_SCAN", {})
    assert agent.can_handle("MARKET_NEWS", {})

    assert not agent.can_handle("OTHER_EVENT", {})


def test_structure_analyst_insufficient_data():
    """Test analysis with insufficient data."""
    agent = StructureAnalystAgent()
    context = {"prices": [100.0, 99.5], "highs": [101.0, 100.5], "lows": [99.0, 98.5]}
    result = agent.analyze(context)

    assert result["agent"] == agent.name
    assert result["signal"] == "NEUTRAL"
    assert result["confidence"] == 0.0
    assert "Insufficient price data" in result["reasoning"]


def test_structure_analyst_detects_trend():
    """Test trend detection with synthetic bullish data."""
    # Create synthetic data: trending up with some noise
    base = 100.0
    prices = [base + i * 1.5 for i in range(50)]
    highs = [base + i * 1.5 + 0.5 for i in range(50)]
    lows = [base + i * 1.5 - 0.5 for i in range(50)]

    context = {"prices": prices, "highs": highs, "lows": lows}
    result = StructureAnalystAgent().analyze(context)

    assert result["agent"] == "structure_analyst"
    assert result["signal"] in ("BULLISH", "WEAK_BULLISH", "NEUTRAL")
    assert result["confidence"] >= 0.0
    assert result["key_levels"] is not None
    assert result["swing_low"] is not None
    assert result["swing_high"] is not None
    assert result["trend_direction"] is not None
    assert "metadata" in result


def test_structure_analyst_key_levels_format():
    """Test that key_levels output matches expected format."""
    agent = StructureAnalystAgent()
    prices = [100.0 + i * 0.5 for i in range(30)]
    highs = [100.0 + i * 0.5 + 0.2 for i in range(30)]
    lows = [100.0 + i * 0.5 - 0.2 for i in range(30)]
    context = {"prices": prices, "highs": highs, "lows": lows}
    result = agent.analyze(context)

    key_levels = result.get("key_levels", [])
    for level in key_levels:
        # Expected fields: either KeyLevel structure or order block
        assert "price" in level
        # Order blocks have 'type', KeyLevels have 'level_type'
        assert "level_type" in level or "type" in level
        if "level_type" in level:
            assert "strength" in level
            assert "touch_count" in level


def test_structure_analyst_fallback_on_error():
    """Test fallback behavior when analysis fails."""
    agent = StructureAnalystAgent()
    # Provoke an error by passing invalid input
    context = {"prices": None, "highs": "invalid", "lows": []}
    result = agent.analyze(context)

    assert result["agent"] == agent.name
    assert result["signal"] == "NEUTRAL"
    assert result["confidence"] == 0.0
    # Fallback triggers for invalid input; reasoning mentions insufficient data
    assert (
        "Insufficient" in result["reasoning"] or "error" in result["reasoning"].lower()
    )


def test_structure_analyst_support_resistance_calculation():
    """Test internal support/resistance calculation logic."""
    agent = StructureAnalystAgent()

    # Simple test case: 20 bars, clear clusters
    prices = [100.0] * 5 + [101.0] * 5 + [102.0] * 5 + [103.0] * 5
    highs = [x + 0.5 for x in prices]
    lows = [x - 0.5 for x in prices]

    context = {"prices": prices, "highs": highs, "lows": lows}
    result = agent.analyze(context)

    # Verify we got some support/resistance levels
    key_levels = result.get("key_levels", [])
    # At least 4 levels expected (2 supports, 2 resistances)
    assert len(key_levels) >= 4


def test_structure_analyst_order_block_detection():
    """Test order block detection in internal logic."""
    agent = StructureAnalystAgent()

    # Recent high and low should be detected as order blocks
    prices = [100.0 + i * 0.2 for i in range(20)]
    highs = prices.copy()
    lows = [p - 1.0 for p in prices]

    context = {"prices": prices, "highs": highs, "lows": lows}
    result = agent.analyze(context)

    # Order blocks should appear in key_levels
    key_levels = result.get("key_levels", [])
    # At least one order block should be detected
    order_blocks = [k for k in key_levels if k.get("type")]
    assert len(order_blocks) >= 1


def test_structure_analyst_smc_pattern_metadata():
    """BOS/CHoCH/sweep fields and FVG count are exposed."""
    agent = StructureAnalystAgent()
    prices = [
        1.1000,
        1.1010,
        1.1020,
        1.1030,
        1.1040,
        1.1050,
        1.1045,
        1.1055,
        1.1065,
        1.1075,
        1.1085,
        1.1095,
        1.1100,
        1.1105,
        1.1120,
        1.1130,
        1.1140,
        1.1150,
    ]
    highs = [p + 0.0005 for p in prices]
    lows = [p - 0.0005 for p in prices]
    result = agent.analyze({"prices": prices, "highs": highs, "lows": lows})
    metadata = result["metadata"]
    assert "structure_pattern" in metadata
    assert "bos" in metadata["structure_pattern"]
    assert "choch" in metadata["structure_pattern"]
    assert "fvg_count" in metadata


def test_structure_analyst_self_improvement_calibration():
    """Agent memory adjusts confidence and appends calibration note."""
    agent = StructureAnalystAgent()

    class FakeMemory:
        def adjust_confidence(self, agent_name, regime, base):
            assert agent_name == "structure_analyst"
            assert regime in {"TRENDING", "RANGING"}
            return min(1.0, base + 0.05), "confidence +0.05"

    prices = [1.1000 + i * 0.0001 for i in range(30)]
    result = agent.analyze(
        {
            "prices": prices,
            "highs": prices,
            "lows": prices,
            "agent_memory": FakeMemory(),
        }
    )
    assert "Memory:" in result["reasoning"]
    assert result["confidence"] > 0.0


def test_structure_analyst_invalid_input_fails_closed():
    """Invalid OHLC length returns NEUTRAL, zero confidence."""
    agent = StructureAnalystAgent()
    result = agent.analyze(
        {
            "prices": [1.1000, 1.1010, 1.1020],
            "highs": [1.1000, 1.1010],
            "lows": [1.1000, 1.1010, 1.1020],
        }
    )
    assert result["signal"] == "NEUTRAL"
    assert result["confidence"] == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
