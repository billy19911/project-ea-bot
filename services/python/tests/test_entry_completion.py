# -*- coding: utf-8 -*-
"""Tests for entry-command completion + arm-gated native execution.

Follow-up to the release-candidate audit:
* The proposal is COMPLETED (entry/SL/TP/size) from market + account context so
  an entry command can reach execution (values the proposal already provides are
  never overridden).
* A native ``mt5.order_send`` is fail-closed unless an operator-armed terminal is
  present — regardless of read-only live-data mode — so an importable
  ``MetaTrader5`` can never send a real order without the arm gate.
"""

from __future__ import annotations

import sys

import pytest

from execution.engine import ExecutionEngine, OrderRequest
from orchestration.pipeline import TradingPipeline


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
def _bearish_supervisor():
    class StubSupervisor:
        def analyze(self, context):
            return {
                "overall_signal": "SELL",
                "overall_confidence": 0.7,
                # Deliberately NO entry/sl/tp/size → must be completed.
                "proposal": {"symbol": "XAUUSD", "direction": "SELL"},
            }

    return StubSupervisor()


class _ApproveGate:
    def __init__(self):
        self.seen = None

    def validate_proposal(self, proposal, account_state, current_positions, market_info):
        from risk.gate import GateDecision

        self.seen = proposal
        # Approve only if the completed proposal has a positive size + SL.
        ok = bool(proposal.get("size") and proposal.get("stop_loss"))
        return GateDecision(
            approved=ok, reason="ok" if ok else "incomplete", checks_passed={}, metrics_snapshot={}
        )


def _context():
    base = 2000.0
    prices = [base + i * 1.5 for i in range(60)]
    return {
        "symbol": "XAUUSD",
        "prices": prices,
        "close_prices": prices,
        "highs": [p + 1 for p in prices],
        "lows": [p - 1 for p in prices],
        "account_state": {
            "equity": 10000.0,
            "balance": 10000.0,
            "peak_equity": 10000.0,
            "daily_pnl": 0.0,
            "used_margin": 0.0,
        },
        "current_positions": [],
        "market_info": {
            "spread_pips": 1.0,
            "point_value": 0.01,
            "contract_size": 100,
            "bid": prices[-1] - 0.5,
            "ask": prices[-1] + 0.5,
        },
        "market_state": {"close": prices[-1], "price": prices[-1], "atr": 3.0},
        "close": prices[-1],
        "atr": 3.0,
    }


# ---------------------------------------------------------------------------
# Proposal completion
# ---------------------------------------------------------------------------
def test_proposal_is_completed_with_sl_tp_and_size():
    """A proposal missing SL/TP/size gets them completed deterministically."""
    gate = _ApproveGate()
    pipeline = TradingPipeline(
        supervisor=_bearish_supervisor(), risk_gate=gate, execution_engine=None
    )

    pipeline.run({"event_type": "TREND_BULLISH", "symbol": "XAUUSD"}, _context())

    # The gate must have received a fully-formed proposal.
    assert gate.seen is not None
    assert gate.seen["entry_price"] > 0
    assert gate.seen["stop_loss"] > 0
    assert gate.seen["take_profit"] > 0
    assert gate.seen["size"] > 0


def test_completion_never_overrides_provided_values():
    """Values the proposal already carries must be preserved verbatim."""
    gate = _ApproveGate()

    class FullSupervisor:
        def analyze(self, context):
            return {
                "overall_signal": "BUY",
                "overall_confidence": 0.9,
                "proposal": {
                    "symbol": "EURUSD",
                    "direction": "BUY",
                    "entry_price": 1.1000,
                    "stop_loss": 1.0950,
                    "take_profit": 1.1100,
                    "size": 0.42,
                },
            }

    pipeline = TradingPipeline(supervisor=FullSupervisor(), risk_gate=gate, execution_engine=None)
    pipeline.run({"event_type": "TREND_BULLISH", "symbol": "EURUSD"}, _context())

    assert gate.seen["entry_price"] == 1.1000
    assert gate.seen["stop_loss"] == 1.0950
    assert gate.seen["take_profit"] == 1.1100
    assert gate.seen["size"] == 0.42


def test_entry_reaches_execution_when_no_terminal(monkeypatch):
    """Full command-entry path reaches a (simulated) execution end to end."""
    monkeypatch.setitem(sys.modules, "MetaTrader5", None)
    engine = ExecutionEngine(mt5_connector=None, simulation_mode=True, require_approval=True)
    pipeline = TradingPipeline(
        supervisor=_bearish_supervisor(), risk_gate=_ApproveGate(), execution_engine=engine
    )

    result = pipeline.run({"event_type": "TREND_BULLISH", "symbol": "XAUUSD"}, _context())

    assert result.status == "EXECUTED", result.error
    assert result.executed is True
    assert result.execution_result["success"] is True


# ---------------------------------------------------------------------------
# Market-evidence shapes (feed-loop regression)
# ---------------------------------------------------------------------------
class _MarketStateObject:
    """Mimics the market detector state OBJECT the feed loop caches.

    The feed loop stores a ``MarketState`` *dataclass instance* (not a dict),
    so ``market_state.get(...)``/``market_state["atr"]`` cannot be used.
    """

    def __init__(self, close: float, atr: float):
        self.close = close
        self.price = close
        self.atr = atr


def test_completion_reads_atr_from_volatility_when_state_is_object():
    """ATR living in ``volatility.atr`` (feed-loop shape) must reach the gate.

    Regression: ``_complete_proposal`` used to read only
    ``market_state["atr"]``/``context["atr"]``. With an object state and ATR
    only under ``volatility``, SL/TP stayed 0 and the gate rejected
    ``risk_reward`` + ``stop_loss`` — exactly the live production failure.
    """
    gate = _ApproveGate()
    pipeline = TradingPipeline(
        supervisor=_bearish_supervisor(), risk_gate=gate, execution_engine=None
    )

    context = {
        "symbol": "XAUUSD",
        "account_state": {"equity": 10000.0, "balance": 10000.0},
        "current_positions": [],
        "market_info": {"bid": 4333.3, "ask": 4333.44, "spread_pips": 0.14},
        # Object state (no dict access) + ATR ONLY in the volatility block.
        "market_state": _MarketStateObject(close=4333.37, atr=3.05),
        "volatility": {"atr": 3.05, "price": 4333.37},
    }

    pipeline.run({"event_type": "MOMENTUM_BEARISH", "symbol": "XAUUSD"}, context)

    assert gate.seen is not None
    assert gate.seen["entry_price"] > 0
    assert gate.seen["stop_loss"] > 0
    assert gate.seen["take_profit"] > 0


def test_run_validation_uses_merged_snapshot_evidence():
    """A snapshot attached to the event must reach the gate's completion step.

    Regression: ``run()`` passed the RAW caller context to
    ``_build_validation_inputs`` — the merged snapshot (ATR/volatility) only
    lived in ``analysis_context``, so completion ran blind. Here the caller
    context has NO ATR at all; only the event snapshot carries it.
    """
    gate = _ApproveGate()
    pipeline = TradingPipeline(
        supervisor=_bearish_supervisor(), risk_gate=gate, execution_engine=None
    )

    context = {
        "symbol": "XAUUSD",
        "account_state": {"equity": 10000.0, "balance": 10000.0},
        "current_positions": [],
        "market_info": {"bid": 4333.3, "ask": 4333.44, "spread_pips": 0.14},
    }
    event = {
        "event_type": "MOMENTUM_BEARISH",
        "symbol": "XAUUSD",
        "market_snapshot": {
            "symbol": "XAUUSD",
            "market_state": _MarketStateObject(close=4333.37, atr=3.05),
            "volatility": {"atr": 3.05, "price": 4333.37},
        },
    }

    pipeline.run(event, context)

    assert gate.seen is not None
    assert gate.seen["entry_price"] > 0
    assert gate.seen["stop_loss"] > 0, "snapshot ATR must complete SL via the gate inputs"


# ---------------------------------------------------------------------------
# Arm-gated native send
# ---------------------------------------------------------------------------
def test_native_send_requires_armed_terminal():
    """With native MT5 importable but no armed terminal, send is fail-closed."""
    # Ensure the real MetaTrader5 is importable (Windows); skip otherwise.
    pytest.importorskip("MetaTrader5")

    engine = ExecutionEngine(mt5_connector=None, simulation_mode=True, require_approval=True)
    req = OrderRequest(
        symbol="EURUSD",
        order_type="BUY",
        volume=0.1,
        approval_token="gate:test",
    )

    result = engine.execute_order(req)

    # Nothing armed → blocked with an explicit, honest error (not a fake fill).
    assert result.success is False
    assert result.error_code == 403
    assert "ARMED" in result.error_message.upper()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
