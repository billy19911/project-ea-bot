# -*- coding: utf-8 -*-
"""Tests for per-dependency circuit breakers — PRD_V2 §24 Circuit Breakers.

A breaker is provided for each external dependency: LLM gateway, market data,
MT5 connection, database, event queue, and execution. When the EXECUTION breaker
is open, new trading orders must be blocked (``check_can_execute``).
"""

from __future__ import annotations

import pytest

from risk.circuit_breaker import BreakerState
from risk.dependency_breakers import Dependency, DependencyBreakers


class TestRegistryIsolation:
    def test_all_dependencies_present(self) -> None:
        reg = DependencyBreakers()
        for dep in Dependency:
            assert reg.is_open(dep.value) is False

    def test_failures_are_isolated_per_dependency(self) -> None:
        reg = DependencyBreakers(failure_threshold=2, reset_window_seconds=60.0)
        reg.record_failure(Dependency.LLM)
        reg.record_failure(Dependency.LLM)
        assert reg.is_open(Dependency.LLM) is True
        # Other dependencies are unaffected.
        assert reg.is_open(Dependency.MARKET_DATA) is False
        assert reg.is_open(Dependency.EXECUTION) is False

    def test_unknown_dependency_key_raises(self) -> None:
        reg = DependencyBreakers()
        with pytest.raises(KeyError):
            reg.is_open("not_a_dependency")


class TestBreakerTripsAtThreshold:
    def test_opens_after_threshold(self) -> None:
        reg = DependencyBreakers(failure_threshold=3, reset_window_seconds=60.0)
        reg.record_failure(Dependency.MARKET_DATA)
        reg.record_failure(Dependency.MARKET_DATA)
        assert reg.is_open(Dependency.MARKET_DATA) is False
        reg.record_failure(Dependency.MARKET_DATA)
        assert reg.is_open(Dependency.MARKET_DATA) is True

    def test_success_resets_counter(self) -> None:
        reg = DependencyBreakers(failure_threshold=3, reset_window_seconds=60.0)
        reg.record_failure(Dependency.LLM)
        reg.record_failure(Dependency.LLM)
        reg.record_success(Dependency.LLM)
        reg.record_failure(Dependency.LLM)
        assert reg.is_open(Dependency.LLM) is False


class TestExecutionCritical:
    def test_check_can_execute_true_when_closed(self) -> None:
        reg = DependencyBreakers(failure_threshold=2, reset_window_seconds=60.0)
        allowed, reason = reg.check_can_execute()
        assert allowed is True
        assert reason == ""

    def test_execution_blocked_when_execution_breaker_open(self) -> None:
        reg = DependencyBreakers(failure_threshold=2, reset_window_seconds=60.0)
        reg.record_failure(Dependency.EXECUTION)
        reg.record_failure(Dependency.EXECUTION)
        assert reg.execution_critical_open() is True
        allowed, reason = reg.check_can_execute()
        assert allowed is False
        assert "execution" in reason.lower()

    def test_non_critical_dependency_does_not_block_execution(self) -> None:
        reg = DependencyBreakers(failure_threshold=2, reset_window_seconds=60.0)
        reg.record_failure(Dependency.LLM)
        reg.record_failure(Dependency.LLM)
        assert reg.is_open(Dependency.LLM) is True
        allowed, _ = reg.check_can_execute()
        assert allowed is True


class TestRecoveryHalfOpen:
    def test_half_open_after_reset_window(self) -> None:
        clock = _Clock()
        reg = DependencyBreakers(failure_threshold=2, reset_window_seconds=10.0, time_fn=clock)
        reg.record_failure(Dependency.MT5)
        reg.record_failure(Dependency.MT5)
        assert reg.is_open(Dependency.MT5) is True

        # Before the window elapses, still OPEN.
        clock.advance(5.0)
        assert reg.is_open(Dependency.MT5) is True

        # After the window, the breaker allows a half-open trial.
        clock.advance(6.0)
        assert reg.is_open(Dependency.MT5) is False

    def test_half_open_success_closes(self) -> None:
        clock = _Clock()
        reg = DependencyBreakers(failure_threshold=2, reset_window_seconds=10.0, time_fn=clock)
        reg.record_failure(Dependency.DB)
        reg.record_failure(Dependency.DB)
        clock.advance(11.0)
        # Pop into HALF_OPEN via is_open probe, then record success.
        reg.is_open(Dependency.DB)
        assert reg.state(Dependency.DB) is BreakerState.HALF_OPEN
        reg.record_success(Dependency.DB)
        assert reg.state(Dependency.DB) is BreakerState.CLOSED

    def test_half_open_failure_reopens(self) -> None:
        clock = _Clock()
        reg = DependencyBreakers(failure_threshold=2, reset_window_seconds=10.0, time_fn=clock)
        reg.record_failure(Dependency.QUEUE)
        reg.record_failure(Dependency.QUEUE)
        clock.advance(11.0)
        reg.is_open(Dependency.QUEUE)  # → HALF_OPEN
        assert reg.state(Dependency.QUEUE) is BreakerState.HALF_OPEN
        reg.record_failure(Dependency.QUEUE)
        assert reg.is_open(Dependency.QUEUE) is True


class TestSerialisation:
    def test_snapshot(self) -> None:
        reg = DependencyBreakers(failure_threshold=2, reset_window_seconds=60.0)
        reg.record_failure(Dependency.EXECUTION)
        snap = reg.snapshot()
        assert snap["execution"]["state"] == "closed"
        assert "llm" in snap
        assert reg.execution_critical_open() is False


class _Clock:
    """Deterministic monotonic clock for tests."""

    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
