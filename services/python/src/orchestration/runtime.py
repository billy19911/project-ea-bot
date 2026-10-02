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
from typing import Any, Callable, Optional

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
from execution.restart_recovery import ReconciliationReadinessGate
from market.news_feed import get_news_feed_provider
from observability.traces import TraceCollector
from risk.dependency_breakers import ExecutionGuard
from risk.engine import RiskEngine
from risk.gate import RiskGate
from risk.money_management import MoneyManager
from trading.event_classes import EventGate
from trading.event_engine import EventQueue
from trading.scheduler import AutonomousScheduler

from .account_context import AccountContextProvider
from .pipeline import TradingPipeline
from .runtime_identity import RuntimeIdentity
from .signal_registry import get_signal_registry

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


def _fanout_enabled() -> bool:
    """Return whether multi-terminal fan-out is enabled (default OFF).

    Read from ``FANOUT_ENABLED`` (true/1/yes/on). Default OFF so the historic
    single-terminal behaviour is preserved unless the operator opts in.
    """
    import os as _os

    raw = (_os.getenv("FANOUT_ENABLED") or "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _canonical_fanout_enabled() -> bool:
    """Return whether canonical-signal fan-out is enabled (default OFF).

    Read from ``CANONICAL_FANOUT_ENABLED`` (true/1/yes/on). Default OFF so the
    historic single-terminal behaviour is preserved unless the operator opts in.
    """
    import os as _os

    raw = (_os.getenv("CANONICAL_FANOUT_ENABLED") or "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _build_fanout_coordinator(risk_gate: Any, order_builder: Any) -> Optional[Any]:
    """Build the canonical-signal fan-out coordinator (TASK 06) — fail-safe None.

    Wired with the real terminal targets (``mt5.terminals.get_fanout_targets``)
    and a per-account Risk Gate that reuses the SAME deterministic
    :class:`~risk.gate.RiskGate` the single-terminal path uses, but applied to
    each account's own state. Returns None when the execution layer is not
    importable so the pipeline falls back to the single-terminal path.
    """
    try:
        from execution.fanout import CanonicalFanout, get_fanout_ledger
    except Exception as exc:  # noqa: BLE001 - never block startup
        logger.warning("Canonical fan-out coordinator not wired: %s", exc)
        return None

    def _targets() -> list[dict[str, Any]]:
        for mod_name in ("mt5.terminals", "src.mt5.terminals"):
            try:
                import importlib

                terms = importlib.import_module(mod_name)
                return list(terms.get_fanout_targets())
            except ImportError:
                continue
            except Exception as exc:  # noqa: BLE001 - any doubt → no targets
                logger.warning("Canonical fan-out target lookup failed: %s", exc)
                return []
        return []

    def _symbol_resolver(symbol: str, target: dict[str, Any]) -> str:
        try:
            from mt5.symbol_resolver import resolve_symbol

            return resolve_symbol(symbol) or symbol
        except Exception:  # noqa: BLE001 - fall back to the base symbol
            return symbol

    return CanonicalFanout(
        # The coordinator places each account's order via the shared execution
        # engine, so account orders go through the exact same armed-terminal
        # gate (real dispatch requires an armed + eligible terminal).
        execution_engine=_default_single_terminal_sender(),
        risk_gate=risk_gate,
        targets_provider=_targets,
        order_builder=order_builder,
        symbol_resolver=_symbol_resolver,
        ledger=get_fanout_ledger(),
    )


def _default_single_terminal_sender() -> Optional[Any]:
    """Return an object exposing ``execute_order`` for one account dispatch.

    Reuses the process-wide :class:`ExecutionEngine` in simulation when MT5 is
    absent; real dispatch still requires an armed+eligible terminal (enforced by
    the engine and ``mt5.terminals``).
    """
    try:
        return ExecutionEngine()
    except Exception:  # noqa: BLE001
        return None


def _zone_entry_enabled() -> bool:
    """Return whether the OB/FVG watch-and-fire entry gate is enabled (F2).

    Read from ``ZONE_ENTRY_ENABLED`` (true/1/yes/on). Default OFF.
    """
    import os as _os

    raw = (_os.getenv("ZONE_ENTRY_ENABLED") or "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _toggle_provider(key: str, env_fallback: "Callable[[], bool]") -> "Callable[[], bool]":
    """Return a live provider for a boolean settings knob.

    Reads the runtime settings store each call (so a dashboard toggle applies
    immediately); when the store is unavailable the env-based fallback is used.
    Fail-safe: any error yields the env fallback's value.
    """

    def _read() -> bool:
        try:
            from system.settings_store import get_settings_store

            values = get_settings_store().snapshot().values
            if key in values:
                return bool(values.get(key))
        except Exception:  # noqa: BLE001 - store optional, fall through to env
            pass
        # Store had no value for this key → fall back to the env flag.
        try:
            return bool(env_fallback())
        except Exception:  # noqa: BLE001
            return False

    return _read


def _build_zone_entry_gate() -> Optional[Any]:
    """Build the process-wide OB/FVG entry gate (F2) — fail-safe None."""
    try:
        from trading.entry_zone import ZoneEntryGate

        return ZoneEntryGate()
    except Exception as exc:  # noqa: BLE001 - never block startup
        logger.warning("Zone entry gate not wired: %s", exc)
        return None


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
            # FOKUS #2: a closed position clears the symbol's active signal so a
            # fresh committee may convene for the next opportunity. Fail-safe.
            try:
                from .signal_registry import get_signal_registry

                symbol = ""
                if isinstance(trade_result, dict):
                    symbol = str(trade_result.get("symbol") or "")
                else:
                    symbol = str(getattr(trade_result, "symbol", "") or "")
                if symbol:
                    get_signal_registry().mark_closed(symbol, "posisi ditutup")
            except Exception as exc:  # noqa: BLE001 - must not block close path
                logger.warning("Signal registry close mark failed: %s", exc)
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


def _build_trade_manager() -> Optional[Any]:
    """Build the dynamic SL/TP trade manager (fail-safe).

    The manager is always constructed so the operator can toggle dynamic SL
    management from the dashboard (Settings → ``sltp_*`` knobs) without a
    restart. The master switch (``sltp_management_enabled``) is read LIVE on
    every cycle; when OFF, :meth:`TradeManager.manage` is a no-op and nothing is
    sent to the broker. The ``SLTP_*`` environment values seed the store
    defaults at startup (see ``main`` lifespan) and remain the fallback when the
    store is unavailable.

    Returns ``None`` only when wiring itself fails (e.g. imports unavailable).
    """
    try:
        from config import settings
        from execution.sltp_manager import SLTPConfig
        from monitoring.trade_manager import TradeManager

        def _env_config() -> SLTPConfig:
            return SLTPConfig(
                enabled=bool(getattr(settings, "sltp_management_enabled", False)),
                breakeven_enabled=bool(getattr(settings, "sltp_breakeven_enabled", True)),
                bep_buffer_r=float(getattr(settings, "sltp_bep_buffer_r", 0.1)),
                tp1_lock_enabled=bool(getattr(settings, "sltp_tp1_lock_enabled", True)),
                tp1_trigger_r=1.0,
                tp1_lock_r=1.0,
                trailing_enabled=bool(getattr(settings, "sltp_trailing_enabled", True)),
                tp2_trigger_r=2.0,
                trail_atr_factor=float(getattr(settings, "sltp_trail_atr_factor", 1.5)),
                min_move_r=float(getattr(settings, "sltp_min_move_r", 0.05)),
            )

        # Static config from env is the fallback (store unavailable / tests).
        base = _env_config()

        def _atr_reader(symbol: str) -> float:
            """Return the feed-loop ATR for the symbol (0.0 when unavailable)."""
            try:
                from trading.market_snapshot import get_latest_snapshot

                snap = get_latest_snapshot(symbol)
                if not isinstance(snap, dict):
                    return 0.0
                vol = snap.get("volatility") or {}
                atr_val = vol.get("atr") or snap.get("atr")
                return float(atr_val or 0.0)
            except Exception:  # noqa: BLE001 - trailing only; never block
                return 0.0

        def _apply(ticket: int, symbol: str, sl: float, tp: Any) -> dict:
            from execution.engine import ExecutionEngine

            return ExecutionEngine().modify_position_sltp(ticket, symbol, sl, tp)

        def _store_values() -> Optional[dict[str, float]]:
            """Read the runtime settings store (None when unavailable)."""
            try:
                from system.settings_store import get_settings_store

                return get_settings_store().snapshot().values
            except Exception as exc:  # noqa: BLE001 - live knob is best-effort
                logger.warning("SLTP settings store unavailable: %s", exc)
                return None

        def _enabled_reader() -> bool:
            values = _store_values()
            if values is None:
                return bool(base.enabled)
            return bool(values.get("sltp_management_enabled", 1.0 if base.enabled else 0.0))

        def _config_reader() -> Optional[SLTPConfig]:
            values = _store_values()
            if values is None:
                return base
            return SLTPConfig(
                enabled=True,
                breakeven_enabled=bool(
                    values.get("sltp_breakeven_enabled", 1.0 if base.breakeven_enabled else 0.0)
                ),
                bep_buffer_r=base.bep_buffer_r,
                tp1_lock_enabled=bool(
                    values.get("sltp_progressive_enabled", 1.0 if base.tp1_lock_enabled else 0.0)
                ),
                tp1_trigger_r=base.tp1_trigger_r,
                tp1_lock_r=base.tp1_lock_r,
                trailing_enabled=bool(
                    values.get("sltp_trailing_enabled", 1.0 if base.trailing_enabled else 0.0)
                ),
                tp2_trigger_r=base.tp2_trigger_r,
                trail_atr_factor=base.trail_atr_factor,
                min_move_r=base.min_move_r,
            )

        return TradeManager(
            config=base,
            atr_reader=_atr_reader,
            apply_sltp=_apply,
            enabled_reader=_enabled_reader,
            config_reader=_config_reader,
        )
    except Exception as exc:  # noqa: BLE001 - management must never block wiring
        logger.warning("Trade manager not wired: %s", exc)
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
            logger.warning("Signal lifecycle failed (%s); using digest", type(exc).__name__)

        try:
            from telegram.notifier import queue_pipeline_result
        except ImportError:
            from ..telegram.notifier import queue_pipeline_result  # type: ignore

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
        event_gate: Optional[EventGate] = None,
        recovery_coordinator: Optional[Any] = None,
    ) -> None:
        # TASK 05: runtime identity — process id + a unique instance id for this
        # runtime and every component it owns, so every analysis log can prove
        # there is exactly ONE scheduler/queue/supervisor/pipeline/feed. Purely
        # diagnostic; never read by the decision path.
        self.identity = RuntimeIdentity("runtime")
        self.identity.register_queue()
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
        # TASK 08: restart-recovery readiness. When a coordinator is supplied the
        # pipeline refuses new orders until recovery has reconciled broker ↔
        # internal state. Default None keeps the pre-restart behaviour so tests
        # and single-process runs are unaffected; the FastAPI lifespan wires a
        # real coordinator (see main.py).
        self.recovery_coordinator = recovery_coordinator
        self._readiness_gate = (
            ReconciliationReadinessGate(recovery_coordinator)
            if recovery_coordinator is not None
            else None
        )
        # Audit P1-2: per-dependency circuit breakers (§24) + kill switch, wired
        # into the pipeline as the execution-critical dependency guard. An open
        # EXECUTION breaker or an engaged kill switch blocks new orders.
        self.execution_guard = execution_guard if execution_guard is not None else ExecutionGuard()
        self.pipeline = (
            pipeline
            if pipeline is not None
            else self._build_pipeline(
                reconciliation_guard=self._reconciliation_guard,
                execution_guard=self.execution_guard,
                readiness_guard=self._readiness_gate,
            )
        )
        # TASK 05: register the singleton component identities (first writer
        # wins; idempotent so a re-constructed runtime never double-registers).
        self.identity.register_reconciliation()
        self.identity.register_pipeline()
        self.identity.register_supervisor()
        self.scheduler = (
            scheduler
            if scheduler is not None
            else AutonomousScheduler(
                queue=self.queue,
                # Scheduler-driven cycles are recorded through the proxy so
                # /decisions + traces stay complete for feed-driven events.
                pipeline=_RecordingPipelineProxy(self.pipeline, self),
                reconciliation_runner=self.reconciliation,
                # TASK 02: qualifying-event gate — only TRADE_TRIGGER events may
                # convene the committee and identical events are suppressed, so
                # the supervisor stays idle when nothing qualifying changed.
                event_gate=event_gate if event_gate is not None else EventGate(),
                # Audit P1-3: supply REAL account/positions/market inputs so the
                # deterministic Risk Gate is account-aware, merged with news.
                context_provider=AccountContextProvider(
                    news_provider=lambda sym: get_news_feed_provider().get_news_context(
                        symbol=sym or "XAUUSD"
                    ),
                ),
                # TASK 05: thread the runtime identity into the scheduler so
                # every analysis log carries process/runtime/scheduler/feed ids.
                identity=self.identity,
            )
        )
        # TASK 05: the scheduler is the single owner of the analysis loop.
        self.identity.register_scheduler()
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
        self.identity.register_position_monitor()
        # Dynamic stop-loss management (BEP / progressive / trailing) applied to
        # open positions once per cycle. Always wired; the master switch is read
        # LIVE from the runtime settings store each cycle (Settings →
        # sltp_management_enabled), so the operator can toggle it from the
        # dashboard without a restart. When OFF it is a no-op. The manager is
        # arm-gated/fail-closed inside the execution engine, so an unarmed
        # terminal never reaches the broker.
        self.trade_manager = _build_trade_manager()

    @property
    def _reconciliation_runner(self) -> ReconciliationRunner:
        """Return the active reconciliation runner.

        Prefers the scheduler's runner (kept in sync in production) but falls back
        to the runtime-owned runner when a custom scheduler was injected.
        """
        return getattr(self.scheduler, "reconciliation_runner", None) or self.reconciliation

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
        readiness_guard: Optional[Any] = None,
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
        # Operator-tunable max spread (in "pips", i.e. price delta / pip_size).
        # Phase 1 Item #4: symbol-aware spread limits. The global gate limit
        # stays wide enough for BTC (~4000 pips normal) and is tightened via the
        # env var. Default 50000 remains for backwards compatibility; the
        # symbol-specific thresholds below are exposed for future per-symbol
        # gating (Phase 2) and documented for operators.
        max_spread_pips = 50000.0
        try:
            import os

            max_spread_pips = float(os.getenv("MAX_SPREAD_PIPS", "") or 50000.0)
            if max_spread_pips <= 0:
                max_spread_pips = 50000.0
        except (TypeError, ValueError):
            max_spread_pips = 50000.0

        # Phase 1 Item #4: symbol-aware spread LIMITS (documented + used by
        # future symbol-aware gate). Values are conservative per class.
        _symbol_spread_limits = {
            "BTC": 8000.0,
            "XAU": 200.0,
            "FX": 5.0,
        }
        for _key, _env in (
            ("BTC", "MAX_SPREAD_BTC"),
            ("XAU", "MAX_SPREAD_XAU"),
            ("FX", "MAX_SPREAD_FX"),
        ):
            try:
                _v = float(os.getenv(_env, "") or _symbol_spread_limits[_key])
                if _v > 0:
                    _symbol_spread_limits[_key] = _v
            except (TypeError, ValueError):
                pass
        # TASK 07: monetary stop-loss risk budget (fraction of equity). When set,
        # the gate enforces abs(entry − initial_SL) × contract_size × volume
        # against this budget using the ACTUAL broker symbol specification, and
        # fails CLOSED when the broker spec is unavailable (no invented contract
        # size). Safety logic (like the other RiskGate limits) is configured via
        # env, never a UI-editable knob; a non-positive/absent value leaves the
        # check informational only.
        max_risk_pct: Optional[float] = None
        try:
            _raw_risk = os.getenv("MAX_RISK_PCT")
            if _raw_risk:
                _candidate = float(_raw_risk)
                if _candidate > 0:
                    max_risk_pct = _candidate
        except (TypeError, ValueError):
            max_risk_pct = None
        risk_gate = RiskGate(
            RiskEngine(max_positions=max_positions),
            MoneyManager(),
            max_spread_pips=max_spread_pips,
            symbol_spread_limits=_symbol_spread_limits,
            max_risk_pct=max_risk_pct,
        )

        # No MT5 connector is wired in the default runtime, so the engine keeps
        # its existing paper behaviour — but ONLY via an explicit, clearly
        # labelled simulation (audit P0-2). Without this flag a missing broker
        # path would now return an honest failure instead of a fabricated fill.
        # Audit B-3: require a gate-issued approval_token so the deterministic
        # Risk Gate is enforced by the executor itself (fail-closed for any
        # direct/ungated caller), not merely by the pipeline's calling discipline.
        # Phase 1 Item #5: inject an order_locator so a lost broker response is
        # adopted when a matching position can be confirmed. If lookup is
        # inconclusive, ExecutionEngine preserves UNKNOWN and does not resend.
        def _order_locator_for_request(request: Any) -> Optional[dict]:
            from mt5 import connector

            want_vol = float(getattr(request, "volume", 0.0) or 0.0)
            if want_vol <= 0:
                return None
            for pos in connector.positions() or []:
                p_d = dict(pos) if not isinstance(pos, dict) else pos
                sym_match = str(p_d.get("symbol") or "").upper() == str(request.symbol).upper()
                vol_match = abs(float(p_d.get("volume") or 0.0) - want_vol) < 1e-6
                magic_match = int(p_d.get("magic") or 0) == int(getattr(request, "magic", 0) or 0)
                if sym_match and vol_match and magic_match:
                    return {"ticket": int(p_d.get("ticket"))}
            return None

        execution_engine = ExecutionEngine(
            mt5_connector=None,
            simulation_mode=True,
            require_approval=True,
            require_durable_state=True,
            order_locator=_order_locator_for_request,
        )
        # Audit P1-4: normalise volume to the broker's lot step and round prices
        # to the symbol digits when a spec is available. Fail-safe: a spec lookup
        # failure leaves the order unchanged.
        order_builder = OrderBuilder(symbol_spec_provider=_default_symbol_spec_provider())
        # One-entry policy (default ON): while one of OUR positions (matched by
        # entry magic) is open, new entries are blocked. The magic id labels our
        # orders so we never count a foreign EA's positions.
        one_entry_policy = True
        entry_magic = 70000
        entry_cooldown_s = 900.0
        entry_min_distance_atr = 1.0
        try:
            import os

            raw_policy = (os.getenv("ONE_ENTRY_POLICY") or "true").strip().lower()
            one_entry_policy = raw_policy not in {"0", "false", "no", "off"}
            entry_magic = int(os.getenv("ENTRY_MAGIC", "") or 70000)
            entry_cooldown_s = float(os.getenv("ENTRY_COOLDOWN_S", "") or 900.0)
            entry_min_distance_atr = float(os.getenv("ENTRY_MIN_DISTANCE_ATR", "") or 1.0)
        except (TypeError, ValueError):
            one_entry_policy = True
            entry_magic = 70000
            entry_cooldown_s = 900.0
            entry_min_distance_atr = 1.0
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

        # FOKUS #4: wire the ACTIVE strategy config into the pipeline so
        # activating a strategy really affects the decision (min_confidence,
        # risk/confidence knobs) instead of being display-only. Fail-safe.
        def _strategy_config_provider() -> Optional[dict[str, Any]]:
            try:
                from strategy.endpoints import get_active_strategy_config

                return get_active_strategy_config()
            except Exception as exc:  # noqa: BLE001 - strategy is optional
                logger.debug("Active strategy config unavailable: %s", exc)
                return None

        # Multi-timeframe entry filter (opt-in). When enabled, an LTF entry
        # fighting a strong HTF bias is vetoed. Default OFF.
        htf_filter_enabled = False
        htf_min_strength = 0.0
        try:
            from config import settings as _settings

            htf_filter_enabled = bool(
                getattr(_settings, "multi_timeframe_enabled", False)
                and getattr(_settings, "multi_timeframe_filter_enabled", True)
            )
            htf_min_strength = float(getattr(_settings, "multi_timeframe_min_strength", 0.0) or 0.0)
        except Exception:  # noqa: BLE001 - filter stays off on any error
            htf_filter_enabled = False

        # Risk/size knobs — read from the runtime settings store at CONSTRUCT
        # time so the pipeline is correct even if the later `_apply_to_runtime`
        # push is skipped (that path is best-effort and can bail early). The
        # store is the operator's source of truth; env/defaults are the fallback.
        # Getting this wrong is how a 1.0-lot order slipped past a 0.05 cap.
        default_risk_pct = 1.0
        max_lot_per_trade = 0.05
        try:
            from system.settings_store import get_settings_store

            values = get_settings_store().snapshot().values
            default_risk_pct = float(
                values.get("risk_per_trade_pct", default_risk_pct) or default_risk_pct
            )
            max_lot_per_trade = float(
                values.get("max_lot_per_trade", max_lot_per_trade) or max_lot_per_trade
            )
        except Exception as exc:  # noqa: BLE001 - fall back to safe defaults
            logger.warning("Pipeline size knobs not read from store: %s", exc)
        # Absolute safety floor: a non-positive/absurd cap must never disable the
        # cap. Clamp to (0, 100].
        if not (0 < max_lot_per_trade <= 100):
            logger.warning(
                "Invalid max_lot_per_trade=%s from store — using safe default 0.05",
                max_lot_per_trade,
            )
            max_lot_per_trade = 0.05

        return TradingPipeline(
            supervisor=supervisor,
            risk_gate=risk_gate,
            execution_engine=execution_engine,
            order_builder=order_builder,
            result_hook=_notify_cycle_result,
            lesson_provider=lesson_provider,
            reconciliation_guard=reconciliation_guard,
            dependency_guard=execution_guard,
            readiness_guard=readiness_guard,
            single_entry_policy=one_entry_policy,
            entry_magic=entry_magic,
            entry_cooldown_s=entry_cooldown_s,
            entry_min_distance_atr=entry_min_distance_atr,
            htf_filter_enabled=htf_filter_enabled,
            htf_min_strength=htf_min_strength,
            signal_registry=get_signal_registry(),
            strategy_config_provider=_strategy_config_provider,
            default_risk_pct=default_risk_pct,
            max_lot_per_trade=max_lot_per_trade,
            # Always recompute the lot from the operator's risk knob (the lot is
            # then capped) so a stale/foreign proposal size can never win.
            force_risk_sizing=True,
            # F1: fan-out ONE decision to every armed terminal. Read LIVE from
            # the settings store (dashboard toggle, no restart); env is the
            # fallback default. Default OFF (safe).
            fanout_enabled=_toggle_provider("fanout_enabled", _fanout_enabled),
            # F2: OB/FVG watch-and-fire entry gate. Read LIVE from the settings
            # store; env is the fallback. Gate is always built so it can be
            # switched on from the dashboard without a restart.
            zone_entry_enabled=_toggle_provider("zone_entry_enabled", _zone_entry_enabled),
            zone_entry_gate=_build_zone_entry_gate(),
            # TASK 06: canonical-signal fan-out. When the toggle is ON, ONE
            # immutable signal is fanned out to N accounts (each broker-
            # normalized + risk-gated per account). Off → single-terminal path.
            fanout_coordinator=(
                _build_fanout_coordinator(risk_gate, order_builder)
                if _toggle_provider("canonical_fanout_enabled", _canonical_fanout_enabled)()
                else None
            ),
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
                    logger.info("Execution refused before dispatch — breaker unaffected.")
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
        # Dynamic stop management (BEP / progressive / trailing) on open
        # positions. No-op unless SLTP_MANAGEMENT_ENABLED. Arm-gated/fail-closed
        # inside the engine, so an unarmed terminal never reaches the broker.
        if self.trade_manager is not None:
            try:
                self.trade_manager.manage()
            except Exception as exc:  # noqa: BLE001 - management is best-effort
                logger.warning("Trade manager failed: %s", exc)
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
        """Append a decision record (with a server timestamp) to the history.

        FOKUS #2: a ``SIGNAL_PENDING`` cycle is a *gate* outcome — the committee
        was intentionally NOT re-run because a signal is already live. Recording
        it as a new "siklus" would recreate exactly the "many signals" clutter
        the user complained about, so gated cycles are not appended to the
        decision history (they remain visible in the trace store for audit).
        """
        if str(record.get("status") or "").upper() == "SIGNAL_PENDING":
            return
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
        except Exception as exc:  # noqa: BLE001 - observability must never break a cycle
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

    # ------------------------------------------------------------------
    # Restart recovery (TASK 08)
    # ------------------------------------------------------------------
    def run_recovery(self) -> Optional[dict[str, Any]]:
        """Run the wired restart-recovery sequence and return its report.

        Returns ``None`` when no recovery coordinator is wired (nothing to do).
        The coordinator is fail-closed: it never raises, and until it reports
        RECONCILED the readiness gate keeps blocking new orders.
        """
        if self.recovery_coordinator is None:
            return None
        report = self.recovery_coordinator.run()
        return report.to_dict() if hasattr(report, "to_dict") else dict(report)

    def recovery_state(self) -> Optional[dict[str, Any]]:
        """Return the current restart-recovery report as a dict (or ``None``)."""
        if self.recovery_coordinator is None:
            return None
        report = getattr(self.recovery_coordinator, "report", None)
        if report is None:
            return None
        return report.to_dict() if hasattr(report, "to_dict") else dict(report)


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
