# -*- coding: utf-8 -*-
"""Tests for Phase 37 — crash/restart/state recovery.

The tests create a temporary checkpoint file, inject mock dependencies, and
verify that the :class:`RecoveryCoordinator` respects the latched risk fields
and returns the correct :class:`RecoveryStatus`."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from src.system.recovery import (
    LATCHED_RISK_FIELDS,
    CheckpointStore,
    RecoveryCoordinator,
    RecoveryStatus,
)


@pytest.fixture
def temp_checkpoint_path() -> Path:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    yield Path(path)
    try:
        os.remove(path)
    except OSError:
        pass


def build_state(risk_overrides: dict | None = None) -> dict:
    base = {
        "system_state": {},
        "market_state": {},
        "decision_state": {},
        "order_state": {},
        "position_state": {},
        "risk_state": {},
        "circuit_breaker_state": {},
        "strategy_state": {},
        "scheduler_state": {},
    }
    if risk_overrides:
        base["risk_state"].update(risk_overrides)
    return base


def test_recovery_ready(temp_checkpoint_path: Path) -> None:
    # Build a checkpoint with normal risk (no latched fields set).
    state = build_state({"daily_loss": 0, "drawdown": 0, "halted": False})
    Path(temp_checkpoint_path).write_text(json.dumps(state, indent=2), encoding="utf-8")
    store = CheckpointStore(path=str(temp_checkpoint_path))
    coordinator = RecoveryCoordinator(
        store=store,
        check_mt5=lambda: True,
        query_broker_positions=lambda: 3,
        reconcile=lambda _s, _p: True,
    )
    result = coordinator.recover()
    assert result.status is RecoveryStatus.READY
    assert result.open_positions == 3
    # Latched fields must be present (defaulted to 0/False).
    for field in LATCHED_RISK_FIELDS:
        assert field in result.risk_state
    assert not result.halted
    assert not result.degraded


def test_recovery_halted_due_to_latched_risk(temp_checkpoint_path: Path) -> None:
    # Check that a latched risk "halted" flag survives restart and forces HALTED.
    state = build_state({"halted": True, "halt_reason": "daily loss exceed"})
    Path(temp_checkpoint_path).write_text(json.dumps(state, indent=2), encoding="utf-8")
    store = CheckpointStore(path=str(temp_checkpoint_path))
    coordinator = RecoveryCoordinator(
        store=store,
        check_mt5=lambda: True,
        query_broker_positions=lambda: 0,
        reconcile=lambda _s, _p: True,
    )
    result = coordinator.recover()
    assert result.status is RecoveryStatus.HALTED
    assert result.halted
    assert result.reason == "daily loss exceed"


def test_recovery_degraded_mt5_unavailable(temp_checkpoint_path: Path) -> None:
    # Simulate MT5 down – should yield DEGRADED.
    state = build_state()
    Path(temp_checkpoint_path).write_text(json.dumps(state, indent=2), encoding="utf-8")
    store = CheckpointStore(path=str(temp_checkpoint_path))
    coordinator = RecoveryCoordinator(
        store=store,
        check_mt5=lambda: False,
        query_broker_positions=lambda: 0,
        reconcile=lambda _s, _p: True,
    )
    result = coordinator.recover()
    assert result.status is RecoveryStatus.DEGRADED
    assert result.degraded
    assert not result.halted
    assert result.reason == "MT5 not connected after restart"


def test_recovery_degraded_reconcile_mismatch(temp_checkpoint_path: Path) -> None:
    # MT5 ok but reconciliation fails – should be DEGRADED.
    state = build_state()
    Path(temp_checkpoint_path).write_text(json.dumps(state, indent=2), encoding="utf-8")
    store = CheckpointStore(path=str(temp_checkpoint_path))
    coordinator = RecoveryCoordinator(
        store=store,
        check_mt5=lambda: True,
        query_broker_positions=lambda: 2,
        reconcile=lambda _s, _p: False,
    )
    result = coordinator.recover()
    assert result.status is RecoveryStatus.DEGRADED
    assert result.degraded
    assert not result.halted
    assert result.reason == "reconciliation mismatch after restart"
