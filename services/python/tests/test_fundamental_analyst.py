# -*- coding: utf-8 -*-
"""Tests for FundamentalAnalystAgent."""

from __future__ import annotations

from agents.analysts.fundamental_analyst import FundamentalAnalystAgent

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_hawkish_events() -> list[dict]:
    """Hawkish events — Fed rate hike expectations."""
    return [
        {
            "title": "Fed Interest Rate Decision: Rate Hike",
            "currency": "USD",
            "impact": "CRITICAL",
            "actual": "5.50%",
            "forecast": "5.25%",
            "previous": "5.25%",
            "sentiment": 0.5,
            "category": "MONETARY_POLICY",
        },
        {
            "title": "Fed Chair Press Conference: Hawkish Tone",
            "currency": "USD",
            "impact": "HIGH",
            "sentiment": 0.3,
        },
    ]


def _make_dovish_events() -> list[dict]:
    """Dovish events — Fed rate cut expectations."""
    return [
        {
            "title": "Fed Interest Rate Decision: Rate Cut",
            "currency": "USD",
            "impact": "CRITICAL",
            "actual": "4.75%",
            "forecast": "5.00%",
            "previous": "5.00%",
            "sentiment": -0.5,
            "category": "MONETARY_POLICY",
        },
        {
            "title": "FOMC Statement: Dovish, Accommodative Policy",
            "currency": "USD",
            "impact": "HIGH",
            "sentiment": -0.3,
        },
    ]


def _make_safe_haven_events() -> list[dict]:
    """Geopolitical crisis events."""
    return [
        {
            "title": "Geopolitical Crisis: War Escalation",
            "currency": "USD",
            "impact": "HIGH",
            "sentiment": -0.4,
        },
        {
            "title": "Recession Fear: Bank Collapse",
            "currency": "USD",
            "impact": "HIGH",
            "sentiment": -0.2,
        },
    ]


def _make_cpi_deviation_events() -> list[dict]:
    """CPI above forecast — USD bullish."""
    return [
        {
            "title": "Core CPI m/m",
            "currency": "USD",
            "impact": "HIGH",
            "actual": "0.5%",
            "forecast": "0.3%",
            "previous": "0.2%",
            "sentiment": 0.0,
        },
    ]


def _make_nfp_miss_events() -> list[dict]:
    """NFP below forecast — USD bearish."""
    return [
        {
            "title": "Nonfarm Payrolls",
            "currency": "USD",
            "impact": "HIGH",
            "actual": "120K",
            "forecast": "180K",
            "previous": "200K",
            "sentiment": 0.0,
        },
    ]


# ---------------------------------------------------------------------------
# Tests — signal direction
# ---------------------------------------------------------------------------


class TestFundamentalSignal:
    """Test fundamental signal direction logic."""

    def setup_method(self) -> None:
        self.agent = FundamentalAnalystAgent()

    def test_hawkish_events_produce_bearish_xauusd(self) -> None:
        """Hawkish Fed → USD strong → XAUUSD bearish."""
        ctx = {
            "economic_events": _make_hawkish_events(),
            "symbol": "XAUUSD",
        }
        result = self.agent.analyze(ctx)
        assert result["signal"] == "BEARISH"
        assert result["confidence"] >= 0.68
        assert result["agent"] == "fundamental_analyst"
        assert result["metrics"]["hawkish_score"] > 0

    def test_dovish_events_produce_bullish_xauusd(self) -> None:
        """Dovish Fed → USD weak → XAUUSD bullish."""
        ctx = {
            "economic_events": _make_dovish_events(),
            "symbol": "XAUUSD",
        }
        result = self.agent.analyze(ctx)
        assert result["signal"] == "BULLISH"
        assert result["confidence"] >= 0.68
        assert result["metrics"]["dovish_score"] > 0

    def test_safe_haven_events_produce_bullish_xauusd(self) -> None:
        """Geopolitical crisis → safe-haven demand → XAUUSD bullish."""
        ctx = {
            "economic_events": _make_safe_haven_events(),
            "symbol": "XAUUSD",
        }
        result = self.agent.analyze(ctx)
        assert result["signal"] == "BULLISH"
        assert result["confidence"] >= 0.68
        assert result["metrics"]["safe_haven_score"] > 0

    def test_cpi_above_forecast_bearish_xauusd(self) -> None:
        """CPI above forecast → USD bullish → XAUUSD bearish."""
        ctx = {
            "economic_events": _make_cpi_deviation_events(),
            "symbol": "XAUUSD",
        }
        result = self.agent.analyze(ctx)
        assert result["signal"] == "BEARISH"
        assert result["confidence"] >= 0.68
        assert result["metrics"]["hawkish_score"] > 0

    def test_nfp_miss_bullish_xauusd(self) -> None:
        """NFP below forecast → USD bearish → XAUUSD bullish."""
        ctx = {
            "economic_events": _make_nfp_miss_events(),
            "symbol": "XAUUSD",
        }
        result = self.agent.analyze(ctx)
        assert result["signal"] == "BULLISH"
        assert result["confidence"] >= 0.68

    def test_no_events_returns_neutral(self) -> None:
        """No events → fail-closed NEUTRAL confidence 0.55."""
        ctx = {"economic_events": [], "symbol": "XAUUSD"}
        result = self.agent.analyze(ctx)
        assert result["signal"] == "NEUTRAL"
        assert result["confidence"] == 0.55
        assert "No economic events" in result["reasons"][0]

    def test_empty_context_returns_neutral(self) -> None:
        """Empty context → NEUTRAL confidence 0.55."""
        result = self.agent.analyze({})
        assert result["signal"] == "NEUTRAL"
        assert result["confidence"] == 0.55


# ---------------------------------------------------------------------------
# Tests — can_handle routing
# ---------------------------------------------------------------------------


class TestCanHandle:
    """Test event routing eligibility."""

    def setup_method(self) -> None:
        self.agent = FundamentalAnalystAgent()

    def test_handles_economic_event(self) -> None:
        assert self.agent.can_handle("ECONOMIC_CPI", {}) is True

    def test_handles_earnings_event(self) -> None:
        assert self.agent.can_handle("EARNINGS_REPORT", {}) is True

    def test_handles_interest_rate_event(self) -> None:
        assert self.agent.can_handle("INTEREST_RATE_FED", {}) is True

    def test_handles_fomc_event(self) -> None:
        assert self.agent.can_handle("FOMC_STATEMENT", {}) is True

    def test_handles_context_with_events(self) -> None:
        """Even without matching prefix, context with events should handle."""
        ctx = {"economic_events": [{"title": "CPI", "impact": "HIGH"}]}
        assert self.agent.can_handle("MARKET_CHECK", ctx) is True

    def test_rejects_non_fundamental_event(self) -> None:
        """Technical events should not be handled."""
        assert self.agent.can_handle("TREND_UP", {}) is False

    def test_rejects_momentum_event(self) -> None:
        assert self.agent.can_handle("MOMENTUM_RSI", {}) is False


# ---------------------------------------------------------------------------
# Tests — output schema
# ---------------------------------------------------------------------------


class TestOutputSchema:
    """Test output dict has required keys."""

    def setup_method(self) -> None:
        self.agent = FundamentalAnalystAgent()

    def test_output_has_required_keys(self) -> None:
        ctx = {"economic_events": _make_hawkish_events()}
        result = self.agent.analyze(ctx)
        for key in ("agent", "signal", "confidence", "reasons", "metrics"):
            assert key in result, f"Missing key: {key}"

    def test_output_agent_name(self) -> None:
        result = self.agent.analyze({"economic_events": []})
        assert result["agent"] == "fundamental_analyst"

    def test_output_metrics_keys(self) -> None:
        ctx = {"economic_events": _make_hawkish_events()}
        result = self.agent.analyze(ctx)
        metrics = result["metrics"]
        for key in (
            "event_count",
            "high_impact_count",
            "hawkish_score",
            "dovish_score",
            "safe_haven_score",
            "net_fundamental_score",
        ):
            assert key in metrics, f"Missing metric: {key}"

    def test_confidence_capped(self) -> None:
        """Confidence should not exceed 0.85."""
        ctx = {"economic_events": _make_hawkish_events() * 5}
        result = self.agent.analyze(ctx)
        assert result["confidence"] <= 0.85


# ---------------------------------------------------------------------------
# Tests — fail-closed behavior
# ---------------------------------------------------------------------------


class TestFailClosed:
    """Test graceful degradation on malformed input."""

    def setup_method(self) -> None:
        self.agent = FundamentalAnalystAgent()

    def test_malformed_events_dont_crash(self) -> None:
        """Malformed event dicts should not crash the agent."""
        ctx = {
            "economic_events": [
                "not a dict",
                {"title": None, "impact": 123},
                {"actual": "N/A", "forecast": None},
            ],
        }
        result = self.agent.analyze(ctx)
        assert result["agent"] == "fundamental_analyst"
        assert result["signal"] in ("NEUTRAL", "BULLISH", "BEARISH")

    def test_none_context_returns_neutral(self) -> None:
        """None-like context should return NEUTRAL safely."""
        result = self.agent.analyze({"economic_events": None})
        assert result["signal"] == "NEUTRAL"
        assert result["confidence"] == 0.55

    def test_string_sentiment_fallback(self) -> None:
        """If actual/forecast are non-numeric, use sentiment field."""
        ctx = {
            "economic_events": [
                {
                    "title": "Fed Rate Decision: Hawkish",
                    "impact": "HIGH",
                    "actual": "N/A",
                    "forecast": "N/A",
                    "sentiment": 0.6,
                },
            ],
        }
        result = self.agent.analyze(ctx)
        assert result["signal"] in ("BEARISH", "NEUTRAL")
        assert result["metrics"]["hawkish_score"] >= 0

    def test_risk_sentiment_context(self) -> None:
        """Risk-off sentiment in context should boost safe-haven score."""
        ctx = {
            "economic_events": _make_hawkish_events(),
            "risk_sentiment": -0.8,
            "symbol": "XAUUSD",
        }
        result = self.agent.analyze(ctx)
        assert result["metrics"]["safe_haven_score"] > 0


# ---------------------------------------------------------------------------
# Tests — agent metadata
# ---------------------------------------------------------------------------


class TestAgentMetadata:
    """Test agent registration metadata."""

    def test_agent_name(self) -> None:
        agent = FundamentalAnalystAgent()
        assert agent.name == "fundamental_analyst"

    def test_agent_type(self) -> None:
        agent = FundamentalAnalystAgent()
        assert agent.agent_type == "fundamental"

    def test_agent_priority(self) -> None:
        from agents.base import AgentPriority

        agent = FundamentalAnalystAgent()
        assert agent.priority == AgentPriority.HIGH

    def test_agent_has_capabilities(self) -> None:
        agent = FundamentalAnalystAgent()
        assert len(agent.capabilities) >= 3

    def test_to_dict_serializable(self) -> None:
        agent = FundamentalAnalystAgent()
        d = agent.to_dict()
        assert d["name"] == "fundamental_analyst"
        assert d["agent_type"] == "fundamental"


# ---------------------------------------------------------------------------
# Tests — EconomicEvent parsing
# ---------------------------------------------------------------------------


class TestEconomicEventParsing:
    """Test EconomicEvent dataclass parsing."""

    def test_parse_events_from_dicts(self) -> None:
        raw = [
            {"title": "CPI", "impact": "HIGH", "actual": "0.5%"},
            {"title": "NFP", "impact": "CRITICAL"},
        ]
        events = FundamentalAnalystAgent._parse_events(raw)
        assert len(events) == 2
        assert events[0].title == "CPI"
        assert events[0].is_high_impact is True

    def test_parse_events_empty(self) -> None:
        assert FundamentalAnalystAgent._parse_events(None) == []
        assert FundamentalAnalystAgent._parse_events([]) == []
        assert FundamentalAnalystAgent._parse_events("not a list") == []

    def test_parse_events_non_dict_items(self) -> None:
        """Non-dict items should be skipped."""
        raw = ["string", 123, None, {"title": "CPI"}]
        events = FundamentalAnalystAgent._parse_events(raw)
        assert len(events) == 1
        assert events[0].title == "CPI"

    def test_text_sentiment_hawkish(self) -> None:
        score = FundamentalAnalystAgent._text_sentiment("Fed Rate Decision: Rate Hike")
        assert score > 0  # hawkish → positive

    def test_text_sentiment_dovish(self) -> None:
        score = FundamentalAnalystAgent._text_sentiment("FOMC Statement: Dovish, Rate Cut")
        assert score < 0  # dovish → negative

    def test_text_sentiment_safe_haven(self) -> None:
        score = FundamentalAnalystAgent._text_sentiment("Geopolitical War Crisis")
        assert score < 0  # safe haven → negative for USD

    def test_text_sentiment_empty(self) -> None:
        assert FundamentalAnalystAgent._text_sentiment("") == 0.0

    def test_parse_numeric(self) -> None:
        assert FundamentalAnalystAgent._parse_numeric("0.5%") == 0.5
        assert FundamentalAnalystAgent._parse_numeric("5.50") == 5.50
        assert FundamentalAnalystAgent._parse_numeric("120K") == 120.0
        assert FundamentalAnalystAgent._parse_numeric("N/A") is None
        assert FundamentalAnalystAgent._parse_numeric("") is None
