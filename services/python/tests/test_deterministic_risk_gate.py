# -*- coding: utf-8 -*-
"""Tests for Phase 13 deterministic pre-execution RiskGate."""

from __future__ import annotations

import pytest

from risk import GateDecision, MoneyManager, RiskEngine, RiskGate


@pytest.fixture
def gate() -> RiskGate:
    """Return a gate with standard limits."""
    return RiskGate(RiskEngine(), MoneyManager())


@pytest.fixture
def account() -> dict[str, float]:
    """Return a safe account state."""
    return {
        "equity": 10_000.0,
        "balance": 10_000.0,
        "peak_equity": 10_000.0,
        "daily_pnl": 0.0,
        "used_margin": 100.0,
        "margin_call_level": 500.0,
    }


@pytest.fixture
def proposal() -> dict[str, float | str]:
    """Return a valid long proposal."""
    return {
        "symbol": "EURUSD",
        "direction": "long",
        "entry_price": 100.0,
        "stop_loss": 90.0,
        "take_profit": 120.0,
        "size": 1.0,
    }


@pytest.fixture
def market() -> dict[str, float]:
    """Return safe market conditions."""
    return {"spread_pips": 1.0}


def validate(gate, proposal, account, market, positions=None) -> GateDecision:
    """Validate using empty positions unless explicitly supplied."""
    return gate.validate_proposal(proposal, account, positions or [], market)


def test_approves_when_every_hard_check_passes(gate, proposal, account, market):
    decision = validate(gate, proposal, account, market)
    assert decision.approved is True
    assert all(decision.checks_passed.values())
    assert decision.reason == "All risk checks passed"


def test_returns_required_decision_shape(gate, proposal, account, market):
    decision = validate(gate, proposal, account, market)
    assert isinstance(decision, GateDecision)
    assert set(decision.checks_passed) == {
        "drawdown_limit",
        "daily_loss_limit",
        "max_positions",
        "max_exposure",
        "margin_level",
        "spread",
        "risk_reward",
        "stop_loss",
    }
    assert "drawdown_pct" in decision.metrics_snapshot


def test_rejects_drawdown_breach(gate, proposal, account, market):
    account.update(equity=8_000.0, peak_equity=10_000.0)
    decision = validate(gate, proposal, account, market)
    assert not decision.approved
    assert not decision.checks_passed["drawdown_limit"]


def test_rejects_daily_loss_breach(gate, proposal, account, market):
    account["daily_pnl"] = -600.0
    decision = validate(gate, proposal, account, market)
    assert not decision.approved
    assert not decision.checks_passed["daily_loss_limit"]


def test_rejects_when_max_positions_already_reached(gate, proposal, account, market):
    positions = [{"size": 0.01, "current_price": 1.0} for _ in range(5)]
    decision = validate(gate, proposal, account, market, positions)
    assert not decision.approved
    assert not decision.checks_passed["max_positions"]


def test_rejects_exposure_breach(gate, proposal, account, market):
    positions = [{"size": 4_000.0, "current_price": 1.0, "account_equity": 10_000.0}]
    decision = validate(gate, proposal, account, market, positions)
    assert not decision.approved
    assert not decision.checks_passed["max_exposure"]


def test_rejects_high_used_margin(gate, proposal, account, market):
    account["used_margin"] = 3_000.0
    decision = validate(gate, proposal, account, market)
    assert not decision.approved
    assert not decision.checks_passed["margin_level"]


def test_rejects_margin_call_level(gate, proposal, account, market):
    account.update(equity=400.0, balance=10_000.0, peak_equity=400.0)
    decision = validate(gate, proposal, account, market)
    assert not decision.approved
    assert not decision.checks_passed["margin_level"]


def test_rejects_wide_spread(gate, proposal, account, market):
    market["spread_pips"] = 5.1
    decision = validate(gate, proposal, account, market)
    assert not decision.approved
    assert not decision.checks_passed["spread"]


def test_accepts_spread_at_limit(gate, proposal, account, market):
    market["spread_pips"] = 5.0
    assert validate(gate, proposal, account, market).approved


def test_rejects_rr_below_minimum(gate, proposal, account, market):
    proposal["take_profit"] = 110.0
    decision = validate(gate, proposal, account, market)
    assert not decision.approved
    assert not decision.checks_passed["risk_reward"]


def test_accepts_rr_at_minimum(gate, proposal, account, market):
    proposal["take_profit"] = 115.0
    assert validate(gate, proposal, account, market).approved


def test_rejects_missing_stop_loss(gate, proposal, account, market):
    del proposal["stop_loss"]
    decision = validate(gate, proposal, account, market)
    assert not decision.approved
    assert not decision.checks_passed["stop_loss"]


def test_rejects_stop_loss_equal_to_entry(gate, proposal, account, market):
    proposal["stop_loss"] = 100.0
    decision = validate(gate, proposal, account, market)
    assert not decision.approved
    assert not decision.checks_passed["stop_loss"]


def test_reports_every_failure_in_single_decision(gate, proposal, account, market):
    account.update(equity=8_000.0, peak_equity=10_000.0, daily_pnl=-600.0, used_margin=3_000.0)
    proposal.update(stop_loss=100.0, take_profit=101.0)
    market["spread_pips"] = 6.0
    decision = validate(gate, proposal, account, market)
    assert not decision.approved
    assert len([passed for passed in decision.checks_passed.values() if not passed]) >= 6


def test_uses_injected_risk_engine_thresholds(proposal, account, market):
    gate = RiskGate(RiskEngine(max_drawdown=0.01), MoneyManager())
    account.update(equity=9_800.0, peak_equity=10_000.0)
    decision = validate(gate, proposal, account, market)
    assert not decision.approved
    assert decision.metrics_snapshot["max_drawdown"] == 0.01
