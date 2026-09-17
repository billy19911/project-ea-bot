# -*- coding: utf-8 -*-
"""Tests for Phase 2 — MarketLead intelligence upgrade.

Covers the upgraded MarketLead (src/market/intelligence.py):

* identity — registered as ``agent_type="department_lead"`` so the
  Supervisor detects and delegates market events to it;
* market regime detection — TRENDING / RANGING / NEWS_SHOCK / BALANCED;
* adaptive specialist weighting per regime (weights sum to 1.0);
* delegation to the REAL production specialists (injectable for tests);
* Supervisor-compatible ``analyze`` return contract (plain dict);
* backward compatibility — the legacy ``synthesize`` committee API and
  the legacy ``can_handle("market_analysis")`` task-type contract.
"""

from __future__ import annotations

import pytest

from agents.base import AgentPriority, AgentRegistry, BaseAgent
from agents.supervisor import SupervisorAgent
from market.intelligence import CommitteeDecision, MarketLead

SPECIALIST_NAMES = {
    "technical_analyst",
    "momentum_analyst",
    "structure_analyst",
    "volatility_analyst",
    "news_sentiment",
    "fundamental_analyst",
}


class _StubSpecialist(BaseAgent):
    """Deterministic specialist used to observe delegation."""

    def __init__(self, name: str, signal: str = "NEUTRAL", confidence: float = 0.5) -> None:
        super().__init__(name=name, agent_type="specialist", priority=AgentPriority.NORMAL)
        self.signal = signal
        self.confidence = confidence
        self.calls = 0

    def analyze(self, context: dict) -> dict:
        self.calls += 1
        return {
            "agent": self.name,
            "signal": self.signal,
            "confidence": self.confidence,
            "reasoning": f"{self.name} stub",
        }


@pytest.fixture(autouse=True)
def _reset_registry():
    AgentRegistry.reset()
    yield
    AgentRegistry.reset()


# ---------------------------------------------------------------------------
# Identity — Supervisor compatibility
# ---------------------------------------------------------------------------


def test_market_lead_is_department_lead():
    lead = MarketLead()
    assert lead.name == "market_lead"
    assert lead.agent_type == "department_lead"
    assert lead.role == "department_lead"


def test_market_lead_to_dict_has_department_metadata():
    data = MarketLead().to_dict()
    assert data["role"] == "department_lead"
    assert data["department"] == "market"


def test_can_handle_market_events():
    lead = MarketLead()
    for event in (
        "TREND_BULLISH",
        "MOMENTUM_BEARISH",
        "RSI_OVERBOUGHT",
        "STOCH_OVERSOLD",
        "EMA_CROSSOVER",
        "MACD_CROSSOVER",
        "BREAKOUT",
        "BREAKDOWN",
        "REVERSAL",
        "STRUCTURE_BREAK",
        "PRICE_ACTION",
        "LEVEL_SCAN",
        "MARKET_CHECK",
        "VOLATILITY_SPIKE",
        "NEWS_FLASH",
        "SOCIAL_BUZZ",
        "EARNINGS_BEAT",
        "ECONOMIC_CPI",
        "GAP_UP",
        "DOJI",
    ):
        assert lead.can_handle(event, {}) is True, event


def test_can_handle_rejects_risk_events():
    lead = MarketLead()
    for event in ("DRAWDOWN_ALERT", "EXPOSURE_LIMIT", "LIQUIDITY_LOW", "RISK_CHECK"):
        assert lead.can_handle(event, {}) is False, event


def test_can_handle_legacy_task_type():
    lead = MarketLead()
    assert lead.can_handle("market_analysis") is True
    assert lead.can_handle("risk_analysis") is False


# ---------------------------------------------------------------------------
# Market regime detection
# ---------------------------------------------------------------------------


def test_detect_regime_trending_from_adx():
    lead = MarketLead()
    context = {"market_state": {"adx_value": 32.0, "trend_direction": "BULLISH"}}
    assert lead.detect_regime(context) == "TRENDING"


def test_detect_regime_trending_from_market_state_object():
    class _MarketState:
        adx_value = 28.0
        trend_direction = "BEARISH"

    assert MarketLead().detect_regime({"market_state": _MarketState()}) == "TRENDING"


def test_detect_regime_trending_from_direction_without_adx():
    assert MarketLead().detect_regime({"trend": "UP"}) == "TRENDING"


def test_detect_regime_ranging():
    context = {"market_state": {"adx_value": 14.0, "trend_direction": "NEUTRAL"}}
    assert MarketLead().detect_regime(context) == "RANGING"


def test_detect_regime_news_shock_from_high_impact_event():
    context = {"economic_events": [{"title": "Non-Farm Payrolls", "impact": "HIGH"}]}
    assert MarketLead().detect_regime(context) == "NEWS_SHOCK"


def test_detect_regime_news_shock_from_critical_news():
    context = {"news_items": [{"title": "Central bank emergency meeting", "impact": "CRITICAL"}]}
    assert MarketLead().detect_regime(context) == "NEWS_SHOCK"


def test_detect_regime_news_shock_from_volatility_spike():
    assert MarketLead().detect_regime({"volatility": {"signal": "HIGH"}}) == "NEWS_SHOCK"


def test_detect_regime_balanced_fallback():
    assert MarketLead().detect_regime({}) == "BALANCED"


# ---------------------------------------------------------------------------
# Adaptive weighting
# ---------------------------------------------------------------------------


def test_adaptive_weights_sum_to_one_for_every_regime():
    lead = MarketLead()
    for regime in ("TRENDING", "RANGING", "NEWS_SHOCK", "BALANCED"):
        weights = lead.get_adaptive_weights(regime)
        assert set(weights) == SPECIALIST_NAMES, regime
        assert abs(sum(weights.values()) - 1.0) < 1e-9, regime


def test_adaptive_weights_shift_with_regime():
    lead = MarketLead()
    trending = lead.get_adaptive_weights("TRENDING")
    ranging = lead.get_adaptive_weights("RANGING")
    shock = lead.get_adaptive_weights("NEWS_SHOCK")

    # Trend following favours technical/momentum; news shock mutes them.
    assert trending["technical_analyst"] > shock["technical_analyst"]
    assert trending["momentum_analyst"] > shock["momentum_analyst"]
    # News shock favours news + fundamental.
    assert shock["news_sentiment"] > trending["news_sentiment"]
    assert shock["fundamental_analyst"] > trending["fundamental_analyst"]
    # Ranging favours structure (S/R) over news shock.
    assert ranging["structure_analyst"] > shock["structure_analyst"]


def test_adaptive_weights_unknown_regime_falls_back_to_balanced():
    lead = MarketLead()
    assert lead.get_adaptive_weights("WHATEVER") == lead.get_adaptive_weights("BALANCED")


# ---------------------------------------------------------------------------
# analyze() — Supervisor-compatible delegation
# ---------------------------------------------------------------------------


def test_analyze_returns_supervisor_compatible_dict():
    lead = MarketLead(specialists={"technical_analyst": _StubSpecialist("technical_analyst")})
    result = lead.analyze({"event_type": "TREND_BULLISH"})

    assert result["agent"] == "market_lead"
    assert result["role"] == "department_lead"
    assert result["department"] == "market"
    assert result["signal"] in ("BULLISH", "BEARISH", "NEUTRAL")
    assert 0.0 <= result["confidence"] <= 1.0
    assert isinstance(result["reasons"], list) and result["reasons"]
    assert result["regime"] in ("TRENDING", "RANGING", "NEWS_SHOCK", "BALANCED")
    assert "specialist_results" in result
    assert "unresolved_conflict" in result


def test_analyze_delegates_to_injected_specialists():
    tech = _StubSpecialist("technical_analyst", signal="BULLISH", confidence=0.9)
    mom = _StubSpecialist("momentum_analyst", signal="BULLISH", confidence=0.8)
    lead = MarketLead(specialists={"technical_analyst": tech, "momentum_analyst": mom})

    result = lead.analyze({"event_type": "TREND_BULLISH", "market_state": {"adx_value": 30.0}})

    assert tech.calls == 1
    assert mom.calls == 1
    assert result["regime"] == "TRENDING"
    assert result["specialist_results"]["technical_analyst"]["signal"] == "BULLISH"
    assert result["specialist_results"]["momentum_analyst"]["signal"] == "BULLISH"
    assert result["signal"] == "BULLISH"


def test_analyze_uses_production_specialists_by_default():
    lead = MarketLead()
    prices = [1.0 + 0.001 * i for i in range(60)]
    result = lead.analyze({"event_type": "MOMENTUM_BULLISH", "prices": prices, "symbol": "EURUSD"})

    assert set(result["specialist_results"]) == SPECIALIST_NAMES
    for specialist_result in result["specialist_results"].values():
        assert "signal" in specialist_result


def test_analyze_returns_neutral_without_directional_evidence():
    stubs = {name: _StubSpecialist(name) for name in SPECIALIST_NAMES}
    lead = MarketLead(specialists=stubs)
    result = lead.analyze({"event_type": "MARKET_CHECK"})

    assert result["signal"] == "NEUTRAL"
    assert result["confidence"] == 0.0


def test_analyze_fail_closed_without_specialists():
    lead = MarketLead(specialists={})
    result = lead.analyze({"event_type": "MARKET_CHECK"})

    assert result["signal"] == "NEUTRAL"
    assert result["specialist_results"] == {}


def test_analyze_isolates_specialist_failure():
    class _BoomSpecialist(_StubSpecialist):
        def analyze(self, context: dict) -> dict:
            raise RuntimeError("boom")

    lead = MarketLead(
        specialists={
            "technical_analyst": _BoomSpecialist("technical_analyst"),
            "momentum_analyst": _StubSpecialist(
                "momentum_analyst", signal="BULLISH", confidence=0.8
            ),
        }
    )
    result = lead.analyze({"event_type": "TREND_BULLISH"})

    failed = result["specialist_results"]["technical_analyst"]
    assert failed["status"] == "ERROR"
    assert failed["signal"] == "NEUTRAL"
    # The healthy specialist still drives the consensus.
    assert result["signal"] == "BULLISH"


def test_analyze_records_dissent_on_conflict():
    lead = MarketLead(
        specialists={
            "technical_analyst": _StubSpecialist(
                "technical_analyst", signal="BULLISH", confidence=0.9
            ),
            "momentum_analyst": _StubSpecialist(
                "momentum_analyst", signal="BEARISH", confidence=0.3
            ),
        }
    )
    result = lead.analyze({"event_type": "TREND_BULLISH"})

    assert result["signal"] == "BULLISH"
    assert result["unresolved_conflict"] is True
    assert any("momentum_analyst" in reason for reason in result["reasons"])


# ---------------------------------------------------------------------------
# Backward compatibility — legacy committee API
# ---------------------------------------------------------------------------


def test_legacy_synthesize_still_returns_committee_decision():
    lead = MarketLead()
    decision = lead.synthesize(
        {
            "symbol": "EURUSD",
            "trend": "UP",
            "rsi": 65.0,
            "macd": 0.002,
            "support": 1.0750,
            "resistance": 1.0950,
            "current_price": 1.0850,
            "sentiment_score": 0.65,
            "historical_volatility": 0.12,
            "implied_volatility": 0.15,
        }
    )

    assert isinstance(decision, CommitteeDecision)
    assert decision.department == "market"
    assert len(decision.reports) == 5


def test_legacy_department_still_has_five_specialists():
    lead = MarketLead()
    department = lead.create_department()
    assert len(department.specialists) == 5


# ---------------------------------------------------------------------------
# Supervisor delegation end-to-end
# ---------------------------------------------------------------------------


def test_supervisor_delegates_to_market_lead():
    registry = AgentRegistry()
    lead = MarketLead(
        specialists={
            "technical_analyst": _StubSpecialist(
                "technical_analyst", signal="BULLISH", confidence=0.9
            )
        }
    )
    registry.register(lead)

    supervisor = SupervisorAgent()
    supervisor._registry_cache = registry

    result = supervisor.analyze({"event_type": "TREND_BULLISH"})

    assert "market_lead" in result["agent_results"]
    lead_result = result["agent_results"]["market_lead"]
    assert lead_result["specialist_results"]["technical_analyst"]["signal"] == "BULLISH"
    assert lead_result["signal"] == "BULLISH"
