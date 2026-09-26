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
from execution.reconciliation_runner import (
    DEFAULT_RECONCILIATION_INTERVAL,
    ReconciliationGuard,
    ReconciliationRunner,
)
from market.news_feed import get_news_feed_provider
from observability.traces import TraceCollector
from risk.dependency_breakers import ExecutionGuard
from risk.engine import RiskEngine
from risk.gate import RiskGate
from risk.money_management import MoneyManager
from trading.event_engine import EventQueue
from trading.scheduler import AutonomousScheduler

from .account_context import AccountContextProvider
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

# Execution-engine error codes for refusals issued BEFORE any broker dispatch
# (see execution/engine.py): 403 = not armed / missing approval token,
# 400 = validation, 409 = duplicate. These are safety/policy refusals, not
# dependency failures — in the default read-only state (no armed terminal)
# every valid signal produces a 403, so counting them would trip the EXECUTION
# breaker → lock the kill switch after three signals and dead-end the loop.
_PRE_DISPATCH_REFUSAL_CODES = frozenset({400, 403, 409})


def _default_symbol_spec_provider():
    """Return a callable ``(symbol) -> spec dict`` for order normalisation.

    Audit P1-4: uses the existing broker symbol-spec helper. Fail-safe: any
    error returns an empty dict (OrderBuilder then leaves values unchanged).
    """

    def _provider(symbol: str) -> dict:
        for mod_name in ("market.symbol_spec", "src.market.symbol_spec"):
            try:
                import importlib

                spec = importlib.import_module(mod_name).get_symbol_spec(symbol)
                return spec if isinstance(spec, dict) else {}
            except ImportError:
                continue
            except Exception as exc:  # noqa: BLE001 - normalisation is best-effort
                logger.debug("Symbol spec provider failed for %s: %s", symbol, exc)
                return {}
        return {}

    return _provider


def _build_position_monitor(
    event_queue: Optional[EventQueue] = None,
    scheduler: Optional[AutonomousScheduler] = None,
) -> Optional[Any]:
    """Build a read-only position monitor wired to the review/learning loop.

    Audit B-6: the production runtime never closed positions and the paper engine
    is unwired, so the trade-close → review → lesson leg never fired. This builds
    a :class:`PositionMonitor` with a :class:`PositionCloseDetector` whose
    ``on_close`` fires the process-wide :class:`ReviewAutoTrigger` (configured in
    ``main.py`` to persist lessons). It is **observation-only**: it reads the
    broker's open positions each cycle and only detects DISAPPEARED tickets — it
    never places, modifies, or closes anything.

    FIX A (RISK/REVIEW event emission): when a close is detected, ALSO enqueue a
    ``TRADE_CLOSE`` event to ``event_queue`` (when supplied) and wake the
    scheduler so the supervisor routes it to ReviewLead. Follows the same
    pattern as :class:`MarketFeedLoop` ``on_emit``.

    Fail-safe: any import/wiring error returns ``None`` (the loop is unaffected).
    """
    try:
        from monitoring.position_monitor import PositionMonitor
        from review.auto_trigger import on_position_closed
        from review.close_detector import PositionCloseDetector

        def _on_close_emit_trade_event(trade_result: Any) -> None:
            """Wrap on_position_closed and also enqueue TRADE_CLOSE event.

            Fail-safe: enqueue errors are swallowed (review still runs first).
            """
            # Original review/lesson path runs first (fail-safe).
            try:
                on_position_closed(trade_result)
            except Exception as exc:  # noqa: BLE001 - review must not block emit
                logger.warning("Review on_position_closed failed: %s", exc)
            # FIX A: also emit TRADE_CLOSE event so supervisor routes to
            # ReviewLead. Follows MarketFeedLoop on_emit pattern.
            if event_queue is None:
                return
            try:
                payload = (
                    dict(trade_result)
                    if isinstance(trade_result, dict)
                    else getattr(trade_result, "model_dump", lambda: {})()
                )
                event_queue.enqueue(
                    {
                        "event_type": "TRADE_CLOSE",
                        "trade_result": payload,
                    }
                )
                if scheduler is not None:
                    scheduler.wake()
            except Exception as exc:  # noqa: BLE001 - never break close path
                logger.warning("TRADE_CLOSE event emit failed: %s", exc)

        detector = PositionCloseDetector(on_close=_on_close_emit_trade_event)

        # Wire durable position reconciliation store (B-5, fail-safe).
        reconciliation_store = None
        try:
            from persistence import PositionReconciliationStore

            reconciliation_store = PositionReconciliationStore()
        except Exception:  # noqa: BLE001 - store is optional
            pass

        # LEDGER-SLTP T1: wire the order-state ledger so a verified position
        # disappearance appends a `closed` record (prevents phantom open
        # positions blocking reconciliation). The store is attached globally by
        # main.py via execution.state_machine.set_store(); read it back here so
        # we do not instantiate a second, competing ledger. Fail-safe.
        order_state_store = None
        try:
            for mod_name in ("execution.state_machine", "src.execution.state_machine"):
                try:
                    import importlib

                    order_state_store = importlib.import_module(mod_name).get_store()
                    if order_state_store is not None:
                        break
                except (ImportError, AttributeError):
                    continue
        except Exception:  # noqa: BLE001 - optional
            order_state_store = None

        return PositionMonitor(
            close_detector=detector,
            reconciliation_store=reconciliation_store,
            order_state_store=order_state_store,
        )
    except Exception as exc:  # noqa: BLE001 - monitoring must never block wiring
        logger.warning("Position monitor not wired: %s", exc)
        return None


def _notify_cycle_result(result: Any) -> None:
    """Offer one finished cycle to the Telegram notifier (fail-safe).

    Wired into :class:`TradingPipeline` as its ``result_hook`` so *both* the
    HTTP-triggered cycles and the scheduler-driven cycles report to the user.

    Signal lifecycle first: a finished BUY/SELL cycle becomes ONE edit-in-place
    signal message (rejected signals are consumed silently). Non-actionable
    cycles fall back to the anti-spam digest (one compact message per window).

    Any failure here — import, conversion, delivery — is swallowed: reporting
    must never break the autonomous loop.
    """
    try:
        try:
            from telegram.signal_lifecycle import get_signal_lifecycle
        except ImportError:
            from ..telegram.signal_lifecycle import get_signal_lifecycle  # type: ignore

        payload = result.to_dict() if hasattr(result, "to_dict") else result
        try:
            if get_signal_lifecycle().observe_cycle_result(payload):
                return
        except Exception as exc:  # noqa: BLE001 - fall back to the digest
            logger.warning(
                "Signal lifecycle failed (%s); using digest", type(exc).__name__
            )

        try:
            from telegram.notifier import queue_pipeline_result
        except ImportError:
            from ..telegram.notifier import queue_pipeline_result  # type: ignore

        queue_pipeline_result(payload)
    except Exception as exc:  # noqa: BLE001 - Telegram must never break autonomy
        logger.warning(
            "Telegram cycle report failed (%s); cycle unaffected", type(exc).__name__
        )


class _RecordingPipelineProxy:
    """Pipeline proxy that records scheduler-driven cycles in the runtime.

    The scheduler calls ``pipeline.run(event, context)`` directly — not via
    :meth:`OrchestrationRuntime.run_cycle` — so without this proxy a
    scheduler-driven decision (e.g. from the market feed loop, Fase 6) would
    never appear in ``/decisions`` or the trace store. The proxy delegates to
    the real pipeline and records the serialised result (fail-safe: a
    recording failure never affects the cycle).
    """

    def __init__(
        self, pipeline: TradingPipeline, runtime: "OrchestrationRuntime"
    ) -> None:
        self._pipeline = pipeline
        self._runtime = runtime

    def run(self, event: Any, context: Optional[dict[str, Any]] = None) -> Any:
        """Run the wrapped pipeline and record the finished cycle."""
        result = self._pipeline.run(event, context)
        try:
            record = result.to_dict() if hasattr(result, "to_dict") else result
            if isinstance(record, dict):
                self._runtime._record_execution_outcome(record)
                self._runtime._record_decision(record)
                self._runtime._record_trace(record)
                # Audit B-6: scheduler-driven cycles also observe positions so the
                # close → review → lesson loop runs without manual API calls.
                self._runtime._monitor_positions()
        except Exception as exc:  # noqa: BLE001 - recording must never break a cycle
            logger.warning("Failed to record scheduler cycle: %s", exc)
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._pipeline, name)


def _is_pre_dispatch_refusal(record: dict[str, Any]) -> bool:
    """True when an ERROR outcome was refused before any broker dispatch.

    The execution engine uses dedicated error codes for refusals that never
    reached the broker (``_PRE_DISPATCH_REFUSAL_CODES``). Those must not count
    toward the EXECUTION breaker — the dependency was never exercised.
    """
    outcome = record.get("execution_result")
    if not isinstance(outcome, dict):
        return False
    try:
        return int(outcome.get("error_code")) in _PRE_DISPATCH_REFUSAL_CODES
    except (TypeError, ValueError):
        return False


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
        reconciliation_runner: Optional[ReconciliationRunner] = None,
        execution_guard: Optional[ExecutionGuard] = None,
    ) -> None:
        self.queue = queue if queue is not None else EventQueue()
        # Periodic reconciliation (PRD_V2 §14). Providers default to the
        # MT5-backed providers (audit P0-3 follow-up) so the reconciliation gate
        # sees real internal↔broker state. In non-live (paper/dev) mode the
        # connector's positions are simulation placeholders that the engine
        # never created, so reconciling them against an empty internal ledger
        # would be a permanent false positive; we therefore keep no-op providers
        # unless MT5 live data is active. Tests can still inject providers.
        if reconciliation_providers is None:
            reconciliation_providers = self._default_reconciliation_providers()
        self.reconciliation = (
            reconciliation_runner
            if reconciliation_runner is not None
            else ReconciliationRunner(
                interval=reconciliation_interval,
                providers=reconciliation_providers,
                history_limit=reconciliation_history_limit,
            )
        )
        # Audit P0-3: a critical reconciliation mismatch BLOCKS new orders. The
        # guard wraps the runner and is injected into the pipeline below.
        self._reconciliation_guard = ReconciliationGuard(self.reconciliation)
        # Audit P1-2: per-dependency circuit breakers (§24) + kill switch, wired
        # into the pipeline as the execution-critical dependency guard. An open
        # EXECUTION breaker or an engaged kill switch blocks new orders.
        self.execution_guard = (
            execution_guard if execution_guard is not None else ExecutionGuard()
        )
        self.pipeline = (
            pipeline
            if pipeline is not None
            else self._build_pipeline(
                reconciliation_guard=self._reconciliation_guard,
                execution_guard=self.execution_guard,
            )
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
                # Audit P1-3: supply REAL account/positions/market inputs so the
                # deterministic Risk Gate is account-aware, merged with news.
                context_provider=AccountContextProvider(
                    news_provider=lambda sym: get_news_feed_provider().get_news_context(
                        symbol=sym or "XAUUSD"
                    ),
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
        # Audit P2-8: a real decision-graph store populated per cycle so the
        # /v2/decision/{id}/replay endpoint returns live data (bounded).
        from review.decision_graph import DecisionGraphStore, GraphStage

        self.decision_graphs = DecisionGraphStore(max_graphs=DECISION_HISTORY_LIMIT)
        self._graph_stage = GraphStage
        # Audit B-6: read-only position monitoring that feeds the review/learning
        # loop when a ticket disappears (observation only; never orders).
        # FIX A: pass queue + scheduler so TRADE_CLOSE events get enqueued and
        # routed to ReviewLead, mirroring MarketFeedLoop's on_emit pattern.
        self.position_monitor = _build_position_monitor(
            event_queue=self.queue,
            scheduler=self.scheduler,
        )

    @property
    def _reconciliation_runner(self) -> ReconciliationRunner:
        """Return the active reconciliation runner.

        Prefers the scheduler's runner (kept in sync in production) but falls back
        to the runtime-owned runner when a custom scheduler was injected.
        """
        return (
            getattr(self.scheduler, "reconciliation_runner", None)
            or self.reconciliation
        )

    @staticmethod
    def _default_reconciliation_providers() -> Any:
        """Pick reconciliation providers based on MT5 mode (audit P0-3).

        Live mode → real MT5-backed providers (internal ledger vs broker state).
        Non-live (paper/dev) → no-op providers, because the connector's
        simulated positions are placeholders the engine never created and would
        otherwise be a permanent false-positive mismatch.
        """
        try:
            from execution.reconciliation_providers import MT5ReconciliationProviders

            live = False
            for mod_name in ("mt5.connector", "src.mt5.connector"):
                try:
                    import importlib

                    live = bool(importlib.import_module(mod_name).is_live_mode())
                    break
                except ImportError:
                    continue
            if live:
                return MT5ReconciliationProviders()
        except Exception as exc:  # noqa: BLE001 - fall back to no-op providers
            logger.warning("MT5 reconciliation providers unavailable: %s", exc)
        from execution.reconciliation_runner import ReconciliationProviders

        return ReconciliationProviders()

    @staticmethod
    def _build_pipeline(
        reconciliation_guard: Optional[Any] = None,
        execution_guard: Optional[Any] = None,
    ) -> TradingPipeline:
        """Build the production pipeline from the registered agents + risk gate."""
        # Audit P2-3: the production supervisor runs the configurable routing
        # policy (default ``all_match``) so all matching department leads
        # genuinely collaborate instead of collapsing to one agent per cycle.
        policy = "all_match"
        try:
            import os

            policy = os.getenv("SUPERVISOR_ROUTING_POLICY", "all_match") or "all_match"
        except Exception:  # noqa: BLE001 - env read is best-effort
            policy = "all_match"
        supervisor = SupervisorAgent(routing_policy=policy)
        # The registry is used by the supervisor for dynamic delegation.
        supervisor._registry_cache = agent_registry
        # Operator-tunable concurrent-position cap. A demo account shared with
        # another EA (which holds its own positions) needs headroom, otherwise
        # the gate counts foreign positions and our bot can never get a slot.
        # Fail-safe: missing/invalid env keeps the production default of 5.
        max_positions = 5
        try:
            import os

            max_positions = int(os.getenv("RISK_MAX_POSITIONS", "") or 5)
            if max_positions < 1:
                max_positions = 5
        except (TypeError, ValueError):
            max_positions = 5
        risk_gate = RiskGate(RiskEngine(max_positions=max_positions), MoneyManager())
        # No MT5 connector is wired in the default runtime, so the engine keeps
        # its existing paper behaviour — but ONLY via an explicit, clearly
        # labelled simulation (audit P0-2). Without this flag a missing broker
        # path would now return an honest failure instead of a fabricated fill.
        # Audit B-3: require a gate-issued approval_token so the deterministic
        # Risk Gate is enforced by the executor itself (fail-closed for any
        # direct/ungated caller), not merely by the pipeline's calling discipline.
        execution_engine = ExecutionEngine(
            mt5_connector=None,
            simulation_mode=True,
            require_approval=True,
        )
        # Audit P1-4: normalise volume to the broker's lot step and round prices
        # to the symbol digits when a spec is available. Fail-safe: a spec lookup
        # failure leaves the order unchanged.
        order_builder = OrderBuilder(
            symbol_spec_provider=_default_symbol_spec_provider()
        )
        # One-entry policy (default ON): while one of OUR positions (matched by
        # entry magic) is open, new entries are blocked. The magic id labels our
        # orders so we never count a foreign EA's positions.
        one_entry_policy = True
        entry_magic = 70000
        try:
            import os

            raw_policy = (os.getenv("ONE_ENTRY_POLICY") or "true").strip().lower()
            one_entry_policy = raw_policy not in {"0", "false", "no", "off"}
            entry_magic = int(os.getenv("ENTRY_MAGIC", "") or 70000)
        except (TypeError, ValueError):
            one_entry_policy = True
            entry_magic = 70000
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
            reconciliation_guard=reconciliation_guard,
            dependency_guard=execution_guard,
            single_entry_policy=one_entry_policy,
            entry_magic=entry_magic,
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
        self._record_execution_outcome(record)
        self._record_decision(record)
        self._record_trace(record, trace_id)
        # A manual (HTTP-triggered) cycle is user-initiated: flush the pending
        # Telegram digest now so the user sees the outcome without waiting for
        # the digest window. Fail-safe — reporting never breaks the cycle.
        try:
            try:
                from telegram.notifier import flush_pipeline_digest
            except ImportError:
                from ..telegram.notifier import flush_pipeline_digest  # type: ignore

            flush_pipeline_digest()
        except Exception as exc:  # noqa: BLE001 - Telegram must never break autonomy
            logger.warning("Telegram digest flush failed (%s)", type(exc).__name__)
        # Periodic reconciliation (PRD_V2 §14) — fail-safe, never raises.
        self._reconciliation_runner.tick()
        # Audit B-6: observe positions to drive close → review → lesson.
        self._monitor_positions()
        return record

    def _record_execution_outcome(self, record: dict[str, Any]) -> None:
        """Feed a finished cycle's execution outcome into the execution guard.

        Audit P1-2: a completed execution (``status == EXECUTED``) resets the
        EXECUTION breaker; an execution that was attempted but errored counts as
        a failure so repeated failures trip the breaker → kill switch → block.
        A pre-dispatch safety/policy refusal (e.g. no armed terminal in the
        default read-only state) is NOT an execution failure — the broker was
        never contacted — and must not count toward the breaker.
        Cycles that never attempted execution (WAIT/BLOCKED/NO_TRADE) do not
        affect the breaker. Fail-safe: bookkeeping must never break a cycle.
        """
        try:
            status = str(record.get("status", "")).upper()
            if status == "EXECUTED":
                self.execution_guard.record_execution_result(True)
            elif status == "ERROR" and record.get("execution_id"):
                if _is_pre_dispatch_refusal(record):
                    # Refused by the safety layer before any dispatch (e.g.
                    # "EXECUTION NOT ARMED") — expected while unarmed; counting
                    # it would self-lock the loop after three valid signals.
                    logger.info(
                        "Execution refused before dispatch — breaker unaffected."
                    )
                    return
                # An order build/execution error — count toward the breaker.
                detail = str(record.get("error") or "execution error")
                self.execution_guard.record_execution_result(False, detail=detail)
        except Exception as exc:  # noqa: BLE001 - guard bookkeeping is best-effort
            logger.warning("Could not record execution outcome: %s", exc)

    def _monitor_positions(self) -> None:
        """Observe open positions once per cycle to drive the review loop.

        Audit B-6: feeds the read-only monitor so a closed (disappeared) ticket
        fires the review auto-trigger → lesson store. Also feeds the signal
        lifecycle's price observation (TP/SL markers edit the signal message in
        place). Fail-safe: monitoring must never break a cycle.
        """
        if self.position_monitor is not None:
            try:
                self.position_monitor.monitor_all_positions()
            except Exception as exc:  # noqa: BLE001 - observation is best-effort
                logger.warning("Position monitoring failed: %s", exc)
        # Exactly one price observation per _monitor_positions call — run_cycle
        # and the scheduler proxy both funnel through here (no double reads).
        self._observe_signal_prices()

    def _observe_signal_prices(self) -> None:
        """Push the latest cached market price into the signal lifecycle.

        For every symbol with an active signal message, read the latest market
        snapshot's ``volatility.price`` (when > 0) so TP1/TP2/TPmax/SL hits are
        marked via ``editMessageText`` — never as a new message. Fail-safe.
        """
        try:
            try:
                from telegram.signal_lifecycle import get_signal_lifecycle
            except ImportError:
                from ..telegram.signal_lifecycle import get_signal_lifecycle  # type: ignore

            from trading.market_snapshot import get_latest_snapshot

            tracker = get_signal_lifecycle()
            symbols = tracker.active_symbols()
            if not symbols:
                return
            for symbol in symbols:
                try:
                    snapshot = get_latest_snapshot(symbol)
                    if not isinstance(snapshot, dict):
                        continue
                    volatility = snapshot.get("volatility")
                    if not isinstance(volatility, dict):
                        continue
                    price = float(volatility.get("price") or 0.0)
                except Exception:  # noqa: BLE001 - per-symbol read is best-effort
                    continue
                if price > 0:
                    tracker.observe_price(symbol, price)
        except Exception as exc:  # noqa: BLE001 - never break the loop
            logger.warning("Signal price observation failed (%s)", type(exc).__name__)

    def _record_trace(
        self, record: dict[str, Any], trace_id: Optional[str] = None
    ) -> None:
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
        self._record_decision_graph(entry)

    def _record_decision_graph(self, record: dict[str, Any]) -> None:
        """Populate a decision graph from a finished cycle (audit P2-8, fail-safe)."""
        try:
            decision_id = str(record.get("decision_id") or record.get("event_id") or "")
            if not decision_id:
                return
            stage = self._graph_stage
            graph = self.decision_graphs.start(
                decision_id,
                event_id=str(record.get("event_id") or ""),
                strategy_version=str(record.get("strategy_version") or ""),
            )
            graph.add_node(stage.EVENT, {"event_type": record.get("event_type", "")})
            graph.add_node(
                stage.SUPERVISOR_SUMMARY,
                {
                    "summary": record.get("summary", ""),
                    "confidence": record.get("confidence"),
                },
            )
            graph.add_node(
                stage.TRADE_PROPOSAL,
                {
                    "decision": record.get("decision", ""),
                    "proposal_id": record.get("proposal_id", ""),
                },
            )
            graph.add_node(
                stage.RISK_CHECKS,
                {
                    "risk_approved": record.get("risk_approved"),
                    "reason": record.get("risk_reason", ""),
                },
            )
            graph.add_node(
                stage.EXECUTION,
                {
                    "executed": record.get("executed"),
                    "client_order_id": record.get("client_order_id", ""),
                },
            )
            graph.add_node(stage.RESULT, {"status": record.get("status", "")})
        except (
            Exception
        ) as exc:  # noqa: BLE001 - observability must never break a cycle
            logger.warning("Failed to record decision graph: %s", exc)

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
