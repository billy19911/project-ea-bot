# -*- coding: utf-8 -*-
"""Tests for EPIC 05 — Risk Intelligence Department."""

from __future__ import annotations

import pytest

from agents.permissions import AgentPermissionError, require_permission
from risk.intelligence import (
    AccountRiskAnalyst,
    DrawdownAnalyst,
    PortfolioRiskAnalyst,
    PositionRiskAnalyst,
    RiskAssessmentReport,
    RiskCommitteeDecision,
    RiskDepartment,
    RiskLead,
)


def test_risk_lead_initialization():
    """RiskLead must have proper attributes and permissions."""
    lead = RiskLead()
    assert lead.name == "Risk Lead"
    assert lead.agent_type == "lead"
    assert "ANALYZE_RISK" in lead.permissions
    assert "SEND_TO_MT5" not in lead.permissions  # Must not have MT5 access


def test_risk_lead_creates_department():
    """RiskLead must create RiskDepartment with specialists."""
    lead = RiskLead()
    dept = lead.create_department()
    assert isinstance(dept, RiskDepartment)
    assert len(dept.specialists) == 4
    types = {type(s) for s in dept.specialists}
    assert AccountRiskAnalyst in types
    assert PositionRiskAnalyst in types
    assert PortfolioRiskAnalyst in types
    assert DrawdownAnalyst in types


def test_account_risk_analyst():
    """AccountRiskAnalyst evaluates account-level metrics."""
    analyst = AccountRiskAnalyst()
    report = analyst.analyze(
        {
            "balance": 10000.0,
            "equity": 9800.0,
            "margin_used": 1000.0,
            "free_margin": 8800.0,
            "daily_loss": 200.0,
        }
    )
    assert isinstance(report, RiskAssessmentReport)
    assert report.analyst == "AccountRiskAnalyst"
    assert report.risk_level in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    assert 0.0 <= report.score <= 1.0


def test_position_risk_analyst():
    """PositionRiskAnalyst evaluates open position exposure and concentration."""
    analyst = PositionRiskAnalyst()
    report = analyst.analyze(
        {
            "positions": [
                {"symbol": "EURUSD", "volume": 0.5, "pnl": -50.0},
                {"symbol": "GBPUSD", "volume": 0.3, "pnl": 20.0},
            ],
            "total_open_lots": 0.8,
        }
    )
    assert isinstance(report, RiskAssessmentReport)
    assert report.analyst == "PositionRiskAnalyst"
    assert report.risk_level in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


def test_portfolio_risk_analyst():
    """PortfolioRiskAnalyst checks correlations and total portfolio exposure."""
    analyst = PortfolioRiskAnalyst()
    report = analyst.analyze(
        {
            "symbols": ["EURUSD", "GBPUSD"],
            "correlation_matrix": {"EURUSD:GBPUSD": 0.85},
            "net_exposure_usd": 8000.0,
        }
    )
    assert isinstance(report, RiskAssessmentReport)
    assert report.analyst == "PortfolioRiskAnalyst"


def test_drawdown_analyst():
    """DrawdownAnalyst assesses peak-to-trough drawdown."""
    analyst = DrawdownAnalyst()
    report = analyst.analyze(
        {
            "current_drawdown_pct": 2.5,
            "max_drawdown_pct": 15.0,
            "peak_equity": 10200.0,
            "current_equity": 9800.0,
        }
    )
    assert isinstance(report, RiskAssessmentReport)
    assert report.analyst == "DrawdownAnalyst"
    assert report.risk_level == "LOW"


def test_risk_lead_synthesis():
    """RiskLead synthesizes all specialist reports into a committee decision."""
    lead = RiskLead()
    lead.create_department()
    decision = lead.synthesize(
        risk_data={
            "balance": 10000.0,
            "equity": 9800.0,
            "margin_used": 1000.0,
            "free_margin": 8800.0,
            "daily_loss": 200.0,
            "positions": [{"symbol": "EURUSD", "volume": 0.5, "pnl": -50.0}],
            "total_open_lots": 0.5,
            "symbols": ["EURUSD"],
            "correlation_matrix": {},
            "net_exposure_usd": 5000.0,
            "current_drawdown_pct": 2.0,
            "max_drawdown_pct": 5.0,
            "peak_equity": 10000.0,
            "current_equity": 9800.0,
        }
    )
    assert isinstance(decision, RiskCommitteeDecision)
    assert decision.department == "risk"
    assert decision.overall_risk in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    assert len(decision.reports) == 4
    assert isinstance(decision.warnings, list)
    assert isinstance(decision.recommendations, list)


def test_risk_lead_separation_cannot_alter_hard_limits():
    """AI risk advice cannot override deterministic hard limits (Separation Test)."""
    lead = RiskLead()
    lead.create_department()
    # RiskLead has no permissions to send orders or bypass limits
    assert "SEND_TO_MT5" not in lead.permissions
    assert "BYPASS_RISK_LIMITS" not in lead.permissions

    with pytest.raises(AgentPermissionError):
        require_permission(lead, "SEND_TO_MT5")


def test_risk_committee_decision_to_dict():
    """RiskCommitteeDecision serializes to dict cleanly."""
    decision = RiskCommitteeDecision(
        department="risk",
        overall_risk="LOW",
        score=0.15,
        reports=[],
        warnings=["Low volume warning"],
        recommendations=["Proceed with normal sizing"],
    )
    data = decision.to_dict()
    assert data["department"] == "risk"
    assert data["overall_risk"] == "LOW"
    assert data["score"] == 0.15
    assert len(data["warnings"]) == 1
    assert len(data["recommendations"]) == 1
