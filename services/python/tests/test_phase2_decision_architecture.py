# -*- coding: utf-8 -*-
"""Phase 2 — Canonical Decision Architecture acceptance tests.
Covers: majority-voting removal, canonical evidence, conflict detection,
challenge flow, unresolved-conflict → WAIT, confidence semantics, signal
state machine, traceability, and adversarial committee cases.
"""
from __future__ import annotations

import pytest

from src.agents.canonical import (
    Challenge,
    Conflict,
    DecisionState,
    EvidenceItem,
    EvidenceKind,
    MarketAssessment,
    SetupCandidate,
)
from src.agents.committee import AgentOutputAdapter, CommitteeCoordinator
from src.agents.synthesis import AgentSynthesizer, TradeDirection
from src.trading.signal_state_machine import Signal, SignalState, is_valid_transition


def _out(signal: str, confidence: float, **extra) -> dict:
    base = {"signal": signal, "confidence": confidence, "reasoning": "test"}
    base.update(extra)
    return base


# ── §4 majority voting removal ──────────────────────────────────────────
def test_four_bullish_two_bearish_does_not_auto_buy():
    """4 bullish vs 2 bearish with strong counter-evidence must NOT auto-BUY."""
    outputs = {
        "regime": _out("BULLISH", 0.55, unresolved_conflict=True),
        "structure": _out("BULLISH", 0.55, unresolved_conflict=True),
        "liquidity": _out("BULLISH", 0.55, unresolved_conflict=True),
        "momentum": _out("BEARISH", 0.95, unresolved_conflict=True),
    }
    result = AgentSynthesizer().generate_proposal({"symbol": "XAUUSD"}, outputs)
    # Majority bullish (3) but severe unresolved conflict → no automatic BUY.
    assert result.proposal.direction == TradeDirection.HOLD


def test_evidence_dominance_not_headcount():
    """One strong bullish piece outweighs three weak bearish (evidence, not votes)."""
    outputs = {
        "structure": _out("BULLISH", 0.95),
        "momentum": _out("BEARISH", 0.2),
        "volatility": _out("BEARISH", 0.2),
        "news": _out("BEARISH", 0.2),
    }
    result = AgentSynthesizer().generate_proposal({"symbol": "EURUSD"}, outputs)
    # Evidence weight: bull 0.95 vs bear 0.6 → bullish dominance (not 1 vs 3).
    assert result.proposal.direction == TradeDirection.BUY


def test_one_reliable_agent_all_weak_evidence_no_auto_buy():
    """High-confidence single agent with weak support must not force a BUY alone."""
    outputs = {
        "structure": _out("BULLISH", 0.9, evidence_quality=0.1),
        "momentum": _out("NEUTRAL", 0.0),
    }
    result = AgentSynthesizer().generate_proposal({"symbol": "EURUSD"}, outputs)
    # Evidence weight ≈ 0.9×0.1 = 0.09 → below escalation floor; still HOLD only
    # if no dominance — here it IS bullish-dominant but escalation flags it.
    assert result.proposal is not None
    assert result.proposal.requires_escalation is True


# ── §6 evidence model ───────────────────────────────────────────────────
def test_evidence_item_requires_content_and_valid_quality():
    with pytest.raises(ValueError):
        EvidenceItem(kind=EvidenceKind.FACT, content="", source="a")
    with pytest.raises(ValueError):
        EvidenceItem(kind=EvidenceKind.FACT, content="ok", source="a", quality=1.5)


def test_adapter_produces_evidence_with_provenance():
    adapter = AgentOutputAdapter()
    bundle = adapter.to_evidence(
        "structure_analyst",
        _out("BULLISH", 0.8, evidence=[{"content": "BOS up confirmed"}]),
        symbol="XAUUSD",
        domain="structure",
    )
    assert len(bundle) >= 2
    assert all(i.source for i in bundle.items())


def test_adapter_marks_incomplete_directional_claim():
    """A BUY/SELL without supporting evidence is marked INCOMPLETE, not trusted."""
    adapter = AgentOutputAdapter()
    bundle = adapter.to_evidence("momentum", _out("BUY", 0.9), domain="momentum")
    recs = bundle.recommendations()
    assert any("[INCOMPLETE]" in i.content for i in recs)


# ── §14 conflict detection ──────────────────────────────────────────────
def test_conflict_detected_for_bullish_structure_bearish_momentum():
    coord = CommitteeCoordinator()
    conflicts = coord.detect_conflicts(domains={"structure": "BULLISH", "momentum": "BEARISH"})
    assert len(conflicts) >= 1
    assert conflicts[0].severity == "HIGH"
    assert set(conflicts[0].domains) >= {"structure", "momentum"}


def test_conflict_news_unknown_is_flagged_not_safe():
    coord = CommitteeCoordinator()
    conflicts = coord.detect_conflicts(domains={"news": "UNKNOWN", "structure": "BULLISH"})
    assert any("news" in c.domains for c in conflicts)


# ── §16 assessment + decision ───────────────────────────────────────────
def test_build_assessment_uses_evidence_not_votes():
    coord = CommitteeCoordinator()
    assessment = coord.build_assessment(
        "XAUUSD",
        "trace-1",
        {
            "structure": _out("BULLISH", 0.8, domain="structure"),
            "momentum": _out("BULLISH", 0.7, domain="momentum"),
        },
    )
    assert isinstance(assessment, MarketAssessment)
    assert assessment.structure == "BULLISH"
    assert assessment.momentum == "BULLISH"
    assert assessment.evidence_bundle is not None
    assert len(assessment.evidence_bundle) >= 2


def test_consistent_evidence_produces_validated_decision():
    coord = CommitteeCoordinator()
    assessment = coord.build_assessment(
        "EURUSD",
        "t2",
        {
            "structure": _out("BULLISH", 0.8, domain="structure"),
            "momentum": _out("BULLISH", 0.8, domain="momentum"),
        },
    )
    setup = SetupCandidate(
        setup_id="s1",
        assessment_id=assessment.assessment_id,
        symbol="EURUSD",
        direction="BUY",
        setup_type="BREAKOUT",
        timeframe="M15",
    )
    decision = coord.build_decision(
        assessment, setup=setup, evidence_quality=0.8, setup_quality=0.8
    )
    assert decision.action == "BUY"
    assert decision.current_state == "VALIDATED"
    assert decision.market_bias == "BULLISH"


def test_unresolved_conflict_blocks_trade():
    coord = CommitteeCoordinator()
    assessment = coord.build_assessment(
        "XAUUSD",
        "t3",
        {
            "structure": _out("BULLISH", 0.9, domain="structure"),
            "momentum": _out("BEARISH", 0.9, domain="momentum"),
        },
    )
    setup = SetupCandidate(
        setup_id="s2",
        assessment_id=assessment.assessment_id,
        symbol="XAUUSD",
        direction="BUY",
        setup_type="BREAKOUT",
        timeframe="M15",
    )
    decision = coord.build_decision(assessment, setup=setup)
    assert decision.action == "WAIT"
    assert assessment.has_critical_conflicts() is True


# ── §15 challenge flow ──────────────────────────────────────────────────
def test_challenge_created_for_conflict():
    coord = CommitteeCoordinator()
    setup = SetupCandidate(
        setup_id="s3",
        assessment_id="a1",
        symbol="XAUUSD",
        direction="BUY",
        setup_type="BREAKOUT",
        timeframe="M15",
    )
    conflict = Conflict(
        id="c1",
        severity="HIGH",
        description="structure vs momentum",
        domains=["structure", "momentum"],
        evidence_refs=["e1"],
    )
    ch = coord.run_challenge(setup, conflict)
    assert isinstance(ch, Challenge)
    assert ch.outcome == "PENDING"
    assert setup.challenges  # recorded on the setup


def test_challenge_runner_can_resolve():
    def runner(agent, issue, ctx):
        return {"outcome": "RESOLVED", "evidence_ref": "ev-2"}

    coord = CommitteeCoordinator(challenge_runner=runner)
    setup = SetupCandidate(
        setup_id="s4",
        assessment_id="a1",
        symbol="XAUUSD",
        direction="BUY",
        setup_type="BREAKOUT",
        timeframe="M15",
    )
    conflict = Conflict(
        id="c2",
        severity="HIGH",
        description="x",
        domains=["momentum"],
        evidence_refs=[],
    )
    ch = coord.run_challenge(setup, conflict)
    assert ch.outcome == "RESOLVED"
    assert ch.secondary_evidence_ref == "ev-2"


# ── §11/§12 state machine + confidence semantics ────────────────────────
def test_valid_state_transitions():
    s = Signal(signal_id="sig1")
    assert s.state == SignalState.DETECTED
    assert s.transition("ANALYZING") is True
    assert s.transition("CANDIDATE") is True
    assert s.transition("VALIDATED") is True
    assert s.transition("ARMED") is True
    assert s.transition("WAITING_TRIGGER") is True


def test_invalid_state_transitions_rejected():
    assert is_valid_transition("DETECTED", "EXECUTING") is False
    assert is_valid_transition("ANALYZING", "OPEN") is False
    assert is_valid_transition("REJECTED", "EXECUTING") is False
    assert is_valid_transition("EXPIRED", "EXECUTING") is False


def test_signal_transition_blocks_executing_jump():
    s = Signal(signal_id="sig2")
    assert s.transition("EXECUTING") is False  # cannot skip lifecycle
    assert s.state == SignalState.DETECTED


def test_decision_state_rejects_detected_to_executing():
    d = DecisionState(
        decision_id="d1",
        trace_id="t",
        assessment_id="a",
        setup_id=None,
        entry_assessment_id=None,
        symbol="EURUSD",
    )
    assert d.is_valid_transition("EXECUTING") is False
    with pytest.raises(ValueError):
        d.state_machine_valid_transition("EXECUTING")


def test_confidence_is_not_probability_of_profit():
    """DecisionState exposes explicit quality dims; legacy confidence is labelled."""
    d = DecisionState(
        decision_id="d2",
        trace_id="t",
        assessment_id="a",
        setup_id=None,
        entry_assessment_id=None,
        symbol="EURUSD",
        evidence_quality=0.7,
        setup_quality=0.6,
        data_quality=0.9,
        legacy_confidence=0.8,
    )
    payload = d.to_dict()
    assert "legacy_confidence" in payload
    assert payload["evidence_quality"] == 0.7
    assert payload["setup_quality"] == 0.6
    # No "probability" key anywhere in the canonical payload.
    assert not any("probability" in k for k in payload)


# ── §20 traceability ────────────────────────────────────────────────────
def test_decision_retains_evidence_and_trace_ids():
    coord = CommitteeCoordinator()
    assessment = coord.build_assessment(
        "EURUSD",
        "trace-xyz",
        {"structure": _out("BULLISH", 0.8, domain="structure")},
    )
    decision = coord.build_decision(assessment)
    assert decision.trace_id == "trace-xyz"
    assert decision.assessment_id == assessment.assessment_id
    assert decision.evidence_bundle_ref == assessment.evidence_bundle.id


# ── §25 adversarial ─────────────────────────────────────────────────────
def test_adversarial_most_agents_bullish_strong_bearish_counterevidence():
    outputs = {
        "regime": _out("BULLISH", 0.5, unresolved_conflict=True),
        "structure": _out("BULLISH", 0.5, unresolved_conflict=True),
        "liquidity": _out("BULLISH", 0.5, unresolved_conflict=True),
        "momentum": _out("BEARISH", 0.99, unresolved_conflict=True),
    }
    result = AgentSynthesizer().generate_proposal({"symbol": "XAUUSD"}, outputs)
    assert result.proposal.direction == TradeDirection.HOLD


def test_adversarial_setup_valid_entry_invalid_waits():
    coord = CommitteeCoordinator()
    assessment = coord.build_assessment(
        "EURUSD", "t", {"structure": _out("BULLISH", 0.9, domain="structure")}
    )
    setup = SetupCandidate(
        setup_id="s",
        assessment_id=assessment.assessment_id,
        symbol="EURUSD",
        direction="BUY",
        setup_type="PULLBACK",
        timeframe="M15",
        missing_conditions=["trigger_not_confirmed"],
    )
    assert setup.validate_all() is False  # entry timing not ready
    assert setup.is_ready_for_entry() is False


def test_adversarial_all_bullish_news_unknown_flagged():
    coord = CommitteeCoordinator()
    assessment = coord.build_assessment(
        "EURUSD",
        "t",
        {
            "structure": _out("BULLISH", 0.9, domain="structure"),
            "momentum": _out("BULLISH", 0.9, domain="momentum"),
            "news": _out("UNKNOWN", 0.0, domain="news"),
        },
    )
    # NEWS UNKNOWN must be surfaced as a conflict, never assumed safe.
    assert any("news" in c.domains for c in assessment.conflicts)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
