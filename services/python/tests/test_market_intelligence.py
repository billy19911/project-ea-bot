# -*- coding: utf-8 -*-
"""Tests for EPIC 04 — Market Intelligence Department."""

from __future__ import annotations

import pytest

from agents.permissions import AgentPermissionError, require_permission
from market.intelligence import (
    AnalystReport,
    CommitteeDecision,
    MarketDepartment,
    MarketLead,
    NewsSentimentAnalyst,
    StructureAnalyst,
    TechnicalAnalyst,
    VolatilityAnalyst,
)


def test_market_lead_creates_department():
    """MarketLead must create and manage MarketDepartment."""
    lead = MarketLead()
    dept = lead.create_department()
    assert isinstance(dept, MarketDepartment)
    assert dept.lead is lead


def test_market_lead_assigns_specialists():
    """MarketLead must assign all required specialists."""
    lead = MarketLead()
    dept = lead.create_department()
    assert len(dept.specialists) == 5
    types = {type(s).__name__ for s in dept.specialists}
    expected = {
        "TechnicalAnalyst",
        "StructureAnalyst",
        "VolatilityAnalyst",
        "NewsSentimentAnalyst",
    }
    assert expected.issubset(types)


def test_technical_analyst_produces_report():
    """TechnicalAnalyst must produce structured report."""
    analyst = TechnicalAnalyst()
    report = analyst.analyze(
        {
            "symbol": "EURUSD",
            "ohlc": [{"open": 1.08, "high": 1.09, "low": 1.07, "close": 1.085}],
            "trend": "UP",
            "rsi": 65.0,
            "macd": 0.002,
        }
    )
    assert isinstance(report, AnalystReport)
    assert report.direction in ("BULLISH", "BEARISH", "NEUTRAL")
    assert 0.0 <= report.confidence <= 1.0


def test_structure_analyst_produces_report():
    """StructureAnalyst must produce structured report."""
    analyst = StructureAnalyst()
    report = analyst.analyze(
        {
            "symbol": "EURUSD",
            "support": 1.0750,
            "resistance": 1.0950,
            "current_price": 1.0850,
            "swing_high": 1.0950,
            "swing_low": 1.0750,
        }
    )
    assert isinstance(report, AnalystReport)
    assert report.direction in ("BULLISH", "BEARISH", "NEUTRAL")


def test_volatility_analyst_produces_report():
    """VolatilityAnalyst must produce structured report."""
    analyst = VolatilityAnalyst()
    report = analyst.analyze(
        {
            "symbol": "EURUSD",
            "atr": 0.008,
            "historical_volatility": 0.12,
            "implied_volatility": 0.15,
            "current_price": 1.0850,
        }
    )
    assert isinstance(report, AnalystReport)
    assert report.direction in ("BULLISH", "BEARISH", "NEUTRAL")


def test_news_sentiment_analyst_produces_report():
    """NewsSentimentAnalyst must produce structured report."""
    analyst = NewsSentimentAnalyst()
    report = analyst.analyze(
        {
            "symbol": "EURUSD",
            "headlines": ["ECB holds rates", "Eurozone PMI beats estimates"],
            "sentiment_score": 0.65,
            "fear_greed_index": 0.7,
        }
    )
    assert isinstance(report, AnalystReport)
    assert report.direction in ("BULLISH", "BEARISH", "NEUTRAL")


def test_market_lead_synthesizes_consensus():
    """MarketLead must produce CommitteeDecision with consensus."""
    lead = MarketLead()
    # create_department returns department, we ignore it
    lead.create_department()
    decision = lead.synthesize(
        market_data={
            "symbol": "EURUSD",
            "ohlc": [],
            "trend": "UP",
            "rsi": 60.0,
            "macd": 0.001,
            "support": 1.0750,
            "resistance": 1.0950,
            "current_price": 1.0850,
            "swing_high": 1.0950,
            "swing_low": 1.0750,
            "atr": 0.008,
            "historical_volatility": 0.12,
            "implied_volatility": 0.15,
            "headlines": [],
            "sentiment_score": 0.5,
            "fear_greed_index": 0.5,
        }
    )
    assert isinstance(decision, CommitteeDecision)
    assert decision.department == "market"
    assert len(decision.reports) == 5


def test_committee_decision_serializes():
    """CommitteeDecision must serialize to dict."""
    lead = MarketLead()
    lead.create_department()
    decision = lead.synthesize(
        market_data={
            "symbol": "EURUSD",
            "ohlc": [],
            "trend": "UP",
            "rsi": 60.0,
            "macd": 0.001,
            "support": 1.0750,
            "resistance": 1.0950,
            "current_price": 1.0850,
            "swing_high": 1.0950,
            "swing_low": 1.0750,
            "atr": 0.008,
            "historical_volatility": 0.12,
            "implied_volatility": 0.15,
            "headlines": [],
            "sentiment_score": 0.5,
            "fear_greed_index": 0.5,
        }
    )
    data = decision.to_dict()
    assert data["department"] == "market"
    assert "direction" in data
    assert "confidence" in data
    assert "agreements" in data
    assert "conflicts" in data


def test_market_lead_permission_required():
    """MarketLead must require ANALYZE_MARKET permission."""
    lead = MarketLead()
    try:
        require_permission(lead, "ANALYZE_MARKET")
    except AgentPermissionError:
        pytest.fail("MarketLead should have ANALYZE_MARKET permission")


def test_market_lead_can_handle():
    """MarketLead must implement can_handle."""
    lead = MarketLead()
    assert lead.can_handle("market_analysis") is True
    assert lead.can_handle("risk_analysis") is False
