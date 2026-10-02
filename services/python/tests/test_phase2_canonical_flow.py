# -*- coding: utf-8 -*-
"""Phase 2 — Canonical Decision Architecture acceptance tests.

Proves the runtime pipeline actually uses the canonical decision objects
(not merely that the modules exist):

    MarketAssessment -> SetupCandidate -> DecisionState -> TradeProposal

and that the signal lifecycle state machine is enforced:

* a proposal may only reach execution from ``VALIDATED``;
* ``EXECUTING`` is never entered merely because an AI decided to trade.
"""

from __future__ import annotations

import types

import pytest

from agents import canonical as canonical_mod
from agents import committee as committee_mod
from orchestration import pipeline as pipeline_mod
from trading import signal_state_machine as signal_sm


def _proposal(direction: str = "BUY") -> dict:
    return {
        "symbol": "XAUUSD",
        "direction": direction,
        "confidence": 0.9,
        "entry_price": 2500.0,
        "stop_loss": 2495.0,
        "take_profit": 2510.0,
        "size": 0.1,
    }


class _StubSupervisor:
    def __init__(self, proposal: dict) -> None:
        self._proposal = proposal

    def analyze(self, context):
        return {
            "overall_confidence": 0.9,
            "summary": "stub",
            "agent_results": {
                "structure_analyst": {
                    "signal": "BULLISH",
                    "confidence": 0.8,
                    "domain": "structure",
                },
                "momentum_analyst": {"signal": "BULLISH", "confidence": 0.7, "domain": "momentum"},
            },
            "proposal": dict(self._proposal),
        }


class _FakeEngine:
    def __init__(self) -> None:
        self.sent = []

    def execute_order(self, request):
        self.sent.append(request)
        return types.SimpleNamespace(success=True, ticket=1, error_code=0, error_message="")


def _gate():
    from risk import MoneyManager, RiskEngine, RiskGate
    from risk.base import RiskThreshold

    engine = RiskEngine()
    engine.set_threshold(RiskThreshold.MAX_EXPOSURE, 0.9)
    engine.set_threshold(RiskThreshold.MAX_POSITION_SIZE, 0.9)
    return RiskGate(engine, MoneyManager(), max_spread_pips=50_000.0, min_rr=1.0)


def _context():
    return {
        "symbol": "XAUUSD",
        "account_state": {
            "equity": 10_000.0,
            "balance": 10_000.0,
            "peak_equity": 10_000.0,
            "daily_pnl": 0.0,
            "used_margin": 0.0,
        },
        "current_positions": [],
        "market_info": {
            "spread_pips": 1.0,
            "contract_size": 1.0,
            "bid": 2500.0,
            "ask": 2500.1,
        },
    }


def _run(proposal: dict):
    engine = _FakeEngine()
    pipe = pipeline_mod.TradingPipeline(
        supervisor=_StubSupervisor(proposal),
        risk_gate=_gate(),
        execution_engine=engine,
        single_entry_policy=False,
        max_lot_per_trade=1.0,
        force_risk_sizing=False,
    )
    result = pipe.run({"event_id": "e1", "event_type": "TREND_BULLISH"}, _context())
    return result, engine


# ── canonical chain is produced and exposed ────────────────────────────
def test_pipeline_emits_canonical_decision_chain() -> None:
    result, _ = _run(_proposal())
    canonical = result.canonical_decision
    assert canonical, "pipeline must expose the canonical decision chain"
    assert canonical["assessment"]["assessment_id"]
    assert canonical["assessment"]["trace_id"]
    assert canonical["decision"]["decision_id"]
    assert canonical["decision"]["current_state"] in signal_sm.SIGNAL_STATES


def test_setup_candidate_created_for_actionable_direction() -> None:
    result, _ = _run(_proposal("BUY"))
    setup = result.canonical_decision["setup"]
    assert setup is not None
    assert setup["direction"] == "BUY"
    assert setup["setup_id"]


def test_no_setup_candidate_for_non_actionable_proposal() -> None:
    result, _ = _run(_proposal("WAIT"))
    assert result.canonical_decision["setup"] is None
    assert result.canonical_decision["decision"]["action"] == "WAIT"


# ── decision state machine gates execution ─────────────────────────────
def test_actionable_proposal_is_validated_before_execution() -> None:
    result, engine = _run(_proposal())
    assert result.status == pipeline_mod.STATUS_EXECUTED
    assert engine.sent, "validated proposal should execute"
    assert result.canonical_decision["decision"]["current_state"] == "VALIDATED"


def test_conflict_blocks_promotion_to_validated(monkeypatch) -> None:
    """An unresolved HIGH conflict must block execution (Phase 2 §2)."""
    original = committee_mod.CommitteeCoordinator.build_assessment

    def conflicting(self, symbol, trace_id, agent_results, **kwargs):
        assessment = original(self, symbol, trace_id, agent_results, **kwargs)
        assessment.conflicts.append(
            canonical_mod.Conflict(
                id="cfl_test",
                severity="HIGH",
                description="structure bullish vs momentum bearish",
                domains=["structure", "momentum"],
                evidence_refs=["structure:BULLISH", "momentum:BEARISH"],
            )
        )
        return assessment

    monkeypatch.setattr(committee_mod.CommitteeCoordinator, "build_assessment", conflicting)
    result, engine = _run(_proposal())
    assessment = (result.canonical_decision or {}).get("assessment") or {}
    assert assessment.get("has_critical_conflicts") is True
    assert result.status != pipeline_mod.STATUS_EXECUTED
    assert engine.sent == []


def test_executing_requires_validated_predecessor() -> None:
    signal = signal_sm.Signal(signal_id="s1", symbol="XAUUSD", direction="BUY")
    assert signal.transition("EXECUTING") is False
    assert signal.transition("ANALYZING") is True
    assert signal.transition("CANDIDATE") is True
    assert signal.transition("VALIDATED") is True
    assert signal.transition("WAITING_TRIGGER") is True
    assert signal.transition("EXECUTING") is True


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
