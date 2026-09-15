# -*- coding: utf-8 -*-
"""Tests for PRD_V2 §25 — dead placeholder agents must be honest.

The Fundamental/Sentiment analyst agents have no data feeds wired yet. They
must NOT fabricate neutral analysis; they must return an explicit UNSUPPORTED
status while remaining registrable in the agent registry.
"""

from __future__ import annotations

from agents.base import (
    AgentRegistry,
    FundamentalAnalystAgent,
    SentimentAnalystAgent,
    TechnicalAnalystAgent,
)


def test_fundamental_agent_returns_unsupported():
    agent = FundamentalAnalystAgent()
    result = agent.analyze({"detected_events": []})
    assert result["status"] == "UNSUPPORTED"
    assert result["supported"] is False
    assert result["confidence"] == 0.0
    # No fabricated analysis text.
    assert all("not implemented" in r for r in result["reasons"])


def test_sentiment_agent_returns_unsupported():
    agent = SentimentAnalystAgent()
    result = agent.analyze({"detected_events": []})
    assert result["status"] == "UNSUPPORTED"
    assert result["supported"] is False
    assert result["confidence"] == 0.0


def test_event_count_is_integer():
    agent = FundamentalAnalystAgent()
    result = agent.analyze({"detected_events": [1, 2, 3]})
    assert result["event_count"] == 3


def test_registry_still_works_with_placeholders():
    AgentRegistry.reset()
    try:
        registry = AgentRegistry()
        registry.register(TechnicalAnalystAgent())
        registry.register(FundamentalAnalystAgent())
        registry.register(SentimentAnalystAgent())
        assert registry.count() == 3
        assert registry.get("fundamental_analyst") is not None
        assert registry.get("sentiment_analyst") is not None
    finally:
        AgentRegistry.reset()


def test_technical_analyst_agent_unaffected():
    agent = TechnicalAnalystAgent()
    result = agent.analyze({"detected_events": []})
    assert result["signal"] == "NEUTRAL"
    assert "status" not in result or result.get("status") != "UNSUPPORTED"
