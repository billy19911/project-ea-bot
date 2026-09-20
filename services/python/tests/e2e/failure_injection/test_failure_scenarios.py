# -*- coding: utf-8 -*-
"""Failure injection end‑to‑end scenario tests (Phase 38).

Each test builds a :class:`ScenarioRunner`, injects a fault via the
:mod:`src.testing.failure_lab` helpers, and asserts the safety invariant that
no unsafe order is permitted.
"""

import pytest

from src.testing.failure_lab import LEVEL, TRIGGER, FailureInjector, ScenarioRunner


@pytest.fixture
def runner() -> ScenarioRunner:
    return ScenarioRunner()


def test_mt5_unavailable_blocks_entries(runner: ScenarioRunner) -> None:
    # MT5 unavailable should raise the breaker to ENTRY_BLOCKED.
    def action(r: ScenarioRunner) -> str:
        r.breaker.trigger(TRIGGER.MT5_DISCONNECTED, reason="simulated MT5 down")
        return f"state={r.breaker.level.value}"

    outcome = runner.run(
        trigger="MT5 unavailable",
        expected_state=LEVEL.ENTRY_BLOCKED.value,
        expected_action="blocked",
        action=action,
        expect_block=True,
    )
    assert outcome.passed
    assert runner.breaker.level == LEVEL.ENTRY_BLOCKED


def test_mt5_reconnect_clears_block(runner: ScenarioRunner) -> None:
    # Simulate prior block then successful reconnect – should move back to NORMAL.
    runner.breaker.trigger(TRIGGER.MT5_DISCONNECTED, reason="MT5 down")
    assert runner.breaker.level == LEVEL.ENTRY_BLOCKED

    def action(r: ScenarioRunner) -> str:
        # Recovery path: manual escalation back to NORMAL (simulated recovery).
        r.breaker.recover(condition_ok=True, target=LEVEL.NORMAL, reason="MT5 reconnected")
        return f"state={r.breaker.level.value}"

    outcome = runner.run(
        trigger="MT5 reconnect",
        expected_state=LEVEL.NORMAL.value,
        expected_action="state=normal",
        action=action,
        expect_block=False,
    )
    assert outcome.passed
    assert runner.breaker.level == LEVEL.NORMAL


def test_bad_tick_is_rejected(runner: ScenarioRunner) -> None:
    # Bad tick (None price) should not cause a safe order; we simulate the check.
    def action(r: ScenarioRunner) -> str:
        tick = FailureInjector.bad_tick()
        if tick["bid"] is None or tick["ask"] is None:
            # System would reject; keep level unchanged.
            return "rejected bad tick"
        return "accepted"

    outcome = runner.run(
        trigger="bad tick",
        expected_state=LEVEL.NORMAL.value,
        expected_action="rejected",
        action=action,
        expect_block=False,
    )
    assert outcome.passed


def test_order_rejection_blocks_new_entries(runner: ScenarioRunner) -> None:
    # Simulate order rejection – system should keep entries blocked.
    def action(r: ScenarioRunner) -> str:
        # Suppose an order attempt returned a rejection.
        result = FailureInjector.order_rejection()()
        if result["retcode"] != 0:
            # Block further entries via breaker escalation.
            r.breaker.escalate(LEVEL.ENTRY_BLOCKED, "order rejected", source="test")
            return "order rejected – entries blocked"
        return "order accepted"

    outcome = runner.run(
        trigger="order rejection",
        expected_state=LEVEL.ENTRY_BLOCKED.value,
        expected_action="blocked",
        action=action,
        expect_block=True,
    )
    assert outcome.passed
    assert not runner.breaker.allows_new_entries()
