# -*- coding: utf-8 -*-
"""AutonomousScheduler — event-driven autonomous operation loop.

Consumes ``DetectedEvent``s from the existing :class:`~trading.event_engine.EventQueue`
in priority order and runs one :class:`~orchestration.pipeline.TradingPipeline`
cycle per event. Designed for fully unattended operation (PRD_V2 §10.3,
§32.17): there is no dependency on Telegram or any other user interaction.

The scheduler is deterministic-safe: a failure in the pipeline is logged and
counted, but never kills the loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from execution.reconciliation_runner import ReconciliationRunner
from trading.event_engine import EventPriority, EventQueue, get_priority

logger = logging.getLogger(__name__)

__all__ = ["AutonomousScheduler"]

# Pipeline statuses counted as a "blocked" trade.
_BLOCKED_STATUS = "BLOCKED"
# Pipeline statuses counted as an "executed" trade.
_EXECUTED_STATUS = "EXECUTED"
# Decisions that represent a proposed (actionable) trade.
_PROPOSED_DECISIONS = {"BUY", "SELL"}


class AutonomousScheduler:
    """Event-driven scheduler that runs the pipeline for queued events.

    Args:
        queue: The :class:`EventQueue` to consume events from.
        pipeline: A :class:`TradingPipeline` (or compatible object exposing
            ``run(event, context)``).
        context_provider: Optional callable returning the context dict passed
            to the pipeline for each event. Defaults to an empty dict.
        poll_interval: Seconds to sleep between polls when the queue is empty.
        max_events_per_cycle: Maximum events processed in one drain pass
            (backpressure guard). ``0`` means drain until empty.
        backpressure: When True, BACKGROUND-priority events (analytics/
            housekeeping; PRD_V2 §15) are skipped so that latency-sensitive
            work is prioritised. Defaults to False.
        reconciliation_runner: Optional :class:`ReconciliationRunner` (PRD_V2
            §14). When supplied, its ``tick()`` is invoked once per drain pass so
            reconciliation runs every N cycles. Fail-safe: a reconciliation error
            is recorded, never raised.
    """

    def __init__(
        self,
        queue: EventQueue,
        pipeline: Any,
        context_provider: Optional[Any] = None,
        poll_interval: float = 1.0,
        max_events_per_cycle: int = 0,
        backpressure: bool = False,
        reconciliation_runner: Optional[ReconciliationRunner] = None,
    ) -> None:
        self.queue = queue
        self.pipeline = pipeline
        self.context_provider = context_provider
        self.poll_interval = max(0.001, float(poll_interval))
        self.max_events_per_cycle = max(0, int(max_events_per_cycle))
        self.backpressure = bool(backpressure)
        self.reconciliation_runner = reconciliation_runner

        self._task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._running = False

        self._stats: dict[str, int] = {
            "events_processed": 0,
            "events_skipped": 0,
            "trades_proposed": 0,
            "trades_blocked": 0,
            "trades_executed": 0,
            "errors": 0,
        }

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def running(self) -> bool:
        """Return True while the async loop is active."""
        return self._running

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------
    def process_available(self) -> int:
        """Drain the queue, running the pipeline per event in priority order.

        The underlying :class:`EventQueue` already dequeues highest-priority
        events first (FIFO within the same priority), so simply looping over
        ``dequeue`` preserves priority ordering.

        When ``backpressure`` is enabled, BACKGROUND-priority events are
        skipped (dropped) so latency-sensitive work is not starved.

        Returns:
            The number of events processed in this pass.
        """
        processed = 0
        limit = self.max_events_per_cycle
        while True:
            if limit and processed >= limit:
                break
            event = self.queue.dequeue()
            if event is None:
                break
            if self.backpressure and self._is_background(event):
                self._stats["events_skipped"] += 1
                continue
            self._process_event(event)
            processed += 1
        self._maybe_reconcile()
        return processed

    def _maybe_reconcile(self) -> None:
        """Tick the periodic reconciler once per drain pass (PRD_V2 §14).

        Fail-safe: :meth:`ReconciliationRunner.tick` never raises, so a broker
        outage can never crash the scheduler loop.
        """
        runner = self.reconciliation_runner
        if runner is None:
            return
        runner.tick()

    @staticmethod
    def _is_background(event: Any) -> bool:
        """Return True if ``event`` is BACKGROUND priority."""
        event_type = getattr(event, "event_type", None)
        if event_type is None:
            return False
        try:
            return get_priority(event_type) is EventPriority.BACKGROUND
        except Exception:  # pragma: no cover - defensive
            return False

    def _process_event(self, event: Any) -> None:
        """Run the pipeline for one event, recording stats and errors."""
        self._stats["events_processed"] += 1
        context = self._build_context(event)
        try:
            result = self.pipeline.run(event, context)
        except Exception as exc:  # deterministic-safe: never kill the loop
            self._stats["errors"] += 1
            logger.exception("Pipeline failed for event %s: %s", _event_label(event), exc)
            return

        status = str(getattr(result, "status", "")).upper()
        decision = str(getattr(result, "decision", "")).upper()

        if decision in _PROPOSED_DECISIONS:
            self._stats["trades_proposed"] += 1
        if status == _BLOCKED_STATUS:
            self._stats["trades_blocked"] += 1
        if status == _EXECUTED_STATUS:
            self._stats["trades_executed"] += 1
        if getattr(result, "error", None):
            self._stats["errors"] += 1

    def _build_context(self, event: Any) -> dict[str, Any]:
        """Build the per-event pipeline context via the provider (if any)."""
        if self.context_provider is None:
            return {}
        try:
            context = self.context_provider(event)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("context_provider failed for %s: %s", _event_label(event), exc)
            return {}
        return context if isinstance(context, dict) else {}

    # ------------------------------------------------------------------
    # Async lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        """Start the async loop (idempotent).

        The loop drains available events, then sleeps for ``poll_interval``
        when the queue is empty. It is created via ``asyncio.create_task`` so
        callers (e.g. the FastAPI lifespan) are never blocked.
        """
        if self._running:
            return
        self._stop_event = asyncio.Event()
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop the async loop and await its completion (safe if not started)."""
        if not self._running and self._task is None:
            return
        self._running = False
        if self._stop_event is not None:
            self._stop_event.set()
        task = self._task
        self._task = None
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:  # pragma: no cover - defensive
                pass

    async def _run_loop(self) -> None:
        """The background loop body."""
        try:
            while self._running:
                processed = self.process_available()
                if processed == 0:
                    await self._idle_sleep()
        except asyncio.CancelledError:  # pragma: no cover - defensive
            raise

    async def _idle_sleep(self) -> None:
        """Sleep for ``poll_interval`` or until stop is requested."""
        stop_event = self._stop_event
        if stop_event is None:  # pragma: no cover - defensive
            await asyncio.sleep(self.poll_interval)
            return
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=self.poll_interval)
        except asyncio.TimeoutError:
            pass

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        """Return a snapshot of scheduler statistics."""
        stats: dict[str, Any] = {
            "events_processed": self._stats["events_processed"],
            "events_skipped": self._stats["events_skipped"],
            "trades_proposed": self._stats["trades_proposed"],
            "trades_blocked": self._stats["trades_blocked"],
            "trades_executed": self._stats["trades_executed"],
            "errors": self._stats["errors"],
            "running": self._running,
            "backpressure": self.backpressure,
            "queue_size": len(self.queue),
        }
        runner = self.reconciliation_runner
        if runner is not None:
            stats.update(runner.summary())
        return stats


def _event_label(event: Any) -> str:
    """Return a human-readable label for an event (for logging)."""
    if isinstance(event, dict):
        return str(event.get("event_id") or event.get("event_type") or event)
    return str(getattr(event, "event_id", None) or getattr(event, "event_type", event))
