# -*- coding: utf-8 -*-
"""Tests for Phase 36 — multi-level circuit breaker & capital preservation."""

import pytest

from src.risk.multi_level_breaker import BreakerLevel, MultiLevelBreaker, TriggerType, level_index


def test_initial_state_normal() -> None:
    b = MultiLevelBreaker()
    assert b.level is BreakerLevel.NORMAL
    assert b.allows_new_entries()
    assert b.size_multiplier() == 1.0
    assert not b.must_flatten()
    assert not b.latched


def test_caution_alert_only() -> None:
    b = MultiLevelBreaker()
    rec = b.trigger(TriggerType.FEED_STALE, reason="feed older than 5s")
    assert rec.to_level is BreakerLevel.CAUTION
    assert b.level is BreakerLevel.CAUTION
    assert b.allows_new_entries()  # still allowed
    assert b.size_multiplier() == 1.0
    assert b.current_trigger is TriggerType.FEED_STALE
    assert b.current_reason == "feed older than 5s"


def test_risk_reduced_reduces_size() -> None:
    b = MultiLevelBreaker(risk_multiplier=0.25)
    b.trigger(TriggerType.SPREAD_SPIKE, reason="spread 5x normal")
    assert b.level is BreakerLevel.RISK_REDUCED
    assert b.allows_new_entries()
    assert b.size_multiplier() == 0.25


def test_entry_blocked_latches_and_blocks() -> None:
    b = MultiLevelBreaker()
    b.trigger(TriggerType.MT5_DISCONNECTED, reason="terminal detached")
    assert b.level is BreakerLevel.ENTRY_BLOCKED
    assert b.latched
    assert not b.allows_new_entries()
    assert b.size_multiplier() == 0.0
    assert not b.must_flatten()


def test_emergency_flatten() -> None:
    b = MultiLevelBreaker()
    b.trigger(TriggerType.DRAWDOWN, reason="drawdown 15%")
    assert b.level is BreakerLevel.EMERGENCY_FLATTEN
    assert b.must_flatten()
    assert b.latched


def test_halted_on_db_unavailable() -> None:
    b = MultiLevelBreaker()
    b.trigger(TriggerType.DATABASE_UNAVAILABLE, reason="db down")
    assert b.level is BreakerLevel.HALTED
    assert b.latched


def test_trigger_does_not_downgrade_latched() -> None:
    b = MultiLevelBreaker()
    b.trigger(TriggerType.MT5_DISCONNECTED)  # ENTRY_BLOCKED (latched)
    b.trigger(TriggerType.FEED_STALE)  # CAUTION — lower; must not downgrade
    assert b.level is BreakerLevel.ENTRY_BLOCKED
    assert b.latched


def test_escalation_only_increases() -> None:
    b = MultiLevelBreaker()
    b.escalate(BreakerLevel.ENTRY_BLOCKED, "manual escalation")
    assert b.level is BreakerLevel.ENTRY_BLOCKED
    with pytest.raises(RuntimeError):
        b.escalate(BreakerLevel.NORMAL, "try to lower")


def test_recovery_requires_condition() -> None:
    b = MultiLevelBreaker()
    b.trigger(TriggerType.DRAWDOWN, reason="drawdown")
    with pytest.raises(RuntimeError):
        b.recover(condition_ok=False)
    rec = b.recover(condition_ok=True, reason="equity recovered")
    assert rec.to_level is BreakerLevel.NORMAL
    assert b.level is BreakerLevel.NORMAL
    assert not b.latched


def test_level_index_ordering() -> None:
    assert level_index(BreakerLevel.NORMAL) < level_index(BreakerLevel.CAUTION)
    assert level_index(BreakerLevel.CAUTION) < level_index(BreakerLevel.HALTED)


def test_to_dict_exposes_state_and_trigger() -> None:
    b = MultiLevelBreaker()
    b.trigger(TriggerType.RECONCILIATION_MISMATCH, reason="dead position")
    d = b.to_dict()
    assert d["level"] == "entry_blocked"
    assert d["trigger"] == "reconciliation_mismatch"
    assert d["latched"] is True
    assert d["allows_new_entries"] is False
    assert d["history_count"] >= 1
