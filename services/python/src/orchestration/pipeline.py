# -*- coding: utf-8 -*-
"""TradingPipeline — a single end-to-end autonomous decision cycle.

The pipeline is the orchestration seam required by PRD_V2 §10.3, §32.1–.7 and
§32.17: the Supervisor analyses an event and produces a synthesis/proposal,
the deterministic Risk Gate validates the proposal (non-bypassable), and only
an explicitly approved proposal reaches the Execution Engine.

Design guarantees:

* The Supervisor never touches MT5 / the Execution Engine directly — only this
  pipeline connects the decision layer to the safety and execution layers.
* Fail-closed: any Supervisor error yields a WAIT/NO_TRADE result; any Risk
  Gate error yields a BLOCKED result; an Execution error is recorded as a
  failed execution. Execution is *never* attempted unless the Risk Gate
  explicitly approved the proposal.
* Every stage is recorded in a per-stage ``trace`` along with the identifiers
  required for full trade traceability.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol, runtime_checkable

from config import settings
from execution.engine import OrderRequest
from execution.order_builder import OrderBuilder
from risk.gate import GateDecision
from risk.money_management import MoneyManager
from trading.level_plan import (
    build_level_plan,
    direction_from_text,
    extract_price_atr,
    indicative_levels,
)
from trading.market_snapshot import get_latest_snapshot

from .signal_registry import get_signal_registry, is_pending_guard_enabled

logger = logging.getLogger(__name__)

# Defaults used when COMPLETING a proposal whose synthesis left sizing/SL-TP
# empty (audit follow-up). Conservative; never override caller-provided values.
DEFAULT_RISK_PCT = 0.01  # risk 1% of equity per trade
DEFAULT_POINT_VALUE = 0.0001  # 1 pip value for standard FX pairs
DEFAULT_CONTRACT_SIZE = 100000.0

__all__ = [
    "TradingPipeline",
    "PipelineResult",
    "PipelineStage",
]

# Status values for the overall pipeline outcome.
STATUS_EXECUTED = "EXECUTED"
STATUS_BLOCKED = "BLOCKED"
STATUS_NO_TRADE = "NO_TRADE"
STATUS_WAIT = "WAIT"
STATUS_ERROR = "ERROR"
# A signal for this symbol is already live (PENDING/EXECUTING/OPEN) or in a
# post-failure cooldown → the committee was intentionally NOT re-convened.
STATUS_SIGNAL_PENDING = "SIGNAL_PENDING"

# Status values for an individual pipeline stage trace entry.
STAGE_OK = "OK"
STAGE_SKIPPED = "SKIPPED"
STAGE_BLOCKED = "BLOCKED"
STAGE_ERROR = "ERROR"

# Directions that represent an actionable trade.
_ACTIONABLE = {"BUY", "SELL"}


@runtime_checkable
class _Supervisor(Protocol):  # pragma: no cover - structural typing only
    """Minimal structural interface the pipeline needs from a supervisor."""

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]: ...


@dataclass
class PipelineStage:
    """A single recorded stage of the pipeline trace.

    ``PipelineResult.trace`` stores these as plain dicts (via
    :meth:`to_dict`) so results are directly JSON-serialisable.
    """

    stage: str
    status: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialise the stage to a plain dict."""
        return {"stage": self.stage, "status": self.status, "detail": self.detail}


@dataclass
class PipelineResult:
    """Structured result of one :meth:`TradingPipeline.run` cycle.

    Attributes:
        event_id: Identifier of the triggering event (generated if missing).
        task_id: Identifier of the supervisor task for this cycle.
        decision_id: Identifier of the resulting decision state.
        proposal_id: Identifier of the trade proposal (empty for no-trade).
        execution_id: Identifier of the execution attempt (empty if not run).
        client_order_id: Idempotency key of the submitted order (if any).
        strategy_version: Strategy version tag used for the cycle.
        decision: Final decision — BUY / SELL / WAIT / NO_TRADE.
        status: Overall pipeline status (EXECUTED/BLOCKED/NO_TRADE/WAIT/ERROR).
        risk_approved: True only when the Risk Gate explicitly approved.
        risk_reason: Human-readable reason from the Risk Gate.
        executed: True only when execution was attempted and succeeded.
        execution_result: Serialised execution result, or None.
        trace: Ordered per-stage trace entries.
        error: Recorded error message when a fail-closed path was taken.
    """

    event_id: str
    decision: str
    status: str
    task_id: str = ""
    decision_id: str = ""
    proposal_id: str = ""
    execution_id: str = ""
    client_order_id: str = ""
    strategy_version: str = ""
    risk_approved: bool = False
    risk_reason: str = ""
    executed: bool = False
    execution_result: Optional[dict[str, Any]] = None
    trace: list[dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    # Synthesis fields surfaced for reports/notifications (Phase 5).
    event_type: str = ""
    confidence: float = 0.0
    summary: str = ""
    # Correlation fields surfaced for reports/notifications (Phase 5):
    # ``trace_id`` is echoed from the caller context, ``symbol`` from the event.
    trace_id: str = ""
    symbol: str = ""
    # Entry/SL/TP1/TP2/TPmax ladder for signal reports. From the real
    # proposal/order when one exists (source "order"), else indicative
    # from the ATR model (source "analysis"); None when not derivable.
    levels: Optional[dict[str, Any]] = None
    # Per-agent analysis results + the supervisor summary, surfaced so the
    # signal report / control plane can show committee evidence (Phase 5).
    agent_results: dict[str, Any] = field(default_factory=dict)
    supervisor_summary: str = ""
    # FOKUS #5: the market-data source behind this cycle — "LIVE" or
    # "SIMULATED". Analysts on synthetic data must never masquerade as real
    # intelligence; the dashboard/reports show this flag.
    data_source: str = "UNKNOWN"

    def add_stage(self, stage: str, status: str, detail: str = "") -> None:
        """Append a stage entry (as a plain dict) to the trace."""
        self.trace.append(PipelineStage(stage=stage, status=status, detail=detail).to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Serialise the whole result to a JSON-friendly dict."""
        return {
            "event_id": self.event_id,
            "task_id": self.task_id,
            "decision_id": self.decision_id,
            "proposal_id": self.proposal_id,
            "execution_id": self.execution_id,
            "client_order_id": self.client_order_id,
            "strategy_version": self.strategy_version,
            "decision": self.decision,
            "status": self.status,
            "risk_approved": self.risk_approved,
            "risk_reason": self.risk_reason,
            "executed": self.executed,
            "execution_result": self.execution_result,
            "trace": list(self.trace),
            "error": self.error,
            "event_type": self.event_type,
            "confidence": self.confidence,
            "summary": self.summary,
            "trace_id": self.trace_id,
            "symbol": self.symbol,
            "levels": self.levels,
            "agent_results": self.agent_results,
            "supervisor_summary": self.supervisor_summary,
            "data_source": self.data_source,
        }


def _new_id(prefix: str) -> str:
    """Generate a short unique identifier with a readable prefix."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _coerce_confidence(value: Any) -> float:
    """Best-effort float conversion for a synthesis confidence (fail-safe 0.0)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _as_toggle(value: Any, default: bool = False) -> Callable[[], bool]:
    """Normalise a bool-or-callable toggle into a zero-arg callable.

    Accepts:
    * a bool → returns a callable yielding it,
    * a callable → returned as-is (evaluated LIVE, so a dashboard toggle
      applies without restarting the process).

    Fail-safe: a callable that raises yields ``default``.
    """
    if callable(value):

        def _call() -> bool:
            try:
                return bool(value())
            except Exception:  # noqa: BLE001 - a broken provider must not break a cycle
                return default

        return _call

    fixed = bool(value)
    return lambda: fixed


class _FanoutExecutionAdapter:
    """Present a fan-out result with the single-order ExecutionResult shape.

    The pipeline's success/failure handling reads ``success`` /
    ``error_message`` / ``ticket``. A fan-out has many outcomes, so this adapter
    reports overall success when at least one terminal executed, carries the
    per-terminal list, and summarises failures in ``error_message``.
    """

    def __init__(self, fanout: Any) -> None:
        self._fanout = fanout
        self.success = bool(getattr(fanout, "any_success", False))
        self.ticket = None
        # First successful ticket (convenience for callers expecting one).
        for row in getattr(fanout, "results", []) or []:
            if row.get("success") and row.get("ticket") is not None:
                self.ticket = row.get("ticket")
                break
        self.error_code = 0 if self.success else 1
        self.retries = 0
        self.position_opened = None
        succeeded = int(getattr(fanout, "succeeded", 0) or 0)
        failed = int(getattr(fanout, "failed", 0) or 0)
        total = int(getattr(fanout, "target_count", 0) or 0)
        if self.success:
            self.error_message = f"Fan-out: {succeeded}/{total} terminal berhasil."
        else:
            fails = [
                f"{r.get('terminal_id')}: {r.get('error_message', '')}"
                for r in (getattr(fanout, "results", []) or [])
                if not r.get("success")
            ]
            self.error_message = (
                f"Fan-out gagal di semua terminal ({failed}). " + "; ".join(fails[:3])
            ).strip()

    def to_dict(self) -> dict[str, Any]:
        base = {
            "success": self.success,
            "ticket": self.ticket,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "retries": self.retries,
            "position_opened": self.position_opened,
        }
        if hasattr(self._fanout, "to_dict"):
            base["fanout"] = self._fanout.to_dict()
        return base


class TradingPipeline:
    """Runs one autonomous decision cycle end-to-end.

    Args:
        supervisor: A ``SupervisorAgent`` (or compatible) exposing
            ``analyze(context) -> dict``. Injected so the pipeline can be
            unit-tested with fakes and so no MT5 access leaks into the brain.
        risk_gate: A :class:`~risk.gate.RiskGate` (or compatible) exposing
            ``validate_proposal(...) -> GateDecision``.
        execution_engine: An :class:`~execution.engine.ExecutionEngine`
            (or compatible) exposing ``execute_order(request)``.
        order_builder: Optional :class:`~execution.order_builder.OrderBuilder`;
            a default instance is created when omitted.
        strategy_version: Strategy version tag recorded for each cycle.
        dependency_guard: Optional execution-critical guard (§24).
        result_hook: Optional callable invoked exactly once per cycle with the
            finished :class:`PipelineResult` (reporting/notification seam).
        lesson_provider: Optional learning-feedback provider (Phase 7) exposing
            ``summarize_for_symbol(symbol)``; when present, prior lessons are
            attached to the analysis context (advisory only).
        reconciliation_guard: Optional execution-critical guard (audit P0-3)
            exposing ``check_can_execute() -> (bool, reason)``. When supplied and
            it reports a critical internal↔MT5 mismatch, new orders are BLOCKED
            (fail-closed). Optional so existing callers are unaffected.
    """

    def __init__(
        self,
        supervisor: Any,
        risk_gate: Any,
        execution_engine: Optional[Any] = None,
        order_builder: Optional[OrderBuilder] = None,
        strategy_version: str = "v1.0.0",
        dependency_guard: Optional[Any] = None,
        result_hook: Optional[Callable[[PipelineResult], None]] = None,
        lesson_provider: Optional[Any] = None,
        reconciliation_guard: Optional[Any] = None,
        money_manager: Optional[Any] = None,
        default_risk_pct: float = DEFAULT_RISK_PCT,
        # Safe default cap: a misconfigured/omitted value must NOT allow 1.0-lot
        # orders. The runtime wires the operator's real cap from the store; this
        # default is the fail-safe floor.
        max_lot_per_trade: float = 0.05,
        force_risk_sizing: bool = False,
        single_entry_policy: bool = False,
        entry_magic: int = 70000,
        entry_cooldown_s: float = 0.0,
        entry_min_distance_atr: float = 0.0,
        htf_filter_enabled: bool = False,
        htf_min_strength: float = 0.0,
        signal_registry: Optional[Any] = None,
        pending_signal_guard: bool = True,
        strategy_config_provider: Optional[Callable[[], Optional[dict[str, Any]]]] = None,
        fanout_enabled: Any = False,
        zone_entry_enabled: Any = False,
        zone_entry_gate: Optional[Any] = None,
    ) -> None:
        self.supervisor = supervisor
        self.risk_gate = risk_gate
        self.execution_engine = execution_engine
        # Fan-out (F1): when enabled and the engine supports it, ONE decision is
        # dispatched to every armed fan-out terminal (each sized from its own
        # account). Default False preserves the historic single-terminal path
        # (tests, paper, sim). May be a bool OR a zero-arg callable (so a
        # dashboard toggle applies LIVE without a restart).
        self._fanout_enabled_provider = _as_toggle(fanout_enabled, default=False)
        # Zone entry (F2): when enabled and a gate is supplied, an approved entry
        # waits until price reaches the OB/FVG zone (watch-and-fire). Bool OR
        # zero-arg callable (live dashboard toggle).
        self._zone_entry_enabled_provider = _as_toggle(zone_entry_enabled, default=False)
        self.zone_entry_gate = zone_entry_gate
        self.order_builder = order_builder if order_builder is not None else OrderBuilder()
        self.strategy_version = strategy_version
        # Risk-% sizing knob: fraction of equity risked when the proposal does
        # not carry its own risk_pct. The UI knob (risk_per_trade_pct) pushes a
        # PERCENT (1.0 = 1%) — see ``_risk_fraction``; the default here is the
        # legacy fraction (0.01 = 1%).
        self.default_risk_pct = float(default_risk_pct)
        # Hard cap on the lot of any single entry (safety cap from the UI).
        self.max_lot_per_trade = float(max_lot_per_trade)
        # When True, lot size is ALWAYS recomputed from the risk-% knob — even
        # if the synthesiser already supplied a size (operator risk control).
        # False keeps the historic behaviour: only missing sizes are completed.
        self.force_risk_sizing = bool(force_risk_sizing)
        # One-entry policy: while one of OUR positions (matched by magic) is
        # open, new entries for the same account are blocked.
        self.single_entry_policy = bool(single_entry_policy)
        self.entry_magic = int(entry_magic)
        # Entry cooldown (0.0 = disabled): after a SUCCESSFUL entry for a
        # symbol, the next entry for that symbol is blocked for this many
        # seconds. Addresses the "new entry every 2 minutes at almost the same
        # price" complaint.
        self.entry_cooldown_s = float(entry_cooldown_s)
        # Price-distance guard (0.0 = disabled): a new entry must be at least
        # ``entry_min_distance_atr * ATR`` away from the last entry price for
        # the same symbol. Needs a positive ATR to apply.
        self.entry_min_distance_atr = float(entry_min_distance_atr)
        # Multi-timeframe filter: when enabled, an LTF entry whose direction
        # fights a STRONG HTF bias is vetoed (becomes NO_TRADE). The bias comes
        # from ``analysis_context["htf_bias"]`` (attached by the feed loop).
        # Only a bias at/above ``htf_min_strength`` triggers the veto; a NEUTRAL
        # or weak bias never blocks a trade.
        self.htf_filter_enabled = bool(htf_filter_enabled)
        self.htf_min_strength = float(htf_min_strength)
        # Signal registry (FOKUS #2): the authoritative per-symbol signal gate.
        # When a signal is already live (PENDING/EXECUTING/OPEN) the committee is
        # NOT re-convened — the pipeline short-circuits to SIGNAL_PENDING. When
        # ``None`` a process-wide registry is resolved lazily so the gate is on
        # by default without extra wiring.
        self._signal_registry = signal_registry
        # Master switch for the pending-signal gate (env override honoured).
        self.pending_signal_guard = bool(pending_signal_guard) and is_pending_guard_enabled()
        # FOKUS #4: strategy config provider. When supplied it returns the ACTIVE
        # strategy's parameters (from StrategyRegistry); the pipeline applies the
        # risk/confidence knobs so activating a strategy really changes what the
        # engine does (not just a display label). Optional → historic behaviour.
        self._strategy_config_provider = strategy_config_provider
        self._strategy_config: dict[str, Any] = {}
        # Last SUCCESSFUL entry per (upper-case) symbol: {"price": float,
        # "ts": float}. Blocked/failed entries are never recorded.
        self._last_entries: dict[str, dict[str, float]] = {}
        # Money manager used to COMPLETE a proposal whose SL/TP/size the synthesis
        # left empty (so an entry command can reach execution). Deterministic;
        # never overrides values the proposal already provides. Default instance
        # keeps existing behaviour when a caller does not inject one.
        self.money_manager = money_manager if money_manager is not None else MoneyManager()
        # Optional execution-critical guard (§24). When supplied it must expose
        # ``check_can_execute() -> (bool, reason)``; a False result blocks new
        # orders at the execution check-point. Optional so existing callers and
        # tests are unaffected.
        self.dependency_guard = dependency_guard
        # Optional reconciliation gate (audit P0-3). Same ``check_can_execute``
        # contract; a critical internal↔MT5 mismatch blocks new orders.
        self.reconciliation_guard = reconciliation_guard
        # Optional per-cycle result hook (Phase 5). Invoked exactly once per
        # cycle with the finished PipelineResult — the reporting seam used to
        # deliver Telegram reports. A broken hook is swallowed: reporting must
        # never break the autonomous loop.
        self.result_hook = result_hook
        # Optional learning-feedback provider (Phase 7). When present, prior
        # lessons are summarised into the analysis context so leads can cite
        # them (advisory only — signals/confidence stay deterministic).
        self.lesson_provider = lesson_provider

    @property
    def signal_registry(self) -> Any:
        """Resolve the signal registry (lazy process-wide default)."""
        if self._signal_registry is None:
            self._signal_registry = get_signal_registry()
        return self._signal_registry

    @property
    def fanout_enabled(self) -> bool:
        """Whether multi-terminal fan-out is enabled RIGHT NOW (live toggle)."""
        return self._fanout_enabled_provider()

    @property
    def zone_entry_enabled(self) -> bool:
        """Whether OB/FVG watch-and-fire entry is enabled RIGHT NOW (live)."""
        return self._zone_entry_enabled_provider()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run(
        self,
        event: Any,
        context: Optional[dict[str, Any]] = None,
    ) -> PipelineResult:
        """Run a single decision cycle for ``event``.

        Args:
            event: The triggering event — a dict or ``DetectedEvent``.
            context: Optional context dict. Recognised keys include
                ``account_state``, ``current_positions``, ``market_info`` and
                ``event_type``. Non-dict values are ignored defensively.

        Returns:
            A :class:`PipelineResult` describing every stage.
        """
        context = dict(context) if isinstance(context, dict) else {}
        event_id = self._event_id(event)
        event_type = self._event_type(event, context)

        result = PipelineResult(
            event_id=event_id,
            decision="NO_TRADE",
            status=STATUS_NO_TRADE,
            task_id=_new_id("task"),
            decision_id=_new_id("dec"),
            strategy_version=self.strategy_version,
            event_type=event_type,
        )

        # Correlation fields for reports/notifications (Phase 5): the caller's
        # trace id when supplied (else the cycle's own event id, which the trace
        # store also uses) and the event symbol travel with the result so the
        # Telegram report can reference a real, traceable id.
        result.trace_id = str(context.get("trace_id") or event_id)
        result.symbol = self._event_symbol(event, context)

        # FOKUS #5: tag the cycle with the market-data source so a synthetic
        # (MT5-not-attached) analysis is never mistaken for real intelligence.
        result.data_source = self._resolve_data_source()

        # ── Step 0: Pending-signal gate (FOKUS #2) ──────────────────────
        # If a signal for this symbol is already live (PENDING/EXECUTING/OPEN)
        # or the symbol is in a post-failure cooldown, do NOT re-convene the
        # committee. The supervisor also does not re-ask while a trade is open.
        # This is what stops the "same BUY/ERROR every cycle" spam.
        if self.pending_signal_guard and result.symbol:
            try:
                should_convene, gate_reason = self.signal_registry.should_convene(result.symbol)
            except Exception as exc:  # fail-open: a broken gate never blocks
                should_convene, gate_reason = True, ""
                logger.debug("Pending-signal gate skipped: %s", exc)
            if not should_convene:
                existing = self.signal_registry.get(result.symbol)
                result.decision = (
                    str(getattr(existing, "direction", "") or "WAIT").upper()
                    if existing is not None
                    else "WAIT"
                )
                result.status = STATUS_SIGNAL_PENDING
                result.risk_reason = gate_reason
                result.summary = gate_reason
                result.add_stage("supervisor", STAGE_SKIPPED, gate_reason)
                result.add_stage("risk", STAGE_SKIPPED, "signal sudah aktif")
                result.add_stage("execution", STAGE_SKIPPED, "signal sudah aktif")
                self._finalise(result, emit=False)
                return result

        # ── Step A: Supervisor analysis ─────────────────────────────────
        analysis_context = self._build_analysis_context(event, event_type, context)
        try:
            analysis = self.supervisor.analyze(analysis_context)
        except Exception as exc:  # fail-closed
            logger.exception("Supervisor analysis failed for event %s", event_id)
            result.status = STATUS_WAIT
            result.decision = "WAIT"
            result.error = f"supervisor error: {exc}"
            result.add_stage("supervisor", STAGE_ERROR, str(exc))
            self._finalise(result)
            return result

        result.add_stage("supervisor", STAGE_OK, "analysis complete")

        # Surface the synthesis fields the report/notification layer consumes.
        if isinstance(analysis, dict):
            result.confidence = _coerce_confidence(analysis.get("overall_confidence"))
            result.summary = str(analysis.get("summary") or "")
            result.agent_results = (
                analysis.get("agent_results")
                if isinstance(analysis.get("agent_results"), dict)
                else {}
            )
            result.supervisor_summary = str(analysis.get("summary") or "")

        # ── Extract trade proposal ──────────────────────────────────────
        proposal = self._extract_proposal(analysis)
        if proposal is None or not self._is_actionable(proposal):
            # NO-TRADE path: skip risk and execution entirely.
            result.decision = self._no_trade_decision(analysis)
            result.status = STATUS_WAIT if result.decision == "WAIT" else STATUS_NO_TRADE
            result.risk_reason = "no actionable proposal"
            # Level reporting: an indicative ladder (ATR model) so the
            # report still carries Entry/SL/TP1/TP2/TPmax for the setup.
            result.levels = self._indicative_levels(analysis, analysis_context)
            result.add_stage("risk", STAGE_SKIPPED, "no proposal to validate")
            result.add_stage("execution", STAGE_SKIPPED, "no approved order")
            self._finalise(result)
            return result

        result.decision = str(proposal.get("direction", "WAIT")).upper()
        result.proposal_id = str(proposal.get("proposal_id") or _new_id("prop"))

        # A real, actionable signal exists → mark it PENDING in the registry so
        # subsequent cycles for this symbol are gated instead of re-convening
        # the committee. Fail-safe: a broken registry never breaks the cycle.
        if self.pending_signal_guard and result.symbol:
            try:
                self.signal_registry.open_signal(
                    result.symbol,
                    result.decision,
                    confidence=result.confidence,
                    levels=proposal,
                    proposal_id=result.proposal_id,
                )
            except Exception as exc:  # noqa: BLE001 - never break the cycle
                logger.debug("Signal registry open skipped: %s", exc)

        # ── Multi-timeframe filter ───────────────────────────────────────
        # An LTF entry that fights a strong HTF bias is vetoed before the gate.
        # Fail-safe: a missing/invalid bias never blocks (returns None).
        htf_veto = self._htf_bias_veto(proposal, analysis_context)
        if htf_veto is not None:
            result.decision = "WAIT"
            result.status = STATUS_NO_TRADE
            result.risk_reason = htf_veto
            result.levels = self._indicative_levels(analysis, analysis_context)
            result.add_stage("risk", STAGE_SKIPPED, "HTF bias veto (multi-timeframe)")
            result.add_stage("execution", STAGE_SKIPPED, "no approved order")
            # The pending signal we just opened must NOT stay live, or the gate
            # would block every future cycle (stuck). Mark it SKIPPED (terminal).
            self._mark_signal(result, "skipped", f"HTF veto: {htf_veto}")
            self._finalise(result)
            return result

        # ── Step B: Deterministic Risk Gate ─────────────────────────────
        # Use the *analysis* context (caller context + merged market snapshot)
        # so deterministic completion can see the market evidence (ATR in
        # ``volatility.atr`` / ``market_state``) — the raw scheduler context
        # only carries account/positions/market_info.
        validation = self._build_validation_inputs(proposal, analysis_context)
        # Level reporting: the ladder comes from the completed proposal
        # (real entry/SL), consistent with what the gate validates. When the
        # proposal still lacks a usable stop (e.g. no ATR in the context) the
        # report falls back to the indicative ATR ladder instead of nothing.
        result.levels = self._order_levels(validation, analysis_context) or self._indicative_levels(
            analysis, analysis_context
        )
        try:
            decision: GateDecision = self.risk_gate.validate_proposal(
                validation["proposal"],
                validation["account_state"],
                validation["current_positions"],
                validation["market_info"],
            )
        except Exception as exc:  # fail-closed → BLOCK
            logger.exception("Risk gate failed for event %s", event_id)
            result.risk_approved = False
            result.status = STATUS_BLOCKED
            result.risk_reason = f"risk error: {exc}"
            result.error = f"risk error: {exc}"
            result.add_stage("risk", STAGE_ERROR, str(exc))
            result.add_stage("execution", STAGE_SKIPPED, "risk did not approve")
            self._finalise(result)
            return result

        result.risk_approved = bool(getattr(decision, "approved", False))
        result.risk_reason = str(getattr(decision, "reason", ""))

        if not result.risk_approved:
            # BLOCKED path: do NOT execute. The signal was not eligible, so mark
            # it SKIPPED in the registry — a new (possibly different) signal may
            # still be raised later, but the identical one is not re-emitted.
            result.status = STATUS_BLOCKED
            result.add_stage("risk", STAGE_BLOCKED, result.risk_reason)
            result.add_stage("execution", STAGE_SKIPPED, "risk did not approve")
            self._mark_signal(result, "skipped", f"ditolak risk gate: {result.risk_reason}")
            self._finalise(result)
            return result

        result.add_stage("risk", STAGE_OK, result.risk_reason)

        # ── Step B2: Execution-critical dependency guard (§24) ──────────
        # When the execution circuit breaker is open, new orders must be
        # blocked. Only runs when a guard is injected (backwards compatible).
        if self.dependency_guard is not None:
            try:
                allowed, guard_reason = self.dependency_guard.check_can_execute()
            except Exception as exc:  # fail-closed: a broken guard blocks
                allowed, guard_reason = False, f"dependency guard error: {exc}"
            if not allowed:
                result.status = STATUS_BLOCKED
                result.risk_reason = guard_reason or "execution blocked by dependency guard"
                result.error = guard_reason or "execution blocked by dependency guard"
                result.add_stage(
                    "dependency_guard",
                    STAGE_BLOCKED,
                    result.risk_reason,
                )
                result.add_stage("execution", STAGE_SKIPPED, "dependency guard blocked")
                self._mark_signal(result, "skipped", f"dependency guard: {result.risk_reason}")
                self._finalise(result)
                return result
            result.add_stage("dependency_guard", STAGE_OK, "execution-critical deps healthy")

        # ── Step B3: Reconciliation gate (audit P0-3) ───────────────────
        # A critical internal↔MT5 mismatch (missing/orphan position, volume
        # drift, …) must BLOCK new orders until the state is reconciled.
        # Fail-closed: a broken guard blocks. Only runs when injected.
        if self.reconciliation_guard is not None:
            try:
                allowed, rec_reason = self.reconciliation_guard.check_can_execute()
            except Exception as exc:  # fail-closed: a broken guard blocks
                allowed, rec_reason = False, f"reconciliation guard error: {exc}"
            if not allowed:
                result.status = STATUS_BLOCKED
                result.risk_reason = rec_reason or "execution blocked by reconciliation"
                result.error = rec_reason or "execution blocked by reconciliation"
                result.add_stage("reconciliation", STAGE_BLOCKED, result.risk_reason)
                result.add_stage("execution", STAGE_SKIPPED, "reconciliation blocked")
                self._mark_signal(result, "skipped", f"reconciliation: {result.risk_reason}")
                self._finalise(result)
                return result
            result.add_stage("reconciliation", STAGE_OK, "internal state matches MT5")

        # ── Step B4: One-entry policy ───────────────────────────────────
        # While one of OUR positions (matched by magic) is still open, a new
        # entry is blocked — one signal / one position at a time. Fail-safe: a
        # broken position read leaves the guard permissive (never blocks).
        if self.single_entry_policy and self._has_own_position(validation["current_positions"]):
            ticket = self._own_position_ticket(validation["current_positions"])
            result.status = STATUS_BLOCKED
            result.risk_reason = f"kebijakan satu entry: posisi #{ticket} masih terbuka"
            result.add_stage("single_entry", STAGE_BLOCKED, result.risk_reason)
            result.add_stage("execution", STAGE_SKIPPED, "single entry policy")
            # Do not leave the freshly-opened signal live (would stick forever).
            self._mark_signal(result, "skipped", f"single-entry: posisi #{ticket} terbuka")
            self._finalise(result)
            return result

        # ── Step B5: Entry cooldown + price-distance guard ──────────────
        # A new entry for the same symbol is blocked when either (a) the last
        # SUCCESSFUL entry was less than ``entry_cooldown_s`` ago or (b) the
        # price is closer than ``entry_min_distance_atr * ATR`` to the last
        # entry price. Fail-open: any error inside the guard is swallowed and
        # never blocks the cycle.
        block_reason = None
        try:
            block_reason = self._entry_guard_reason(result.symbol, validation, analysis_context)
        except Exception as exc:  # noqa: BLE001 - fail-open, never block blind
            logger.debug("Entry cooldown guard skipped: %s", exc)
        if block_reason:
            result.status = STATUS_BLOCKED
            result.risk_reason = block_reason
            result.add_stage("entry_cooldown", STAGE_BLOCKED, block_reason)
            result.add_stage("execution", STAGE_SKIPPED, "entry cooldown guard")
            # CRITICAL: a signal parked by the entry cooldown must NOT stay
            # PENDING, or the pending-signal gate would block every future cycle
            # for this symbol (the "stuck, no new signal" symptom).
            self._mark_signal(result, "skipped", block_reason)
            self._finalise(result)
            return result

        # ── Step B6: Zone entry (F2) — watch-and-fire at the OB/FVG ─────
        # When enabled, an approved entry WAITS until price reaches the OB/FVG
        # zone (aligned with the M30/H1 bias). If price is not there yet, the
        # signal is parked as pending and NO order is sent this cycle.
        if self.zone_entry_enabled and self.zone_entry_gate is not None:
            plan, zone_reason = self._zone_entry_plan(
                result.symbol, proposal, validation, analysis_context
            )
            if plan is None:
                result.status = STATUS_BLOCKED
                result.risk_reason = f"entry OB/FVG: {zone_reason}"
                result.add_stage("zone_entry", STAGE_BLOCKED, result.risk_reason)
                result.add_stage("execution", STAGE_SKIPPED, "menunggu zona entry")
                self._mark_signal(result, "skipped", f"menunggu zona OB/FVG: {zone_reason}")
                self._finalise(result)
                return result
            # At the zone → apply the plan's levels onto the proposal so the
            # order carries the OB-based entry/SL/TP (RR-based).
            try:
                proposal["entry_price"] = plan["entry"]
                proposal["stop_loss"] = plan["stop_loss"]
                proposal["take_profit"] = plan["take_profit"]
                result.add_stage("zone_entry", STAGE_OK, "harga di zona OB/FVG")
            except Exception as exc:  # noqa: BLE001 - never block on a notes error
                logger.debug("Zone entry plan apply skipped: %s", exc)

        # ── Step C: Execution (only when explicitly approved) ───────────
        if self.execution_engine is None:
            result.status = STATUS_ERROR
            result.error = "execution engine not configured"
            result.add_stage("execution", STAGE_ERROR, "execution engine not configured")
            self._finalise(result)
            return result

        try:
            request = self._build_order_request(proposal, validation, result)
        except Exception as exc:  # cannot build a valid order → do not execute
            logger.exception("Order build failed for event %s", event_id)
            result.status = STATUS_ERROR
            result.error = f"order build error: {exc}"
            result.add_stage("execution", STAGE_ERROR, str(exc))
            self._finalise(result)
            return result

        # Audit B-3: stamp the gate-issued approval token. Reaching this point
        # means the deterministic Risk Gate returned approved=True AND both the
        # dependency and reconciliation guards passed. The token lets an
        # ``ExecutionEngine(require_approval=True)`` enforce the boundary itself.
        request.approval_token = f"gate:{result.decision_id}"

        result.client_order_id = request.idempotency_key
        result.execution_id = _new_id("exec")

        try:
            exec_result = self._dispatch_execution(request)
        except Exception as exc:  # recorded failure, never propagate
            logger.exception("Execution failed for event %s", event_id)
            result.status = STATUS_ERROR
            result.error = f"execution error: {exc}"
            result.add_stage("execution", STAGE_ERROR, str(exc))
            self._finalise(result)
            return result

        success = bool(getattr(exec_result, "success", False))
        result.execution_result = self._serialise_execution(exec_result)
        result.executed = success
        result.status = STATUS_EXECUTED if success else STATUS_ERROR
        if not success:
            result.error = str(getattr(exec_result, "error_message", "execution failed"))
        result.add_stage(
            "execution",
            STAGE_OK if success else STAGE_ERROR,
            result.execution_result.get("error_message", "") or "executed",
        )
        if success:
            # Record the successful entry so the cooldown / price-distance
            # guard can apply to the NEXT entry for this symbol. Blocked or
            # failed entries are never recorded (fail-open on a bad price).
            self._record_entry(result.symbol, proposal, validation)
            # T3b: remember the entry-time decision context (agent outputs /
            # news events / regime) keyed by ticket so the close path can
            # bridge it into the review learning loops. Fail-safe.
            self._remember_entry_context(
                exec_result, result, proposal, validation, analysis_context
            )
            # The position is live → OPEN. No re-analysis until it closes.
            self._mark_signal(
                result, "open", "entry terbuka", ticket=result.execution_result.get("ticket")
            )
        else:
            # Execution failed (e.g. terminal not armed → 403). Mark FAILED so
            # the symbol enters a cooldown and the identical BUY/ERROR signal is
            # NOT re-emitted every cycle — this is the spam fix.
            self._mark_signal(
                result,
                "failed",
                result.error or "eksekusi gagal",
            )
        self._finalise(result)
        return result

    # ------------------------------------------------------------------
    # Helpers — event/context extraction
    # ------------------------------------------------------------------
    @staticmethod
    def _event_id(event: Any) -> str:
        """Return the event id, generating one when absent."""
        if isinstance(event, dict):
            candidate = event.get("event_id") or event.get("id")
        else:
            candidate = getattr(event, "event_id", None) or getattr(event, "id", None)
        return str(candidate) if candidate else _new_id("evt")

    @staticmethod
    def _event_type(event: Any, context: dict[str, Any]) -> str:
        """Return the event type string from the event or context."""
        candidate = None
        if isinstance(event, dict):
            candidate = event.get("event_type")
        else:
            candidate = getattr(event, "event_type", None)
        if candidate is None:
            candidate = context.get("event_type")
        # Normalise enums to their value.
        value = getattr(candidate, "value", candidate)
        return str(value) if value is not None else "UNKNOWN"

    @staticmethod
    def _event_symbol(event: Any, context: dict[str, Any]) -> str:
        """Return the traded symbol from the event (fallback: context)."""
        symbol = None
        if isinstance(event, dict):
            symbol = event.get("symbol")
        else:
            symbol = getattr(event, "symbol", None)
        if not symbol:
            symbol = context.get("symbol")
        return str(symbol) if symbol else ""

    @staticmethod
    def _merge_market_snapshot(event: Any, analysis_context: dict[str, Any]) -> None:
        """Merge market evidence into the analysis context (fail-safe).

        The market feed loop attaches a snapshot (close/high/low series,
        market state, detected events, volatility inputs) to every event it
        emits, and caches the latest snapshot per symbol. Cycles that arrive
        without one (e.g. a manual ``POST /pipeline/run``) still receive the
        cached snapshot so the committee never runs blind. Explicit
        caller-provided context keys always win; missing evidence changes
        nothing.
        """
        snapshot: Any = None
        if isinstance(event, dict):
            snapshot = event.get("market_snapshot")
        else:
            snapshot = getattr(event, "market_snapshot", None)
        if not isinstance(snapshot, dict) or not snapshot:
            try:
                symbol = str(analysis_context.get("symbol") or "")
                snapshot = get_latest_snapshot(symbol)
            except Exception:  # noqa: BLE001 - evidence is best-effort only
                return
        if not isinstance(snapshot, dict):
            return
        for key, value in snapshot.items():
            analysis_context.setdefault(key, value)

    def _build_analysis_context(
        self,
        event: Any,
        event_type: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the context dict handed to the Supervisor."""
        analysis_context: dict[str, Any] = dict(context)
        analysis_context["event_type"] = event_type
        analysis_context.setdefault("event", event)
        # Trade-close payloads arrive under ``trade_result`` (producer
        # contract — see orchestration/runtime); the review path reads
        # ``closed_trade``. Alias it so a TRADE_CLOSE event reaches ReviewLead
        # with its payload. Fail-safe: dict payloads only.
        if "closed_trade" not in analysis_context:
            trade_result = (
                event.get("trade_result")
                if isinstance(event, dict)
                else getattr(event, "trade_result", None)
            )
            if isinstance(trade_result, dict) and trade_result:
                analysis_context["closed_trade"] = trade_result
        # Surface symbol from the event when the caller omitted it (needed
        # *before* lesson feedback so the summary is symbol-scoped).
        if "symbol" not in analysis_context:
            symbol = None
            if isinstance(event, dict):
                symbol = event.get("symbol")
            else:
                symbol = getattr(event, "symbol", None)
            if symbol:
                analysis_context["symbol"] = symbol
        # Fase 6: merge the market evidence behind this event (or the latest
        # cached snapshot) so the analysis committee runs on real data.
        self._merge_market_snapshot(event, analysis_context)
        # FOKUS #5: tell the committee (and any consumer) whether the merged
        # market data is LIVE or SIMULATED.
        analysis_context.setdefault("data_source", self._resolve_data_source())
        # Phase 7: attach prior lessons (advisory). Fail-safe — a broken
        # provider must never break the cycle.
        if self.lesson_provider is not None:
            try:
                symbol = analysis_context.get("symbol") or "*"
                analysis_context["lessons"] = self.lesson_provider.summarize_for_symbol(str(symbol))
            except Exception as exc:  # noqa: BLE001 - feedback must never break a cycle
                logger.warning("Lesson provider failed (cycle continues): %s", exc)
        return analysis_context

    # ------------------------------------------------------------------
    # Helpers — proposal extraction
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_proposal(analysis: Any) -> Optional[dict[str, Any]]:
        """Extract a normalised proposal dict from a supervisor analysis.

        Supports ``analysis["proposal"]`` being a dict or a ``TradeProposal``
        object, and ``analysis["synthesis"]["proposal"]`` as a fallback.
        """
        if not isinstance(analysis, dict):
            return None

        raw = analysis.get("proposal")
        if raw is None and isinstance(analysis.get("synthesis"), dict):
            raw = analysis["synthesis"].get("proposal")
        if raw is None:
            return None

        if isinstance(raw, dict):
            proposal = dict(raw)
        elif hasattr(raw, "to_dict"):
            proposal = dict(raw.to_dict())
        else:  # pragma: no cover - defensive
            return None

        # Backfill symbol from the top-level analysis when missing.
        if not proposal.get("symbol") and analysis.get("symbol"):
            proposal["symbol"] = analysis["symbol"]
        if not proposal.get("proposal_id") and analysis.get("proposal_id"):
            proposal["proposal_id"] = analysis["proposal_id"]
        # Alias the synthesiser's SL/TP key names (target_sl/target_tp) to the
        # ones the risk gate/order builder expects (stop_loss/take_profit).
        if proposal.get("stop_loss") is None and proposal.get("target_sl") is not None:
            proposal["stop_loss"] = proposal["target_sl"]
        if proposal.get("take_profit") is None and proposal.get("target_tp") is not None:
            proposal["take_profit"] = proposal["target_tp"]
        return proposal

    def _is_actionable(self, proposal: dict[str, Any]) -> bool:
        """Return True only for proposals with an actionable BUY/SELL direction
        and confidence above the minimum threshold.

        The threshold is the ACTIVE strategy's ``min_confidence`` when one is
        wired (FOKUS #4), else the global ``settings.min_signal_confidence``.
        Fail-closed: missing confidence is treated as 0.0 (not actionable).
        """
        direction = str(proposal.get("direction", "")).upper()
        if direction not in _ACTIONABLE:
            return False

        confidence = float(proposal.get("confidence") or 0.0)
        threshold = self._min_signal_confidence()
        return confidence >= threshold

    def _min_signal_confidence(self) -> float:
        """Return the actionable-confidence threshold (strategy-aware)."""
        config = self._strategy_params()
        try:
            value = config.get("min_confidence")
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            pass
        return float(settings.min_signal_confidence)

    @staticmethod
    def _resolve_data_source() -> str:
        """Return ``"LIVE"`` or ``"SIMULATED"`` for the active market feed.

        Fail-safe: any import/read error returns ``"UNKNOWN"`` rather than
        claiming live data.
        """
        try:
            from mt5.connector import data_source

            return str(data_source())
        except Exception:  # noqa: BLE001 - never break a cycle
            return "UNKNOWN"

    def _strategy_params(self) -> dict[str, Any]:
        """Return the active strategy parameters (cached, fail-safe)."""
        if self._strategy_config:
            return self._strategy_config
        if self._strategy_config_provider is None:
            return {}
        try:
            params = self._strategy_config_provider()
        except Exception as exc:  # noqa: BLE001 - strategy must never break a cycle
            logger.debug("Strategy config provider failed: %s", exc)
            return {}
        if isinstance(params, dict):
            self._strategy_config = params
            # Surface the active strategy version on the cycle for traceability.
            version = params.get("version")
            if version:
                self.strategy_version = str(version)
        return self._strategy_config

    def _htf_bias_veto(
        self,
        proposal: dict[str, Any],
        analysis_context: dict[str, Any],
    ) -> Optional[str]:
        """Return a veto reason when the entry fights a strong HTF bias.

        Returns ``None`` (no veto) when: the filter is disabled, the bias is
        missing/NEUTRAL/below ``htf_min_strength``, the entry direction is
        undetermined, or the entry agrees with the bias. Fail-safe by design.
        """
        if not self.htf_filter_enabled:
            return None
        bias = analysis_context.get("htf_bias")
        if not isinstance(bias, dict):
            return None
        direction = str(bias.get("direction", "")).upper()
        if direction not in ("BULLISH", "BEARISH"):
            return None
        try:
            strength = float(bias.get("strength") or 0.0)
        except (TypeError, ValueError):
            strength = 0.0
        if strength < self.htf_min_strength:
            return None

        entry = str(proposal.get("direction", "")).upper()
        if entry not in _ACTIONABLE:
            return None
        # A BUY fights a BEARISH bias; a SELL fights a BULLISH bias.
        fights = (entry == "BUY" and direction == "BEARISH") or (
            entry == "SELL" and direction == "BULLISH"
        )
        if not fights:
            return None
        tf = str(bias.get("timeframe") or "")
        return (
            f"HTF bias veto: {entry} entry fights {direction} bias on {tf} "
            f"(strength {strength:.2f} >= {self.htf_min_strength:.2f})"
        )

    @staticmethod
    def _no_trade_decision(analysis: Any) -> str:
        """Map a proposal-less analysis to WAIT or NO_TRADE."""
        if isinstance(analysis, dict):
            signal = str(analysis.get("overall_signal", "")).upper()
            if signal == "NEUTRAL":
                return "WAIT"
        return "NO_TRADE"

    @staticmethod
    def _indicative_levels(
        analysis: Any,
        analysis_context: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Indicative Entry/SL/TP1/TP2/TPmax from market evidence.

        Used for no-trade cycles so the report still shows the ladder the
        setup *would* use (project ATR model: SL = 1.5 x ATR). Never
        fabricates: no direction / price / ATR means no ladder.
        """
        try:
            summary = analysis.get("summary") if isinstance(analysis, dict) else ""
            signal = analysis.get("overall_signal") if isinstance(analysis, dict) else ""
            direction = direction_from_text(signal, summary)
            if not direction:
                return None
            price, atr = extract_price_atr(analysis_context)
            return indicative_levels(direction, price, atr)
        except Exception as exc:  # noqa: BLE001 - reporting is best-effort
            logger.debug("Indicative level plan skipped: %s", exc)
            return None

    @staticmethod
    def _order_levels(
        validation: dict[str, Any],
        analysis_context: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Entry/SL/TP1/TP2/TPmax from the (completed) proposal levels."""
        try:
            proposal = validation.get("proposal") or {}
            _, atr = extract_price_atr(analysis_context)
            return build_level_plan(
                proposal.get("direction", ""),
                proposal.get("entry_price", 0.0),
                proposal.get("stop_loss", 0.0),
                take_profit=proposal.get("take_profit", 0.0),
                atr=atr,
            )
        except Exception as exc:  # noqa: BLE001 - reporting is best-effort
            logger.debug("Order level plan skipped: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Helpers — deterministic validation inputs
    # ------------------------------------------------------------------
    def _build_validation_inputs(
        self,
        proposal: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the deterministic inputs required by the Risk Gate.

        The proposal is normalised into the shape expected by
        ``RiskGate.validate_proposal`` (entry_price / stop_loss /
        take_profit / size). Missing account/position/market inputs fall back
        to safe conservative defaults so the gate always runs deterministically.

        When the synthesis leaves ``entry_price``/``stop_loss``/``take_profit``/
        ``size`` empty, they are *completed* deterministically from the market
        context via the injected :class:`MoneyManager` (audit follow-up). Values
        the proposal already provides are NEVER overridden, and any completion
        error is swallowed (the gate then fails closed on the missing field).
        """
        account_state = context.get("account_state")
        if not isinstance(account_state, dict):
            account_state = {
                "equity": 0.0,
                "balance": 0.0,
                "peak_equity": 0.0,
                "daily_pnl": 0.0,
                "used_margin": 0.0,
            }

        current_positions = context.get("current_positions")
        if not isinstance(current_positions, list):
            current_positions = []

        market_info = context.get("market_info")
        if not isinstance(market_info, dict):
            market_info = {}

        normalised_proposal = {
            "symbol": proposal.get("symbol") or context.get("symbol", ""),
            "direction": str(proposal.get("direction", "")).upper(),
            "entry_price": float(proposal.get("entry_price") or proposal.get("price") or 0.0),
            "stop_loss": float(proposal.get("stop_loss") or proposal.get("sl") or 0.0),
            "take_profit": float(proposal.get("take_profit") or proposal.get("tp") or 0.0),
            "size": float(proposal.get("size") or proposal.get("volume") or 0.0),
            "risk_pct": float(proposal.get("risk_pct") or 0.0),
        }

        # Complete SL/TP/size when the synthesis did not supply them so an
        # approved entry can actually reach execution. Fail-safe: any error
        # leaves the values unchanged (the gate then rejects missing fields).
        try:
            self._complete_proposal(normalised_proposal, context, account_state, market_info)
        except Exception as exc:  # noqa: BLE001 - completion is best-effort
            logger.warning("Proposal completion skipped: %s", exc)

        return {
            "proposal": normalised_proposal,
            "account_state": account_state,
            "current_positions": current_positions,
            "market_info": market_info,
        }

    def _complete_proposal(
        self,
        proposal: dict[str, Any],
        context: dict[str, Any],
        account_state: dict[str, Any],
        market_info: dict[str, Any],
    ) -> None:
        """Fill entry/SL/TP/size from market + account context when missing.

        Deterministic only (uses :class:`MoneyManager`, no LLM). Entry/SL/TP are
        only filled when left empty (``<= 0``) — never overridden. The SIZE is
        computed from the risk-% knob when missing (or always when
        ``force_risk_sizing``) and then capped by ``max_lot_per_trade``.
        """
        direction = str(proposal.get("direction", "")).upper()
        if direction not in ("BUY", "SELL"):
            return  # nothing actionable to size

        # --- Resolve a usable entry price -------------------------------
        entry = float(proposal.get("entry_price") or 0.0)
        market_state = context.get("market_state")
        if not isinstance(market_state, dict):
            market_state = {}
        # Market evidence fallback: understands the shapes the feed loop
        # actually emits — ``volatility.price``, a ``market_state`` object or
        # dict (close/atr), and the ``prices`` series tail.
        evidence_price, evidence_atr = extract_price_atr(context)
        if entry <= 0:
            for candidate in (
                market_state.get("close"),
                market_state.get("price"),
                evidence_price,
                (market_info.get("ask") if direction == "BUY" else market_info.get("bid")),
                market_info.get("price"),
                context.get("close"),
                context.get("price"),
            ):
                try:
                    if candidate:
                        entry = float(candidate)
                        break
                except (TypeError, ValueError):
                    continue
        if entry <= 0:
            # No price → cannot size deterministically. Still apply the safety
            # cap so a stale/foreign proposal size can never slip through
            # uncapped (defence in depth).
            self._cap_lot(proposal)
            return
        proposal["entry_price"] = entry

        # --- Resolve ATR (for SL/TP) and point/contract values ----------
        atr = evidence_atr
        if atr <= 0:
            atr = market_state.get("atr", context.get("atr"))
            try:
                atr = float(atr) if atr else 0.0
            except (TypeError, ValueError):
                atr = 0.0

        # --- Complete SL/TP via ATR when both are missing ---------------
        sl = float(proposal.get("stop_loss") or 0.0)
        tp = float(proposal.get("take_profit") or 0.0)
        if (sl <= 0 or tp <= 0) and atr > 0:
            mm_direction = "long" if direction == "BUY" else "short"
            try:
                spread_price = float(market_info.get("spread_price") or 0.0)
            except (TypeError, ValueError):
                spread_price = 0.0
            try:
                sl_price, tp_price = self.money_manager.calculate_sl_tp(
                    entry_price=entry,
                    direction=mm_direction,
                    atr_value=atr,
                    spread=spread_price,
                )
                if sl <= 0:
                    proposal["stop_loss"] = round(float(sl_price), 5)
                    sl = proposal["stop_loss"]
                if tp <= 0:
                    # Place the order's TP at TPmax (3R) so the trade has room to
                    # run the full ladder (TP1=1R, TP2=2R, TPmax=3R). The stop
                    # ladder protects profit rung by rung and the runner trails
                    # after TP2. TPmax = SL_distance × 3.
                    risk_distance = abs(entry - sl) if sl > 0 else 0.0
                    if risk_distance > 0:
                        if direction == "BUY":
                            tp = entry + 3.0 * risk_distance
                        else:
                            tp = entry - 3.0 * risk_distance
                    else:
                        tp = float(tp_price)
                    proposal["take_profit"] = round(float(tp), 5)
                    tp = proposal["take_profit"]
            except Exception as exc:  # noqa: BLE001 - SL/TP is best-effort
                logger.debug("SL/TP completion skipped: %s", exc)

        # --- Complete size via risk-% sizing when missing ---------------
        self._size_proposal(proposal, entry, sl, account_state, market_info)

    def _size_proposal(
        self,
        proposal: dict[str, Any],
        entry: float,
        sl: float,
        account_state: dict[str, Any],
        market_info: dict[str, Any],
    ) -> None:
        """Compute/cap the lot size from the risk-% knob.

        Missing size → always completed. When ``force_risk_sizing`` is enabled
        the size is recomputed even if the proposal already carries one (the
        operator's risk knob wins) — but only when the recompute yields a usable
        lot, so a bad computation falls back to the existing value. Every lot is
        finally capped via :meth:`MoneyManager.cap_lot_size`.
        """
        size = float(proposal.get("size") or 0.0)
        recompute = self.force_risk_sizing or size <= 0
        if recompute and sl > 0 and entry > 0:
            risk_pct = self._risk_fraction()
            equity = float(account_state.get("equity") or account_state.get("balance") or 0.0)
            point_value, contract_size = self._resolve_point_contract(proposal, market_info)
            sl_distance = abs(entry - sl)
            sl_pips = sl_distance / point_value if point_value > 0 else 0.0
            if sl_pips > 0 and equity > 0:
                try:
                    sizing = self.money_manager.calculate_lot_size(
                        balance=equity,
                        risk_pct=risk_pct,
                        sl_pips=sl_pips,
                        point_value=point_value,
                        contract_size=contract_size,
                        equity=equity,
                    )
                    lot = float(getattr(sizing, "lot_size", 0.0) or 0.0)
                    if lot > 0:
                        proposal["size"] = round(lot, 2)
                        proposal["risk_pct"] = risk_pct
                except Exception as exc:  # noqa: BLE001 - sizing is best-effort
                    logger.debug("Position sizing skipped: %s", exc)

        # Safety cap: never exceed the per-trade lot cap (fail-safe).
        self._cap_lot(proposal)

    def _cap_lot(self, proposal: dict[str, Any]) -> None:
        """Clamp ``proposal['size']`` to the per-trade cap (fail-safe).

        The cap is the last line of defence for money safety: it must run on
        EVERY path that could carry a size, including early returns. If the cap
        computation itself fails, we FAIL CLOSED by forcing the size to the cap
        value — never leaving an uncapped order.
        """
        try:
            raw_size = float(proposal.get("size") or 0.0)
        except (TypeError, ValueError):
            raw_size = 0.0
        try:
            capped = self.money_manager.cap_lot_size(
                raw_size,
                max_lot_per_trade=self.max_lot_per_trade,
            )
            proposal["size"] = round(float(capped or 0.0), 2)
        except Exception as exc:  # noqa: BLE001 - fail-CLOSED, never uncapped
            logger.warning(
                "Lot cap computation failed (%s) — forcing size to cap %.4f (fail-closed)",
                exc,
                self.max_lot_per_trade,
            )
            # A non-positive raw size stays 0; otherwise clamp hard to the cap.
            proposal["size"] = round(min(raw_size, float(self.max_lot_per_trade)), 2)

    def _own_position_ticket(self, positions: Any) -> Optional[str]:
        """Return the ticket of one of OUR positions (matched by magic), else None.

        ``positions`` entries may be dicts or objects (the MT5 layer hands back
        either shape). Fail-safe: any read/parse error returns ``None`` (the
        single-entry guard then stays permissive — never blocks on bad data).
        """
        try:
            if not isinstance(positions, (list, tuple)):
                return None
            wanted = int(self.entry_magic)
            for position in positions:
                try:
                    if isinstance(position, dict):
                        magic = position.get("magic")
                        ticket = position.get("ticket")
                    else:
                        magic = getattr(position, "magic", None)
                        ticket = getattr(position, "ticket", None)
                    if magic is None:
                        continue
                    if int(magic) == wanted:
                        return str(ticket) if ticket is not None else "?"
                except Exception:  # noqa: BLE001 - skip an unreadable entry
                    continue
        except Exception:  # noqa: BLE001 - fail open, never block on bad input
            return None
        return None

    def _has_own_position(self, positions: Any) -> bool:
        """True when ``positions`` contains a position with our own magic."""
        return self._own_position_ticket(positions) is not None

    def _entry_guard_reason(
        self,
        symbol: str,
        validation: dict[str, Any],
        analysis_context: dict[str, Any],
    ) -> Optional[str]:
        """Return a block reason when the entry guards apply, else ``None``.

        Two independent guards, both keyed by upper-case symbol:

        * **Entry cooldown** (``entry_cooldown_s > 0``): blocked while less
          than ``entry_cooldown_s`` has elapsed since the last SUCCESSFUL entry.
        * **Price-distance** (``entry_min_distance_atr > 0``): blocked while
          the new entry price is closer than ``entry_min_distance_atr * ATR``
          to the last entry price. Requires a positive ATR — when ATR is
          unavailable only the distance check is skipped; the time cooldown
          still applies.

        Only positive evidence blocks; a missing last entry never blocks.
        """
        key = str(symbol or "").upper()
        if not key:
            return None
        last = self._last_entries.get(key)
        if not isinstance(last, dict):
            return None

        # --- Time cooldown ---------------------------------------------
        if self.entry_cooldown_s > 0:
            try:
                last_ts = float(last.get("ts") or 0.0)
            except (TypeError, ValueError):
                last_ts = 0.0
            remaining = self.entry_cooldown_s - (time.time() - last_ts)
            if remaining > 0:
                return f"entry cooldown: {remaining:.0f}s left for {key}"

        # --- Price-distance guard --------------------------------------
        if self.entry_min_distance_atr > 0:
            _, atr = extract_price_atr(analysis_context)
            if atr > 0:
                try:
                    last_price = float(last.get("price") or 0.0)
                except (TypeError, ValueError):
                    last_price = 0.0
                new_price = self._entry_price(validation)
                if last_price > 0 and new_price > 0:
                    distance = abs(new_price - last_price)
                    min_dist = self.entry_min_distance_atr * atr
                    if distance < min_dist:
                        return (
                            f"jarak entry terlalu dekat: {distance:.5f} < "
                            f"{min_dist:.5f} ({self.entry_min_distance_atr}xATR)"
                        )
        return None

    @staticmethod
    def _entry_price(validation: dict[str, Any]) -> float:
        """Resolve the entry price used in the order (fail-safe → 0.0).

        Prefers the (completed) proposal's ``entry_price``; falls back to the
        market ask/bid when it is missing or non-positive.
        """
        proposal = validation.get("proposal") or {}
        try:
            price = float(proposal.get("entry_price") or 0.0)
        except (TypeError, ValueError):
            price = 0.0
        if price > 0:
            return price
        market_info = validation.get("market_info") or {}
        for candidate in (market_info.get("ask"), market_info.get("bid")):
            try:
                if candidate and float(candidate) > 0:
                    return float(candidate)
            except (TypeError, ValueError):
                continue
        return 0.0

    def _record_entry(
        self,
        symbol: str,
        proposal: dict[str, Any],
        validation: dict[str, Any],
    ) -> None:
        """Record a SUCCESSFUL entry so the guards apply to the next cycle.

        Fail-open: a symbol-less or price-less entry is skipped (never records
        a bogus price); any parse error is swallowed.
        """
        try:
            key = str(symbol or "").upper()
            if not key:
                return
            price = self._entry_price(validation)
            if price <= 0:
                price = float(proposal.get("entry_price") or 0.0)
            if price <= 0:
                return
            self._last_entries[key] = {"price": float(price), "ts": time.time()}
        except Exception as exc:  # noqa: BLE001 - recording is best-effort
            logger.debug("Entry record skipped: %s", exc)

    def _remember_entry_context(
        self,
        exec_result: Any,
        result: Any,
        proposal: dict[str, Any],
        validation: dict[str, Any],
        analysis_context: dict[str, Any],
    ) -> None:
        """T3b: remember entry-time decision context keyed by broker ticket.

        The close path only sees the broker position, so the raw material the
        learning loops need (agent outputs / news events / regime) is captured
        HERE — when the entry executes — and bridged into the review record by
        ``review.close_detector`` when the position later disappears.

        Fail-safe: any error is logged at debug level and swallowed; a failed
        capture only means the learning loops skip this trade.
        """
        try:
            ticket = getattr(exec_result, "ticket", None)
            if ticket is None and isinstance(result.execution_result, dict):
                ticket = result.execution_result.get("ticket")
            if ticket is None:
                return

            agent_outputs = (
                dict(result.agent_results) if isinstance(result.agent_results, dict) else {}
            )

            # News events: prefer the news context's economic events (mapped to
            # the shape the news-pattern memory consumes); fall back to an
            # explicit ``news_events`` list on the analysis context.
            news_events: list[dict[str, Any]] = []
            sentiment = analysis_context.get("sentiment")
            if isinstance(sentiment, dict):
                raw_events = sentiment.get("economic_events")
                if isinstance(raw_events, list):
                    for ev in raw_events:
                        if not isinstance(ev, dict):
                            continue
                        title = ev.get("title") or ev.get("headline")
                        if not title:
                            continue
                        news_events.append(
                            {
                                "title": str(title),
                                "country": str(ev.get("country") or ev.get("currency") or "XX"),
                                "impact": str(ev.get("impact") or "low"),
                                "forecast": str(ev.get("forecast") or ""),
                                "actual": str(ev.get("actual") or ""),
                            }
                        )
            if not news_events:
                raw = analysis_context.get("news_events")
                if isinstance(raw, list):
                    news_events = [
                        dict(ev) for ev in raw if isinstance(ev, dict) and ev.get("title")
                    ]

            # Regime: explicit key, else the market snapshot's state fields.
            regime = str(analysis_context.get("regime") or "").strip()
            if not regime:
                market_state = analysis_context.get("market_state")
                if isinstance(market_state, dict):
                    regime = str(
                        market_state.get("regime")
                        or market_state.get("trend")
                        or market_state.get("state")
                        or ""
                    ).strip()
            if not regime:
                regime = "unknown"

            price = self._entry_price(validation)
            if price <= 0:
                try:
                    price = float(proposal.get("entry_price") or 0.0)
                except (TypeError, ValueError):
                    price = 0.0

            # Initial stop-loss of THIS order — captured so the close path can
            # compute the trade's R-multiple (risk = |entry - initial SL|).
            # Prefer the completed proposal's stop_loss; fall back to the raw
            # proposal, the validation proposal, then the execution result.
            # Never overridden by later trailing changes (that is the whole
            # point: R is defined against the ORIGINAL risk).
            stop_loss = 0.0
            for candidate in (
                proposal.get("stop_loss"),
                proposal.get("sl"),
                (validation.get("proposal") or {}).get("stop_loss"),
                getattr(exec_result, "stop_loss", None),
            ):
                try:
                    if candidate:
                        stop_loss = float(candidate)
                        if stop_loss > 0:
                            break
                except (TypeError, ValueError):
                    continue

            # Direction must be a definite BUY/SELL so the R sign is correct;
            # never store an ambiguous "" / "HOLD" that would flip the sign.
            direction = str(result.decision or proposal.get("direction") or "").strip().upper()
            if direction not in ("BUY", "SELL"):
                # Fall back to the executed order side when available.
                exec_side = ""
                if isinstance(getattr(result, "execution_result", None), dict):
                    exec_side = str(result.execution_result.get("side") or "").strip().upper()
                direction = exec_side if exec_side in ("BUY", "SELL") else ""

            from review.entry_context import remember_entry_context

            remember_entry_context(
                ticket,
                {
                    "symbol": str(result.symbol or proposal.get("symbol") or ""),
                    "direction": direction,
                    "agent_outputs": agent_outputs,
                    "news_events": news_events,
                    "regime": regime,
                    "entry_price": float(price),
                    "stop_loss": float(stop_loss),
                    "ts": time.time(),
                },
            )
        except Exception as exc:  # noqa: BLE001 - capture is best-effort
            logger.debug("Entry context capture skipped: %s", exc)

    def _risk_fraction(self) -> float:
        """Resolve ``default_risk_pct`` to a FRACTION of equity (0.01 = 1%).

        The UI knob ``risk_per_trade_pct`` pushes a PERCENT (>= 0.1, e.g. 1.0
        = 1%); the legacy ``DEFAULT_RISK_PCT`` is already a fraction (0.01).
        Values >= 0.1 are therefore treated as percent, smaller ones as
        fractions. Non-positive values fall back to ``DEFAULT_RISK_PCT``.
        """
        try:
            value = float(self.default_risk_pct)
        except (TypeError, ValueError):
            value = 0.0
        if value <= 0:
            return DEFAULT_RISK_PCT
        return value / 100.0 if value >= 0.1 else value

    def _resolve_point_contract(
        self,
        proposal: dict[str, Any],
        market_info: dict[str, Any],
    ) -> tuple[float, float]:
        """Resolve ``(point_value, contract_size)`` — market_info, spec, defaults."""
        try:
            point_value = float(market_info.get("point_value") or 0.0)
        except (TypeError, ValueError):
            point_value = 0.0
        try:
            contract_size = float(market_info.get("contract_size") or 0.0)
        except (TypeError, ValueError):
            contract_size = 0.0
        if point_value <= 0 or contract_size <= 0:
            # Broker symbol spec fallback (local import — fail-safe).
            try:
                from market.symbol_spec import get_symbol_spec
            except ImportError:  # pragma: no cover - alternate import identity
                try:
                    from src.market.symbol_spec import get_symbol_spec  # type: ignore
                except Exception:  # noqa: BLE001 - spec lookup is best-effort
                    get_symbol_spec = None  # type: ignore
            if get_symbol_spec is not None:
                try:
                    spec = get_symbol_spec(str(proposal.get("symbol") or ""))
                    if point_value <= 0:
                        point_value = float(spec.get("point") or 0.0)
                    if contract_size <= 0:
                        contract_size = float(spec.get("contract_size") or 0.0)
                except Exception as exc:  # noqa: BLE001 - spec lookup is best-effort
                    logger.debug("Symbol spec lookup skipped: %s", exc)
        if point_value <= 0:
            point_value = DEFAULT_POINT_VALUE
        if contract_size <= 0:
            contract_size = DEFAULT_CONTRACT_SIZE
        return point_value, contract_size

    def _zone_entry_plan(
        self,
        symbol: str,
        proposal: dict[str, Any],
        validation: dict[str, Any],
        analysis_context: dict[str, Any],
    ) -> tuple[Optional[dict[str, Any]], str]:
        """Return ``(plan, reason)`` for the OB/FVG gate (F2).

        ``plan`` is the executable entry plan (or ``None``); ``reason`` is a
        short human-readable explanation surfaced in the cycle result so the
        operator can see WHY a signal did not fire (bias neutral, no zone,
        too far, direction mismatch, …). Fail-safe: any error → ``(None, ...)``.
        """
        try:
            gate = self.zone_entry_gate
            ctx = analysis_context if isinstance(analysis_context, dict) else {}
            market = validation.get("market_info") if isinstance(validation, dict) else {}
            market = market if isinstance(market, dict) else {}

            trigger_price = 0.0
            for candidate in (
                market.get("ask"),
                market.get("bid"),
                market.get("price"),
                ctx.get("price"),
                ctx.get("close"),
            ):
                try:
                    trigger_price = float(candidate)
                    if trigger_price > 0:
                        break
                except (TypeError, ValueError):
                    continue
            if trigger_price <= 0:
                return None, "tidak ada harga live untuk cek zona"

            bars = self._zone_bars(symbol, ctx)
            bias_closes = bars.get("bias_closes") or []
            zone_highs = bars.get("zone_highs") or []
            zone_lows = bars.get("zone_lows") or []
            zone_opens = bars.get("zone_opens") or []
            atr = float(bars.get("atr") or 0.0)

            rr = 0.0
            try:
                rr = float(ctx.get("zone_rr") or 0.0)
            except (TypeError, ValueError):
                rr = 0.0

            import trading.entry_zone as ez

            plan = gate.evaluate(
                symbol=symbol,
                htf_closes=bias_closes,
                zone_highs=zone_highs,
                zone_lows=zone_lows,
                zone_opens=zone_opens,
                trigger_price=trigger_price,
                atr=atr,
                rr=(rr if rr > 0 else ez.DEFAULT_RR),
            )
            if plan is None:
                return None, self._zone_wait_reason(
                    bias_closes, zone_highs, zone_lows, trigger_price, atr
                )
            plan_dict = plan.to_dict()
            want = str(proposal.get("direction", "")).upper()
            if want and plan_dict.get("direction") != want:
                logger.info(
                    "Zone entry skipped for %s: plan %s != proposal %s",
                    symbol,
                    plan_dict.get("direction"),
                    want,
                )
                return None, f"arah zona {plan_dict.get('direction')} != sinyal {want}"
            return plan_dict, "harga di zona OB/FVG"
        except Exception as exc:  # noqa: BLE001 - never break the cycle
            logger.debug("Zone entry plan skipped for %s: %s", symbol, exc)
            return None, "gagal menghitung zona"

    def _zone_wait_reason(
        self,
        bias_closes: list[float],
        zone_highs: list[float],
        zone_lows: list[float],
        price: float,
        atr: float,
    ) -> str:
        """Explain why the zone gate did not fire (best-effort, fail-safe)."""
        try:
            import trading.entry_zone as ez

            if len(bias_closes) < 51:
                return f"data bias kurang ({len(bias_closes)} bar)"
            bias = ez.compute_bias(bias_closes)
            if bias.get("direction") == "NEUTRAL":
                return "bias pasar netral (M30/H1 tak searah)"
            want = "bullish" if bias["direction"] == "BULLISH" else "bearish"
            zones = ez.find_fair_value_gaps(zone_highs, zone_lows) + ez.find_order_blocks(
                zone_highs, zone_lows
            )
            zone = ez.pick_zone(zones, want, price)
            if zone is None:
                return "tak ada zona OB/FVG yang cocok"
            dist = ez.zone_distance(zone, price)
            return (
                f"harga {dist:.4g} dari zona (window {ez.DEFAULT_ENTRY_TRIGGER_ATR}×ATR"
                f"={ez.DEFAULT_ENTRY_TRIGGER_ATR * atr:.4g}); menunggu harga mendekat"
            )
        except Exception:  # noqa: BLE001
            return "menunggu harga masuk zona OB/FVG"

    def _zone_bars(self, symbol: str, ctx: dict[str, Any]) -> dict[str, Any]:
        """Fetch MTF bars for the zone gate (bias/zones/atr) — fail-safe {}."""
        provider = ctx.get("zone_bars_provider")
        if callable(provider):
            try:
                data = provider(symbol)
                return data if isinstance(data, dict) else {}
            except Exception:  # noqa: BLE001
                return {}
        try:
            import os

            from mt5 import connector

            bias_tfs = (os.getenv("ZONE_BIAS_TFS") or "M30,H1").split(",")
            zone_tf = (os.getenv("ZONE_TF") or "M5").strip()

            bias_closes: list[float] = []
            for tf in bias_tfs:
                tf = tf.strip()
                if not tf:
                    continue
                bars = connector.get_ohlc(symbol, tf, 120)
                for b in bars or []:
                    close = b.get("close") if isinstance(b, dict) else getattr(b, "close", None)
                    try:
                        if close is not None:
                            bias_closes.append(float(close))
                    except (TypeError, ValueError):
                        continue

            zone_bars = connector.get_ohlc(symbol, zone_tf, 60) or []
            zone_highs = [
                float(b.get("high", 0.0)) if isinstance(b, dict) else float(getattr(b, "high", 0.0))
                for b in zone_bars
            ]
            zone_lows = [
                float(b.get("low", 0.0)) if isinstance(b, dict) else float(getattr(b, "low", 0.0))
                for b in zone_bars
            ]
            zone_opens = [
                float(b.get("open", 0.0)) if isinstance(b, dict) else float(getattr(b, "open", 0.0))
                for b in zone_bars
            ]
            atr = 0.0
            try:
                from trading.indicators import atr_series

                closes = [
                    (
                        float(b.get("close", 0.0))
                        if isinstance(b, dict)
                        else float(getattr(b, "close", 0.0))
                    )
                    for b in zone_bars
                ]
                if len(closes) >= 15:
                    series = atr_series(zone_highs, zone_lows, closes, 14)
                    atr = float(series[-1]) if series else 0.0
            except Exception:  # noqa: BLE001 - ATR is optional
                atr = 0.0
            return {
                "bias_closes": bias_closes,
                "zone_highs": zone_highs,
                "zone_lows": zone_lows,
                "zone_opens": zone_opens,
                "atr": atr,
            }
        except Exception:  # noqa: BLE001
            return {}

    def _dispatch_execution(self, request: OrderRequest) -> Any:
        """Dispatch one decision — fan-out to many terminals, or single order.

        When ``fanout_enabled`` and the engine implements
        ``execute_order_fanout``, the decision is sent to EVERY armed fan-out
        terminal. SL/TP are passed as DISTANCES (|entry − sl|, |tp − entry|) so
        each terminal recomputes absolute levels from its own price. The result
        is a small adapter exposing ``success`` / ``error_message`` plus the
        per-terminal list, so the existing success/failure handling keeps
        working unchanged.

        Otherwise the historic single-terminal call is used.
        """
        if self.fanout_enabled and hasattr(self.execution_engine, "execute_order_fanout"):
            entry = float(getattr(request, "price", 0.0) or 0.0)
            sl = float(getattr(request, "sl", 0.0) or 0.0)
            tp = float(getattr(request, "tp", 0.0) or 0.0)
            risk_distance = abs(entry - sl) if (entry > 0 and sl > 0) else 0.0
            tp_distance = abs(tp - entry) if (entry > 0 and tp > 0) else 0.0
            fanout = self.execution_engine.execute_order_fanout(
                request,
                risk_price=risk_distance,
                tp_price=tp_distance,
            )
            return _FanoutExecutionAdapter(fanout)
        return self.execution_engine.execute_order(request)

    def _build_order_request(
        self,
        proposal: dict[str, Any],
        validation: dict[str, Any],
        result: PipelineResult,
    ) -> OrderRequest:
        """Build an :class:`OrderRequest` from an approved proposal.

        The idempotency key / client order id is taken from the proposal when
        present, otherwise a deterministic one is generated and recorded.
        """
        symbol = proposal.get("symbol") or validation["proposal"]["symbol"]
        direction = str(proposal.get("direction", "")).upper()

        build_proposal = {
            "symbol": symbol,
            "order_type": direction,
            "volume": validation["proposal"]["size"],
            "price": validation["proposal"]["entry_price"],
            "stop_loss": validation["proposal"]["stop_loss"],
            "take_profit": validation["proposal"]["take_profit"],
            "comment": f"EA-Bot-{direction}",
        }

        client_order_id = proposal.get("client_order_id") or proposal.get("idempotency_key")
        if client_order_id:
            build_proposal["client_order_id"] = str(client_order_id)
        else:
            client_order_id = _new_id("coid")
            build_proposal["client_order_id"] = client_order_id
        result.client_order_id = str(client_order_id)

        market_quote = validation["market_info"]
        return self.order_builder.build_order_request(build_proposal, market_quote)

    # ------------------------------------------------------------------
    # Helpers — serialisation
    # ------------------------------------------------------------------
    @staticmethod
    def _serialise_execution(exec_result: Any) -> dict[str, Any]:
        """Serialise an ExecutionResult (or compatible) to a plain dict."""
        if isinstance(exec_result, dict):
            return dict(exec_result)
        # Prefer a rich ``to_dict`` when the object provides one (e.g. the
        # fan-out adapter), so per-terminal results survive serialisation.
        to_dict = getattr(exec_result, "to_dict", None)
        if callable(to_dict):
            try:
                data = dict(to_dict())
                if data:
                    return data
            except Exception:  # noqa: BLE001 - fall back to the field read
                pass
        return {
            "success": bool(getattr(exec_result, "success", False)),
            "ticket": getattr(exec_result, "ticket", None),
            "error_code": getattr(exec_result, "error_code", 0),
            "error_message": getattr(exec_result, "error_message", ""),
            "retries": getattr(exec_result, "retries", 0),
            "position_opened": getattr(exec_result, "position_opened", None),
        }

    def _mark_signal(
        self,
        result: PipelineResult,
        action: str,
        reason: str = "",
        ticket: Any = None,
    ) -> None:
        """Update the signal registry for ``result.symbol`` (fail-safe).

        ``action`` is one of ``open`` / ``executing`` / ``failed`` / ``skipped``
        / ``closed``. Never raises into the cycle.
        """
        if not self.pending_signal_guard or not result.symbol:
            return
        try:
            registry = self.signal_registry
            if action == "open":
                registry.mark_open(result.symbol, ticket, reason)
            elif action == "executing":
                registry.mark_executing(result.symbol, reason)
            elif action == "failed":
                registry.mark_failed(result.symbol, reason)
            elif action == "skipped":
                registry.mark_skipped(result.symbol, reason)
            elif action == "closed":
                registry.mark_closed(result.symbol, reason)
        except Exception as exc:  # noqa: BLE001 - never break the cycle
            logger.debug("Signal registry update (%s) skipped: %s", action, exc)

    def _finalise(self, result: PipelineResult, emit: bool = True) -> None:
        """Finish a cycle: invoke the optional result hook (fail-safe).

        Every ``run()`` exit path funnels through here, so the hook observes
        exactly one finished result per cycle. A broken hook is logged and
        swallowed — reporting must never break the autonomous loop.

        Args:
            emit: When False the result hook is NOT invoked. Used for the
                pending-signal short-circuit: no new signal exists, so nothing
                should be reported/notified (that would be the spam we are
                trying to stop). The result still returns to the caller and is
                recorded by the runtime's decision history.
        """
        if not emit or self.result_hook is None:
            return
        try:
            self.result_hook(result)
        except Exception as exc:  # noqa: BLE001 - reporting must never break a cycle
            logger.warning("Pipeline result hook failed: %s", exc)
