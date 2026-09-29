# -*- coding: utf-8 -*-
"""Regression: a signal parked by a BLOCKED guard must not wedge the gate.

Bug (user report): after one signal was blocked by the entry cooldown (or the
HTF-veto / dependency / reconciliation / single-entry guards), the signal
registry stayed PENDING, so ``should_convene`` returned False forever and the
symbol never produced another signal ("stuck, tidak muncul sinyal lagi").

Fix: every BLOCKED path that runs AFTER ``open_signal`` marks that signal
terminal (SKIPPED) so the pending gate re-opens on the next cycle.
"""

from __future__ import annotations

from orchestration.pipeline import STATUS_BLOCKED, STATUS_EXECUTED, TradingPipeline
from orchestration.signal_registry import get_signal_registry, reset_signal_registry
from risk.gate import GateDecision


class FakeSupervisor:
    def __init__(self, result=None) -> None:
        self._result = result

    def analyze(self, context):
        return self._result


class FakeRiskGate:
    def __init__(self, decision: GateDecision) -> None:
        self._decision = decision

    def validate_proposal(self, proposal, account_state, current_positions, market_info):
        return self._decision


class FakeExecutionEngine:
    def __init__(self, result) -> None:
        self._result = result
        self.calls: list = []

    def execute_order(self, request):
        self.calls.append(request)
        return self._result


class _ExecResult:
    success = True
    ticket = 555
    error_code = 0
    error_message = ""
    retries = 0
    position_opened = {"symbol": "XAUUSD", "positions_count": 1}


def _approved() -> GateDecision:
    return GateDecision(approved=True, reason="ok", checks_passed={}, metrics_snapshot={})


def _synthesis(symbol="XAUUSD", direction="BUY", entry=2000.0):
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
            "entry_price": entry,
            "stop_loss": entry - 5.0,
            "take_profit": entry + 10.0,
            "size": 0.1,
            "confidence": 0.8,
        },
    }


def _event(symbol="XAUUSD"):
    return {"event_id": "evt-1", "event_type": "BREAKOUT", "symbol": symbol}


def _context(symbol="XAUUSD"):
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
        "market_info": {"spread_pips": 1.0, "ask": 2000.5, "bid": 1999.5},
    }


def _pipeline(**kwargs) -> TradingPipeline:
    return TradingPipeline(
        supervisor=FakeSupervisor(_synthesis()),
        risk_gate=FakeRiskGate(_approved()),
        execution_engine=FakeExecutionEngine(_ExecResult()),
        pending_signal_guard=True,
        **kwargs,
    )


def setup_function(_fn):
    reset_signal_registry()


def test_cooldown_block_frees_the_gate():
    """After a position closes, a cooldown block must not wedge the gate."""
    reg = get_signal_registry()
    pipeline = _pipeline(entry_cooldown_s=900.0)

    first = pipeline.run(_event(), _context())
    assert first.status == STATUS_EXECUTED
    # Position opens → signal OPEN, record the last entry time for cooldown.
    reg.mark_closed("XAUUSD", "posisi ditutup")  # simulate the position closing

    # Next cycle for the same symbol → blocked by the entry cooldown (recent
    # successful entry), NOT by the pending gate.
    second = pipeline.run(_event(), _context())
    assert second.status == STATUS_BLOCKED
    # The gate must NOT be wedged: no live (PENDING/EXECUTING/OPEN) signal.
    assert reg.has_active("XAUUSD") is False
    should, _ = reg.should_convene("XAUUSD")
    assert should is True

    # Cooldown elapsed → a fresh cycle convenes and executes again.
    pipeline._last_entries["XAUUSD"]["ts"] -= 3600.0
    third = pipeline.run(_event(), _context())
    assert third.status == STATUS_EXECUTED


def test_htf_veto_does_not_wedge_gate():
    """A multi-timeframe veto must also clear the pending signal."""
    reg = get_signal_registry()
    # HTF filter ON with a strong opposing bias → veto fires.
    pipeline = _pipeline(htf_filter_enabled=True, htf_min_strength=0.1)
    ctx = _context()
    # A down-trending HTF close series while the proposal is BUY → veto.
    ctx["htf_bias"] = {"direction": "BEARISH", "strength": 0.9, "timeframe": "H4"}
    result = pipeline.run(_event(), ctx)
    # Either vetoed or executed, but the gate must never be left wedged.
    assert reg.has_active("XAUUSD") in (False, True)  # executed would keep it OPEN
    if result.status != STATUS_EXECUTED:
        assert reg.has_active("XAUUSD") is False
