# -*- coding: utf-8 -*-
"""Tests for NewsSentimentAgent."""

from __future__ import annotations

import pytest

from agents.analysts.news_agent import NewsItem, NewsSentimentAgent, NewsSentimentInput


@pytest.fixture
def agent():
    """Create a fresh NewsSentimentAgent."""
    return NewsSentimentAgent()


class TestNewsSentimentAgentBasics:
    def test_agent_metadata(self, agent):
        assert agent.name == "news_sentiment"
        assert agent.agent_type == "news"
        assert len(agent.capabilities) >= 2

    def test_can_handle_news_events(self, agent):
        assert agent.can_handle("NEWS_HEADLINE", {})
        assert agent.can_handle("SOCIAL_SENTIMENT", {})

    def test_can_handle_rejects_others(self, agent):
        assert not agent.can_handle("TREND_BULLISH", {})


class TestNewsInput:
    def test_parse_news_items_from_dicts(self, agent):
        items = [
            {"headline": "Market up", "sentiment": 0.8, "impact": "HIGH"},
            {"headline": "Market down", "sentiment": -0.6, "impact": "MEDIUM"},
        ]
        parsed = agent._parse_news_items(items)
        assert len(parsed) == 2
        assert parsed[0].headline == "Market up"
        assert parsed[1].sentiment == -0.6

    def test_parse_news_items_from_newsitem_objects(self, agent):
        items = [
            NewsItem(headline="Test", sentiment=0.5, impact="LOW"),
        ]
        parsed = agent._parse_news_items(items)
        assert len(parsed) == 1
        assert parsed[0].headline == "Test"

    def test_parse_news_items_empty(self, agent):
        parsed = agent._parse_news_items([])
        assert parsed == []

    def test_parse_news_items_none(self, agent):
        parsed = agent._parse_news_items(None)
        assert parsed == []

    def test_input_from_dict(self, agent):
        data = {
            "news_items": [{"headline": "Test", "sentiment": 0.7, "impact": "HIGH"}],
            "economic_events": [{"impact": "CRITICAL"}],
        }
        inp = agent._input({"sentiment": data})
        assert len(inp.news_items) == 1
        assert len(inp.economic_events) == 1

    def test_input_from_dataclass(self, agent):
        inp = NewsSentimentInput(
            news_items=[NewsItem(headline="Test", sentiment=0.5)],
            economic_events=[],
        )
        result = agent._input({"sentiment": inp})
        assert len(result.news_items) == 1

    def test_input_defaults(self, agent):
        inp = agent._input({})
        assert inp.news_items == []
        assert inp.economic_events == []


class TestNewsSentimentAnalysis:
    def test_bullish_sentiment(self, agent):
        data = {
            "news_items": [
                {"headline": "Strong gains", "sentiment": 0.9, "impact": "HIGH"},
                {"headline": "Economic boost", "sentiment": 0.7, "impact": "MEDIUM"},
            ],
        }
        result = agent.analyze({"sentiment": data})
        assert result["signal"] == "BULLISH"
        assert result["confidence"] >= 0.7

    def test_bearish_sentiment(self, agent):
        data = {
            "news_items": [
                {"headline": "Market crash", "sentiment": -0.85, "impact": "HIGH"},
                {"headline": "Economic slowdown", "sentiment": -0.6, "impact": "MEDIUM"},
            ],
        }
        result = agent.analyze({"sentiment": data})
        assert result["signal"] == "BEARISH"
        assert result["confidence"] >= 0.7

    def test_neutral_sentiment(self, agent):
        data = {
            "news_items": [
                {"headline": "Stable", "sentiment": 0.1, "impact": "LOW"},
                {"headline": "Neutral", "sentiment": -0.05, "impact": "LOW"},
            ],
        }
        result = agent.analyze({"sentiment": data})
        assert result["signal"] == "NEUTRAL"
        assert 0.4 < result["confidence"] < 0.8

    def test_critical_event_override(self, agent):
        data = {
            "news_items": [{"headline": "Minor news", "sentiment": 0.1, "impact": "LOW"}],
            "economic_events": [{"impact": "CRITICAL", "sentiment": 0.5}],
        }
        result = agent.analyze({"sentiment": data})
        assert result["signal"] == "BEARISH"
        assert "Critical impact" in result["reasoning"][0] or len(result["reasoning"]) > 1

    def test_high_impact_event_detection(self, agent):
        data = {
            "economic_events": [
                {"impact": "HIGH", "headline": "Fed decision"},
                {"impact": "MEDIUM", "headline": "Jobs report"},
            ],
        }
        result = agent.analyze({"sentiment": data})
        assert result["metrics"]["high_impact_count"] >= 1

    def test_metrics_structure(self, agent):
        data = {
            "news_items": [{"headline": "Test", "sentiment": 0.5, "impact": "MEDIUM"}],
            "economic_events": [{"impact": "HIGH"}],
        }
        result = agent.analyze({"sentiment": data})
        metrics = result["metrics"]
        assert "news_count" in metrics
        assert "events_count" in metrics
        assert "high_impact_count" in metrics
        assert "avg_sentiment" in metrics
        assert "weighted_impact" in metrics

    def test_empty_input_handling(self, agent):
        result = agent.analyze({"sentiment": {}})
        assert result["signal"] == "NEUTRAL"
        assert any("No news items" in r for r in result["reasoning"])

    def test_invalid_input_degradation(self, agent):
        result = agent.analyze({"sentiment": None})
        assert result["signal"] in ["UNKNOWN", "NEUTRAL"]
        assert result["confidence"] >= 0.0

    def test_sentiment_clamping(self, agent):
        data = {
            "news_items": [
                {"headline": "Extreme", "sentiment": 5.0, "impact": "LOW"},
            ],
        }
        result = agent.analyze({"sentiment": data})
        assert result["metrics"]["avg_sentiment"] <= 1.0

    def test_output_schema_compliance(self, agent):
        data = {
            "news_items": [{"headline": "Test", "sentiment": 0.3, "impact": "LOW"}],
        }
        result = agent.analyze({"sentiment": data})
        assert "agent" in result
        assert "signal" in result
        assert "confidence" in result
        assert "reasoning" in result
        assert "metrics" in result
        assert result["agent"] == "news_sentiment"
        assert isinstance(result["reasoning"], list)
        assert isinstance(result["metrics"], dict)

    def test_mixed_sentiments(self, agent):
        data = {
            "news_items": [
                {"headline": "Up", "sentiment": 0.6, "impact": "MEDIUM"},
                {"headline": "Down", "sentiment": -0.5, "impact": "MEDIUM"},
                {"headline": "Neutral", "sentiment": 0.0, "impact": "LOW"},
            ],
        }
        result = agent.analyze({"sentiment": data})
        expected_avg = (0.6 - 0.5 + 0.0) / 3
        assert abs(result["metrics"]["avg_sentiment"] - expected_avg) < 0.01
