# -*- coding: utf-8 -*-
"""Tests for premium/discount zone classification in StructureAnalystAgent."""

from __future__ import annotations

import pytest
from agents.analysts import StructureAnalystAgent


class TestClassifyZoneUnit:
    """Unit tests for _classify_zone static method."""

    def test_price_above_equilibrium_is_premium(self):
        result = StructureAnalystAgent._classify_zone(
            current_price=2700.0, swing_high=2750.0, swing_low=2550.0
        )
        assert result["zone"] == "premium"
        assert result["distance_pct"] > 0
        assert result["equilibrium"] == round((2750.0 + 2550.0) / 2.0, 5)

    def test_price_below_equilibrium_is_discount(self):
        result = StructureAnalystAgent._classify_zone(
            current_price=2600.0, swing_high=2750.0, swing_low=2550.0
        )
        assert result["zone"] == "discount"
        assert result["distance_pct"] < 0
        assert result["equilibrium"] == round((2750.0 + 2550.0) / 2.0, 5)

    def test_price_at_exact_equilibrium(self):
        result = StructureAnalystAgent._classify_zone(
            current_price=2650.0, swing_high=2750.0, swing_low=2550.0
        )
        assert result["zone"] == "equilibrium"
        assert result["distance_pct"] == pytest.approx(0.0, abs=0.01)

    def test_invalid_swing_high_lte_low(self):
        result = StructureAnalystAgent._classify_zone(
            current_price=100.0, swing_high=50.0, swing_low=60.0
        )
        assert result["zone"] == "unknown"
        assert result["equilibrium"] == 0.0
        assert result["distance_pct"] == 0.0

    def test_invalid_swing_high_equal_low(self):
        result = StructureAnalystAgent._classify_zone(
            current_price=100.0, swing_high=100.0, swing_low=100.0
        )
        assert result["zone"] == "unknown"

    def test_invalid_swing_high_zero(self):
        result = StructureAnalystAgent._classify_zone(
            current_price=100.0, swing_high=0.0, swing_low=-10.0
        )
        assert result["zone"] == "unknown"


class TestZoneClassificationIntegration:
    """Integration test: analyze() output contains zone_classification."""

    def test_analyze_output_contains_zone_classification(self):
        agent = StructureAnalystAgent()
        prices = [1.1000 + i * 0.001 for i in range(30)]
        highs = [p + 0.0005 for p in prices]
        lows = [p - 0.0005 for p in prices]
        result = agent.analyze({"prices": prices, "highs": highs, "lows": lows})

        assert "zone_classification" in result
        zc = result["zone_classification"]
        assert "zone" in zc
        assert zc["zone"] in ("premium", "discount", "equilibrium", "unknown")
        assert "equilibrium" in zc
        assert "distance_pct" in zc
        assert isinstance(zc["equilibrium"], float)
        assert isinstance(zc["distance_pct"], float)

    def test_analyze_insufficient_data_no_zone_crash(self):
        agent = StructureAnalystAgent()
        result = agent.analyze(
            {"prices": [100.0, 99.5], "highs": [101.0], "lows": [99.0]}
        )
        assert result["signal"] == "NEUTRAL"
