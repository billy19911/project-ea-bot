# -*- coding: utf-8 -*-
"""Tests for VolatilityAnalystAgent."""

from __future__ import annotations

import pytest

from agents.analysts.volatility_analyst import VolatilityAnalystAgent, VolatilityInput


@pytest.fixture
def agent():
    """Create a fresh VolatilityAnalystAgent."""
    return VolatilityAnalystAgent()


class TestVolatilityAnalystBasics:
    def test_agent_metadata(self, agent):
        assert agent.name == "volatility_analyst"
        assert agent.agent_type == "volatility"
        assert len(agent.capabilities) >= 3

    def test_can_handle_volatility_events(self, agent):
        assert agent.can_handle("VOLATILITY_HIGH", {})
        assert agent.can_handle("VOLATILITY_LOW", {})
        assert agent.can_handle("ANY_EVENT", {"volatility": {}})

    def test_can_handle_rejects_others(self, agent):
        assert not agent.can_handle("TREND_BULLISH", {})


class TestVolatilityInput:
    def test_input_from_dict(self, agent):
        data = {
            "atr": 10.5,
            "price": 100.0,
            "bollinger_width": 0.05,
            "returns": [0.01, -0.02, 0.015],
        }
        inp = agent._input({"volatility": data})
        assert inp.atr == 10.5
        assert inp.price == 100.0
        assert len(inp.returns) == 3

    def test_input_from_dataclass(self, agent):
        inp = VolatilityInput(atr=5.0, price=50.0)
        result = agent._input({"volatility": inp})
        assert result.atr == 5.0
        assert result.price == 50.0

    def test_input_defaults(self, agent):
        inp = agent._input({})
        assert inp.atr == 0.0
        assert inp.price == 0.0
        assert inp.returns == []


class TestVolatilityAnalysis:
    def test_squeeze_detection(self, agent):
        data = {
            "atr": 1.0,
            "price": 100.0,
            "bollinger_width": 0.015,
            "returns": [0.001, -0.001],
        }
        result = agent.analyze({"volatility": data})
        assert result["signal"] == "LOW"
        assert result["confidence"] >= 0.7
        assert "squeeze" in " ".join(result["reasoning"]).lower()

    def test_high_volatility(self, agent):
        data = {
            "atr": 5.0,
            "price": 100.0,
            "bollinger_width": 0.10,
            "returns": [0.05, -0.04, 0.06, -0.03],
        }
        result = agent.analyze({"volatility": data})
        assert result["signal"] == "HIGH"
        assert result["confidence"] >= 0.8

    def test_normal_volatility(self, agent):
        data = {
            "atr": 2.0,
            "price": 100.0,
            "bollinger_width": 0.04,
            "returns": [0.01, -0.01, 0.005],
        }
        result = agent.analyze({"volatility": data})
        assert result["signal"] == "NORMAL"
        assert 0.5 < result["confidence"] < 0.8

    def test_metrics_completeness(self, agent):
        data = {"atr": 2.0, "price": 100.0, "bollinger_width": 0.05}
        result = agent.analyze({"volatility": data})
        metrics = result["metrics"]
        assert "atr" in metrics
        assert "atr_percent" in metrics
        assert "bollinger_width" in metrics
        assert "expected_range" in metrics
        assert "squeeze" in metrics

    def test_invalid_input_degradation(self, agent):
        result = agent.analyze({"volatility": None})
        assert result["signal"] == "UNKNOWN"
        assert result["confidence"] == 0.0

    def test_empty_returns_handling(self, agent):
        data = {"atr": 0.0, "price": 100.0, "bollinger_width": 0.0, "returns": []}
        result = agent.analyze({"volatility": data})
        assert result["signal"] == "UNKNOWN"
        assert "Historical returns unavailable" in result["reasoning"]

    def test_atr_percent_high(self, agent):
        data = {
            "atr": 4.0,
            "price": 100.0,
            "bollinger_width": 0.025,
            "returns": [0.01],
        }
        result = agent.analyze({"volatility": data})
        assert result["signal"] == "HIGH"

    def test_output_schema_compliance(self, agent):
        data = {"atr": 1.0, "price": 50.0}
        result = agent.analyze({"volatility": data})
        assert "signal" in result
        assert "confidence" in result
        assert "reasoning" in result
        assert "metrics" in result
        assert isinstance(result["reasoning"], list)
        assert isinstance(result["metrics"], dict)
