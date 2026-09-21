# -*- coding: utf-8 -*-
"""Tests for EPIC 02 — MT5 Write Guard & Monetary Risk Gate.

Guards dangerous MT5 operations (order_send) behind:
1. Permission check (SEND_TO_MT5)
2. Monetary validation (volume, exposure, daily loss)
3. Risk Gate approval before transmission
"""

from __future__ import annotations

import pytest

from agents.base import BaseAgent
from agents.permissions import AgentPermissionError
from mt5.write_guard import MT5WriteGuard, validate_daily_loss, validate_exposure, validate_volume


class _TestAgent(BaseAgent):
    def __init__(self, name: str, permissions: list[str] | None = None):
        super().__init__(name=name, agent_type="executor", permissions=permissions or [])

    def analyze(self, context: dict) -> dict:
        return {}


# ---------------------------------------------------------------------------
# Volume validation
# ---------------------------------------------------------------------------


def test_validate_volume_within_limits():
    """Volume within min/max should pass."""
    result = validate_volume(symbol="EURUSD", volume=1.0, min_volume=0.01, max_volume=100.0)
    assert result.valid is True


def test_validate_volume_below_minimum():
    """Volume below minimum should fail."""
    result = validate_volume(symbol="EURUSD", volume=0.001, min_volume=0.01, max_volume=100.0)
    assert result.valid is False
    assert "minimum" in result.reason.lower()


def test_validate_volume_above_maximum():
    """Volume above maximum should fail."""
    result = validate_volume(symbol="EURUSD", volume=150.0, min_volume=0.01, max_volume=100.0)
    assert result.valid is False
    assert "maximum" in result.reason.lower()


# ---------------------------------------------------------------------------
# Daily loss validation
# ---------------------------------------------------------------------------


def test_validate_daily_loss_within_limit():
    """Daily loss within limit should pass."""
    account_state = {"daily_pnl": -500.0, "balance": 10000.0}
    result = validate_daily_loss(account_state, daily_loss_limit=0.1)  # 10% = -1000
    assert result.valid is True


def test_validate_daily_loss_exceeded():
    """Daily loss exceeding limit should fail."""
    account_state = {"daily_pnl": -1500.0, "balance": 10000.0}
    result = validate_daily_loss(account_state, daily_loss_limit=0.1)  # 10% = -1000
    assert result.valid is False
    assert "daily loss" in result.reason.lower()


# ---------------------------------------------------------------------------
# Exposure validation
# ---------------------------------------------------------------------------


def test_validate_exposure_within_limit():
    """Total exposure within limit should pass (real balance supplied)."""
    positions = [
        {"symbol": "EURUSD", "volume": 1.0, "price": 1.0850},
        {"symbol": "GBPUSD", "volume": 0.5, "price": 1.2700},
    ]
    result = validate_exposure(positions, max_exposure_pct=0.2, account_balance=10000.0)
    assert result.valid is True


def test_validate_exposure_exceeded():
    """Total exposure exceeding limit should fail."""
    positions = [
        {"symbol": "EURUSD", "volume": 50.0, "price": 1.0850},
        {"symbol": "GBPUSD", "volume": 50.0, "price": 1.2700},
    ]
    result = validate_exposure(positions, max_exposure_pct=0.001, account_balance=10000.0)
    assert result.valid is False
    assert "exposure" in result.reason.lower()


def test_validate_exposure_fails_closed_without_balance():
    """Audit P2-10: no real balance → exposure cannot be validated → fail."""
    result = validate_exposure([{"symbol": "EURUSD", "volume": 1.0, "price": 1.08}], 0.2, 0.0)
    assert result.valid is False
    assert "balance" in result.reason.lower()


# ---------------------------------------------------------------------------
# MT5WriteGuard enforcement
# ---------------------------------------------------------------------------


def test_write_guard_requires_permission():
    """MT5WriteGuard must check SEND_TO_MT5 permission."""
    agent = _TestAgent("trader", permissions=["READ_MARKET_DATA"])
    guard = MT5WriteGuard()

    with pytest.raises(AgentPermissionError):
        guard.send_order(agent, {"symbol": "EURUSD", "side": "BUY", "volume": 1.0})


def test_write_guard_validates_volume():
    """MT5WriteGuard must validate volume before sending."""
    agent = _TestAgent("executor", permissions=["SEND_TO_MT5"])
    guard = MT5WriteGuard(min_volume=0.01, max_volume=100.0)

    result = guard.validate_order(
        agent,
        {"symbol": "EURUSD", "side": "BUY", "volume": 150.0},
        positions=[],
        account_state={"daily_pnl": 0.0, "balance": 10000.0},
    )
    assert result["valid"] is False


def test_write_guard_all_checks_pass():
    """When all checks pass, order should be cleared for MT5."""
    agent = _TestAgent("executor", permissions=["SEND_TO_MT5"])
    guard = MT5WriteGuard(
        min_volume=0.01,
        max_volume=100.0,
        daily_loss_limit=0.1,
        max_exposure_pct=0.2,
    )

    result = guard.validate_order(
        agent,
        {"symbol": "EURUSD", "side": "BUY", "volume": 1.0},
        positions=[],
        account_state={"daily_pnl": -500.0, "balance": 10000.0},
    )
    assert result["valid"] is True


def test_write_guard_fails_closed_without_account_state():
    """Audit P2-9: missing account state must block (fail-closed)."""
    agent = _TestAgent("executor", permissions=["SEND_TO_MT5"])
    guard = MT5WriteGuard()
    result = guard.validate_order(agent, {"symbol": "EURUSD", "volume": 1.0})
    assert result["valid"] is False
    assert "account state" in result["reason"].lower()


def test_send_order_delegates_to_executor():
    """Audit P2-9: send_order must actually call the executor, not fake success."""
    agent = _TestAgent("executor", permissions=["SEND_TO_MT5"])
    guard = MT5WriteGuard()
    sent: list[dict] = []

    def fake_executor(order):
        sent.append(order)
        return {"success": True, "order_id": 123, "message": "sent"}

    out = guard.send_order(
        agent,
        {"symbol": "EURUSD", "volume": 1.0},
        positions=[],
        account_state={"daily_pnl": 0.0, "balance": 10000.0},
        executor=fake_executor,
    )
    assert out["success"] is True
    assert len(sent) == 1  # the executor was actually invoked
