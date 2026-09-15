# -*- coding: utf-8 -*-
"""Tests for Trading Modes — PRD_V2 §23 Trading Modes.

Mode transitions must be explicit, audited, and fail-safe: downgrades to
PAPER/OFFLINE are always allowed; LIVE requires an explicit confirmation phrase
AND a PASSED live-readiness gate (delegated to ``readiness.gate``).
"""

from __future__ import annotations

import pytest

from readiness.gate import LiveReadinessGate
from trading.modes import TradingMode, TradingModeError, TradingModeManager


def _ready_gate() -> LiveReadinessGate:
    """Return a LIVE-readiness gate with every gate PASSED."""
    gate = LiveReadinessGate()
    for name in gate.gate_names():
        gate.submit(name, passed=True, evidence={"ok": True})
    assert gate.is_ready()
    return gate


# ---------------------------------------------------------------------------
# Enum
# ---------------------------------------------------------------------------
class TestTradingModeEnum:
    def test_prd_modes_present(self) -> None:
        values = {m.value for m in TradingMode}
        for required in ("OFFLINE", "BACKTEST", "PAPER", "DEMO", "LIVE", "EMERGENCY_STOP"):
            assert required in values


# ---------------------------------------------------------------------------
# Happy transitions
# ---------------------------------------------------------------------------
class TestHappyTransitions:
    def test_default_mode_offline(self) -> None:
        manager = TradingModeManager()
        assert manager.mode is TradingMode.OFFLINE

    def test_offline_to_paper_allowed(self) -> None:
        manager = TradingModeManager()
        record = manager.transition(TradingMode.PAPER, reason="start research")
        assert manager.mode is TradingMode.PAPER
        assert record.from_mode is TradingMode.OFFLINE
        assert record.to_mode is TradingMode.PAPER

    def test_paper_to_demo_allowed(self) -> None:
        manager = TradingModeManager()
        manager.transition(TradingMode.PAPER)
        manager.transition(TradingMode.DEMO)
        assert manager.mode is TradingMode.DEMO

    def test_live_allowed_with_gate_and_phrase(self) -> None:
        manager = TradingModeManager(readiness_gate=_ready_gate())
        manager.transition(TradingMode.PAPER)
        manager.transition(
            TradingMode.DEMO,
        )
        record = manager.transition(
            TradingMode.LIVE,
            confirmation=manager.confirmation_phrase,
            reason="all gates passed",
        )
        assert manager.mode is TradingMode.LIVE
        assert record.to_mode is TradingMode.LIVE


# ---------------------------------------------------------------------------
# LIVE guards
# ---------------------------------------------------------------------------
class TestLiveGuards:
    def test_live_blocked_without_confirmation(self) -> None:
        manager = TradingModeManager(readiness_gate=_ready_gate())
        manager.transition(TradingMode.DEMO)
        with pytest.raises(TradingModeError, match="confirmation"):
            manager.transition(TradingMode.LIVE)
        assert manager.mode is TradingMode.DEMO

    def test_live_blocked_without_readiness_gate(self) -> None:
        manager = TradingModeManager()  # no gate → not ready
        manager.transition(TradingMode.DEMO)
        with pytest.raises(TradingModeError, match="readiness"):
            manager.transition(TradingMode.LIVE, confirmation=manager.confirmation_phrase)
        assert manager.mode is TradingMode.DEMO

    def test_live_blocked_when_gates_fail(self) -> None:
        gate = LiveReadinessGate()
        # Leave gates PENDING / fail one gate.
        names = gate.gate_names()
        gate.submit(names[0], passed=False, reason="drawdown too high")
        manager = TradingModeManager(readiness_gate=gate)
        manager.transition(TradingMode.DEMO)
        with pytest.raises(TradingModeError, match="readiness"):
            manager.transition(TradingMode.LIVE, confirmation=manager.confirmation_phrase)


# ---------------------------------------------------------------------------
# Fail-safe downgrades
# ---------------------------------------------------------------------------
class TestFailSafeDowngrades:
    def test_forced_downgrade_to_paper_always_allowed(self) -> None:
        manager = TradingModeManager(readiness_gate=_ready_gate())
        manager.transition(TradingMode.DEMO)
        manager.transition(TradingMode.LIVE, confirmation=manager.confirmation_phrase)
        manager.force_downgrade(TradingMode.PAPER, reason="anomaly detected")
        assert manager.mode is TradingMode.PAPER

    def test_forced_downgrade_to_offline_always_allowed(self) -> None:
        manager = TradingModeManager()
        manager.transition(TradingMode.PAPER)
        manager.transition(TradingMode.OFFLINE)
        assert manager.mode is TradingMode.OFFLINE

    def test_emergency_stop_always_allowed_from_live(self) -> None:
        manager = TradingModeManager(readiness_gate=_ready_gate())
        manager.transition(TradingMode.DEMO)
        manager.transition(TradingMode.LIVE, confirmation=manager.confirmation_phrase)
        manager.transition(TradingMode.EMERGENCY_STOP, reason="kill switch")
        assert manager.mode is TradingMode.EMERGENCY_STOP


# ---------------------------------------------------------------------------
# Audit history
# ---------------------------------------------------------------------------
class TestAuditHistory:
    def test_history_records_from_to_reason_timestamp(self) -> None:
        manager = TradingModeManager()
        manager.transition(TradingMode.PAPER, reason="began paper")
        record = manager.history()[-1]
        assert record.from_mode is TradingMode.OFFLINE
        assert record.to_mode is TradingMode.PAPER
        assert record.reason == "began paper"
        assert record.timestamp

    def test_history_is_bounded(self) -> None:
        manager = TradingModeManager(history_limit=3)
        for _ in range(6):
            manager.transition(TradingMode.PAPER)
            manager.transition(TradingMode.OFFLINE)
        assert len(manager.history()) <= 3

    def test_blocked_transition_recorded(self) -> None:
        manager = TradingModeManager()
        manager.transition(TradingMode.DEMO)
        with pytest.raises(TradingModeError):
            manager.transition(TradingMode.LIVE)
        # A blocked attempt is still audited (fail-safe visibility).
        last = manager.history()[-1]
        assert last.to_mode is TradingMode.LIVE
        assert last.allowed is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
