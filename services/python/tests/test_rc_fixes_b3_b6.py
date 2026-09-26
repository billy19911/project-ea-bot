# -*- coding: utf-8 -*-
"""Tests for the release-candidate fixes (audit B-3 and B-6).

B-3: the executor enforces the deterministic gate via a required approval token
     (``ExecutionEngine(require_approval=True)``), and the pipeline stamps it.
B-6: the runtime wires a read-only position monitor so a disappeared ticket
     fires the review → lesson loop (previously inert).
"""

from __future__ import annotations

import pytest
from execution.engine import ExecutionEngine, OrderRequest

# ---------------------------------------------------------------------------
# B-3 — pipeline-level integration of the approval token
# ---------------------------------------------------------------------------


def test_runtime_engine_opts_into_require_approval():
    """The production runtime must build the engine with require_approval=True."""
    from orchestration.runtime import OrchestrationRuntime

    runtime = OrchestrationRuntime()
    engine = runtime.pipeline.execution_engine

    assert isinstance(engine, ExecutionEngine)
    assert engine.require_approval is True


def test_pipeline_stamps_token_and_engine_accepts_it(monkeypatch):
    """End-to-end: the pipeline's stamped token satisfies the executor.

    Combines the real pipeline (stamp) with a real ExecutionEngine configured
    to require approval and simulate (no broker), asserting the order is NOT
    rejected for a missing token.
    """
    import sys

    from orchestration.pipeline import TradingPipeline

    class StubSupervisor:
        def analyze(self, context):
            return {
                "overall_signal": "BUY",
                "overall_confidence": 0.8,
                "proposal": {
                    "symbol": "EURUSD",
                    "direction": "BUY",
                    "entry_price": 1.0850,
                    "stop_loss": 1.0800,
                    "take_profit": 1.0950,
                    "size": 0.1,
                    "confidence": 0.8,
                },
            }

    class StubGate:
        def validate_proposal(
            self, proposal, account_state, current_positions, market_info
        ):
            from risk.gate import GateDecision

            return GateDecision(
                approved=True,
                reason="ok",
                checks_passed={},
                metrics_snapshot={},
            )

    engine = ExecutionEngine(
        mt5_connector=None, simulation_mode=True, require_approval=True
    )
    monkeypatch.setitem(sys.modules, "MetaTrader5", None)

    pipeline = TradingPipeline(
        supervisor=StubSupervisor(), risk_gate=StubGate(), execution_engine=engine
    )
    result = pipeline.run({"event_type": "TREND_BULLISH", "symbol": "EURUSD"}, {})

    # The pipeline-stamped token must let the executor dispatch (simulated).
    assert result.status == "EXECUTED", result.error
    assert result.executed is True


def test_direct_engine_call_without_token_is_blocked(monkeypatch):
    """A direct (un-gated) call to the executor fails closed under B-3."""
    import sys

    engine = ExecutionEngine(
        mt5_connector=None, simulation_mode=True, require_approval=True
    )
    monkeypatch.setitem(sys.modules, "MetaTrader5", None)

    result = engine.execute_order(
        OrderRequest(symbol="EURUSD", order_type="BUY", volume=0.1)
    )

    assert result.success is False
    assert result.error_code == 403


# ---------------------------------------------------------------------------
# B-6 — position monitoring wired into the review loop
# ---------------------------------------------------------------------------


def test_runtime_builds_position_monitor_with_close_detector():
    """The runtime wires a PositionMonitor whose detector fires review (B-6)."""
    from orchestration.runtime import OrchestrationRuntime

    runtime = OrchestrationRuntime()

    assert runtime.position_monitor is not None
    detector = runtime.position_monitor.close_detector
    assert detector is not None
    # The detector must have a close hook wired (review auto-trigger).
    assert detector._on_close is not None


def test_disappeared_ticket_fires_review_hook(monkeypatch):
    """A ticket present then absent triggers the review hook exactly once.

    Observation only — no order is ever placed/closed by the monitor.
    """
    from orchestration.runtime import _build_position_monitor

    fired: list[dict] = []

    from review.close_detector import PositionCloseDetector

    monitor = _build_position_monitor()
    assert monitor is not None
    # Replace the detector's hook with a spy so we can assert the fire without
    # depending on the global review trigger's persistence.
    monitor.close_detector = PositionCloseDetector(
        on_close=lambda rec: fired.append(rec)
    )

    class FakeConnector:
        def __init__(self):
            self.positions = [
                {
                    "ticket": 111,
                    "symbol": "EURUSD",
                    "side": "BUY",
                    "volume": 0.1,
                    "price_open": 1.0850,
                    "price_current": 1.0860,
                    "profit": 5.0,
                }
            ]

        def get_positions(self):
            return list(self.positions)

        def get_tick(self, symbol):
            return {"bid": 1.0860, "ask": 1.0861}

    connector = FakeConnector()
    monitor.mt5_connector = connector
    # Provide a symbol-spec-free minimal tick/ohlc path; monitor tolerates gaps.
    connector.get_ohlc = lambda symbol, timeframe, count: []

    # First observation records the ticket (nothing closes yet).
    monitor.monitor_all_positions()
    assert fired == []

    # Position disappears → close record fires once.
    connector.positions = []
    monitor.monitor_all_positions()

    assert len(fired) == 1
    assert fired[0]["ticket"] == 111
    assert fired[0]["status"] == "CLOSED"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
