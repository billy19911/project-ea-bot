# -*- coding: utf-8 -*-
"""Tests for EPIC 07.08 — Circuit Breaker.

Deterministic auto-trip on repeated failures.
"""

from __future__ import annotations

from risk.circuit_breaker import BreakerState, BreakerTripReason, CircuitBreaker
from risk.kill_switch import KillSwitch, KillSwitchState


class TestCircuitBreaker:
    """Tests for CircuitBreaker class."""

    def test_initial_state_closed(self) -> None:
        """Breaker starts CLOSED — trading allowed."""
        breaker = CircuitBreaker(failure_threshold=3)
        assert breaker.state == BreakerState.CLOSED
        assert breaker.allow() is True

    def test_failure_count_increments(self) -> None:
        """Recording failures increments counter."""
        breaker = CircuitBreaker(failure_threshold=3)
        breaker.record_failure(BreakerTripReason.RISK_BREACH, "drawdown breach")
        assert breaker.consecutive_failures == 1
        assert breaker.state == BreakerState.CLOSED

    def test_trips_at_threshold(self) -> None:
        """Failure count reaching threshold trips the breaker."""
        breaker = CircuitBreaker(failure_threshold=3)
        breaker.record_failure(BreakerTripReason.EXECUTION_ERROR)
        breaker.record_failure(BreakerTripReason.REJECTION)
        breaker.record_failure(BreakerTripReason.EXECUTION_ERROR)
        assert breaker.state == BreakerState.OPEN
        assert breaker.allow() is False

    def test_success_resets_counter(self) -> None:
        """Success resets consecutive failures and keeps CLOSED."""
        breaker = CircuitBreaker(failure_threshold=3)
        breaker.record_failure(BreakerTripReason.RISK_BREACH)
        breaker.record_success()
        assert breaker.consecutive_failures == 0
        assert breaker.state == BreakerState.CLOSED

    def test_open_stays_open(self) -> None:
        """Once OPEN, additional failures do not change state."""
        breaker = CircuitBreaker(failure_threshold=2)
        breaker.record_failure(BreakerTripReason.RISK_BREACH)
        breaker.record_failure(BreakerTripReason.RISK_BREACH)
        breaker.record_failure(BreakerTripReason.REJECTION)
        assert breaker.state == BreakerState.OPEN
        assert breaker.consecutive_failures == 2  # capped at threshold

    def test_manual_trip(self) -> None:
        """Manual trip opens breaker immediately."""
        breaker = CircuitBreaker(failure_threshold=5)
        breaker.trip_manual()
        assert breaker.state == BreakerState.OPEN
        assert breaker.allow() is False

    def test_manual_reset(self) -> None:
        """Manual reset closes breaker and clears counter."""
        breaker = CircuitBreaker(failure_threshold=2)
        breaker.record_failure(BreakerTripReason.RISK_BREACH)
        breaker.record_failure(BreakerTripReason.RISK_BREACH)
        assert breaker.state == BreakerState.OPEN
        breaker.reset()
        assert breaker.state == BreakerState.CLOSED
        assert breaker.consecutive_failures == 0

    def test_to_dict(self) -> None:
        """Serialization includes all fields."""
        breaker = CircuitBreaker(failure_threshold=2)
        breaker.record_failure(BreakerTripReason.RISK_BREACH)
        d = breaker.to_dict()
        assert d["state"] == "closed"
        assert d["consecutive_failures"] == 1
        assert d["allow_trading"] is True
        assert d["events_recorded"] == 1


class TestCircuitBreakerWithKillSwitch:
    """Breaker integration with KillSwitch."""

    def test_trip_triggers_kill_switch(self) -> None:
        """When breaker trips, it triggers and locks the kill switch."""
        ks = KillSwitch()
        breaker = CircuitBreaker(failure_threshold=2, kill_switch=ks)
        breaker.record_failure(BreakerTripReason.RISK_BREACH)
        assert ks.state == KillSwitchState.ACTIVE  # threshold not reached
        breaker.record_failure(BreakerTripReason.REJECTION)
        # Auto-lock is the safe default: manual reset + confirmation required.
        assert ks.state == KillSwitchState.LOCKED
        assert breaker.state == BreakerState.OPEN
        assert ks.locked is True
        assert ks.is_blocked() is True

    def test_trips_kill_switch_even_without_kill_switch(self) -> None:
        """Breaker opens even if no kill switch supplied."""
        breaker = CircuitBreaker(failure_threshold=2)
        breaker.record_failure(BreakerTripReason.EXECUTION_ERROR)
        breaker.record_failure(BreakerTripReason.EXECUTION_ERROR)
        assert breaker.state == BreakerState.OPEN

    def test_manual_trip_locks_kill_switch(self) -> None:
        """Manual trip triggers and locks kill switch."""
        ks = KillSwitch()
        breaker = CircuitBreaker(failure_threshold=10, kill_switch=ks)
        breaker.trip_manual()
        assert ks.state == KillSwitchState.LOCKED
        assert ks.locked is True
        assert breaker.state == BreakerState.OPEN
