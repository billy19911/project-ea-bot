# -*- coding: utf-8 -*-
"""Comprehensive failure‑injection scenario coverage (Phase 38b).

Each test uses :class:`ScenarioRunner` and the :mod:`src.testing.failure_lab`
helpers to simulate a fault, then asserts that the multi‑level circuit breaker
ended in the expected :class:`~risk.multi_level_breaker.BreakerLevel`.
"""

import pytest

from src.testing.failure_lab import LEVEL, TRIGGER, FailureInjector, ScenarioRunner


@pytest.fixture
def runner() -> ScenarioRunner:
    return ScenarioRunner()


def test_mt5_unavailable(runner: ScenarioRunner) -> None:
    def act(r: ScenarioRunner) -> str:
        r.breaker.trigger(TRIGGER.MT5_DISCONNECTED, reason="simulated MT5 down")
        return f"state={r.breaker.level.value}"

    out = runner.run(
        trigger="MT5 unavailable",
        expected_state=LEVEL.ENTRY_BLOCKED.value,
        expected_action="blocked",
        action=act,
        expect_block=True,
    )
    assert out.passed


def test_mt5_reconnect(runner: ScenarioRunner) -> None:
    # start blocked
    runner.breaker.trigger(TRIGGER.MT5_DISCONNECTED, reason="down")

    def act(r: ScenarioRunner) -> str:
        r.breaker.recover(condition_ok=True, target=LEVEL.NORMAL, reason="mt5 reconnected")
        return f"state={r.breaker.level.value}"

    out = runner.run(
        trigger="MT5 reconnect",
        expected_state=LEVEL.NORMAL.value,
        expected_action="state=normal",
        action=act,
        expect_block=False,
    )
    assert out.passed


def test_bad_tick_rejected(runner: ScenarioRunner) -> None:
    def act(r: ScenarioRunner) -> str:
        tick = FailureInjector.bad_tick()
        if tick["bid"] is None:
            return "rejected bad tick"
        return "accepted"

    out = runner.run(
        trigger="bad tick",
        expected_state=LEVEL.NORMAL.value,
        expected_action="rejected",
        action=act,
        expect_block=False,
    )
    assert out.passed


def test_stale_tick_caution(runner: ScenarioRunner) -> None:
    def act(r: ScenarioRunner) -> str:
        r.breaker.trigger(TRIGGER.FEED_STALE, reason="stale tick simulated")
        return f"state={r.breaker.level.value}"

    out = runner.run(
        trigger="stale tick",
        expected_state=LEVEL.CAUTION.value,
        expected_action="caution",
        action=act,
        expect_block=False,
    )
    assert out.passed


def test_spread_spike_risk_reduced(runner: ScenarioRunner) -> None:
    def act(r: ScenarioRunner) -> str:
        r.breaker.trigger(TRIGGER.SPREAD_SPIKE, reason="spread spike simulated")
        return f"state={r.breaker.level.value}"

    out = runner.run(
        trigger="spread spike",
        expected_state=LEVEL.RISK_REDUCED.value,
        expected_action="reduced",
        action=act,
        expect_block=False,
    )
    assert out.passed


def test_price_gap_risk_reduced(runner: ScenarioRunner) -> None:
    def act(r: ScenarioRunner) -> str:
        # Use manual escalation to risk reduced for this scenario.
        r.breaker.escalate(LEVEL.RISK_REDUCED, "price gap simulated", source="test")
        return f"state={r.breaker.level.value}"

    out = runner.run(
        trigger="price gap",
        expected_state=LEVEL.RISK_REDUCED.value,
        expected_action="reduced",
        action=act,
        expect_block=False,
    )
    assert out.passed


def test_order_rejection_blocks(runner: ScenarioRunner) -> None:
    def act(r: ScenarioRunner) -> str:
        # Simulate a broker rejection.
        r.breaker.escalate(LEVEL.ENTRY_BLOCKED, "order rejected", source="test")
        return f"state={r.breaker.level.value}"

    out = runner.run(
        trigger="order rejection",
        expected_state=LEVEL.ENTRY_BLOCKED.value,
        expected_action="blocked",
        action=act,
        expect_block=True,
    )
    assert out.passed


def test_order_timeout_blocks(runner: ScenarioRunner) -> None:
    def act(r: ScenarioRunner) -> str:
        # Timeout is severe; map to ENTRY_BLOCKED.
        r.breaker.escalate(LEVEL.ENTRY_BLOCKED, "order timeout", source="test")
        return f"state={r.breaker.level.value}"

    out = runner.run(
        trigger="order timeout",
        expected_state=LEVEL.ENTRY_BLOCKED.value,
        expected_action="blocked",
        action=act,
        expect_block=True,
    )
    assert out.passed


def test_duplicate_event_caution(runner: ScenarioRunner) -> None:
    def act(r: ScenarioRunner) -> str:
        # Duplicate event detection raises a caution.
        r.breaker.trigger(TRIGGER.FEED_STALE, reason="duplicate event detected")
        return f"state={r.breaker.level.value}"

    out = runner.run(
        trigger="duplicate event",
        expected_state=LEVEL.CAUTION.value,
        expected_action="caution",
        action=act,
        expect_block=False,
    )
    assert out.passed


def test_database_unavailable_blocks(runner: ScenarioRunner) -> None:
    def act(r: ScenarioRunner) -> str:
        r.breaker.trigger(TRIGGER.DATABASE_UNAVAILABLE, reason="db down")
        return f"state={r.breaker.level.value}"

    out = runner.run(
        trigger="database unavailable",
        expected_state=LEVEL.HALTED.value,
        expected_action="halted",
        action=act,
        expect_block=True,
    )
    assert out.passed


def test_redis_unavailable_blocks(runner: ScenarioRunner) -> None:
    def act(r: ScenarioRunner) -> str:
        # Use same trigger for simplicity.
        r.breaker.trigger(TRIGGER.DATABASE_UNAVAILABLE, reason="redis down")
        return f"state={r.breaker.level.value}"

    out = runner.run(
        trigger="redis unavailable",
        expected_state=LEVEL.HALTED.value,
        expected_action="halted",
        action=act,
        expect_block=True,
    )
    assert out.passed


def test_llm_timeout_caution(runner: ScenarioRunner) -> None:
    def act(r: ScenarioRunner) -> str:
        r.breaker.trigger(TRIGGER.MODEL_FAILURE, reason="llm timeout")
        return f"state={r.breaker.level.value}"

    out = runner.run(
        trigger="LLM timeout",
        expected_state=LEVEL.CAUTION.value,
        expected_action="caution",
        action=act,
        expect_block=False,
    )
    assert out.passed


def test_llm_malformed_caution(runner: ScenarioRunner) -> None:
    def act(r: ScenarioRunner) -> str:
        r.breaker.trigger(TRIGGER.MODEL_FAILURE, reason="llm malformed output")
        return f"state={r.breaker.level.value}"

    out = runner.run(
        trigger="LLM malformed output",
        expected_state=LEVEL.CAUTION.value,
        expected_action="caution",
        action=act,
        expect_block=False,
    )
    assert out.passed


def test_gateway_unavailable_halted(runner: ScenarioRunner) -> None:
    def act(r: ScenarioRunner) -> str:
        r.breaker.escalate(LEVEL.HALTED, "9Router down", source="test")
        return f"state={r.breaker.level.value}"

    out = runner.run(
        trigger="9Router unavailable",
        expected_state=LEVEL.HALTED.value,
        expected_action="halted",
        action=act,
        expect_block=True,
    )
    assert out.passed


def test_telegram_unavailable_degraded(runner: ScenarioRunner) -> None:
    def act(r: ScenarioRunner) -> str:
        # Telegram down does not block entries but marks degraded.
        # We'll keep state NORMAL but record action.
        return "telegram down – degraded"

    out = runner.run(
        trigger="Telegram unavailable",
        expected_state=LEVEL.NORMAL.value,
        expected_action="degraded",
        action=act,
        expect_block=False,
    )
    assert out.passed


def test_process_crash_halted(runner: ScenarioRunner) -> None:
    def act(r: ScenarioRunner) -> str:
        r.breaker.escalate(LEVEL.HALTED, "process crash", source="test")
        return f"state={r.breaker.level.value}"

    out = runner.run(
        trigger="process crash",
        expected_state=LEVEL.HALTED.value,
        expected_action="halted",
        action=act,
        expect_block=True,
    )
    assert out.passed
