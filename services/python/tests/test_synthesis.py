# -*- coding: utf-8 -*-
"""Tests for Phase 12 supervisor planning and synthesis."""

from __future__ import annotations

from agents import AgentSynthesizer, SynthesisResult, TradeProposal
from agents.synthesis import TradeDirection
from trading.events import DetectedEvent, EventTypes


def _output(signal: str, confidence: float, reasoning: str = "test") -> dict:
    """Build a compact agent output fixture."""
    return {"signal": signal, "confidence": confidence, "reasoning": reasoning}


def test_plan_agents_returns_all_core_market_agents():
    """Planning covers structure, momentum, volatility, and news domains."""
    plan = AgentSynthesizer().plan_agents("TREND_BULLISH")

    assert plan == [
        "structure_analyst",
        "momentum_analyst",
        "volatility_analyst",
        "news_sentiment",
    ]


def test_plan_agents_filters_to_available_agents():
    """Planning only schedules registered agents when availability is supplied."""
    plan = AgentSynthesizer().plan_agents(
        "TREND_BULLISH", available_agents=["momentum_analyst", "custom_agent"]
    )

    assert plan == ["momentum_analyst", "custom_agent"]


def test_aggregate_signals_counts_directions_and_confidence():
    """Aggregation classifies outputs and calculates weighted totals."""
    result = AgentSynthesizer().aggregate_signals(
        {
            "structure": _output("BULLISH", 0.8),
            "momentum": _output("BEARISH", 0.6),
            "volatility": _output("HIGH", 0.7),
        }
    )

    assert result["bullish_count"] == 1
    assert result["bearish_count"] == 1
    assert result["neutral_count"] == 1
    assert result["weighted_bullish"] == 0.8
    assert result["weighted_bearish"] == 0.6
    assert abs(result["avg_confidence"] - 0.7) < 0.0001


def test_aggregate_signals_accepts_reasons_list():
    """Aggregation normalises legacy reasons-list output."""
    result = AgentSynthesizer().aggregate_signals(
        {"structure": {"signal": "BULLISH", "confidence": 0.8, "reasons": ["EMA", "ADX"]}}
    )

    assert result["signals"][0]["reasoning"] == "EMA; ADX"


def test_detect_conflicts_finds_bullish_bearish_pair():
    """Opposing directional agent outputs are surfaced."""
    conflicts = AgentSynthesizer().detect_conflicts(
        {"structure": _output("BULLISH", 0.8), "momentum": _output("BEARISH", 0.7)}
    )

    assert len(conflicts) == 1
    assert "structure=BULLISH" in conflicts[0]
    assert "momentum=BEARISH" in conflicts[0]


def test_detect_conflicts_ignores_neutral_signal():
    """Neutral volatility regime does not conflict with direction."""
    conflicts = AgentSynthesizer().detect_conflicts(
        {"structure": _output("BULLISH", 0.8), "volatility": _output("HIGH", 0.7)}
    )

    assert conflicts == []


def test_generate_buy_proposal_from_bullish_consensus():
    """Bullish majority emits BUY proposal with full agreement."""
    result = AgentSynthesizer().generate_proposal(
        {"symbol": "EURUSD"},
        {"structure": _output("BULLISH", 0.8), "momentum": _output("STRONG_BULLISH", 0.9)},
    )

    assert result.proposal is not None
    assert result.proposal.symbol == "EURUSD"
    assert result.proposal.direction == TradeDirection.BUY
    assert result.proposal.confidence == 0.85
    assert result.agreement_score == 1.0
    assert result.conflicts_found == []


def test_generate_sell_proposal_calculates_atr_targets():
    """Bearish consensus derives SL and 2:1 TP from ATR."""
    result = AgentSynthesizer().generate_proposal(
        {"symbol": "GBPUSD"},
        {"structure": _output("BEARISH", 0.8), "momentum": _output("BEARISH", 0.7)},
        market_state={"close": 1.2, "atr": 0.01},
    )

    assert result.proposal is not None
    assert result.proposal.direction == TradeDirection.SELL
    assert result.proposal.target_sl == 1.22
    assert result.proposal.target_tp == 1.16


def test_generate_hold_proposal_for_tied_directional_signals():
    """Equal opposing votes produce HOLD proposal."""
    result = AgentSynthesizer().generate_proposal(
        {"symbol": "XAUUSD"},
        {"structure": _output("BULLISH", 0.8), "momentum": _output("BEARISH", 0.8)},
    )

    assert result.proposal is not None
    assert result.proposal.direction == TradeDirection.HOLD
    assert result.agreement_score == 0.5
    assert len(result.conflicts_found) == 1


def test_generate_proposal_accepts_detected_event():
    """Proposal derives symbol from the project's DetectedEvent type."""
    event = DetectedEvent(EventTypes.TREND_BULLISH, 0.8, "test", "now", "USDJPY")
    result = AgentSynthesizer().generate_proposal(event, {"structure": _output("BULLISH", 0.8)})

    assert result.proposal is not None
    assert result.proposal.symbol == "USDJPY"


def test_empty_outputs_return_no_proposal_and_escalate():
    """Synthesis cannot propose a trade without agent output."""
    synthesizer = AgentSynthesizer()
    result = synthesizer.generate_proposal({"symbol": "EURUSD"}, {})

    assert result.proposal is None
    assert result.agreement_score == 0.0
    assert synthesizer.check_escalation(result) is True


def test_low_confidence_proposal_requires_escalation():
    """Weak consensus requires manual review."""
    result = AgentSynthesizer().generate_proposal(
        {"symbol": "EURUSD"}, {"structure": _output("BULLISH", 0.4)}
    )

    assert result.proposal is not None
    assert result.proposal.requires_escalation is True


def test_high_conflict_proposal_requires_escalation():
    """Two conflict pairs trigger manual-review escalation."""
    result = AgentSynthesizer().generate_proposal(
        {"symbol": "EURUSD"},
        {
            "structure": _output("BULLISH", 0.8),
            "momentum": _output("BULLISH", 0.8),
            "news": _output("BEARISH", 0.8),
        },
    )

    assert len(result.conflicts_found) == 2
    assert result.proposal is not None
    assert result.proposal.requires_escalation is True


def test_dataclasses_serialize_to_plain_dict():
    """Public dataclasses provide API-ready serialisation."""
    proposal = TradeProposal("EURUSD", TradeDirection.BUY, 0.8, "consensus")
    result = SynthesisResult(proposal, 1.0)

    assert proposal.to_dict()["direction"] == "BUY"
    assert result.to_dict()["proposal"]["symbol"] == "EURUSD"
