# -*- coding: utf-8 -*-
"""Demo trading session management with risk gate enforcement and latency tracking.

Phase 20: MT5 demo account integration with stability, latency measurement,
execution confirmation, risk enforcement, and agent consistency verification.
"""

from __future__ import annotations

import logging
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class DemoTrade:
    """Single trade within a demo session."""

    ticket: Optional[int] = None
    symbol: str = ""
    order_type: str = ""
    volume: float = 0.0
    executed_at: Optional[datetime] = None
    fill_confirmed: bool = False
    error_code: int = 0
    error_message: str = ""
    execution_latency_ms: float = 0.0


@dataclass
class DemoTradingSession:
    """Demo trading session tracking."""

    session_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    trades: list[DemoTrade] = field(default_factory=list)
    status: str = "active"  # "active" | "ended"


class DemoTradingManager:
    """Manages demo trading sessions with risk enforcement and metrics.

    Coordinates order execution against a demo MT5 account,
    enforces risk gate checks, measures latency, and verifies
    agent output consistency.
    """

    RISK_BLOCKED_CODE = 9999

    def __init__(
        self,
        mt5_connector: Any,
        risk_gate: Any,
        execution_engine: Any,
    ) -> None:
        """Initialize demo trading manager.

        Args:
            mt5_connector: MT5 connector instance.
            risk_gate: RiskGate instance for pre-trade validation.
            execution_engine: ExecutionEngine for order execution.
        """
        self.connector = mt5_connector
        self.risk_gate = risk_gate
        self.execution_engine = execution_engine
        self.current_session: Optional[DemoTradingSession] = None
        self._latencies_ms: list[float] = []

    def start_session(self) -> DemoTradingSession:
        """Start or return active demo trading session.

        Returns:
            Active DemoTradingSession.
        """
        if self.current_session and self.current_session.status == "active":
            return self.current_session

        session_id = f"demo_{int(time.time() * 1000)}"
        self.current_session = DemoTradingSession(
            session_id=session_id,
            start_time=datetime.now(timezone.utc),
        )
        logger.info(f"Demo session started: {session_id}")
        return self.current_session

    def end_session(self) -> DemoTradingSession:
        """End current demo trading session.

        Returns:
            Ended DemoTradingSession with stats.
        """
        if not self.current_session:
            raise RuntimeError("No active session to end")

        self.current_session.status = "ended"
        self.current_session.end_time = datetime.now(timezone.utc)
        logger.info(
            f"Demo session ended: {self.current_session.session_id}, "
            f"trades: {len(self.current_session.trades)}"
        )
        return self.current_session

    def execute_demo_trade(self, order_request: Any) -> Any:
        """Execute a demo trade with risk gate enforcement and fill confirmation.

        Args:
            order_request: OrderRequest with symbol, order_type, volume, etc.

        Returns:
            ExecutionResult with success status and latency.
        """
        if not self.current_session or self.current_session.status != "active":
            return type(
                "Result",
                (),
                {
                    "success": False,
                    "error_code": -1,
                    "error_message": "No active demo session",
                    "ticket": None,
                },
            )()

        # Measure latency
        start = time.perf_counter()

        # Risk gate check
        account = self.connector.account_info()
        validation = self.risk_gate.validate(
            account_equity=account.equity,
            margin_used_percent=account.margin / 1000.0 if account.margin else 0.0,
        )

        if not validation.is_safe:
            latency_ms = (time.perf_counter() - start) * 1000
            self._latencies_ms.append(latency_ms)
            return type(
                "Result",
                (),
                {
                    "success": False,
                    "error_code": self.RISK_BLOCKED_CODE,
                    "error_message": f"Risk gate blocked: {validation.errors}",
                    "ticket": None,
                },
            )()

        # Execute order
        try:
            exec_result = self.execution_engine.execute_order(order_request)
            latency_ms = (time.perf_counter() - start) * 1000
            self._latencies_ms.append(latency_ms)

            trade = DemoTrade(
                ticket=exec_result.ticket,
                symbol=order_request.symbol,
                order_type=order_request.order_type,
                volume=order_request.volume,
                executed_at=datetime.now(timezone.utc),
                fill_confirmed=False,
                error_code=exec_result.error_code,
                error_message=exec_result.error_message,
                execution_latency_ms=latency_ms,
            )

            if exec_result.success:
                confirmed = self.execution_engine.confirm_execution(exec_result.ticket)
                trade.fill_confirmed = confirmed
                logger.info(
                    f"Demo trade executed: ticket={exec_result.ticket}, "
                    f"latency={latency_ms:.2f}ms, confirmed={confirmed}"
                )

            self.current_session.trades.append(trade)
            return exec_result

        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            self._latencies_ms.append(latency_ms)
            logger.error(f"Demo trade execution failed: {exc}")
            return type(
                "Result",
                (),
                {
                    "success": False,
                    "error_code": -1,
                    "error_message": str(exc),
                    "ticket": None,
                },
            )()

    def measure_latency(self, order_request: Any) -> float:
        """Measure order execution latency in milliseconds.

        Args:
            order_request: OrderRequest to measure.

        Returns:
            Latency in milliseconds.
        """
        start = time.perf_counter()
        try:
            self.execution_engine.execute_order(order_request)
        except Exception:
            pass
        latency_ms = (time.perf_counter() - start) * 1000
        return max(0.0, latency_ms)

    def check_agent_consistency(self, agent_outputs: dict[str, Any]) -> bool:
        """Verify agent outputs are consistent across runs.

        Args:
            agent_outputs: Dict mapping agent names to their output.

        Returns:
            True if all outputs are equivalent.
        """
        if not agent_outputs:
            return True

        values = list(agent_outputs.values())
        if not values:
            return True

        first = values[0]
        for val in values[1:]:
            if not self._deep_equal(first, val):
                return False
        return True

    @staticmethod
    def _deep_equal(a: Any, b: Any) -> bool:
        """Deep equality check supporting common types."""
        if not isinstance(a, type(b)):
            return False

        if isinstance(a, dict):
            if set(a.keys()) != set(b.keys()):
                return False
            return all(DemoTradingManager._deep_equal(a[k], b[k]) for k in a.keys())

        if isinstance(a, (list, tuple)):
            if len(a) != len(b):
                return False
            return all(DemoTradingManager._deep_equal(x, y) for x, y in zip(a, b))

        return a == b

    def get_session_stats(self) -> dict[str, Any]:
        """Get session statistics including latency percentiles.

        Returns:
            Dict with trade count, latency stats, uptime, etc.
        """
        if not self.current_session:
            return {}

        trades = self.current_session.trades
        latencies = self._latencies_ms or []

        p95 = (
            statistics.quantiles(latencies, n=20)[18]
            if len(latencies) >= 20
            else (max(latencies) if latencies else 0.0)
        )
        p99 = (
            statistics.quantiles(latencies, n=100)[98]
            if len(latencies) >= 100
            else (max(latencies) if latencies else 0.0)
        )

        confirmed = sum(1 for t in trades if t.fill_confirmed)
        failed = sum(1 for t in trades if t.error_code != 0)

        return {
            "session_id": self.current_session.session_id,
            "trades_total": len(trades),
            "trades_confirmed": confirmed,
            "trades_failed": failed,
            "latency_count": len(latencies),
            "latency_min_ms": min(latencies) if latencies else 0.0,
            "latency_max_ms": max(latencies) if latencies else 0.0,
            "latency_mean_ms": (sum(latencies) / len(latencies) if latencies else 0.0),
            "latency_p95_ms": p95,
            "latency_p99_ms": p99,
        }
