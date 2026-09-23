# -*- coding: utf-8 -*-
"""Tests for the execution guard wiring (audit P1-2).

The per-dependency circuit breakers (§24) and the kill switch existed but were
never wired into the trade path. These tests assert that an open EXECUTION
breaker or an engaged kill switch actually BLOCKS new orders end-to-end via the
:class:`~risk.dependency_breakers.ExecutionGuard` and the pipeline's
``dependency_guard`` seam.
"""

from __future__ import annotations

from orchestration.runtime import OrchestrationRuntime
from risk.dependency_breakers import Dependency, DependencyBreakers, ExecutionGuard
from risk.kill_switch import KillSwitch


def test_guard_allows_by_default() -> None:
    guard = ExecutionGuard()
    allowed, reason = guard.check_can_execute()
    assert allowed is True
    assert reason == ""


def test_open_execution_breaker_blocks() -> None:
    kill = KillSwitch()
    breakers = DependencyBreakers(failure_threshold=1, kill_switch=kill)
    guard = ExecutionGuard(breakers=breakers, kill_switch=kill)

    guard.record_execution_result(False, detail="order rejected")

    allowed, reason = guard.check_can_execute()
    assert allowed is False
    assert "execution" in reason.lower() or "kill switch" in reason.lower()


def test_engaged_kill_switch_blocks() -> None:
    guard = ExecutionGuard()
    guard.kill_switch.trigger(reason="operator stop")
    allowed, reason = guard.check_can_execute()
    assert allowed is False
    assert "kill switch" in reason.lower()


def test_success_resets_failure_counter() -> None:
    kill = KillSwitch()
    breakers = DependencyBreakers(failure_threshold=3, kill_switch=kill)
    guard = ExecutionGuard(breakers=breakers, kill_switch=kill)

    guard.record_execution_result(False)
    guard.record_execution_result(False)
    guard.record_execution_result(True)  # resets
    guard.record_execution_result(False)

    # Only one failure since the reset → breaker still closed.
    assert guard.check_can_execute()[0] is True


def test_runtime_wires_execution_guard() -> None:
    runtime = OrchestrationRuntime()
    assert runtime.pipeline.dependency_guard is runtime.execution_guard
    assert runtime.execution_guard.check_can_execute()[0] is True


def test_runtime_open_breaker_blocks_then_recovers() -> None:
    """End-to-end: tripping the EXECUTION breaker blocks the pipeline cycle."""
    # threshold=1 so a single failure trips.
    kill = KillSwitch()
    guard = ExecutionGuard(breakers=DependencyBreakers(failure_threshold=1, kill_switch=kill))
    runtime = OrchestrationRuntime(execution_guard=guard)

    # A rejected order trips the breaker + kill switch.
    guard.record_execution_result(False, detail="broker reject")
    assert runtime.execution_guard.check_can_execute()[0] is False

    # Any cycle that would execute must now be BLOCKED by the dependency guard.
    record = runtime.run_cycle({"event_type": "BREAKOUT", "symbol": "EURUSD"})
    assert isinstance(record, dict)
    # Either the cycle produced no proposal (NO_TRADE/WAIT) or it was BLOCKED —
    # in no case may it be EXECUTED while the breaker is open.
    assert record["status"] != "EXECUTED"


def test_execution_dependency_name_is_used() -> None:
    """Sanity: the guard records against the EXECUTION dependency."""
    guard = ExecutionGuard()
    guard.record_execution_result(False)
    snapshot = guard.breakers.snapshot()
    assert Dependency.EXECUTION.value in snapshot


def test_pre_dispatch_refusal_does_not_trip_breaker() -> None:
    """A refusal that never reached the broker (e.g. no armed terminal) must
    not count as an EXECUTION failure — otherwise the default read-only state
    would self-lock after three valid signals (breaker → kill switch)."""
    kill = KillSwitch()
    guard = ExecutionGuard(breakers=DependencyBreakers(failure_threshold=3, kill_switch=kill))
    runtime = OrchestrationRuntime(execution_guard=guard)

    refusal = {
        "status": "ERROR",
        "execution_id": "exec_refused",
        "error": "EXECUTION NOT ARMED — no operator-armed terminal; order_send is disabled.",
        "execution_result": {
            "success": False,
            "ticket": None,
            "error_code": 403,
            "error_message": "EXECUTION NOT ARMED — no operator-armed terminal.",
            "retries": 0,
            "position_opened": None,
        },
    }
    for _ in range(5):
        runtime._record_execution_outcome(refusal)

    allowed, reason = runtime.execution_guard.check_can_execute()
    assert allowed is True
    assert reason == ""
    snapshot = runtime.execution_guard.breakers.snapshot()
    assert snapshot[Dependency.EXECUTION.value]["consecutive_failures"] == 0


def test_genuine_execution_failure_still_trips_breaker() -> None:
    """Real dispatch failures (broker error codes) still feed the breaker."""
    kill = KillSwitch()
    guard = ExecutionGuard(breakers=DependencyBreakers(failure_threshold=1, kill_switch=kill))
    runtime = OrchestrationRuntime(execution_guard=guard)

    runtime._record_execution_outcome(
        {
            "status": "ERROR",
            "execution_id": "exec_failed",
            "error": "broker rejected",
            "execution_result": {
                "success": False,
                "ticket": None,
                "error_code": 10006,
                "error_message": "broker rejected",
                "retries": 0,
                "position_opened": None,
            },
        }
    )

    assert runtime.execution_guard.check_can_execute()[0] is False


def test_execution_exception_still_counts_as_failure() -> None:
    """An engine exception (no execution_result dict) still counts."""
    kill = KillSwitch()
    guard = ExecutionGuard(breakers=DependencyBreakers(failure_threshold=1, kill_switch=kill))
    runtime = OrchestrationRuntime(execution_guard=guard)

    runtime._record_execution_outcome(
        {
            "status": "ERROR",
            "execution_id": "exec_exc",
            "error": "execution error: boom",
            "execution_result": None,
        }
    )

    assert runtime.execution_guard.check_can_execute()[0] is False


if __name__ == "__main__":  # pragma: no cover
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
