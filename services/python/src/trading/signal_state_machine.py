# -*- coding: utf-8 -*-
"""Signal lifecycle state machine (Phase 2 §11).
Explicit, auditable signal states:
    DETECTED → ANALYZING → CANDIDATE → VALIDATED → ARMED → WAITING_TRIGGER
    → EXECUTING → OPEN → MANAGING → CLOSED
Rejections:
    ANALYZING → REJECTED
    CANDIDATE → REJECTED
    VALIDATED → REJECTED
    ARMED → EXPIRED
    WAITING_TRIGGER → EXPIRED
``EXECUTING`` must correspond to an actual execution lifecycle controlled by
the execution subsystem — never mark EXECUTING merely because an AI decided
to trade.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

__all__ = [
    "SignalState",
    "SIGNAL_STATES",
    "VALID_TRANSITIONS",
    "Signal",
    "is_valid_transition",
    "transition_signal",
]


class SignalState:
    DETECTED = "DETECTED"
    ANALYZING = "ANALYZING"
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    ARMED = "ARMED"
    WAITING_TRIGGER = "WAITING_TRIGGER"
    EXECUTING = "EXECUTING"
    OPEN = "OPEN"
    MANAGING = "MANAGING"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


SIGNAL_STATES = (
    SignalState.DETECTED,
    SignalState.ANALYZING,
    SignalState.CANDIDATE,
    SignalState.VALIDATED,
    SignalState.ARMED,
    SignalState.WAITING_TRIGGER,
    SignalState.EXECUTING,
    SignalState.OPEN,
    SignalState.MANAGING,
    SignalState.CLOSED,
    SignalState.REJECTED,
    SignalState.EXPIRED,
)
#: Allowed next states per current state. Terminal states map to ().
VALID_TRANSITIONS: dict[str, tuple[str, ...]] = {
    SignalState.DETECTED: (SignalState.ANALYZING, SignalState.REJECTED),
    SignalState.ANALYZING: (SignalState.CANDIDATE, SignalState.REJECTED),
    SignalState.CANDIDATE: (SignalState.VALIDATED, SignalState.REJECTED),
    SignalState.VALIDATED: (SignalState.ARMED, SignalState.REJECTED),
    SignalState.ARMED: (SignalState.WAITING_TRIGGER, SignalState.EXPIRED),
    SignalState.WAITING_TRIGGER: (SignalState.EXECUTING, SignalState.EXPIRED),
    SignalState.EXECUTING: (SignalState.OPEN,),
    SignalState.OPEN: (SignalState.MANAGING, SignalState.CLOSED),
    SignalState.MANAGING: (SignalState.CLOSED,),
    SignalState.CLOSED: (),
    SignalState.REJECTED: (),
    SignalState.EXPIRED: (),
}


def is_valid_transition(current: str, new: str) -> bool:
    """True when ``current → new`` is an allowed signal transition."""
    return new in VALID_TRANSITIONS.get(str(current).upper(), ())


@dataclass
class Signal:
    """A tracked trading signal with explicit lifecycle."""

    signal_id: str
    trace_id: str = ""
    symbol: str = ""
    direction: str = "WAIT"
    state: str = SignalState.DETECTED
    decision_id: str = ""
    setup_id: str = ""
    proposal_id: str = ""
    reason: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    history: list[dict[str, Any]] = field(default_factory=list)

    def transition(self, new_state: str, reason: str = "") -> bool:
        """Attempt ``state → new_state``; returns False (no mutation) when invalid."""
        new_state = str(new_state).upper()
        if new_state not in SIGNAL_STATES:
            return False
        if not is_valid_transition(self.state, new_state):
            return False
        self.history.append(
            {
                "from": self.state,
                "to": new_state,
                "reason": reason,
                "at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self.state = new_state
        self.reason = reason
        self.updated_at = datetime.now(timezone.utc).isoformat()
        return True

    def is_terminal(self) -> bool:
        return self.state in (
            SignalState.CLOSED,
            SignalState.REJECTED,
            SignalState.EXPIRED,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "trace_id": self.trace_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "state": self.state,
            "decision_id": self.decision_id,
            "setup_id": self.setup_id,
            "proposal_id": self.proposal_id,
            "reason": self.reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "history": list(self.history),
        }


def transition_signal(signal: Signal, new_state: str, reason: str = "") -> bool:
    """Functional helper: transition ``signal`` and return success."""
    if not isinstance(signal, Signal):
        return False
    return signal.transition(new_state, reason)
