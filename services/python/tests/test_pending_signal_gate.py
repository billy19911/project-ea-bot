# -*- coding: utf-8 -*-
"""Integration tests: the pipeline's pending-signal gate (FOKUS #2).

Scenario the user reported: the same ``#BTCUSD BUY`` signal was recorded every
cycle, and when execution failed closed (terminal not armed) the identical
``BUY / ERROR`` row repeated indefinitely. The gate must:

* run the committee and open a signal on the FIRST actionable cycle,
* NOT re-run the committee while that signal is live (PENDING/EXECUTING/OPEN),
* put a FAILED execution into cooldown so the identical signal is not re-emitted,
* free the symbol again once the signal is CLOSED.
"""

from __future__ import annotations

from test_pipeline_orchestration import (
    FakeExecutionEngine,
    FakeRiskGate,
    FakeSupervisor,
    _approved,
    _context,
    _event,
    _synthesis,
)

from orchestration import pipeline as pipeline_mod
from orchestration.pipeline import TradingPipeline
from orchestration.signal_registry import SignalRegistry
from risk.gate import GateDecision


class _Ok:
    success = True
    ticket = 999
    error_code = 0
    error_message = ""
    retries = 0
    position_opened = {"symbol": "EURUSD", "positions_count": 1}


class _Fail:
    success = False
    ticket = None
    error_code = 403
    error_message = "EXECUTION NOT ARMED"
    retries = 0
    position_opened = None


def _build(engine, registry) -> TradingPipeline:
    return TradingPipeline(
        supervisor=FakeSupervisor(_synthesis()),
        risk_gate=FakeRiskGate(_approved()),
        execution_engine=engine,
        signal_registry=registry,
    )


def test_first_cycle_opens_signal_and_executes():
    registry = SignalRegistry()
    result = _build(FakeExecutionEngine(_Ok()), registry).run(_event(), _context())

    assert result.status == pipeline_mod.STATUS_EXECUTED
    record = registry.get("EURUSD")
    assert record is not None
    assert record.phase == "OPEN"


def test_second_cycle_is_gated_while_signal_open():
    registry = SignalRegistry()
    pipe = _build(FakeExecutionEngine(_Ok()), registry)

    first = pipe.run(_event(), _context())
    second = pipe.run(_event(), _context())

    assert first.status == pipeline_mod.STATUS_EXECUTED
    # The second cycle must NOT re-run the committee: it is gated.
    assert second.status == pipeline_mod.STATUS_SIGNAL_PENDING
    assert second.decision == "BUY"


def test_failed_execution_enters_cooldown_not_respam():
    registry = SignalRegistry()
    pipe = _build(FakeExecutionEngine(_Fail()), registry)

    first = pipe.run(_event(), _context())
    second = pipe.run(_event(), _context())

    assert first.status == pipeline_mod.STATUS_ERROR
    assert registry.get("EURUSD").phase == "FAILED"
    # Second cycle is gated by the failure cooldown, not re-executed.
    assert second.status == pipeline_mod.STATUS_SIGNAL_PENDING


def test_closed_signal_allows_fresh_cycle():
    registry = SignalRegistry()
    pipe = _build(FakeExecutionEngine(_Ok()), registry)

    pipe.run(_event(), _context())
    assert pipe.run(_event(), _context()).status == pipeline_mod.STATUS_SIGNAL_PENDING

    # Position closes → the symbol frees up again.
    registry.mark_closed("EURUSD")
    third = pipe.run(_event(), _context())
    assert third.status == pipeline_mod.STATUS_EXECUTED


def test_risk_rejection_skips_not_open():
    registry = SignalRegistry()
    pipe = TradingPipeline(
        supervisor=FakeSupervisor(_synthesis()),
        risk_gate=FakeRiskGate(
            GateDecision(approved=False, reason="spread", checks_passed={}, metrics_snapshot={})
        ),
        execution_engine=FakeExecutionEngine(_Ok()),
        signal_registry=registry,
    )
    result = pipe.run(_event(), _context())

    assert result.status == pipeline_mod.STATUS_BLOCKED
    # Skipped → terminal, not active (a different signal may come later).
    assert registry.get("EURUSD").phase == "SKIPPED"
    assert registry.has_active("EURUSD") is False


def test_gate_disabled_still_reexecutes():
    registry = SignalRegistry()
    pipe = TradingPipeline(
        supervisor=FakeSupervisor(_synthesis()),
        risk_gate=FakeRiskGate(_approved()),
        execution_engine=FakeExecutionEngine(_Ok()),
        signal_registry=registry,
        pending_signal_guard=False,
    )
    first = pipe.run(_event(), _context())
    second = pipe.run(_event(), _context())
    assert first.status == pipeline_mod.STATUS_EXECUTED
    assert second.status == pipeline_mod.STATUS_EXECUTED


def test_gate_skips_when_no_symbol():
    """A cycle without a resolvable symbol is never gated."""
    registry = SignalRegistry()
    registry.open_signal("EURUSD", "BUY")  # unrelated live signal
    pipe = _build(FakeExecutionEngine(_Ok()), registry)
    # Event/context without a symbol → pipeline uses "" → gate must not fire.
    result = pipe.run({"event_id": "e", "event_type": "X"}, {"event_type": "X"})
    assert result.status != pipeline_mod.STATUS_SIGNAL_PENDING
