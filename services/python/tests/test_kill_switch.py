# -*- coding: utf-8 -*-
"""Tests for EPIC 07.07 — Kill Switch.

Deterministic emergency stop that halts all trading activity.
"""

from __future__ import annotations

import pytest

from risk.kill_switch import KillSwitch, KillSwitchEvent, KillSwitchState


class TestKillSwitch:
    """Tests for KillSwitch class."""

    def test_initial_state_is_active(self) -> None:
        """Kill switch starts in ACTIVE state."""
        ks = KillSwitch()
        assert ks.state == KillSwitchState.ACTIVE
        assert not ks.is_blocked()

    def test_trigger_transitions_to_triggered(self) -> None:
        """Triggering moves state to TRIGGERED."""
        ks = KillSwitch()
        record = ks.trigger(reason="Test trigger", triggered_by="unit_test")
        assert ks.state == KillSwitchState.TRIGGERED
        assert ks.triggered_at is not None
        assert record.event == KillSwitchEvent.TRIGGER
        assert record.reason == "Test trigger"

    def test_trigger_blocks_trading(self) -> None:
        """After trigger, all trades are blocked."""
        ks = KillSwitch()
        ks.trigger("Emergency stop", "system")
        assert ks.is_blocked()
        approved, reason = ks.approve_trade({"symbol": "EURUSD"})
        assert approved is False
        assert "blocked" in reason.lower()

    def test_cannot_retrigger_when_triggered(self) -> None:
        """Cannot trigger an already-triggered switch."""
        ks = KillSwitch()
        ks.trigger("First trigger", "system")
        with pytest.raises(RuntimeError, match="already triggered"):
            ks.trigger("Second trigger", "system")

    def test_lock_after_trigger(self) -> None:
        """Locking moves state to LOCKED."""
        ks = KillSwitch()
        ks.trigger("Trigger before lock", "system")
        record = ks.lock("Automatic lock")
        assert ks.state == KillSwitchState.LOCKED
        assert ks.locked is True
        assert ks.locked_at is not None
        assert record.event == KillSwitchEvent.LOCK

    def test_cannot_lock_when_not_triggered(self) -> None:
        """Lock requires the switch to be triggered first."""
        ks = KillSwitch()
        with pytest.raises(RuntimeError, match="not triggered"):
            ks.lock("Invalid lock attempt")

    def test_request_reset_from_locked(self) -> None:
        """Reset request moves LOCKED → RESET_PENDING."""
        ks = KillSwitch()
        ks.trigger("Trigger", "system")
        ks.lock()
        record = ks.request_reset(requested_by="operator")
        assert ks.state == KillSwitchState.RESET_PENDING
        assert record.event == KillSwitchEvent.RESET_REQUEST

    def test_confirm_reset_returns_to_active(self) -> None:
        """Confirming reset returns to ACTIVE state."""
        ks = KillSwitch()
        ks.trigger("Trigger", "system")
        ks.lock()
        ks.request_reset()
        record = ks.confirm_reset()
        assert ks.state == KillSwitchState.ACTIVE
        assert not ks.is_blocked()
        assert ks.locked is False
        assert ks.reset_at is not None
        assert record.event == KillSwitchEvent.CONFIRM_RESET

    def test_cannot_confirm_reset_without_request(self) -> None:
        """Confirm reset requires RESET_PENDING state."""
        ks = KillSwitch()
        ks.trigger("Trigger", "system")
        with pytest.raises(RuntimeError, match="reset_pending"):
            ks.confirm_reset()

    def test_history_records_events(self) -> None:
        """All state transitions are recorded in history."""
        ks = KillSwitch()
        ks.trigger("First event", "system")
        ks.lock()
        ks.request_reset()
        ks.confirm_reset()
        assert len(ks.history) == 4
        events = [r.event for r in ks.history]
        assert KillSwitchEvent.TRIGGER in events
        assert KillSwitchEvent.LOCK in events
        assert KillSwitchEvent.RESET_REQUEST in events
        assert KillSwitchEvent.CONFIRM_RESET in events

    def test_to_dict_includes_state(self) -> None:
        """Serialization includes all key fields."""
        ks = KillSwitch()
        ks.trigger("Test", "unit_test")
        d = ks.to_dict()
        assert d["state"] == "triggered"
        assert d["is_blocked"] is True
        assert d["triggered_at"] is not None
        assert d["history_count"] == 1
        assert "recent_events" in d


class TestKillSwitchIntegration:
    """Integration scenarios for kill switch with trading."""

    def test_active_switch_approves_valid_trade(self) -> None:
        """When active, trades are allowed."""
        ks = KillSwitch()
        approved, reason = ks.approve_trade({"symbol": "GBPUSD", "direction": "BUY"})
        assert approved is True
        assert "approved" in reason.lower()

    def test_locked_switch_blocks_all_trades(self) -> None:
        """Locked switch blocks everything."""
        ks = KillSwitch()
        ks.trigger("Emergency", "risk_breach")
        ks.lock()
        approved, reason = ks.approve_trade({"symbol": "EURUSD"})
        assert approved is False

    def test_reset_pending_still_blocks(self) -> None:
        """Reset pending does not immediately allow trading."""
        ks = KillSwitch()
        ks.trigger("Trigger", "system")
        ks.lock()
        ks.request_reset()
        assert ks.is_blocked()
