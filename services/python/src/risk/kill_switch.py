# -*- coding: utf-8 -*-
"""Kill Switch — hard emergency stop for all trading activity.

Phase 13 (EPIC 07.07): A deterministic, non-bypassable kill switch that
halts all order submission, position opening, and risk-gate approvals.
Once activated, no LLM or Supervisor can resume trading without an
explicit reset and manual confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

__all__ = ["KillSwitchState", "KillSwitch", "KillSwitchEvent"]


class KillSwitchState(str, Enum):
    """Operational state of the kill switch."""

    ACTIVE = "active"
    """Normal operation — trading allowed."""

    TRIGGERED = "triggered"
    """Kill switch activated — all trading halted."""

    LOCKED = "locked"
    """Post-trigger lock — requires manual reset and confirmation."""

    RESET_PENDING = "reset_pending"
    """Reset requested but not yet confirmed."""


class KillSwitchEvent(str, Enum):
    """Events that cause state transitions."""

    TRIGGER = "trigger"
    """Trigger the kill switch."""

    RESET_REQUEST = "reset_request"
    """Request a reset (moves to RESET_PENDING)."""

    CONFIRM_RESET = "confirm_reset"
    """Confirm reset (moves back to ACTIVE)."""

    LOCK = "lock"
    """Force-lock after trigger (cannot be reset automatically)."""


@dataclass(frozen=True)
class KillSwitchRecord:
    """Immutable record of a kill switch event."""

    event: KillSwitchEvent
    timestamp: str
    reason: str
    triggered_by: str


@dataclass
class KillSwitch:
    """Deterministic kill switch for all trading activity.

    Once triggered, ALL order submissions and risk-gate approvals are
    blocked until a manual reset with confirmation is performed.

    Attributes:
        state: Current operational state.
        triggered_at: ISO timestamp of the last trigger.
        reset_at: ISO timestamp of the last reset (if any).
        history: Immutable event log.
        locked: Whether the switch is locked (cannot auto-reset).
        locked_at: ISO timestamp when locked (if applicable).
    """

    state: KillSwitchState = KillSwitchState.ACTIVE
    triggered_at: str | None = None
    reset_at: str | None = None
    history: list[KillSwitchRecord] = field(default_factory=list)
    locked: bool = False
    locked_at: str | None = None

    def _now(self) -> str:
        """Return current UTC ISO timestamp."""
        return datetime.now(timezone.utc).isoformat()

    def trigger(self, reason: str, triggered_by: str = "system") -> KillSwitchRecord:
        """Activate the kill switch.

        Transitions ACTIVE → TRIGGERED → LOCKED.

        Args:
            reason: Human-readable reason for triggering.
            triggered_by: Who/what triggered the switch.

        Returns:
            The immutable record of the trigger event.

        Raises:
            RuntimeError: If already triggered and locked.
        """
        if self.state == KillSwitchState.LOCKED:
            raise RuntimeError("Kill switch is locked — cannot re-trigger without reset.")
        if self.state == KillSwitchState.TRIGGERED:
            raise RuntimeError("Kill switch already triggered.")

        now = self._now()
        record = KillSwitchRecord(
            event=KillSwitchEvent.TRIGGER,
            timestamp=now,
            reason=reason,
            triggered_by=triggered_by,
        )
        self.state = KillSwitchState.TRIGGERED
        self.triggered_at = now
        self.history.append(record)
        return record

    def lock(self, reason: str = "Automatic lock after trigger") -> KillSwitchRecord:
        """Force-lock the kill switch after trigger.

        Transitions TRIGGERED → LOCKED. No automatic reset is possible.

        Args:
            reason: Why the switch was locked.

        Returns:
            The immutable record of the lock event.

        Raises:
            RuntimeError: If not triggered or already locked.
        """
        if self.state != KillSwitchState.TRIGGERED:
            raise RuntimeError("Cannot lock — kill switch not triggered.")
        if self.locked:
            raise RuntimeError("Kill switch already locked.")

        now = self._now()
        record = KillSwitchRecord(
            event=KillSwitchEvent.LOCK,
            timestamp=now,
            reason=reason,
            triggered_by="system",
        )
        self.state = KillSwitchState.LOCKED
        self.locked = True
        self.locked_at = now
        self.history.append(record)
        return record

    def request_reset(self, requested_by: str = "operator") -> KillSwitchRecord:
        """Request a reset of the kill switch.

        Transitions LOCKED → RESET_PENDING or TRIGGERED → RESET_PENDING.

        Args:
            requested_by: Who is requesting the reset.

        Returns:
            The immutable record of the reset request.

        Raises:
            RuntimeError: If already active or reset pending.
        """
        if self.state == KillSwitchState.ACTIVE:
            raise RuntimeError("Kill switch is already active — no reset needed.")
        if self.state == KillSwitchState.RESET_PENDING:
            raise RuntimeError("Reset already pending — awaiting confirmation.")

        now = self._now()
        record = KillSwitchRecord(
            event=KillSwitchEvent.RESET_REQUEST,
            timestamp=now,
            reason="Reset requested by operator",
            triggered_by=requested_by,
        )
        self.state = KillSwitchState.RESET_PENDING
        self.history.append(record)
        return record

    def confirm_reset(self) -> KillSwitchRecord:
        """Confirm and execute a reset.

        Transitions RESET_PENDING → ACTIVE.

        Returns:
            The immutable record of the reset confirmation.

        Raises:
            RuntimeError: If not in RESET_PENDING state.
        """
        if self.state != KillSwitchState.RESET_PENDING:
            raise RuntimeError("Cannot confirm reset — kill switch not in reset_pending state.")

        now = self._now()
        record = KillSwitchRecord(
            event=KillSwitchEvent.CONFIRM_RESET,
            timestamp=now,
            reason="Reset confirmed by operator",
            triggered_by="operator",
        )
        self.state = KillSwitchState.ACTIVE
        self.reset_at = now
        self.locked = False
        self.locked_at = None
        self.history.append(record)
        return record

    def is_blocked(self) -> bool:
        """Check if trading is currently blocked.

        Returns True when state is TRIGGERED or LOCKED or RESET_PENDING.
        """
        return self.state in (
            KillSwitchState.TRIGGERED,
            KillSwitchState.LOCKED,
            KillSwitchState.RESET_PENDING,
        )

    def approve_trade(self, proposal: dict[str, Any]) -> tuple[bool, str]:
        """Approve or block a trade proposal.

        Returns:
            (approved, reason) — always False when blocked.
        """
        if self.is_blocked():
            return (
                False,
                f"Kill switch is {self.state.value} — all trades blocked.",
            )
        return (True, "Kill switch active — trade approved.")

    def to_dict(self) -> dict[str, Any]:
        """Serialize kill switch state to dictionary."""
        return {
            "state": self.state.value,
            "triggered_at": self.triggered_at,
            "reset_at": self.reset_at,
            "locked": self.locked,
            "locked_at": self.locked_at,
            "is_blocked": self.is_blocked(),
            "history_count": len(self.history),
            "recent_events": [
                {"event": r.event.value, "timestamp": r.timestamp, "reason": r.reason}
                for r in self.history[-5:]
            ],
        }
