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
from typing import Any, Optional, Protocol, runtime_checkable

from execution.engine import OrderRequest
from execution.order_builder import OrderBuilder
from risk.gate import GateDecision

logger = logging.getLogger(__name__)

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
        }


def _new_id(prefix: str) -> str:
    """Generate a short unique identifier with a readable prefix."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


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
    """

    def __init__(
        self,
        supervisor: Any,
        risk_gate: Any,
        execution_engine: Optional[Any] = None,
        order_builder: Optional[OrderBuilder] = None,
        strategy_version: str = "v1.0.0",
        dependency_guard: Optional[Any] = None,
    ) -> None:
        self.supervisor = supervisor
        self.risk_gate = risk_gate
        self.execution_engine = execution_engine
        self.order_builder = order_builder if order_builder is not None else OrderBuilder()
        self.strategy_version = strategy_version
        # Optional execution-critical guard (§24). When supplied it must expose
        # ``check_can_execute() -> (bool, reason)``; a False result blocks new
        # orders at the execution check-point. Optional so existing callers and
        # tests are unaffected.
        self.dependency_guard = dependency_guard

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
        )

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

        # ── Extract trade proposal ──────────────────────────────────────
        proposal = self._extract_proposal(analysis)
        if proposal is None or not self._is_actionable(proposal):
            # NO-TRADE path: skip risk and execution entirely.
            result.decision = self._no_trade_decision(analysis)
            result.status = STATUS_WAIT if result.decision == "WAIT" else STATUS_NO_TRADE
            result.risk_reason = "no actionable proposal"
            result.add_stage("risk", STAGE_SKIPPED, "no proposal to validate")
            result.add_stage("execution", STAGE_SKIPPED, "no approved order")
            self._finalise(result)
            return result

        result.decision = str(proposal.get("direction", "WAIT")).upper()
        result.proposal_id = str(proposal.get("proposal_id") or _new_id("prop"))

        # ── Step B: Deterministic Risk Gate ─────────────────────────────
        validation = self._build_validation_inputs(proposal, context)
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
        # Surface symbol from the event when the caller omitted it.
        if "symbol" not in analysis_context:
            symbol = None
            if isinstance(event, dict):
                symbol = event.get("symbol")
            else:
                symbol = getattr(event, "symbol", None)
            if symbol:
                analysis_context["symbol"] = symbol
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

    # ------------------------------------------------------------------
    # Helpers — deterministic validation inputs
    # ------------------------------------------------------------------
    @staticmethod
    def _build_validation_inputs(
        proposal: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the deterministic inputs required by the Risk Gate.

        The proposal is normalised into the shape expected by
        ``RiskGate.validate_proposal`` (entry_price / stop_loss /
        take_profit / size). Missing account/position/market inputs fall back
        to safe conservative defaults so the gate always runs deterministically.
        """
        normalised_proposal = {
            "symbol": proposal.get("symbol") or context.get("symbol", ""),
            "direction": str(proposal.get("direction", "")).upper(),
            "entry_price": float(proposal.get("entry_price") or proposal.get("price") or 0.0),
            "stop_loss": float(proposal.get("stop_loss") or proposal.get("sl") or 0.0),
            "take_profit": float(proposal.get("take_profit") or proposal.get("tp") or 0.0),
            "size": float(proposal.get("size") or proposal.get("volume") or 0.0),
            "risk_pct": float(proposal.get("risk_pct") or 0.0),
        }

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

        return {
            "proposal": normalised_proposal,
            "account_state": account_state,
            "current_positions": current_positions,
            "market_info": market_info,
        }

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

    @staticmethod
    def _finalise(result: PipelineResult) -> None:
        """Attach a default execution result placeholder for no-trade paths."""
        # Nothing to do today; kept as an explicit hook so status invariants
        # (executed => execution_result present) can be asserted later.
        if not result.executed and result.execution_result is None:
            return
