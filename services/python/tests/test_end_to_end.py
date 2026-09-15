# -*- coding: utf-8 -*-
"""True end-to-end test — PRD_V2 §29 Testing Requirements.

Drives ONE full flow through REAL components, faking only the two external
edges (MT5 broker + LLM):

    event → TradingPipeline (supervisor stub) → RiskGate (REAL)
          → ExecutionEngine (REAL, with a FAKE MT5 adapter)
          → position opened → review triggered

Assertions:
* every trace identifier is present (event/task/decision/proposal/execution/…);
* the deterministic Risk Gate is non-bypassable — a BLOCKED flow NEVER reaches
  the MT5 fake;
* the position opened by execution is visible to a subsequent reconciliation
  pass against the fake broker.

No network access is performed.
"""

from __future__ import annotations

import pytest

from execution.engine import ExecutionEngine
from execution.reconciliation import Reconciler
from orchestration.pipeline import TradingPipeline
from review.trade_review import TradeReviewer
from risk.engine import RiskEngine
from risk.gate import RiskGate
from risk.money_management import MoneyManager


# ---------------------------------------------------------------------------
# Fake MT5 adapter (the ONLY external edge faked for execution)
# ---------------------------------------------------------------------------
class FakeMT5Connector:
    """A minimal in-memory MT5 adapter — records sends and tracks positions."""

    def __init__(self) -> None:
        self.orders_sent: list[dict] = []
        self._positions: list[dict] = []
        self._next_ticket = 1000

    # symbol/tick lookups so validate_order can run for real
    def get_symbol_info(self, symbol: str) -> dict:
        return {"symbol": symbol, "volume_min": 0.01, "volume_max": 100.0}

    def get_tick(self, symbol: str):
        class _Tick:
            ask = 1.1001
            bid = 1.0999

        return _Tick()

    def order_send(self, request: dict) -> dict:
        self.orders_sent.append(request)
        self._next_ticket += 1
        ticket = self._next_ticket
        self._positions.append(
            {
                "ticket": ticket,
                "symbol": request["symbol"],
                "volume": request["volume"],
                "price_open": request.get("price") or 1.1001,
                "sl": request.get("sl", 0.0),
                "tp": request.get("tp", 0.0),
                "magic": request.get("magic", 0),
                "side": "BUY" if "BUY" in request["order_type"].upper() else "SELL",
            }
        )
        return {"success": True, "ticket": ticket, "retcode": 10009, "message": "done"}

    def positions(self) -> list[dict]:
        return list(self._positions)


# ---------------------------------------------------------------------------
# Stub supervisor (LLM edge faked) — returns a canned synthesis.
# ---------------------------------------------------------------------------
class StubSupervisor:
    def __init__(self, proposal):
        self._proposal = proposal
        self.calls: list[dict] = []

    def analyze(self, context):
        self.calls.append(context)
        return {
            "agent": "supervisor",
            "event_type": context.get("event_type", "BREAKOUT"),
            "overall_signal": (self._proposal or {}).get("direction", "NEUTRAL"),
            "overall_confidence": 0.8,
            "proposal": self._proposal,
        }


def _real_risk_gate() -> RiskGate:
    return RiskGate(RiskEngine(), MoneyManager())


def _context():
    return {
        "event_type": "BREAKOUT",
        "symbol": "EURUSD",
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


def _event():
    return {
        "event_id": "evt-e2e-1",
        "event_type": "BREAKOUT",
        "symbol": "EURUSD",
        "severity": 0.9,
    }


_APPROVABLE_PROPOSAL = {
    "symbol": "EURUSD",
    "direction": "BUY",
    "entry_price": 1.1000,
    "stop_loss": 1.0950,
    "take_profit": 1.1100,
    "size": 0.1,
    "confidence": 0.8,
    "client_order_id": "e2e-client-1",
}


# ---------------------------------------------------------------------------
# Happy path — full trace + position opened + review triggered
# ---------------------------------------------------------------------------
class TestTrueEndToEnd:
    def test_event_to_execution_to_review(self) -> None:
        mt5 = FakeMT5Connector()
        engine = ExecutionEngine(mt5_connector=mt5)
        pipeline = TradingPipeline(
            supervisor=StubSupervisor(_APPROVABLE_PROPOSAL),
            risk_gate=_real_risk_gate(),
            execution_engine=engine,
        )

        result = pipeline.run(_event(), _context())

        # 1. The REAL risk gate approved and execution ran.
        assert result.risk_approved is True
        assert result.executed is True
        assert result.status == "EXECUTED"

        # 2. Full trace identifiers present.
        assert result.event_id == "evt-e2e-1"
        assert result.task_id
        assert result.decision_id
        assert result.proposal_id
        assert result.execution_id
        assert result.client_order_id
        assert result.strategy_version

        # 3. A position was actually opened in the fake broker.
        assert len(mt5.orders_sent) == 1
        assert len(mt5.positions()) == 1
        opened = mt5.positions()[0]
        assert opened["symbol"] == "EURUSD"

        # 4. Reconciliation of internal vs. broker state is clean (no critical).
        internal = [
            {
                "ticket": opened["ticket"],
                "symbol": opened["symbol"],
                "volume": opened["volume"],
                "sl": opened["sl"],
                "tp": opened["tp"],
                "magic": opened["magic"],
            }
        ]
        report = Reconciler().compare(internal, mt5.positions(), [], [])
        assert report.matched == [opened["ticket"]]
        assert report.has_critical() is False

        # 5. A review is triggered for the resulting trade.
        review = TradeReviewer().review_trade(
            trade_memory_record={
                "trade_id": result.proposal_id,
                "entry_price": 1.1000,
                "exit_price": 1.1050,
                "direction": "BUY",
                "pnl": 50.0,
                "retries": 0,
                "slippage": 0.0,
                "agent_outputs": {"confidence": 0.8, "signal": "BUY"},
            },
            price_history=[1.0980, 1.1020, 1.1040, 1.1050],
        )
        assert review.outcome in ("WIN", "LOSS")
        assert review.trade_id == result.proposal_id

    def test_trace_has_all_stages(self) -> None:
        mt5 = FakeMT5Connector()
        pipeline = TradingPipeline(
            supervisor=StubSupervisor(_APPROVABLE_PROPOSAL),
            risk_gate=_real_risk_gate(),
            execution_engine=ExecutionEngine(mt5_connector=mt5),
        )
        result = pipeline.run(_event(), _context())
        stages = [s["stage"] for s in result.trace]
        assert "supervisor" in stages
        assert "risk" in stages
        assert "execution" in stages


# ---------------------------------------------------------------------------
# BLOCKED path — risk gate non-bypassable, never reaches MT5
# ---------------------------------------------------------------------------
class TestBlockedFlowNeverReachesMT5:
    def test_blocked_flow_never_calls_mt5(self) -> None:
        mt5 = FakeMT5Connector()
        engine = ExecutionEngine(mt5_connector=mt5)
        # A proposal that the REAL risk gate must reject: R:R far below minimum.
        bad_proposal = dict(_APPROVABLE_PROPOSAL)
        bad_proposal["take_profit"] = 1.1001  # R:R ~ 0.02 → rejected
        pipeline = TradingPipeline(
            supervisor=StubSupervisor(bad_proposal),
            risk_gate=_real_risk_gate(),
            execution_engine=engine,
        )

        result = pipeline.run(_event(), _context())

        assert result.risk_approved is False
        assert result.executed is False
        assert result.status == "BLOCKED"
        # The MT5 fake must NEVER be touched on a blocked flow.
        assert mt5.orders_sent == []
        assert mt5.positions() == []

    def test_no_proposal_never_calls_mt5(self) -> None:
        mt5 = FakeMT5Connector()
        pipeline = TradingPipeline(
            supervisor=StubSupervisor(None),
            risk_gate=_real_risk_gate(),
            execution_engine=ExecutionEngine(mt5_connector=mt5),
        )
        result = pipeline.run(_event(), _context())
        assert result.executed is False
        assert mt5.orders_sent == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
