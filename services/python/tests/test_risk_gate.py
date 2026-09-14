# -*- coding: utf-8 -*-
"""Tests for EPIC 03 — Deterministic Risk Gate validation."""

from __future__ import annotations

import pytest

from risk.base import RiskThreshold
from risk.engine import RiskEngine
from risk.gate import GateDecision, RiskGate
from risk.money_management import MoneyManager


@pytest.fixture
def risk_engine():
    """Minimal RiskEngine for testing."""
    engine = RiskEngine()
    engine.set_threshold(RiskThreshold.MAX_DRAWDOWN, 0.2)
    engine.set_threshold(RiskThreshold.DAILY_LOSS_LIMIT, 0.1)
    engine.set_threshold(RiskThreshold.MAX_POSITIONS, 5)
    engine.set_threshold(RiskThreshold.MAX_EXPOSURE, 0.3)
    return engine


@pytest.fixture
def money_manager():
    """Minimal MoneyManager for testing."""
    return MoneyManager()


@pytest.fixture
def risk_gate(risk_engine, money_manager):
    """RiskGate instance with default thresholds."""
    return RiskGate(
        risk_engine=risk_engine,
        money_manager=money_manager,
        max_spread_pips=5.0,
        min_rr=1.5,
    )


def test_gate_decision_dataclass():
    """GateDecision has required fields."""
    decision = GateDecision(
        approved=True,
        reason="All checks passed",
        checks_passed={"drawdown": True},
        metrics_snapshot={"dd": 0.05},
    )
    assert decision.approved is True
    assert "drawdown" in decision.checks_passed


def test_drawdown_check_pass(risk_gate):
    """Drawdown within limit passes."""
    account_state = {
        "equity": 9500.0,
        "balance": 10000.0,
        "peak_equity": 10000.0,
        "daily_pnl": -500.0,
        "used_margin": 200.0,
        "margin_call_level": 0.3,
        "free_margin": 9800.0,
    }
    decision = risk_gate.validate_proposal(
        proposal={
            "symbol": "EURUSD",
            "direction": "BUY",
            "entry_price": 1.0850,
            "stop_loss": 1.0750,
            "take_profit": 1.1050,
            "size": 1.0,
            "risk_pct": 0.02,
        },
        account_state=account_state,
        current_positions=[],
        market_info={
            "spread_pips": 2.0,
            "point_value": 10.0,
            "contract_size": 100000,
        },
    )
    assert decision.approved is True
    assert decision.checks_passed.get("drawdown_limit") is True


def test_drawdown_check_fail(risk_gate):
    """Drawdown exceeding limit fails."""
    account_state = {
        "equity": 7500.0,  # 25% drawdown
        "balance": 10000.0,
        "peak_equity": 10000.0,
        "daily_pnl": -2500.0,
        "used_margin": 200.0,
        "margin_call_level": 0.3,
        "free_margin": 7300.0,
    }
    decision = risk_gate.validate_proposal(
        proposal={
            "symbol": "EURUSD",
            "direction": "BUY",
            "entry_price": 1.0850,
            "stop_loss": 1.0750,
            "take_profit": 1.1050,
            "size": 1.0,
            "risk_pct": 0.02,
        },
        account_state=account_state,
        current_positions=[],
        market_info={
            "spread_pips": 2.0,
            "point_value": 10.0,
            "contract_size": 100000,
        },
    )
    assert decision.approved is False
    assert decision.checks_passed.get("drawdown_limit") is False


def test_daily_loss_check_fail(risk_gate):
    """Daily loss exceeding limit fails."""
    account_state = {
        "equity": 9000.0,
        "balance": 10000.0,
        "peak_equity": 10000.0,
        "daily_pnl": -1500.0,  # 15% daily loss > 10% limit
        "used_margin": 200.0,
        "margin_call_level": 0.3,
        "free_margin": 8800.0,
    }
    decision = risk_gate.validate_proposal(
        proposal={
            "symbol": "EURUSD",
            "direction": "BUY",
            "entry_price": 1.0850,
            "stop_loss": 1.0750,
            "take_profit": 1.1050,
            "size": 1.0,
            "risk_pct": 0.02,
        },
        account_state=account_state,
        current_positions=[],
        market_info={
            "spread_pips": 2.0,
            "point_value": 10.0,
            "contract_size": 100000,
        },
    )
    assert decision.approved is False
    assert decision.checks_passed.get("daily_loss_limit") is False


def test_max_positions_check_fail(risk_gate):
    """Max positions reached fails."""
    account_state = {
        "equity": 9500.0,
        "balance": 10000.0,
        "peak_equity": 10000.0,
        "daily_pnl": -500.0,
        "used_margin": 1000.0,
        "margin_call_level": 0.3,
        "free_margin": 8500.0,
    }
    current_positions = [
        {"symbol": "EURUSD", "volume": 1.0, "side": "BUY"},
        {"symbol": "GBPUSD", "volume": 1.0, "side": "BUY"},
        {"symbol": "USDJPY", "volume": 1.0, "side": "BUY"},
        {"symbol": "AUDUSD", "volume": 1.0, "side": "BUY"},
        {"symbol": "USDCAD", "volume": 1.0, "side": "BUY"},
    ]
    decision = risk_gate.validate_proposal(
        proposal={
            "symbol": "NZDUSD",
            "direction": "BUY",
            "entry_price": 0.6000,
            "stop_loss": 0.5950,
            "take_profit": 0.6050,
            "size": 1.0,
            "risk_pct": 0.02,
        },
        account_state=account_state,
        current_positions=current_positions,
        market_info={
            "spread_pips": 2.0,
            "point_value": 10.0,
            "contract_size": 100000,
        },
    )
    assert decision.approved is False
    assert decision.checks_passed.get("max_positions") is False


def test_all_checks_pass(risk_gate):
    """All checks pass for valid proposal."""
    account_state = {
        "equity": 9700.0,
        "balance": 10000.0,
        "peak_equity": 10000.0,
        "daily_pnl": -300.0,
        "used_margin": 200.0,
        "margin_call_level": 0.3,
        "free_margin": 9500.0,
    }
    current_positions = [
        {"symbol": "EURUSD", "volume": 0.5, "side": "BUY"},
    ]
    decision = risk_gate.validate_proposal(
        proposal={
            "symbol": "GBPUSD",
            "direction": "BUY",
            "entry_price": 1.2700,
            "stop_loss": 1.2650,
            "take_profit": 1.2850,
            "size": 1.0,
            "risk_pct": 0.02,
        },
        account_state=account_state,
        current_positions=current_positions,
        market_info={
            "spread_pips": 2.0,
            "point_value": 10.0,
            "contract_size": 100000,
        },
    )
    assert decision.approved is True
    assert all(decision.checks_passed.values())
