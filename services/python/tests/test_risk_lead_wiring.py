# -*- coding: utf-8 -*-
"""Tests for Phase 3 — RiskLead wiring & upgrade.

Covers the upgraded RiskLead (src/risk/intelligence.py):

* identity — registered as ``agent_type="department_lead"`` so the
  Supervisor detects and delegates risk events to it;
* ``can_handle`` — accepts risk event families, rejects market ones;
* ``analyze`` — Supervisor-compatible dict with a RISK_ON / RISK_OFF /
  NEUTRAL advisory signal and the four specialist reports;
* fail-closed behaviour — missing or malformed risk data yields NEUTRAL,
  never an exception;
* advisory-only safety — no MT5 access, no limit bypass, no veto field;
* backward compatibility — the legacy ``synthesize`` / ``create_department``
  committee API and the legacy ``can_handle("risk_analysis")`` contract.
"""

from __future__ import annotations

import pytest

from agents.base import AgentPriority, AgentRegistry
from agents.permissions import AgentPermissionError, require_permission
from agents.supervisor import SupervisorAgent
from risk.intelligence import (
    AccountRiskAnalyst,
    DrawdownAnalyst,
    PortfolioRiskAnalyst,
    PositionRiskAnalyst,
    RiskCommitteeDecision,
    RiskDepartment,
    RiskLead,
)

SPECIALIST_KEYS = {"account_risk", "position_risk", "portfolio_risk", "drawdown"}

SAFE_RISK_DATA = {
    "balance": 10000.0,
    "equity": 10000.0,
    "margin_used": 100.0,
    "free_margin": 9900.0,
    "daily_loss": 0.0,
    "positions": [],
    "total_open_lots": 0.0,
    "symbols": [],
    "correlation_matrix": {},
    "net_exposure_usd": 0.0,
    "current_drawdown_pct": 0.0,
    "max_drawdown_pct": 10.0,
    "peak_equity": 10000.0,
    "current_equity": 10000.0,
}

DANGEROUS_RISK_DATA = {
    "balance": 10000.0,
    "equity": 7000.0,
    "margin_used": 5000.0,
    "free_margin": 2000.0,
    "daily_loss": 1500.0,
    "positions": [{"symbol": "EURUSD", "volume": 3.0, "pnl": -900.0}],
    "total_open_lots": 3.0,
    "symbols": ["EURUSD", "GBPUSD"],
    "correlation_matrix": {"EURUSD:GBPUSD": 0.9},
    "net_exposure_usd": 30000.0,
    "current_drawdown_pct": 25.0,
    "max_drawdown_pct": 30.0,
    "peak_equity": 10000.0,
    "current_equity": 7000.0,
}


@pytest.fixture(autouse=True)
def _reset_registry():
    AgentRegistry.reset()
    yield
    AgentRegistry.reset()


# ---------------------------------------------------------------------------
# Identity — Supervisor compatibility
# ---------------------------------------------------------------------------


def test_risk_lead_is_department_lead():
    lead = RiskLead()
    assert lead.name == "risk_lead"
    assert lead.agent_type == "department_lead"
    assert lead.role == "department_lead"


def test_risk_lead_priority_is_high():
    assert RiskLead().priority == AgentPriority.HIGH


def test_risk_lead_to_dict_has_department_metadata():
    data = RiskLead().to_dict()
    assert data["role"] == "department_lead"
    assert data["department"] == "risk"


# ---------------------------------------------------------------------------
# can_handle — routing contract
# ---------------------------------------------------------------------------


def test_can_handle_risk_events():
    lead = RiskLead()
    for event in (
        "RISK_CHECK",
        "RISK_BREACH",
        "DRAWDOWN_ALERT",
        "DRAWDOWN_WARNING",
        "EXPOSURE_LIMIT",
        "EXPOSURE_LIMIT_REACHED",
        "LIQUIDITY_LOW",
        "MARGIN_CALL",
        "PORTFOLIO_REBALANCE",
        "CORRELATION_SPIKE",
    ):
        assert lead.can_handle(event, {}) is True, event


def test_can_handle_rejects_market_events():
    lead = RiskLead()
    for event in (
        "TREND_BULLISH",
        "MOMENTUM_BEARISH",
        "RSI_OVERBOUGHT",
        "BREAKOUT",
        "STRUCTURE_BREAK",
        "VOLATILITY_SPIKE",
        "NEWS_FLASH",
        "ECONOMIC_CPI",
    ):
        assert lead.can_handle(event, {}) is False, event


def test_can_handle_legacy_task_type():
    lead = RiskLead()
    assert lead.can_handle("risk_analysis") is True
    assert lead.can_handle("market_analysis") is False


# ---------------------------------------------------------------------------
# analyze() — Supervisor-compatible advisory contract
# ---------------------------------------------------------------------------


def test_analyze_returns_supervisor_compatible_dict():
    lead = RiskLead()
    result = lead.analyze({"risk_data": SAFE_RISK_DATA})

    assert result["agent"] == "risk_lead"
    assert result["role"] == "department_lead"
    assert result["department"] == "risk"
    assert result["signal"] in ("RISK_ON", "RISK_OFF", "NEUTRAL")
    assert 0.0 <= result["confidence"] <= 1.0
    assert isinstance(result["reasons"], list) and result["reasons"]
    assert set(result["specialist_results"]) == SPECIALIST_KEYS
    assert result["advisory"] is True


def test_analyze_low_risk_is_risk_on():
    result = RiskLead().analyze({"risk_data": SAFE_RISK_DATA})

    assert result["signal"] == "RISK_ON"
    assert result["overall_risk"] == "LOW"
    assert result["confidence"] > 0.9


def test_analyze_high_risk_is_risk_off():
    result = RiskLead().analyze({"risk_data": DANGEROUS_RISK_DATA})

    assert result["signal"] == "RISK_OFF"
    assert result["overall_risk"] in ("HIGH", "CRITICAL")
    assert result["recommendations"]
    assert result["risk_score"] is not None


def test_analyze_extracts_account_and_positions_from_context():
    result = RiskLead().analyze(
        {
            "account": {"balance": 10000.0, "equity": 9900.0, "used_margin": 500.0},
            "positions": [{"symbol": "EURUSD", "volume": 0.5, "pnl": -100.0}],
            "total_open_lots": 0.5,
        }
    )

    account = result["specialist_results"]["account_risk"]
    assert account["score"] > 0.0
    position = result["specialist_results"]["position_risk"]
    assert "Positions: 1" in position["evidence"]


def test_analyze_derives_drawdown_from_equity_peak():
    result = RiskLead().analyze(
        {"peak_equity": 10000.0, "current_equity": 9000.0, "max_drawdown_pct": 20.0}
    )

    drawdown = result["specialist_results"]["drawdown"]
    assert drawdown["score"] == pytest.approx(0.5, abs=0.01)


def test_analyze_fail_closed_without_data():
    result = RiskLead().analyze({"event_type": "RISK_CHECK"})

    assert result["signal"] == "NEUTRAL"
    assert result["confidence"] == 0.0
    assert result["specialist_results"] == {}
    assert "No risk data" in result["reasons"][0]


def test_analyze_never_raises_on_garbage_input():
    for bad in ({"risk_data": "nope"}, {"positions": "nope"}, {"balance": "nope"}, {}):
        result = RiskLead().analyze(bad)
        assert result["signal"] in ("RISK_ON", "RISK_OFF", "NEUTRAL"), bad


def test_analyze_is_advisory_never_veto():
    result = RiskLead().analyze({"risk_data": DANGEROUS_RISK_DATA})

    assert result["advisory"] is True
    assert "veto" not in result


# ---------------------------------------------------------------------------
# Safety — advisory-only separation from the deterministic gate
# ---------------------------------------------------------------------------


def test_risk_lead_cannot_reach_execution():
    lead = RiskLead()
    assert "SEND_TO_MT5" not in lead.permissions
    assert "BYPASS_RISK_LIMITS" not in lead.permissions

    with pytest.raises(AgentPermissionError):
        require_permission(lead, "SEND_TO_MT5")
    with pytest.raises(AgentPermissionError):
        require_permission(lead, "BYPASS_RISK_LIMITS")


# ---------------------------------------------------------------------------
# Backward compatibility — legacy committee API
# ---------------------------------------------------------------------------


def test_legacy_synthesize_still_returns_committee_decision():
    lead = RiskLead()
    decision = lead.synthesize(DANGEROUS_RISK_DATA)

    assert isinstance(decision, RiskCommitteeDecision)
    assert decision.department == "risk"
    assert len(decision.reports) == 4


def test_legacy_department_still_has_four_specialists():
    department = RiskLead().create_department()

    assert isinstance(department, RiskDepartment)
    assert len(department.specialists) == 4
    types = {type(s) for s in department.specialists}
    assert AccountRiskAnalyst in types
    assert PositionRiskAnalyst in types
    assert PortfolioRiskAnalyst in types
    assert DrawdownAnalyst in types


# ---------------------------------------------------------------------------
# Supervisor delegation end-to-end
# ---------------------------------------------------------------------------


def test_supervisor_delegates_to_risk_lead():
    registry = AgentRegistry()
    registry.register(RiskLead())

    supervisor = SupervisorAgent()
    supervisor._registry_cache = registry

    result = supervisor.analyze({"event_type": "RISK_CHECK", "risk_data": DANGEROUS_RISK_DATA})

    assert "risk_lead" in result["agent_results"]
    lead_result = result["agent_results"]["risk_lead"]
    assert lead_result["signal"] == "RISK_OFF"
    assert set(lead_result["specialist_results"]) == SPECIALIST_KEYS
