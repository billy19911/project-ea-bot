# -*- coding: utf-8 -*-
"""Tests for EPIC 01.04 — Permission enforcement for dangerous operations.

Only agents that declare the appropriate ``permissions`` may invoke the
guarded helpers: ``submit_to_risk_gate``, ``propose_execution``,
``send_to_mt5``.  The permission check is enforced by the ``BaseAgent``
itself so that direct calls outside ``Supervisor`` cannot bypass it.
"""

from __future__ import annotations

import pytest

from agents.base import BaseAgent
from agents.permissions import (
    AgentPermissionError,
    can_invoke,
    propose_execution,
    require_permission,
    send_to_mt5,
    submit_to_risk_gate,
)


class _StubAgent(BaseAgent):
    """Plain BaseAgent with no special behavior."""

    def __init__(self, name: str, permissions: list[str] | None = None):
        super().__init__(
            name=name,
            agent_type="stub",
            permissions=permissions or [],
        )

    def analyze(self, context: dict) -> dict:
        return {"agent": self.name, "signal": "NEUTRAL"}


# ---------------------------------------------------------------------------
# Permission decorator
# ---------------------------------------------------------------------------


def test_require_permission_grants_when_present():
    agent = _StubAgent("executor", permissions=["EXECUTE_TRADE"])
    # Should not raise
    require_permission(agent, "EXECUTE_TRADE")


def test_require_permission_blocks_when_missing():
    agent = _StubAgent("observer", permissions=["READ_MARKET_DATA"])
    with pytest.raises(AgentPermissionError) as exc_info:
        require_permission(agent, "EXECUTE_TRADE")
    assert "EXECUTE_TRADE" in str(exc_info.value)
    assert "observer" in str(exc_info.value)


def test_can_invoke_returns_bool():
    agent = _StubAgent("a", permissions=["X"])
    assert can_invoke(agent, "X") is True
    assert can_invoke(agent, "Y") is False


# ---------------------------------------------------------------------------
# Guarded helpers
# ---------------------------------------------------------------------------


def test_submit_to_risk_gate_requires_permission():
    agent = _StubAgent("risk_officer", permissions=["SUBMIT_TO_RISK_GATE"])
    result = submit_to_risk_gate(agent, {"symbol": "EURUSD"})
    assert result == {"accepted": True, "agent": "risk_officer"}


def test_submit_to_risk_gate_rejects_unauthorized():
    agent = _StubAgent("trader", permissions=["EXECUTE_TRADE"])
    with pytest.raises(AgentPermissionError):
        submit_to_risk_gate(agent, {"symbol": "EURUSD"})


def test_propose_execution_requires_permission():
    agent = _StubAgent("proposer", permissions=["PROPOSE_EXECUTION"])
    result = propose_execution(agent, {"symbol": "EURUSD", "side": "BUY"})
    assert result["accepted"] is True
    assert result["proposer"] == "proposer"


def test_propose_execution_rejects_unauthorized():
    agent = _StubAgent("reader", permissions=["READ_MARKET_DATA"])
    with pytest.raises(AgentPermissionError):
        propose_execution(agent, {"symbol": "EURUSD"})


def test_send_to_mt5_requires_permission():
    agent = _StubAgent("executor", permissions=["SEND_TO_MT5"])
    result = send_to_mt5(agent, {"symbol": "EURUSD", "side": "BUY", "volume": 1.0})
    assert result["success"] is True
    assert result["order_id"] is not None


def test_send_to_mt5_rejects_unauthorized():
    agent = _StubAgent("proposer", permissions=["PROPOSE_EXECUTION"])
    with pytest.raises(AgentPermissionError):
        send_to_mt5(agent, {"ticket": 1, "action": "OPEN"})
