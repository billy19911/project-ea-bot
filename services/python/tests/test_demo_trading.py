"""Tests for Phase 20 demo trading controls."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from demo.demo_trading import DemoTradingManager
from demo.stability import StabilityMonitor
from execution import ExecutionResult, OrderRequest
from trading.risk_gate import RiskGate


@dataclass
class Account:
    equity: float = 10_000.0
    profit: float = 0.0
    margin: float = 100.0


class Connector:
    def __init__(self) -> None:
        self.account = Account()
        self.positions: list[dict] = []
        self.connected = True
        self.reconnects = 0

    def account_info(self) -> Account:
        return self.account

    def positions_get(self) -> list[dict]:
        return self.positions

    def health_check(self) -> object:
        return type("Health", (), {"connected": self.connected})()

    def reconnect(self) -> bool:
        self.reconnects += 1
        self.connected = True
        return True


class Engine:
    def __init__(self, result: ExecutionResult | None = None) -> None:
        self.result = result or ExecutionResult(True, ticket=123, position_opened={"ok": True})
        self.requests: list[OrderRequest] = []

    def execute_order(self, request: OrderRequest) -> ExecutionResult:
        self.requests.append(request)
        return self.result

    def confirm_execution(self, ticket: int | None) -> bool:
        return ticket == 123


@pytest.fixture
def connector() -> Connector:
    return Connector()


@pytest.fixture
def engine() -> Engine:
    return Engine()


@pytest.fixture
def manager(connector: Connector, engine: Engine) -> DemoTradingManager:
    return DemoTradingManager(connector, RiskGate(min_signal_confidence=0.0), engine)


def order() -> OrderRequest:
    return OrderRequest("EURUSD", "BUY", 0.1)


def test_start_session_creates_active_session(manager: DemoTradingManager) -> None:
    session = manager.start_session()
    assert session.status == "active"
    assert session.start_time.tzinfo is not None


def test_start_session_reuses_active_session(manager: DemoTradingManager) -> None:
    assert manager.start_session() is manager.start_session()


def test_end_session_sets_end_time(manager: DemoTradingManager) -> None:
    manager.start_session()
    session = manager.end_session()
    assert session.status == "ended"
    assert session.end_time is not None


def test_execute_requires_active_session(manager: DemoTradingManager) -> None:
    result = manager.execute_demo_trade(order())
    assert not result.success
    assert "No active demo session" in result.error_message


def test_execute_runs_risk_gate_and_confirms_fill(
    manager: DemoTradingManager, engine: Engine
) -> None:
    manager.start_session()
    result = manager.execute_demo_trade(order())
    assert result.success
    assert len(engine.requests) == 1
    assert manager.current_session is not None
    assert manager.current_session.trades[0].fill_confirmed


def test_execute_blocks_unsafe_risk_state(
    connector: Connector, manager: DemoTradingManager, engine: Engine
) -> None:
    connector.account.equity = 0
    manager.start_session()
    result = manager.execute_demo_trade(order())
    assert not result.success
    assert result.error_code == DemoTradingManager.RISK_BLOCKED_CODE
    assert engine.requests == []


def test_execute_records_failed_order(manager: DemoTradingManager) -> None:
    manager.execution_engine.result = ExecutionResult(False, error_code=7, error_message="rejected")
    manager.start_session()
    result = manager.execute_demo_trade(order())
    assert not result.success
    assert manager.current_session is not None
    assert manager.current_session.trades[0].error_message == "rejected"


def test_measure_latency_returns_nonnegative_value(manager: DemoTradingManager) -> None:
    manager.start_session()
    assert manager.measure_latency(order()) >= 0.0


def test_stats_include_latency_percentiles(manager: DemoTradingManager) -> None:
    manager.start_session()
    # Need at least 20 samples for quantiles calculation
    manager._latencies_ms = [float(i) for i in range(1, 21)] + [100.0]  # 1-20 + 100
    stats = manager.get_session_stats()
    # quantiles(n=20)[18] gives 95th percentile of 21 samples
    assert stats["latency_p95_ms"] == pytest.approx(92.0)
    # quantiles(n=100)[98] not available with 21 samples, falls back to max
    assert stats["latency_p99_ms"] == pytest.approx(100.0)


def test_consistency_accepts_equal_outputs(manager: DemoTradingManager) -> None:
    assert manager.check_agent_consistency({"a": {"x": 1}, "b": {"x": 1}})


def test_consistency_rejects_different_outputs(manager: DemoTradingManager) -> None:
    assert not manager.check_agent_consistency({"a": {"x": 1}, "b": {"x": 2}})


def test_consistency_is_independent_of_mapping_order(manager: DemoTradingManager) -> None:
    assert manager.check_agent_consistency({"a": {"x": [2, 1]}, "b": {"x": [2, 1]}})


def test_uptime_tracks_elapsed_connected_time(connector: Connector) -> None:
    monitor = StabilityMonitor(connector, clock=lambda: 15.0)
    monitor.started_at = 5.0
    assert monitor.track_uptime() == 10.0


def test_error_rate_tracks_failures(connector: Connector) -> None:
    monitor = StabilityMonitor(connector)
    monitor.record_check(False)
    monitor.record_check(True)
    assert monitor.check_error_rate() == 0.5


def test_auto_reconnect_recovers_disconnected_connector(connector: Connector) -> None:
    connector.connected = False
    monitor = StabilityMonitor(connector)
    assert monitor.auto_reconnect()
    assert connector.reconnects == 1


def test_auto_reconnect_skips_healthy_connector(connector: Connector) -> None:
    monitor = StabilityMonitor(connector)
    assert monitor.auto_reconnect()
    assert connector.reconnects == 0
