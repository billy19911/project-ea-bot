# -*- coding: utf-8 -*-
"""Circuit Breaker — auto-triggered emergency halt on repeated failures.

Phase 13 (EPIC 07.08): A deterministic circuit breaker that trips when
consecutive failures or risk breaches reach a threshold. Trading is
auto-halted and the kill switch is triggered. Manual reset required.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from .kill_switch import KillSwitch

__all__ = ["BreakerState", "CircuitBreaker", "BreakerTripReason"]


class BreakerState(str, Enum):
    """Operational state of the circuit breaker."""

    CLOSED = "closed"
    """Normal — passing traffic, counting failures."""

    OPEN = "open"
    """Tripped — failing all calls."""

    HALF_OPEN = "half_open"
    """Reset trial — limited traffic allowed."""


class BreakerTripReason(str, Enum):
    """Why the circuit breaker tripped."""

    RISK_BREACH = "risk_breach"
    """Hard risk gate blocked a proposal."""

    EXECUTION_ERROR = "execution_error"
    """Order execution returned an error."""

    REJECTION = "rejection"
    """Broker rejected an order."""

    CONNECTION_LOST = "connection_lost"
    """MT5 connection was lost."""

    MANUAL = "manual"
    """Manually tripped by operator."""


@dataclass
class BreakerEvent:
    """A single failure or success event recorded by the breaker."""

    timestamp: str
    failure: bool
    reason: BreakerTripReason | None = None
    detail: str = ""


@dataclass
class CircuitBreaker:
    """Deterministic circuit breaker for trading operations.

    Counts consecutive failures. When the count reaches ``failure_threshold``,
    the breaker trips to OPEN and triggers the supplied kill switch.

    Attributes:
        failure_threshold: Failures before tripping (default 3).
        reset_window_seconds: Seconds of quiet before allowing half-open
            trial (default 60).
        state: Current breaker state.
        consecutive_failures: Current run of failures.
        last_failure_at: ISO timestamp of the last failure.
        kill_switch: The kill switch to trigger on trip.
        events: Recent breaker events.
    """

    failure_threshold: int = 3
    reset_window_seconds: float = 60.0
    state: BreakerState = BreakerState.CLOSED
    consecutive_failures: int = 0
    last_failure_at: str | None = None
    kill_switch: KillSwitch | None = None
    events: list[BreakerEvent] = field(default_factory=list)
    # Monotonic epoch of the last failure — used for the OPEN → HALF_OPEN
    # cooldown. Not part of ``to_dict`` (kept internal for observability).
    last_failure_epoch: float | None = None
    # Injectable clock (monotonic seconds) so the cooldown is testable.
    time_fn: Callable[[], float] = field(default=time.monotonic, repr=False)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def record_failure(self, reason: BreakerTripReason, detail: str = "") -> BreakerState:
        """Record a failure. Trips breaker when threshold is reached.

        Args:
            reason: Failure category.
            detail: Optional human-readable detail.

        Returns:
            The new breaker state (CLOSED or OPEN).
        """
        if self.state == BreakerState.OPEN:
            self.events.append(BreakerEvent(self._now(), True, reason, detail))
            return self.state

        self.consecutive_failures += 1
        self.last_failure_at = self._now()
        self.last_failure_epoch = self.time_fn()
        self.events.append(BreakerEvent(self._now(), True, reason, detail))

        if self.consecutive_failures >= self.failure_threshold:
            self.state = BreakerState.OPEN
            if self.kill_switch is not None:
                self.kill_switch.trigger(
                    reason=f"Circuit breaker tripped: {reason.value}",
                    triggered_by="circuit_breaker",
                )
                self.kill_switch.lock()

        return self.state

    def record_success(self) -> BreakerState:
        """Record a success — resets the failure counter.

        Returns:
            The new state (CLOSED).
        """
        self.consecutive_failures = 0
        self.events.append(BreakerEvent(self._now(), False))
        if self.state == BreakerState.HALF_OPEN:
            self.state = BreakerState.CLOSED
        return self.state

    def allow(self) -> bool:
        """Check if a call should be allowed.

        Returns:
            True when the breaker is CLOSED, False when OPEN.
        """
        return self.state == BreakerState.CLOSED

    def check_allow(self) -> bool:
        """Check whether a call is allowed, applying the HALF_OPEN cooldown.

        If the breaker is OPEN and ``reset_window_seconds`` have elapsed since
        the last failure, the breaker transitions to HALF_OPEN (a limited
        trial) and allows the call. A subsequent success closes the breaker; a
        subsequent failure re-opens it.

        Returns:
            True when a call may proceed (CLOSED or fresh HALF_OPEN), else False.
        """
        if self.state == BreakerState.OPEN:
            if self._cooldown_elapsed():
                self.state = BreakerState.HALF_OPEN
                return True
            return False
        return True

    def _cooldown_elapsed(self) -> bool:
        """True when the reset window has elapsed since the last failure."""
        if self.last_failure_epoch is None:
            # Trip without a recorded failure epoch (e.g. manual trip) — treat
            # the trip as immediate so a half-open trial is not blocked forever.
            return True
        return (self.time_fn() - self.last_failure_epoch) >= self.reset_window_seconds

    def reset(self) -> None:
        """Manually reset the breaker.

        Resets consecutive_failures but does not affect the kill switch.
        """
        self.state = BreakerState.CLOSED
        self.consecutive_failures = 0
        self.events.append(
            BreakerEvent(self._now(), False, BreakerTripReason.MANUAL, "manual reset")
        )

    def trip_manual(self) -> None:
        """Manually trip the breaker and trigger the kill switch."""
        self.state = BreakerState.OPEN
        self.consecutive_failures = self.failure_threshold
        self.events.append(BreakerEvent(self._now(), True, BreakerTripReason.MANUAL, "manual trip"))
        if self.kill_switch is not None:
            self.kill_switch.trigger(reason="Manual breaker trip", triggered_by="operator")
            self.kill_switch.lock()

    def to_dict(self) -> dict[str, Any]:
        """Serialize breaker state to dictionary."""
        return {
            "state": self.state.value,
            "consecutive_failures": self.consecutive_failures,
            "failure_threshold": self.failure_threshold,
            "last_failure_at": self.last_failure_at,
            "allow_trading": self.allow(),
            "kill_switch_state": (self.kill_switch.state.value if self.kill_switch else None),
            "events_recorded": len(self.events),
        }
