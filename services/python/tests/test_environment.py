# -*- coding: utf-8 -*-
"""Tests for Environment Separation (Phase 51)."""

import pytest

from src.live_readiness.environment import (
    Environment,
    EnvironmentGuard,
    EnvironmentViolation,
    ExecutionIdentity,
    LivePreconditions,
)


def _ready_preconds() -> LivePreconditions:
    return LivePreconditions(
        terminal_armed=True,
        risk_gate_healthy=True,
        reconciliation_healthy=True,
        production_strategy=True,
    )


def test_non_live_rejects_live_execution() -> None:
    for env in (Environment.DEV, Environment.PAPER, Environment.DEMO):
        guard = EnvironmentGuard(environment=env.value, preconditions=_ready_preconds())
        allowed, reason = guard.can_execute_live()
        assert allowed is False
        assert "REJECT" in reason


def test_live_with_preconditions_allowed() -> None:
    guard = EnvironmentGuard(environment=Environment.LIVE.value, preconditions=_ready_preconds())
    allowed, _ = guard.can_execute_live()
    assert allowed is True


def test_live_without_terminal_armed_rejected() -> None:
    preconds = _ready_preconds()
    preconds.terminal_armed = False
    guard = EnvironmentGuard(environment=Environment.LIVE.value, preconditions=preconds)
    allowed, reason = guard.can_execute_live()
    assert allowed is False
    assert "terminal_armed" in reason


def test_live_without_risk_healthy_rejected() -> None:
    preconds = _ready_preconds()
    preconds.risk_gate_healthy = False
    guard = EnvironmentGuard(environment=Environment.LIVE.value, preconditions=preconds)
    allowed, reason = guard.can_execute_live()
    assert allowed is False
    assert "risk_gate_healthy" in reason


def test_check_live_raises_on_violation() -> None:
    guard = EnvironmentGuard(environment=Environment.DEMO.value)
    with pytest.raises(EnvironmentViolation):
        guard.check_live()


def test_check_live_passes_when_ready() -> None:
    guard = EnvironmentGuard(environment=Environment.LIVE.value, preconditions=_ready_preconds())
    guard.check_live()  # should not raise


def test_execution_identity_fields() -> None:
    ident = ExecutionIdentity(
        environment="LIVE",
        broker="ICMarkets",
        server="ICMarkets-Live01",
        account="12345",
        login="12345",
        terminal_id="term-1",
        strategy_version="v12",
    )
    d = ident.to_dict()
    for key in (
        "environment",
        "broker",
        "server",
        "account",
        "login",
        "terminal_id",
        "strategy_version",
    ):
        assert key in d


def test_stamp_returns_identity() -> None:
    ident = ExecutionIdentity("LIVE", "B", "S", "A", "L", "T", "v1")
    guard = EnvironmentGuard(environment="LIVE", identity=ident)
    stamped = guard.stamp()
    assert stamped.broker == "B"
    assert stamped.strategy_version == "v1"
