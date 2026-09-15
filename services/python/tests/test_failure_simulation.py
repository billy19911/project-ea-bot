# -*- coding: utf-8 -*-
"""Failure simulation tests — EPIC 18.

Covers supervisor simulation (18.03), agent timeout/failure (18.04),
duplicate order (18.07), circuit breaker (18.10), reconciliation
mismatch (18.09), and chaos scenarios (18.14).
"""

from __future__ import annotations

import pytest

from execution import ExecutionEngine, OrderRequest
from execution.order_builder import ExecutionRecoveryEngine
from risk.circuit_breaker import CircuitBreaker
from risk.kill_switch import KillSwitch


class FlakyAgent:
    """Agent double that fails or hangs on demand."""

    def __init__(self, name: str = "flaky", fail_times: int = 0, hang: bool = False):
        self.name = name
        self.agent_type = "analyst"
        self.permissions: list[str] = []
        self.fail_times = fail_times
        self.hang = hang
        self.calls = 0
        self.token_budget = 100000

    def can_handle(self, event_type: str, context: dict) -> bool:
        return True

    def analyze(self, context: dict) -> dict:
        self.calls += 1
        if self.hang:
            raise TimeoutError("agent exceeded time budget")
        if self.calls <= self.fail_times:
            raise RuntimeError("transient agent failure")
        return {
            "agent": self.name,
            "signal": "BUY",
            "confidence": 0.8,
            "reasons": ["ok"],
        }


@pytest.fixture
def mock_connector():
    """Minimal mock MT5 connector (mirrors test_execution_engine)."""

    class MockSymbolInfo:
        volume_min = 0.01
        volume_max = 100.0

    class MockTick:
        bid = 1.0849
        ask = 1.0851

    class MockOrderSendResult:
        def __init__(self, success, ticket=None, message=""):
            self.retcode = 0 if success else 1
            self.order = ticket
            self.deal = ticket
            self.comment = message
            self.price = 1.0850 if success else 0.0

    class Connector:
        def __init__(self):
            self._positions = []

        def order_send(self, payload):
            ticket = int(payload.get("volume", 1.0) * 10000)
            return MockOrderSendResult(True, ticket=ticket, message="Order executed")

        def positions_get(self, ticket=None):
            return []

        def positions_get_all(self):
            return self._positions

        def get_symbol_info(self, symbol):
            return MockSymbolInfo()

        def get_tick(self, symbol):
            return MockTick()

        def get_positions(self):
            return self._positions

    return Connector()


class TestSupervisorFailureIsolation:
    """18.03–18.04 Supervisor simulation & agent failure isolation."""

    def test_failing_agent_does_not_break_cycle(self) -> None:
        from agents.supervisor import SupervisorAgent

        good = FlakyAgent(name="good")
        bad = FlakyAgent(name="bad", fail_times=99)
        sup = SupervisorAgent(routing_policy="all_match", token_budget=100000)
        sup.add_route("ANALYZE", ["good", "bad"])
        result = sup.analyze({"event_type": "ANALYZE", "agents": [good, bad]})
        assert "good" in result["agent_results"]
        assert "bad" in result["agent_results"]
        assert result["agent_results"]["bad"]["signal"] == "NEUTRAL"
        assert result["agent_results"]["good"]["signal"] == "BUY"

    def test_timeout_agent_isolated(self) -> None:
        from agents.supervisor import SupervisorAgent

        hanging = FlakyAgent(name="hanging", hang=True)
        healthy = FlakyAgent(name="healthy")
        sup = SupervisorAgent(routing_policy="all_match", token_budget=100000)
        sup.add_route("ANALYZE", ["hanging", "healthy"])
        result = sup.analyze({"event_type": "ANALYZE", "agents": [hanging, healthy]})
        assert result["agent_results"]["hanging"]["signal"] == "NEUTRAL"
        assert result["agent_results"]["healthy"]["signal"] == "BUY"

    def test_transient_failure_recovered_on_retry_cycle(self) -> None:
        from agents.supervisor import SupervisorAgent

        flaky = FlakyAgent(name="flaky", fail_times=1)
        sup = SupervisorAgent(routing_policy="all_match", token_budget=100000)
        sup.add_route("ANALYZE", ["flaky"])
        first = sup.analyze({"event_type": "ANALYZE", "agents": [flaky]})
        second = sup.analyze({"event_type": "ANALYZE", "agents": [flaky]})
        assert first["agent_results"]["flaky"]["signal"] == "NEUTRAL"
        assert second["agent_results"]["flaky"]["signal"] == "BUY"

    def test_unregistered_agent_returns_neutral(self) -> None:
        from agents.supervisor import SupervisorAgent

        sup = SupervisorAgent(routing_policy="all_match", token_budget=100000)
        sup.add_route("ANALYZE", ["ghost"])
        result = sup.analyze({"event_type": "ANALYZE", "agents": []})
        assert result["agent_results"]["ghost"]["signal"] == "NEUTRAL"


class TestDuplicateOrderPrevention:
    """18.07 Duplicate order."""

    def test_duplicate_rejected(self, mock_connector) -> None:
        engine = ExecutionEngine(mt5_connector=mock_connector)
        req = OrderRequest(
            symbol="EURUSD",
            order_type="BUY",
            volume=1.0,
            idempotency_key="idem-dup",
        )
        first = engine.execute_order(req)
        second = engine.execute_order(req)
        assert first.success is True
        assert second.success is False
        assert second.error_code == 409

    def test_distinct_keys_both_execute(self, mock_connector) -> None:
        engine = ExecutionEngine(mt5_connector=mock_connector)
        r1 = engine.execute_order(
            OrderRequest(symbol="EURUSD", order_type="BUY", volume=1.0, idempotency_key="k1")
        )
        r2 = engine.execute_order(
            OrderRequest(symbol="EURUSD", order_type="BUY", volume=1.0, idempotency_key="k2")
        )
        assert r1.success is True
        assert r2.success is True


class TestCircuitBreakerFailureSimulation:
    """18.10 Circuit breaker."""

    def test_repeated_failures_trip_breaker_and_lock_kill_switch(self) -> None:
        from risk.circuit_breaker import BreakerTripReason

        ks = KillSwitch()
        cb = CircuitBreaker(failure_threshold=3, kill_switch=ks)
        for _ in range(3):
            cb.record_failure(BreakerTripReason.EXECUTION_ERROR, "execution error")
        assert cb.allow() is False
        assert ks.locked is True
        assert ks.is_blocked() is True

    def test_success_resets_failure_count(self) -> None:
        from risk.circuit_breaker import BreakerTripReason

        ks = KillSwitch()
        cb = CircuitBreaker(failure_threshold=3, kill_switch=ks)
        cb.record_failure(BreakerTripReason.EXECUTION_ERROR, "e1")
        cb.record_failure(BreakerTripReason.EXECUTION_ERROR, "e2")
        cb.record_success()
        cb.record_failure(BreakerTripReason.EXECUTION_ERROR, "e3")
        assert cb.allow() is True
        assert ks.locked is False


class TestReconciliationMismatch:
    """18.09 Reconciliation mismatch."""

    def test_mismatch_blocks_new_orders(self) -> None:
        engine = ExecutionRecoveryEngine(critical_mismatch_threshold=1)
        engine.audit_reconciliation(
            internal_positions=[],
            broker_positions=[{"ticket": 1, "symbol": "EURUSD", "volume": 0.1}],
        )
        assert engine.is_execution_blocked() is True

    def test_clean_reconciliation_does_not_block(self) -> None:
        engine = ExecutionRecoveryEngine(critical_mismatch_threshold=1)
        engine.audit_reconciliation(
            internal_positions=[{"ticket": 1, "symbol": "EURUSD", "volume": 0.1}],
            broker_positions=[{"ticket": 1, "symbol": "EURUSD", "volume": 0.1}],
        )
        assert engine.is_execution_blocked() is False

    def test_recovery_block_can_be_cleared_manually(self) -> None:
        engine = ExecutionRecoveryEngine(critical_mismatch_threshold=1)
        engine.audit_reconciliation(
            internal_positions=[],
            broker_positions=[{"ticket": 9, "symbol": "XAUUSD", "volume": 0.5}],
        )
        assert engine.is_execution_blocked() is True
        engine.clear_recovery_block(notes="manual reconcile")
        assert engine.is_execution_blocked() is False


class TestChaosScenarios:
    """18.14 Chaos scenarios — combined failure storms."""

    def test_kill_switch_requires_manual_reset_after_trip(self) -> None:
        from risk.circuit_breaker import BreakerTripReason

        ks = KillSwitch()
        cb = CircuitBreaker(failure_threshold=2, kill_switch=ks)
        cb.record_failure(BreakerTripReason.RISK_BREACH, "storm1")
        cb.record_failure(BreakerTripReason.RISK_BREACH, "storm2")
        assert ks.locked is True
        assert cb.allow() is False
        # Manual two-step reset required — no auto-recovery
        ks.request_reset(requested_by="operator")
        assert ks.is_blocked() is True  # reset pending still blocks
        ks.confirm_reset()
        assert ks.is_blocked() is False
        assert ks.locked is False

    def test_agent_storm_with_failures_and_recovery(self) -> None:
        from agents.supervisor import SupervisorAgent

        agents = [FlakyAgent(name=f"a{i}", fail_times=1 if i % 2 == 0 else 0) for i in range(4)]
        sup = SupervisorAgent(routing_policy="all_match", token_budget=100000)
        for a in agents:
            sup.add_route("ANALYZE", [a.name])
        cycle1 = sup.analyze({"event_type": "ANALYZE", "agents": agents})
        cycle2 = sup.analyze({"event_type": "ANALYZE", "agents": agents})
        # All agents eventually produce BUY after transient failures clear
        assert all(cycle2["agent_results"][a.name]["signal"] == "BUY" for a in agents)
        # Cycle 1 had at least one isolated failure
        assert any(cycle1["agent_results"][a.name]["signal"] == "NEUTRAL" for a in agents)
