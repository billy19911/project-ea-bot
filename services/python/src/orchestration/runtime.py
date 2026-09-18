# -*- coding: utf-8 -*-
"""Shared orchestration runtime — pipeline + scheduler singletons.

This module owns the process-wide :class:`TradingPipeline` and
:class:`AutonomousScheduler` instances so the FastAPI endpoints, the lifespan
startup/shutdown hooks, and integration tests all operate on the same objects.

The runtime is lazily constructed and is intentionally decoupled from MT5:
when no live MT5 connector is supplied, the :class:`ExecutionEngine` runs in
its built-in simulated mode (existing behaviour).
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any, Optional

from agents.registry import agent_registry
from agents.supervisor import SupervisorAgent
from execution.engine import ExecutionEngine
from execution.order_builder import OrderBuilder
from execution.reconciliation import ReconciliationReport
from execution.reconciliation_runner import DEFAULT_RECONCILIATION_INTERVAL, ReconciliationRunner
from market.news_feed import get_news_feed_provider
from observability.traces import TraceCollector
from risk.engine import RiskEngine
from risk.gate import RiskGate
from risk.money_management import MoneyManager
from trading.event_engine import EventQueue
from trading.scheduler import AutonomousScheduler

from .pipeline import TradingPipeline

logger = logging.getLogger(__name__)

__all__ = [
    "OrchestrationRuntime",
    "get_runtime",
    "set_runtime",
]

# Bound on the in-process decision history retained for the control plane.
DECISION_HISTORY_LIMIT = 100
# Bound on the in-process trace history retained for the control plane.
TRACE_HISTORY_LIMIT = 200
# Bound on the in-process reconciliation history retained for the control plane.
RECONCILIATION_HISTORY_LIMIT = 50


def _notify_cycle_result(result: Any) -> None:
    """Offer one finished cycle to the Telegram notifier (fail-safe).

    Wired into :class:`TradingPipeline` as its ``result_hook`` so *both* the
    HTTP-triggered cycles and the scheduler-driven cycles report to the user.
    Reports go through the anti-spam digest: a burst of autonomous cycles
    becomes ONE compact message per window instead of one message per cycle
    (urgent trade outcomes are still delivered immediately).
    Any failure here — import, conversion, delivery — is swallowed: reporting
    must never break the autonomous loop.
    """
    try:
        from ..telegram.notifier import queue_pipeline_result

        payload = result.to_dict() if hasattr(result, "to_dict") else result
        queue_pipeline_result(payload)
    except Exception as exc:  # noqa: BLE001 - Telegram must never break autonomy
        logger.warning("Telegram cycle report failed (%s); cycle unaffected", type(exc).__name__)


class _RecordingPipelineProxy:
    """Pipeline proxy that records scheduler-driven cycles in the runtime.

    The scheduler calls ``pipeline.run(event, context)`` directly — not via
    :meth:`OrchestrationRuntime.run_cycle` — so without this proxy a
    scheduler-driven decision (e.g. from the market feed loop, Fase 6) would
    never appear in ``/decisions`` or the trace store. The proxy delegates to
    the real pipeline and records the serialised result (fail-safe: a
    recording failure never affects the cycle).
    """

    def __init__(self, pipeline: TradingPipeline, runtime: "OrchestrationRuntime") -> None:
        self._pipeline = pipeline
        self._runtime = runtime

    def run(self, event: Any, context: Optional[dict[str, Any]] = None) -> Any:
        """Run the wrapped pipeline and record the finished cycle."""
        result = self._pipeline.run(event, context)
        try:
            record = result.to_dict() if hasattr(result, "to_dict") else result
            if isinstance(record, dict):
                self._runtime._record_decision(record)
                self._runtime._record_trace(record)
        except Exception as exc:  # noqa: BLE001 - recording must never break a cycle
            logger.warning("Failed to record scheduler cycle: %s", exc)
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._pipeline, name)


class OrchestrationRuntime:
    """Holds the pipeline, event queue, and scheduler for one process."""

    def __init__(
        self,
        queue: Optional[EventQueue] = None,
        pipeline: Optional[TradingPipeline] = None,
        scheduler: Optional[AutonomousScheduler] = None,
        decision_limit: int = DECISION_HISTORY_LIMIT,
        trace_collector: Optional[TraceCollector] = None,
        reconciliation_interval: int = DEFAULT_RECONCILIATION_INTERVAL,
        reconciliation_providers: Optional[Any] = None,
        reconciliation_history_limit: int = RECONCILIATION_HISTORY_LIMIT,
    ) -> None:
        self.queue = queue if queue is not None else EventQueue()
        self.pipeline = pipeline if pipeline is not None else self._build_pipeline()
        # Periodic reconciliation (PRD_V2 §14). Providers default to safe no-ops
        # so production wiring can inject MT5-backed providers without forcing
        # tests to spin up MT5.
        self.reconciliation = ReconciliationRunner(
            interval=reconciliation_interval,
            providers=reconciliation_providers,
            history_limit=reconciliation_history_limit,
        )
        self.scheduler = (
            scheduler
            if scheduler is not None
            else AutonomousScheduler(
                queue=self.queue,
                # Scheduler-driven cycles are recorded through the proxy so
                # /decisions + traces stay complete for feed-driven events.
                pipeline=_RecordingPipelineProxy(self.pipeline, self),
                reconciliation_runner=self.reconciliation,
                context_provider=lambda evt: get_news_feed_provider().get_news_context(
                    symbol=str(getattr(evt, "symbol", "XAUUSD") or "XAUUSD")
                ),
            )
        )
        # Bounded in-memory history of PipelineResult dicts (oldest first).
        self._decisions: deque[dict[str, Any]] = deque(maxlen=decision_limit)
        # Real trace store for pipeline cycles (PRD §26/§27, bounded).
        self.traces = (
            trace_collector
            if trace_collector is not None
            else TraceCollector(max_traces=TRACE_HISTORY_LIMIT)
        )

    @property
    def _reconciliation_runner(self) -> ReconciliationRunner:
        """Return the active reconciliation runner.

        Prefers the scheduler's runner (kept in sync in production) but falls back
        to the runtime-owned runner when a custom scheduler was injected.
        """
        return getattr(self.scheduler, "reconciliation_runner", None) or self.reconciliation

    @staticmethod
    def _build_pipeline() -> TradingPipeline:
        """Build the production pipeline from the registered agents + risk gate."""
        supervisor = SupervisorAgent()
        # The registry is used by the supervisor for dynamic delegation.
        supervisor._registry_cache = agent_registry
        risk_gate = RiskGate(RiskEngine(), MoneyManager())
        execution_engine = ExecutionEngine(mt5_connector=None)
        order_builder = OrderBuilder()
        # Fase 7: prior lessons are summarised into the analysis context
        # (advisory only). Fail-safe — a missing/broken store simply disables
        # feedback without affecting the pipeline.
        lesson_provider = None
        try:
            from agents.analysts.review_agent import get_lesson_store
            from learning.feedback import LessonFeedbackProvider

            lesson_provider = LessonFeedbackProvider(get_lesson_store())
        except Exception as exc:  # noqa: BLE001 - feedback must never block wiring
            logger.warning("Lesson feedback not wired: %s", exc)
        return TradingPipeline(
            supervisor=supervisor,
            risk_gate=risk_gate,
            execution_engine=execution_engine,
            order_builder=order_builder,
            result_hook=_notify_cycle_result,
            lesson_provider=lesson_provider,
        )

    def run_cycle(
        self,
        event: Any,
        context: Optional[dict[str, Any]] = None,
        trace_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Run one pipeline cycle and return the serialised result.

        Args:
            event: The triggering event.
            context: Optional pipeline context.
            trace_id: Optional externally supplied trace id (e.g. from an
                ``X-Trace-Id`` request header). Echoed as ``trace_id`` in the
                result and used as the recorded trace's id.

        Returns:
            The serialised :class:`PipelineResult` with an added ``trace_id``.
        """
        # Surface the caller's trace id to the pipeline so the cycle result (and
        # therefore the Telegram report) can reference it.
        run_context = dict(context) if isinstance(context, dict) else {}
        if trace_id:
            run_context.setdefault("trace_id", trace_id)
        result = self.pipeline.run(event, run_context)
        record = result.to_dict()
        if trace_id:
            record["trace_id"] = str(trace_id)
        self._record_decision(record)
        self._record_trace(record, trace_id)
        # A manual (HTTP-triggered) cycle is user-initiated: flush the pending
        # Telegram digest now so the user sees the outcome without waiting for
        # the digest window. Fail-safe — reporting never breaks the cycle.
        try:
            from ..telegram.notifier import flush_pipeline_digest

            flush_pipeline_digest()
        except Exception as exc:  # noqa: BLE001 - Telegram must never break autonomy
            logger.warning("Telegram digest flush failed (%s)", type(exc).__name__)
        # Periodic reconciliation (PRD_V2 §14) — fail-safe, never raises.
        self._reconciliation_runner.tick()
        return record

    def _record_trace(self, record: dict[str, Any], trace_id: Optional[str] = None) -> None:
        """Record the cycle into the bounded trace store (fail-safe)."""
        try:
            self.traces.record_pipeline_result(record, trace_id=trace_id)
        except Exception as exc:  # observability must never break a cycle
            logger.warning("Failed to record trace for cycle: %s", exc)

    def recent_traces(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the most recent recorded traces (newest first)."""
        return self.traces.recent(limit)

    def _record_decision(self, record: dict[str, Any]) -> None:
        """Append a decision record (with a server timestamp) to the history."""
        entry = dict(record)
        entry.setdefault("recorded_at", time.time())
        self._decisions.append(entry)

    def recent_decisions(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the most recent decision records (newest first)."""
        if limit <= 0:
            return []
        items = list(self._decisions)[-limit:]
        items.reverse()
        return items

    # ------------------------------------------------------------------
    # Reconciliation (PRD_V2 §14)
    # ------------------------------------------------------------------
    def last_reconciliation(self) -> Optional[ReconciliationReport]:
        """Return the most recent reconciliation report, or ``None``."""
        return self._reconciliation_runner.last_report()

    def reconciliation_history(self) -> list[ReconciliationReport]:
        """Return retained reconciliation reports (oldest first, bounded)."""
        return self._reconciliation_runner.history()

    def reconciliations_run(self) -> int:
        """Return the number of reconciliation runs performed."""
        return self._reconciliation_runner.runs

    def reconciliation_errors(self) -> int:
        """Return the number of failed reconciliation runs (fail-safe)."""
        return self._reconciliation_runner.errors

    def last_reconciliation_ok(self) -> bool:
        """Whether the most recent reconciliation completed without criticals."""
        return self._reconciliation_runner.last_ok


_runtime: Optional[OrchestrationRuntime] = None


def get_runtime() -> OrchestrationRuntime:
    """Return the process-wide runtime, constructing it on first use."""
    global _runtime
    if _runtime is None:
        _runtime = OrchestrationRuntime()
    return _runtime


def set_runtime(runtime: Optional[OrchestrationRuntime]) -> None:
    """Override the process-wide runtime (used by tests)."""
    global _runtime
    _runtime = runtime
