# -*- coding: utf-8 -*-
"""Tests for EPIC 02 integration — MT5WriteGuard wrapping execute_order."""

from __future__ import annotations

from agents.base import BaseAgent
from mt5.write_guard import MT5WriteGuard


class _Executor(BaseAgent):
    """Minimal executor agent for testing."""

    def __init__(self, perms=None):
        super().__init__(
            name="Test Executor",
            agent_type="executor",
            description="Test agent",
            permissions=[] if perms is not None else ["SEND_TO_MT5"],
        )

    def execute(self, task):
        return {"status": "ok"}

    def analyze(self, data):
        return {"analysis": "noop"}


def _make_guard(**kwargs):
    defaults = dict(
        min_volume=0.01,
        max_volume=100.0,
        daily_loss_limit=0.1,
        max_exposure_pct=0.2,
    )
    defaults.update(kwargs)
    return MT5WriteGuard(**defaults)


# --- guarded_execute_order tests ---


def test_guarded_execute_blocks_unauthorized_agent():
    """Agent without SEND_TO_MT5 must be blocked."""
    agent = _Executor(perms=[])
    guard = _make_guard()

    from mt5.connector import guarded_execute_order

    result = guarded_execute_order(
        agent=agent,
        order={"symbol": "EURUSD", "side": "BUY", "volume": 1.0},
        guard=guard,
    )
    assert result["success"] is False
    assert "permission" in result["message"].lower() or "denied" in result["message"].lower()


def test_guarded_execute_blocks_oversize_volume():
    """Volume above max_volume must be blocked."""
    agent = _Executor()
    guard = _make_guard(max_volume=5.0)

    from mt5.connector import guarded_execute_order

    result = guarded_execute_order(
        agent=agent,
        order={"symbol": "EURUSD", "side": "BUY", "volume": 10.0},
        guard=guard,
    )
    assert result["success"] is False
    assert "volume" in result["message"].lower() or "volume" in result["reason"].lower()


def test_guarded_execute_passes_valid_order():
    """Valid order should pass guard and execute (simulation)."""
    agent = _Executor()
    guard = _make_guard()

    from mt5.connector import guarded_execute_order

    result = guarded_execute_order(
        agent=agent,
        order={"symbol": "EURUSD", "side": "BUY", "volume": 1.0},
        guard=guard,
    )
    assert result["success"] is True
    assert result["order_id"] is not None


def test_guarded_execute_checks_daily_loss():
    """Daily loss limit exceeded must block execution."""
    agent = _Executor()
    guard = _make_guard(daily_loss_limit=0.05)  # 5%

    from mt5.connector import guarded_execute_order

    # daily_pnl = -1000, balance = 10000 => -10% > -5% limit
    result = guarded_execute_order(
        agent=agent,
        order={"symbol": "EURUSD", "side": "BUY", "volume": 1.0},
        guard=guard,
        account_state={"daily_pnl": -1000.0, "balance": 10000.0},
    )
    assert result["success"] is False
    assert "loss" in result["message"].lower() or "loss" in result["reason"].lower()


def test_guarded_execute_with_real_execute_order():
    """Integration: guard + real execute_order (simulation mode)."""
    agent = _Executor()
    guard = _make_guard()

    from mt5.connector import execute_order, guarded_execute_order

    result = guarded_execute_order(
        agent=agent,
        order={"symbol": "GBPUSD", "side": "SELL", "volume": 0.5},
        guard=guard,
        executor=execute_order,
    )
    assert result["success"] is True
    assert "order_id" in result


def test_guard_with_default_config():
    """MT5WriteGuard can be instantiated with defaults."""
    guard = MT5WriteGuard()
    assert guard.min_volume == 0.01
    assert guard.max_volume == 100.0
    assert guard.daily_loss_limit == 0.1
    assert guard.max_exposure_pct == 0.2
