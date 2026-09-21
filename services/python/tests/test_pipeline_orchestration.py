# -*- coding: utf-8 -*-
"""Tests for the end-to-end TradingPipeline orchestration.

These tests use injected fakes/stubs for the Supervisor, RiskGate, and
ExecutionEngine so that no real MT5 connection or broker interaction is
performed. The pipeline is the *only* component allowed to wire the
Supervisor to deterministic risk validation and order execution.
"""

from __future__ import annotations

import pytest

from orchestration.pipeline import PipelineResult, TradingPipeline
from risk.gate import GateDecision


# ---------------------------------------------------------------------------
# Fakes / stubs
# ---------------------------------------------------------------------------
class FakeSupervisor:
    """Supervisor stub returning a canned synthesis dict or raising."""

    def __init__(self, result=None, exc: Exception | None = None) -> None:
        self._result = result
        self._exc = exc
        self.calls: list[dict] = []

    def analyze(self, context):
        self.calls.append(context)
        if self._exc is not None:
            raise self._exc
        return self._result


class FakeRiskGate:
    """Risk gate stub returning a canned GateDecision or raising."""

    def __init__(self, decision: GateDecision | None = None, exc: Exception | None = None) -> None:
        self._decision = decision
        self._exc = exc
        self.calls: list[tuple] = []

    def validate_proposal(self, proposal, account_state, current_positions, market_info):
        self.calls.append((proposal, account_state, current_positions, market_info))
        if self._exc is not None:
            raise self._exc
        return self._decision


class FakeExecutionEngine:
    """Execution engine stub capturing the OrderRequest it was given."""

    def __init__(self, result=None, exc: Exception | None = None) -> None:
        self._result = result
        self._exc = exc
        self.calls: list = []

    def execute_order(self, request):
        self.calls.append(request)
        if self._exc is not None:
            raise self._exc
        return self._result


def _approved() -> GateDecision:
    return GateDecision(
        approved=True,
        reason="All risk checks passed",
        checks_passed={"stop_loss": True, "risk_reward": True},
        metrics_snapshot={"risk_reward_ratio": 2.0},
    )


def _rejected() -> GateDecision:
    return GateDecision(
        approved=False,
        reason="REJECTED: failed checks — spread",
        checks_passed={"spread": False},
        metrics_snapshot={"spread_pips": 9.0},
    )


def _synthesis(symbol="EURUSD", direction="BUY"):
    """Build a supervisor-style synthesis payload with a trade proposal."""
    return {
        "agent": "supervisor",
        "event_type": "BREAKOUT",
        "overall_signal": direction,
        "overall_confidence": 0.8,
        "agent_results": {},
        "summary": "stub",
        "proposal": {
            "symbol": symbol,
            "direction": direction,
            "entry_price": 1.1000,
            "stop_loss": 1.0950,
            "take_profit": 1.1100,
            "size": 0.1,
            "confidence": 0.8,
        },
    }


def _event(symbol="EURUSD"):
    return {
        "event_id": "evt-123",
        "event_type": "BREAKOUT",
        "symbol": symbol,
        "severity": 0.9,
        "description": "price broke out",
    }


def _context(symbol="EURUSD"):
    return {
        "event_type": "BREAKOUT",
        "symbol": symbol,
        "account_state": {
            "equity": 10_000.0,
            "balance": 10_000.0,
            "peak_equity": 10_000.0,
            "daily_pnl": 0.0,
            "used_margin": 100.0,
        },
        "current_positions": [],
        "market_info": {"spread_pips": 1.0, "ask": 1.1001, "bid": 1.0999},
    }


class _ExecResult:
    success = True
    ticket = 555
    error_code = 0
    error_message = ""
    retries = 0
    position_opened = {"symbol": "EURUSD", "positions_count": 1}


def _pipeline(supervisor, gate, engine=None) -> TradingPipeline:
    return TradingPipeline(
        supervisor=supervisor,
        risk_gate=gate,
        execution_engine=engine if engine is not None else FakeExecutionEngine(_ExecResult()),
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
class TestHappyPath:
    def test_event_to_execution_success(self):
        supervisor = FakeSupervisor(_synthesis())
        gate = FakeRiskGate(_approved())
        engine = FakeExecutionEngine(_ExecResult())

        result = _pipeline(supervisor, gate, engine).run(_event(), _context())

        assert isinstance(result, PipelineResult)
        assert result.decision == "BUY"
        assert result.risk_approved is True
        assert result.executed is True
        assert len(engine.calls) == 1
        order = engine.calls[0]
        assert order.symbol == "EURUSD"
        assert order.order_type == "BUY"
        assert result.execution_result is not None
        assert result.execution_result["success"] is True
        assert result.execution_result["ticket"] == 555

    def test_supervisor_and_risk_receive_context(self):
        supervisor = FakeSupervisor(_synthesis())
        gate = FakeRiskGate(_approved())
        _pipeline(supervisor, gate).run(_event(), _context())

        assert len(supervisor.calls) == 1
        assert len(gate.calls) == 1
        # Risk gate must receive the deterministic validation inputs.
        proposal, account_state, positions, market = gate.calls[0]
        assert proposal["symbol"] == "EURUSD"
        assert account_state["equity"] == 10_000.0
        assert positions == []
        assert market["spread_pips"] == 1.0

    def test_trace_and_identifiers_present(self):
        result = _pipeline(FakeSupervisor(_synthesis()), FakeRiskGate(_approved())).run(
            _event(), _context()
        )

        # Required identifiers regenerated/filled by the pipeline.
        assert result.event_id == "evt-123"
        assert result.task_id
        assert result.decision_id
        assert result.proposal_id
        assert result.execution_id
        assert result.client_order_id
        assert result.strategy_version

        # A per-stage trace is recorded for every stage.
        stage_names = [s["stage"] for s in result.trace]
        assert "supervisor" in stage_names
        assert "risk" in stage_names
        assert "execution" in stage_names
        for stage in result.trace:
            assert "status" in stage and "detail" in stage


# ---------------------------------------------------------------------------
# Blocked path
# ---------------------------------------------------------------------------
class TestBlockedPath:
    def test_risk_rejection_prevents_execution(self):
        supervisor = FakeSupervisor(_synthesis())
        gate = FakeRiskGate(_rejected())
        engine = FakeExecutionEngine(_ExecResult())

        result = _pipeline(supervisor, gate, engine).run(_event(), _context())

        assert result.decision == "BUY"
        assert result.risk_approved is False
        assert result.executed is False
        assert result.execution_result is None
        # Execution engine must NOT be invoked when risk rejects.
        assert engine.calls == []
        assert "REJECTED" in result.risk_reason

    def test_blocked_is_valid_outcome(self):
        result = _pipeline(FakeSupervisor(_synthesis()), FakeRiskGate(_rejected())).run(
            _event(), _context()
        )
        assert result.status == "BLOCKED"
        assert result.error is None


# ---------------------------------------------------------------------------
# No-trade path
# ---------------------------------------------------------------------------
class TestNoTradePath:
    def test_no_proposal_skips_risk_and_execution(self):
        supervisor = FakeSupervisor(
            {
                "agent": "supervisor",
                "event_type": "DOJI",
                "overall_signal": "NEUTRAL",
                "overall_confidence": 0.1,
                "agent_results": {},
                "summary": "no consensus",
                "proposal": None,
            }
        )
        gate = FakeRiskGate(_approved())
        engine = FakeExecutionEngine(_ExecResult())

        result = _pipeline(supervisor, gate, engine).run(_event(), _context())

        assert result.decision in ("WAIT", "NO_TRADE")
        assert result.executed is False
        assert result.risk_approved is False
        assert result.execution_result is None
        # Neither risk nor execution should run without a proposal.
        assert gate.calls == []
        assert engine.calls == []
        assert result.status in ("NO_TRADE", "WAIT")

    def test_hold_direction_is_no_trade(self):
        supervisor = FakeSupervisor(_synthesis(direction="HOLD"))
        gate = FakeRiskGate(_approved())
        result = _pipeline(supervisor, gate).run(_event(), _context())
        assert result.decision in ("WAIT", "NO_TRADE")
        assert gate.calls == []


# ---------------------------------------------------------------------------
# Fail-closed behaviour
# ---------------------------------------------------------------------------
class TestFailClosed:
    def test_supervisor_exception_fails_closed(self):
        supervisor = FakeSupervisor(exc=RuntimeError("supervisor boom"))
        gate = FakeRiskGate(_approved())
        engine = FakeExecutionEngine(_ExecResult())

        result = _pipeline(supervisor, gate, engine).run(_event(), _context())

        assert result.decision in ("WAIT", "NO_TRADE")
        assert result.error is not None
        assert "supervisor boom" in result.error
        assert gate.calls == []
        assert engine.calls == []
        assert result.executed is False

    def test_risk_exception_blocks(self):
        supervisor = FakeSupervisor(_synthesis())
        gate = FakeRiskGate(exc=RuntimeError("risk boom"))
        engine = FakeExecutionEngine(_ExecResult())

        result = _pipeline(supervisor, gate, engine).run(_event(), _context())

        assert result.risk_approved is False
        assert result.status == "BLOCKED"
        assert result.error is not None
        assert "risk boom" in result.error
        # Must never execute when risk did not explicitly approve.
        assert engine.calls == []
        assert result.executed is False

    def test_execution_exception_recorded(self):
        supervisor = FakeSupervisor(_synthesis())
        gate = FakeRiskGate(_approved())
        engine = FakeExecutionEngine(exc=RuntimeError("engine boom"))

        result = _pipeline(supervisor, gate, engine).run(_event(), _context())

        assert result.executed is False
        assert result.error is not None
        assert "engine boom" in result.error
        # Execution was attempted (approved) but failed.
        assert len(engine.calls) == 1

    def test_never_executes_when_risk_absent(self):
        # A gate that never approves must never lead to an execution attempt.
        engine = FakeExecutionEngine(_ExecResult())
        result = _pipeline(FakeSupervisor(_synthesis()), FakeRiskGate(_rejected()), engine).run(
            _event(), _context()
        )
        assert engine.calls == []
        assert result.executed is False


# ---------------------------------------------------------------------------
# Result serialisation
# ---------------------------------------------------------------------------
class TestSerialisation:
    def test_pipeline_result_to_dict_roundtrip(self):
        result = _pipeline(FakeSupervisor(_synthesis()), FakeRiskGate(_approved())).run(
            _event(), _context()
        )
        payload = result.to_dict()
        assert payload["decision"] == "BUY"
        assert payload["status"] == "EXECUTED"
        assert isinstance(payload["trace"], list)
        assert payload["execution_result"]["ticket"] == 555

    def test_blocked_result_to_dict(self):
        result = _pipeline(FakeSupervisor(_synthesis()), FakeRiskGate(_rejected())).run(
            _event(), _context()
        )
        payload = result.to_dict()
        assert payload["status"] == "BLOCKED"
        assert payload["execution_result"] is None


def test_pipeline_accepts_dict_event_without_event_id():
    supervisor = FakeSupervisor(_synthesis())
    result = _pipeline(supervisor, FakeRiskGate(_approved())).run(
        {"event_type": "BREAKOUT", "symbol": "EURUSD"}, _context()
    )
    # An event id is generated when the caller does not supply one.
    assert result.event_id


def test_pipeline_import_and_defaults():
    # Importing / constructing must not require a live MT5 connection.
    p = TradingPipeline(
        supervisor=FakeSupervisor(_synthesis()), risk_gate=FakeRiskGate(_approved())
    )
    assert p is not None


# ---------------------------------------------------------------------------
# Audit P0-3 — reconciliation gate blocks new orders
# ---------------------------------------------------------------------------
class TestReconciliationGate:
    def test_critical_mismatch_blocks_execution(self):
        """A blocked reconciliation guard must prevent the order from being sent."""
        engine = FakeExecutionEngine(_ExecResult())

        class BlockedGuard:
            def check_can_execute(self):
                return False, "execution blocked — reconciliation mismatch"

        pipeline = TradingPipeline(
            supervisor=FakeSupervisor(_synthesis()),
            risk_gate=FakeRiskGate(_approved()),
            execution_engine=engine,
            reconciliation_guard=BlockedGuard(),
        )

        result = pipeline.run(_event(), _context())

        assert result.status == "BLOCKED"
        assert result.executed is False
        assert engine.calls == []  # never reached the broker
        assert any(stage["stage"] == "reconciliation" for stage in result.trace)

    def test_healthy_reconciliation_allows_execution(self):
        """A clean reconciliation guard must not block an approved order."""
        engine = FakeExecutionEngine(_ExecResult())

        class HealthyGuard:
            def check_can_execute(self):
                return True, ""

        pipeline = TradingPipeline(
            supervisor=FakeSupervisor(_synthesis()),
            risk_gate=FakeRiskGate(_approved()),
            execution_engine=engine,
            reconciliation_guard=HealthyGuard(),
        )

        result = pipeline.run(_event(), _context())

        assert result.status == "EXECUTED"
        assert len(engine.calls) == 1

    def test_broken_reconciliation_guard_fails_closed(self):
        """A guard that raises must block (fail-closed), never allow."""
        engine = FakeExecutionEngine(_ExecResult())

        class BrokenGuard:
            def check_can_execute(self):
                raise RuntimeError("guard exploded")

        pipeline = TradingPipeline(
            supervisor=FakeSupervisor(_synthesis()),
            risk_gate=FakeRiskGate(_approved()),
            execution_engine=engine,
            reconciliation_guard=BrokenGuard(),
        )

        result = pipeline.run(_event(), _context())

        assert result.status == "BLOCKED"
        assert engine.calls == []


# ---------------------------------------------------------------------------
# Audit B-3 — the pipeline stamps a gate-issued approval_token
# ---------------------------------------------------------------------------
class TestApprovalToken:
    def test_approved_order_carries_approval_token(self):
        """An executed order must carry the gate-issued approval_token (B-3).

        This lets an ``ExecutionEngine(require_approval=True)`` enforce the
        deterministic gate at the executor, not just at the pipeline.
        """
        engine = FakeExecutionEngine(_ExecResult())
        result = _pipeline(FakeSupervisor(_synthesis()), FakeRiskGate(_approved()), engine).run(
            _event(), _context()
        )

        assert result.status == "EXECUTED"
        assert len(engine.calls) == 1
        order = engine.calls[0]
        assert getattr(order, "approval_token", None)
        assert order.approval_token.startswith("gate:")

    def test_rejected_order_never_reaches_engine(self):
        """A rejected proposal must not produce an order at all (no token)."""
        engine = FakeExecutionEngine(_ExecResult())
        result = _pipeline(FakeSupervisor(_synthesis()), FakeRiskGate(_rejected()), engine).run(
            _event(), _context()
        )

        assert result.status == "BLOCKED"
        assert engine.calls == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
