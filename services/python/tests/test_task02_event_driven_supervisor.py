# -*- coding: utf-8 -*-
"""Tests for TASK 02 — event-driven supervisor / wake model.

Covers:
  * Event classification (TRADE_TRIGGER / CONTEXT_UPDATE / HOUSEKEEPING /
    TRADE_CLOSE) — housekeeping must never create a trade proposal.
  * Qualifying-event gating: a qualifying event wakes the scheduler and runs
    the committee; a non-qualifying event does NOT.
  * No-event behaviour: an empty queue processes nothing (supervisor idle).
  * Duplicate-event behaviour: identical events within the TTL window do not
    re-run the committee; materially changed events do.
  * Event trace: each analysis records its exact wake cause.
  * End-to-end runtime wiring: the production scheduler carries an EventGate,
    and the RISK/housekeeping events from the risk monitor cannot convene the
    committee.

These tests are hermetic: they use an in-process pipeline stub and never touch
MT5/execution.
"""

from __future__ import annotations

from typing import Any

from orchestration.pipeline import PipelineResult
from trading.event_classes import (
    EventClassKind,
    EventFingerprintGuillotine,
    EventGate,
    classify_event_class,
    is_trade_trigger,
    should_run_committee,
)
from trading.event_engine import EventQueue
from trading.events import DetectedEvent, EventTypes
from trading.scheduler import AutonomousScheduler

# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


class CountingPipeline:
    """Pipeline stub that records every cycle it runs."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def run(self, event: Any, context: Any = None) -> PipelineResult:
        symbol = event.symbol if hasattr(event, "symbol") else event.get("symbol", "")
        event_type = getattr(event.event_type, "value", event.event_type)
        self.calls.append((symbol, event_type))
        return PipelineResult(event_id=symbol, decision="WAIT", status="NO_TRADE")


def _event(
    event_type: EventTypes, symbol: str = "XAUUSD", timestamp: str = "bar-1"
) -> DetectedEvent:
    ev = DetectedEvent(
        event_type=event_type,
        severity=0.5,
        description=f"{event_type.value}",
        timestamp=timestamp,
        symbol=symbol,
    )
    # bar_time drives the fingerprint (a new bar = materially changed event).
    ev.bar_time = timestamp
    return ev


# ===========================================================================
# 1. Event classification
# ===========================================================================
class TestEventClassification:
    def test_trade_triggers(self):
        for name in (
            "BREAKOUT",
            "BREAKDOWN",
            "REVERSAL",
            "STRUCTURE_SHIFT",
            "MOMENTUM_CONFIRMATION",
            "ZONE_ENTRY",
            "VOLATILITY_EXPANSION",
        ):
            assert classify_event_class(name) == EventClassKind.TRADE_TRIGGER, name
            assert is_trade_trigger(name) is True
            assert should_run_committee(name) is True

    def test_trend_and_momentum_are_triggers(self):
        # The production detector emits these; the committee acts on them.
        for name in ("TREND_BULLISH", "TREND_BEARISH", "MOMENTUM_BULLISH", "DOJI"):
            assert classify_event_class(name) == EventClassKind.TRADE_TRIGGER, name

    def test_housekeeping_must_not_create_signal(self):
        for name in (
            "RISK_DRAWDOWN",
            "RISK_EXPOSURE",
            "RISK_MARGIN",
            "DRAWDOWN_WARNING",
            "EXPOSURE_LIMIT_REACHED",
            "RECONCILIATION",
            "HEALTH_CHECK",
            "METRICS",
            "POSITION_OPENED",
            "POSITION_CLOSED",
        ):
            assert classify_event_class(name) == EventClassKind.HOUSEKEEPING, name
            assert should_run_committee(name) is False, name

    def test_context_update_events(self):
        for name in ("NEWS_HIGH_IMPACT", "NEWS_UPDATE", "ECONOMIC_EVENT", "MACRO_EVENT"):
            assert classify_event_class(name) == EventClassKind.CONTEXT_UPDATE, name
            assert should_run_committee(name) is False, name

    def test_regime_change_is_context_not_trigger(self):
        assert classify_event_class("REGIME_CHANGE") == EventClassKind.CONTEXT_UPDATE

    def test_trade_close_is_review_not_trigger(self):
        assert classify_event_class("TRADE_CLOSE") == EventClassKind.TRADE_CLOSE
        assert should_run_committee("TRADE_CLOSE") is False

    def test_unknown_defaults_to_context(self):
        assert classify_event_class("SOME_RANDOM_NOISE") == EventClassKind.CONTEXT_UPDATE

    def test_case_insensitive(self):
        assert classify_event_class("breakout") == EventClassKind.TRADE_TRIGGER
        assert classify_event_class("risk_drawdown") == EventClassKind.HOUSEKEEPING


# ===========================================================================
# 2. Fingerprint deduplication
# ===========================================================================
class TestFingerprintGuillotine:
    def test_first_seen_is_new_then_duplicate_suppressed(self):
        guillotine = EventFingerprintGuillotine(default_ttl_seconds=300.0)
        fp = ("XAUUSD", "BREAKOUT", "bar-1")
        assert guillotine.check_and_record("XAUUSD", "BREAKOUT", fp) is True
        assert guillotine.check_and_record("XAUUSD", "BREAKOUT", fp) is False
        assert guillotine.check_and_record("XAUUSD", "BREAKOUT", fp) is False

    def test_materially_changed_fingerprint_passes(self):
        guillotine = EventFingerprintGuillotine(default_ttl_seconds=300.0)
        assert guillotine.check_and_record("XAUUSD", "BREAKOUT", ("XAUUSD", "BREAKOUT", "bar-1"))
        # New bar → materially different event → allowed.
        assert guillotine.check_and_record("XAUUSD", "BREAKOUT", ("XAUUSD", "BREAKOUT", "bar-2"))

    def test_ttl_expiry_allows_re_emission(self):
        now = [1000.0]
        guillotine = EventFingerprintGuillotine(default_ttl_seconds=300.0)
        guillotine._clock = lambda: now[0]
        fp = ("XAUUSD", "REVERSAL", "bar-1")
        assert guillotine.check_and_record("XAUUSD", "REVERSAL", fp) is True
        assert guillotine.check_and_record("XAUUSD", "REVERSAL", fp) is False
        now[0] += 301.0
        assert guillotine.check_and_record("XAUUSD", "REVERSAL", fp) is True

    def test_distinct_symbols_and_types_are_independent(self):
        guillotine = EventFingerprintGuillotine(default_ttl_seconds=300.0)
        assert guillotine.check_and_record("XAUUSD", "BREAKOUT", ("XAUUSD", "BREAKOUT", "b1"))
        assert guillotine.check_and_record("EURUSD", "BREAKOUT", ("EURUSD", "BREAKOUT", "b1"))
        assert guillotine.check_and_record("XAUUSD", "REVERSAL", ("XAUUSD", "REVERSAL", "b1"))


# ===========================================================================
# 3. EventGate (classification + dedup)
# ===========================================================================
class TestEventGate:
    def test_housekeeping_blocked(self):
        gate = EventGate()
        allowed, reason = gate.check("RISK_DRAWDOWN", "XAUUSD", ("XAUUSD", "RISK_DRAWDOWN", "b1"))
        assert allowed is False
        assert "non-qualifying" in reason

    def test_context_update_blocked(self):
        gate = EventGate()
        allowed, _ = gate.check("NEWS_HIGH_IMPACT", "XAUUSD", ("XAUUSD", "NEWS", "b1"))
        assert allowed is False

    def test_trade_trigger_allowed_then_deduped(self):
        gate = EventGate()
        fp = ("XAUUSD", "BREAKOUT", "b1")
        allowed, _ = gate.check("BREAKOUT", "XAUUSD", fp)
        assert allowed is True
        allowed, reason = gate.check("BREAKOUT", "XAUUSD", fp)
        assert allowed is False
        assert "duplicate" in reason

    def test_stats(self):
        gate = EventGate()
        gate.check("BREAKOUT", "XAUUSD", ("XAUUSD", "BREAKOUT", "b1"))
        gate.check("BREAKOUT", "XAUUSD", ("XAUUSD", "BREAKOUT", "b1"))  # dup
        gate.check("RISK_DRAWDOWN", "XAUUSD", ("XAUUSD", "RISK", "b1"))  # class
        stats = gate.stats()
        assert stats["checked"] == 3
        assert stats["allowed"] == 1
        assert stats["blocked_duplicate"] == 1
        assert stats["blocked_classification"] == 1

    def test_no_fingerprint_skips_dedup_but_keeps_class(self):
        gate = EventGate()
        # Housekeeping blocked regardless of fingerprint.
        allowed, _ = gate.check("METRICS", "XAUUSD", None)
        assert allowed is False
        # Trade trigger with no fingerprint always allowed (no dedup possible).
        allowed, _ = gate.check("BREAKOUT", "XAUUSD", None)
        assert allowed is True
        allowed, _ = gate.check("BREAKOUT", "XAUUSD", None)
        assert allowed is True


# ===========================================================================
# 4. Scheduler-integrated behaviour — event / no-event / duplicate-event
# ===========================================================================
class TestSchedulerEventDriven:
    def test_no_event_supervisor_idle(self):
        """Empty queue → zero cycles run (no fixed timer)."""
        queue = EventQueue()
        pipeline = CountingPipeline()
        scheduler = AutonomousScheduler(queue=queue, pipeline=pipeline, event_gate=EventGate())

        processed = scheduler.process_available()

        assert processed == 0
        assert pipeline.calls == []
        assert scheduler.stats()["events_processed"] == 0

    def test_qualifying_event_wakes_and_runs_committee(self):
        queue = EventQueue()
        pipeline = CountingPipeline()
        scheduler = AutonomousScheduler(queue=queue, pipeline=pipeline, event_gate=EventGate())
        queue.enqueue(_event(EventTypes.BREAKOUT))

        processed = scheduler.process_available()

        assert processed == 1
        assert pipeline.calls == [("XAUUSD", "BREAKOUT")]

    def test_housekeeping_event_does_not_reach_committee(self):
        queue = EventQueue()
        pipeline = CountingPipeline()
        scheduler = AutonomousScheduler(queue=queue, pipeline=pipeline, event_gate=EventGate())
        queue.enqueue(_event(EventTypes.RISK_DRAWDOWN, symbol="XAUUSD"))

        processed = scheduler.process_available()

        assert processed == 0
        assert pipeline.calls == []
        assert scheduler.stats()["events_gated"] == 1

    def test_duplicate_event_does_not_re_run_committee(self):
        queue = EventQueue()
        pipeline = CountingPipeline()
        scheduler = AutonomousScheduler(queue=queue, pipeline=pipeline, event_gate=EventGate())
        # Same symbol + type + bar_time → identical event.
        queue.enqueue(_event(EventTypes.BREAKOUT, timestamp="bar-1"))
        queue.enqueue(_event(EventTypes.BREAKOUT, timestamp="bar-1"))
        queue.enqueue(_event(EventTypes.BREAKOUT, timestamp="bar-1"))

        processed = scheduler.process_available()

        assert processed == 1, "identical events must not create duplicate committee cycles"
        assert len(pipeline.calls) == 1
        assert scheduler.stats()["events_gated"] == 2

    def test_new_bar_event_is_a_fresh_cycle(self):
        queue = EventQueue()
        pipeline = CountingPipeline()
        scheduler = AutonomousScheduler(queue=queue, pipeline=pipeline, event_gate=EventGate())
        queue.enqueue(_event(EventTypes.BREAKOUT, timestamp="bar-1"))
        queue.enqueue(_event(EventTypes.BREAKOUT, timestamp="bar-2"))  # new bar

        processed = scheduler.process_available()

        assert processed == 2
        assert len(pipeline.calls) == 2

    def test_gate_disabled_preserves_legacy_behaviour(self):
        """Without an event_gate the scheduler processes everything (legacy)."""
        queue = EventQueue()
        pipeline = CountingPipeline()
        scheduler = AutonomousScheduler(queue=queue, pipeline=pipeline)  # no gate
        queue.enqueue(_event(EventTypes.DOJI))
        queue.enqueue(_event(EventTypes.RISK_DRAWDOWN))

        processed = scheduler.process_available()

        assert processed == 2


# ===========================================================================
# 5. Event trace — exact wake cause
# ===========================================================================
class TestEventTrace:
    def test_trace_records_wake_cause_for_qualifying_event(self):
        queue = EventQueue()
        pipeline = CountingPipeline()
        scheduler = AutonomousScheduler(queue=queue, pipeline=pipeline, event_gate=EventGate())
        queue.enqueue(_event(EventTypes.BREAKOUT))
        scheduler.process_available()

        traces = scheduler.recent_event_traces(limit=10)
        assert traces, "a processed event must produce a trace"
        entry = traces[0]
        assert entry["event_type"] == "BREAKOUT"
        assert entry["symbol"] == "XAUUSD"
        assert entry["gate_allowed"] is True
        assert entry["wake_cause"].startswith("qualifying:")

    def test_trace_records_gated_housekeeping(self):
        queue = EventQueue()
        pipeline = CountingPipeline()
        scheduler = AutonomousScheduler(queue=queue, pipeline=pipeline, event_gate=EventGate())
        queue.enqueue(_event(EventTypes.RISK_DRAWDOWN))
        scheduler.process_available()

        traces = scheduler.recent_event_traces(limit=10)
        assert traces
        entry = traces[0]
        assert entry["gate_allowed"] is False
        assert entry["wake_cause"] == "gated:HOUSEKEEPING"

    def test_stats_expose_gate_and_trace(self):
        scheduler = AutonomousScheduler(
            queue=EventQueue(), pipeline=CountingPipeline(), event_gate=EventGate()
        )
        stats = scheduler.stats()
        assert stats["event_gate_enabled"] is True
        assert "event_gate" in stats
        assert stats["event_trace_size"] == 0


# ===========================================================================
# 6. Runtime wiring — production scheduler carries the gate
# ===========================================================================
class TestRuntimeWiring:
    def test_orchestration_runtime_scheduler_has_gate(self):
        from orchestration.runtime import OrchestrationRuntime

        runtime = OrchestrationRuntime()
        assert runtime.scheduler.event_gate is not None
        assert isinstance(runtime.scheduler.event_gate, EventGate)

    def test_runtime_housekeeping_does_not_convene_committee(self):
        """A RISK_* event enqueued via the runtime must not run the committee."""
        from orchestration.runtime import OrchestrationRuntime

        runtime = OrchestrationRuntime()
        queue = runtime.queue
        queue.enqueue(
            {
                "event_type": "RISK_DRAWDOWN",
                "symbol": "XAUUSD",
                "drawdown": 0.2,
            }
        )

        processed = runtime.scheduler.process_available()

        assert processed == 0
        assert runtime.scheduler.stats()["events_gated"] == 1
        # No decision recorded because the committee never ran.
        assert runtime.recent_decisions(limit=5) == []

    def test_runtime_event_gate_can_be_injected(self):
        from orchestration.runtime import OrchestrationRuntime

        custom_gate = EventGate(duplicate_ttl_seconds=42.0)
        runtime = OrchestrationRuntime(event_gate=custom_gate)
        assert runtime.scheduler.event_gate is custom_gate
