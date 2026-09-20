# -*- coding: utf-8 -*-
"""Tests for Strategy Lifecycle Governance (Phase 44)."""

import pytest

from src.strategy.lifecycle import (
    LifecycleGovernor,
    LifecycleState,
    PromotionProposal,
    StrategyVersion,
)


def _sv(strategy_id: str = "S1", version: int = 1) -> StrategyVersion:
    return StrategyVersion(strategy_id=strategy_id, version=version)


def _governor_with_draft() -> tuple[LifecycleGovernor, StrategyVersion]:
    gov = LifecycleGovernor()
    sv = gov.register(_sv())
    return gov, sv


def test_register_starts_in_draft() -> None:
    gov, sv = _governor_with_draft()
    assert sv.status == LifecycleState.DRAFT.value


def test_forward_advancement() -> None:
    gov, sv = _governor_with_draft()
    gov.advance("S1", 1)  # EXPERIMENT
    gov.advance("S1", 1)  # BACKTESTED
    gov.advance("S1", 1)  # WALK_FORWARD_PASSED
    gov.advance("S1", 1)  # PAPER
    gov.advance("S1", 1)  # DEMO
    gov.advance("S1", 1)  # CANDIDATE
    assert sv.status == LifecycleState.CANDIDATE.value


def test_cannot_advance_into_production_via_advance() -> None:
    gov, sv = _governor_with_draft()
    for _ in range(6):  # to CANDIDATE
        gov.advance("S1", 1)
    with pytest.raises(RuntimeError):
        gov.advance("S1", 1)  # would be APPROVED → blocked


def test_reject_and_archive() -> None:
    gov, sv = _governor_with_draft()
    gov.advance("S1", 1)
    gov.reject("S1", 1, "failed validation")
    assert sv.status == LifecycleState.REJECTED.value
    gov.archive("S1", 1)
    assert sv.status == LifecycleState.ARCHIVED.value


def test_archive_requires_rejected() -> None:
    gov, _ = _governor_with_draft()
    with pytest.raises(RuntimeError):
        gov.archive("S1", 1)


def test_ai_proposal_refused_without_evidence() -> None:
    gov, sv = _governor_with_draft()
    for _ in range(6):  # to CANDIDATE
        gov.advance("S1", 1)
    result = gov.propose(
        PromotionProposal(strategy_id="S1", version=1, target="APPROVED", proposed_by="ai")
    )
    assert result.approved is False
    assert sv.status == LifecycleState.CANDIDATE.value
    assert any("missing evidence" in r for r in result.reasons)


def test_ai_proposal_refused_without_risk_policy() -> None:
    gov, sv = _governor_with_draft()
    for _ in range(6):
        gov.advance("S1", 1)
    sv.evidence.update(
        {
            "backtest": "ok",
            "walk_forward": "ok",
            "monte_carlo": "ok",
            "paper": "ok",
            "demo": "ok",
            "test": "ok",
        }
    )
    result = gov.propose(
        PromotionProposal(strategy_id="S1", version=1, target="APPROVED", proposed_by="ai")
    )
    assert result.approved is False
    assert any("risk" in r for r in result.reasons)


def test_full_promotion_approved() -> None:
    gov, sv = _governor_with_draft()
    for _ in range(6):
        gov.advance("S1", 1)
    sv.risk_policy_id = "RP-1"
    sv.evidence.update(
        {
            "backtest": "ok",
            "walk_forward": "ok",
            "monte_carlo": "ok",
            "paper": "ok",
            "demo": "ok",
            "test": "ok",
        }
    )
    result = gov.propose(
        PromotionProposal(strategy_id="S1", version=1, target="APPROVED", proposed_by="operator")
    )
    assert result.approved is True
    assert sv.status == LifecycleState.APPROVED.value
    # Promotion must be recorded in the audit trail.
    assert any("promotion approved" in a["action"] for a in sv.audit)


def test_refused_proposal_is_audited() -> None:
    gov, sv = _governor_with_draft()
    for _ in range(6):
        gov.advance("S1", 1)
    gov.propose(
        PromotionProposal(strategy_id="S1", version=1, target="PRODUCTION", proposed_by="ai")
    )
    assert any("promotion refused" in a["action"] for a in sv.audit)


def test_duplicate_registration_rejected() -> None:
    gov, _ = _governor_with_draft()
    with pytest.raises(ValueError):
        gov.register(_sv())
