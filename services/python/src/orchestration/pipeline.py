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
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol, runtime_checkable

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
    ) -> None:
        self.supervisor = supervisor
        self.risk_gate = risk_gate
        self.execution_engine = execution_engine
        self.order_builder = order_builder if order_builder is not None else OrderBuilder()
        self.strategy_version = strategy_version
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
            # BLOCKED path: do NOT execute.
            result.status = STATUS_BLOCKED
            result.add_stage("risk", STAGE_BLOCKED, result.risk_reason)
            result.add_stage("execution", STAGE_SKIPPED, "risk did not approve")
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
                self._finalise(result)
                return result
            result.add_stage("reconciliation", STAGE_OK, "internal state matches MT5")

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
            exec_result = self.execution_engine.execute_order(request)
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

    @staticmethod
    def _is_actionable(proposal: dict[str, Any]) -> bool:
        """Return True only for proposals with an actionable BUY/SELL direction."""
        direction = str(proposal.get("direction", "")).upper()
        return direction in _ACTIONABLE

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

        Deterministic only (uses :class:`MoneyManager`, no LLM). Only fills a
        field the proposal left empty (``<= 0``); never overrides caller intent.
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
                market_info.get("ask") if direction == "BUY" else market_info.get("bid"),
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
            return  # no price → cannot size deterministically
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
                sl_price, tp_price = self.money_manager.calculate_sl_tp(
                    entry_price=entry, direction=mm_direction, atr_value=atr
                )
                if sl <= 0:
                    proposal["stop_loss"] = round(float(sl_price), 5)
                    sl = proposal["stop_loss"]
                if tp <= 0:
                    proposal["take_profit"] = round(float(tp_price), 5)
                    tp = proposal["take_profit"]
            except Exception as exc:  # noqa: BLE001 - SL/TP is best-effort
                logger.debug("SL/TP completion skipped: %s", exc)

        # --- Complete size via risk-% sizing when missing ---------------
        size = float(proposal.get("size") or 0.0)
        if size <= 0 and sl > 0 and entry > 0:
            risk_pct = float(proposal.get("risk_pct") or 0.0) or DEFAULT_RISK_PCT
            equity = float(account_state.get("equity") or account_state.get("balance") or 0.0)
            if equity > 0:
                point_value = (
                    float(market_info.get("point_value") or DEFAULT_POINT_VALUE)
                    or DEFAULT_POINT_VALUE
                )
                contract_size = (
                    float(market_info.get("contract_size") or DEFAULT_CONTRACT_SIZE)
                    or DEFAULT_CONTRACT_SIZE
                )
                # SL distance in "pips" = price distance / point_value.
                sl_distance = abs(entry - sl)
                sl_pips = sl_distance / point_value if point_value > 0 else 0.0
                if sl_pips > 0:
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
        return {
            "success": bool(getattr(exec_result, "success", False)),
            "ticket": getattr(exec_result, "ticket", None),
            "error_code": getattr(exec_result, "error_code", 0),
            "error_message": getattr(exec_result, "error_message", ""),
            "retries": getattr(exec_result, "retries", 0),
            "position_opened": getattr(exec_result, "position_opened", None),
        }

    def _finalise(self, result: PipelineResult) -> None:
        """Finish a cycle: invoke the optional result hook (fail-safe).

        Every ``run()`` exit path funnels through here, so the hook observes
        exactly one finished result per cycle. A broken hook is logged and
        swallowed — reporting must never break the autonomous loop.
        """
        if self.result_hook is None:
            return
        try:
            self.result_hook(result)
        except Exception as exc:  # noqa: BLE001 - reporting must never break a cycle
            logger.warning("Pipeline result hook failed: %s", exc)
