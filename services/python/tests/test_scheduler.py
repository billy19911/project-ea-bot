# -*- coding: utf-8 -*-
"""Tests for the AutonomousScheduler.

The scheduler consumes events from an EventQueue, runs the TradingPipeline
for each event, and tracks aggregate statistics. There is no dependency on
Telegram or any user interaction.

pytest-asyncio is not installed, so lifecycle tests are driven with
``asyncio.run(...)``.
"""

from __future__ import annotations

import asyncio

from orchestration.pipeline import PipelineResult
from trading.event_engine import EventQueue
from trading.events import DetectedEvent, EventTypes
from trading.scheduler import AutonomousScheduler


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------
class RecordingPipeline:
    """Pipeline stub that records calls and returns a canned result.

    ``outcomes`` maps an event_type value to a PipelineResult; the special
    ``"__raise__"`` key triggers an exception for resilience tests.
    """

    def __init__(self, default_status="EXECUTED") -> None:
        self.calls: list[str] = []
        self._status = default_status
        self._status_by_symbol: dict[str, str] = {}
        self.raise_for: set[str] = set()

    def set_status(self, symbol: str, status: str) -> None:
        self._status_by_symbol[symbol] = status

    def run(self, event, context=None) -> PipelineResult:
        symbol = event.symbol if hasattr(event, "symbol") else event.get("symbol", "")
        self.calls.append(symbol)
        if symbol in self.raise_for:
            raise RuntimeError(f"pipeline boom for {symbol}")
        status = self._status_by_symbol.get(symbol, self._status)
        approved = status in ("EXECUTED", "BLOCKED")
        return PipelineResult(
            event_id=symbol,
            decision="BUY" if approved else "WAIT",
            status=status,
            risk_approved=status == "EXECUTED",
            executed=status == "EXECUTED",
        )


class PriorityPipeline:
    """Pipeline stub recording the priority order it processes events in."""

    def __init__(self, stats: dict) -> None:
        self.order: list[str] = []
        self._stats = stats

    def run(self, event, context=None) -> PipelineResult:
        self.order.append(event.event_type.value)
        return PipelineResult(event_id=event.event_type.value, decision="WAIT", status="NO_TRADE")


def _event(event_type, symbol="EURUSD"):
    return DetectedEvent(
        event_type=event_type,
        severity=0.5,
        description=f"{event_type.value}",
        timestamp="2024-01-01T00:00:00+00:00",
        symbol=symbol,
    )


# ---------------------------------------------------------------------------
# Priority ordering
# ---------------------------------------------------------------------------
class TestPriorityOrdering:
    def test_processes_in_priority_order(self):
        queue = EventQueue(max_size=100)
        queue.enqueue(_event(EventTypes.DOJI))  # LOW
        queue.enqueue(_event(EventTypes.DRAWDOWN_WARNING))  # CRITICAL
        queue.enqueue(_event(EventTypes.BREAKOUT))  # HIGH

        pipeline = PriorityPipeline({})
        scheduler = AutonomousScheduler(queue=queue, pipeline=pipeline)
        processed = scheduler.process_available()

        assert processed == 3
        assert pipeline.order == [
            EventTypes.DRAWDOWN_WARNING.value,
            EventTypes.BREAKOUT.value,
            EventTypes.DOJI.value,
        ]
        assert len(queue) == 0

    def test_empty_queue_processes_nothing(self):
        queue = EventQueue(max_size=10)
        scheduler = AutonomousScheduler(queue=queue, pipeline=RecordingPipeline())
        assert scheduler.process_available() == 0


# ---------------------------------------------------------------------------
# Loop resilience
# ---------------------------------------------------------------------------
class TestLoopResilience:
    def test_continues_after_pipeline_error(self):
        queue = EventQueue(max_size=100)
        queue.enqueue(_event(EventTypes.BREAKOUT, symbol="EURUSD"))
        queue.enqueue(_event(EventTypes.BREAKDOWN, symbol="GBPUSD"))

        pipeline = RecordingPipeline()
        pipeline.raise_for.add("EURUSD")
        scheduler = AutonomousScheduler(queue=queue, pipeline=pipeline)

        processed = scheduler.process_available()

        # Both events were attempted despite the first raising.
        assert processed == 2
        assert pipeline.calls == ["EURUSD", "GBPUSD"]
        assert scheduler.stats()["errors"] == 1

    def test_asyncio_loop_survives_error(self):
        queue = EventQueue(max_size=100)
        queue.enqueue(_event(EventTypes.BREAKOUT, symbol="EURUSD"))

        pipeline = RecordingPipeline()
        pipeline.raise_for.add("EURUSD")
        scheduler = AutonomousScheduler(queue=queue, pipeline=pipeline, poll_interval=0.01)

        async def scenario():
            await scheduler.start()
            await asyncio.sleep(0.08)
            await scheduler.stop()

        asyncio.run(scenario())
        assert scheduler.stats()["errors"] >= 1
        assert scheduler.running is False


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
class TestStats:
    def test_counts_processed_proposed_blocked_executed_errors(self):
        queue = EventQueue(max_size=100)
        queue.enqueue(_event(EventTypes.BREAKOUT, symbol="EURUSD"))  # EXECUTED
        queue.enqueue(_event(EventTypes.BREAKDOWN, symbol="GBPUSD"))  # BLOCKED
        queue.enqueue(_event(EventTypes.DOJI, symbol="USDJPY"))  # NO_TRADE
        queue.enqueue(_event(EventTypes.REVERSAL, symbol="AUDUSD"))  # raises

        pipeline = RecordingPipeline()
        pipeline.set_status("EURUSD", "EXECUTED")
        pipeline.set_status("GBPUSD", "BLOCKED")
        pipeline.set_status("USDJPY", "NO_TRADE")
        pipeline.raise_for.add("AUDUSD")

        scheduler = AutonomousScheduler(queue=queue, pipeline=pipeline)
        scheduler.process_available()

        stats = scheduler.stats()
        assert stats["events_processed"] == 4
        assert stats["trades_executed"] == 1
        assert stats["trades_blocked"] == 1
        assert stats["errors"] == 1
        # Proposed counts events that produced a trade decision (BUY/SELL).
        assert stats["trades_proposed"] == 2

    def test_stats_start_at_zero(self):
        scheduler = AutonomousScheduler(queue=EventQueue(), pipeline=RecordingPipeline())
        stats = scheduler.stats()
        assert stats == {
            "events_processed": 0,
            "events_skipped": 0,
            "trades_proposed": 0,
            "trades_blocked": 0,
            "trades_executed": 0,
            "errors": 0,
            "running": False,
            "backpressure": False,
            "queue_size": 0,
        }


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
class TestLifecycle:
    def test_start_stop_asyncio(self):
        queue = EventQueue(max_size=100)
        pipeline = RecordingPipeline()

        scheduler = AutonomousScheduler(queue=queue, pipeline=pipeline, poll_interval=0.01)

        async def scenario():
            await scheduler.start()
            assert scheduler.running is True
            queue.enqueue(_event(EventTypes.BREAKOUT, symbol="EURUSD"))
            await asyncio.sleep(0.08)
            await scheduler.stop()
            assert scheduler.running is False

        asyncio.run(scenario())
        assert pipeline.calls == ["EURUSD"]

    def test_start_is_idempotent(self):
        scheduler = AutonomousScheduler(
            queue=EventQueue(), pipeline=RecordingPipeline(), poll_interval=0.01
        )

        async def scenario():
            await scheduler.start()
            task_one = scheduler._task
            await scheduler.start()  # second call must not spawn a new task
            assert scheduler._task is task_one
            await scheduler.stop()

        asyncio.run(scenario())

    def test_stop_without_start_is_safe(self):
        scheduler = AutonomousScheduler(queue=EventQueue(), pipeline=RecordingPipeline())

        asyncio.run(scheduler.stop())
        assert scheduler.running is False
