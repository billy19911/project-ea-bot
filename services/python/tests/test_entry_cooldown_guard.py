# -*- coding: utf-8 -*-
"""Tests for the entry-cooldown + price-distance guards in TradingPipeline.

The user complaint (msg 130191): after a position closes, the very next event
opened a new entry at almost the same price — "masa tiap 2 mnt muncul entry
baru trs padahal jarak untuk entry nya selisih sedikit". These guards add:

1. an entry COOLDOWN between successive entries for the same symbol; and
2. a price-DISTANCE guard (relative to ATR) versus the last entry price.

Both guards are DISABLED by default (0.0) so existing callers/tests are
unaffected. Fail-open: any exception inside a guard is swallowed and never
blocks the cycle.

Fakes mirror ``test_pipeline_orchestration.py`` (the simplest setup that
produces an EXECUTED cycle).
"""

from __future__ import annotations

from orchestration.pipeline import STAGE_BLOCKED, STATUS_BLOCKED, STATUS_EXECUTED, TradingPipeline
from risk.gate import GateDecision


# ---------------------------------------------------------------------------
# Fakes / stubs (reused from test_pipeline_orchestration.py)
# ---------------------------------------------------------------------------
class FakeSupervisor:
    def __init__(self, result=None, exc: Exception | None = None) -> None:
        self._result = result
        self._exc = exc

    def analyze(self, context):
        if self._exc is not None:
            raise self._exc
        return self._result


class FakeRiskGate:
    def __init__(self, decision: GateDecision | None = None) -> None:
        self._decision = decision

    def validate_proposal(self, proposal, account_state, current_positions, market_info):
        return self._decision


class FakeExecutionEngine:
    def __init__(self, result=None) -> None:
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
    position_opened = {"symbol": "EURUSD", "positions_count": 1}


def _approved() -> GateDecision:
    return GateDecision(
        approved=True,
        reason="All risk checks passed",
        checks_passed={"stop_loss": True},
        metrics_snapshot={"risk_reward_ratio": 2.0},
    )


def _synthesis(symbol="EURUSD", direction="BUY", entry=1.1000):
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
            "stop_loss": entry - 0.0050,
            "take_profit": entry + 0.0100,
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


def _context(symbol="EURUSD", atr=0.0):
    context = {
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
    if atr:
        context["atr"] = atr
    return context


def _pipeline(entry_cooldown_s=0.0, entry_min_distance_atr=0.0) -> TradingPipeline:
    # The pending-signal gate (FOKUS #2) intentionally supersedes the cooldown
    # guard: after a successful entry the symbol is OPEN and no further cycle
    # runs. These tests target the cooldown guard in isolation, so the gate is
    # disabled here. The gate itself is covered by test_signal_registry.py and
    # test_pending_signal_gate.py.
    return TradingPipeline(
        supervisor=FakeSupervisor(_synthesis()),
        risk_gate=FakeRiskGate(_approved()),
        execution_engine=FakeExecutionEngine(_ExecResult()),
        entry_cooldown_s=entry_cooldown_s,
        entry_min_distance_atr=entry_min_distance_atr,
        pending_signal_guard=False,
    )


def _run(pipeline, symbol="EURUSD", entry=1.1000, atr=0.0):
    """Run one cycle with a fresh synthesis/event for the given entry price."""
    pipeline.supervisor = FakeSupervisor(_synthesis(symbol=symbol, entry=entry))
    return pipeline.run(_event(symbol), _context(symbol, atr=atr))


def _stage(result, name):
    for entry in result.trace:
        if entry.get("stage") == name:
            return entry
    return None


# ---------------------------------------------------------------------------
# 1. Cooldown active
# ---------------------------------------------------------------------------
def test_cooldown_active_blocks_second_entry():
    pipeline = _pipeline(entry_cooldown_s=900.0)

    first = _run(pipeline)
    assert first.status == STATUS_EXECUTED
    assert "EURUSD" in pipeline._last_entries

    second = _run(pipeline)
    assert second.status == STATUS_BLOCKED
    stage = _stage(second, "entry_cooldown")
    assert stage is not None
    assert stage["status"] == STAGE_BLOCKED
    assert stage["detail"]


# ---------------------------------------------------------------------------
# 2. Cooldown elapsed
# ---------------------------------------------------------------------------
def test_cooldown_elapsed_proceeds():
    pipeline = _pipeline(entry_cooldown_s=900.0)

    first = _run(pipeline)
    assert first.status == STATUS_EXECUTED

    # Backdate the recorded entry so the cooldown has clearly elapsed.
    pipeline._last_entries["EURUSD"]["ts"] -= 3600.0

    second = _run(pipeline)
    assert second.status == STATUS_EXECUTED


# ---------------------------------------------------------------------------
# 3. Distance guard — too close
# ---------------------------------------------------------------------------
def test_distance_guard_blocks_too_close():
    # k = 2.0 ATR, ATR = 0.0100 -> min distance 0.0200; move only 0.0010.
    pipeline = _pipeline(entry_cooldown_s=900.0, entry_min_distance_atr=2.0)
    pipeline._last_entries["EURUSD"] = {"price": 1.1000, "ts": 0.0}

    result = _run(pipeline, entry=1.1010, atr=0.0100)

    assert result.status == STATUS_BLOCKED
    stage = _stage(result, "entry_cooldown")
    assert stage is not None
    assert "jarak" in stage["detail"].lower() or "distance" in stage["detail"].lower()


# ---------------------------------------------------------------------------
# 4. Distance guard — far enough
# ---------------------------------------------------------------------------
def test_distance_guard_allows_far_enough():
    # k = 2.0 ATR, ATR = 0.0100 -> min distance 0.0200; move 0.0300.
    pipeline = _pipeline(entry_cooldown_s=900.0, entry_min_distance_atr=2.0)
    pipeline._last_entries["EURUSD"] = {"price": 1.1000, "ts": 0.0}

    result = _run(pipeline, entry=1.1300, atr=0.0100)

    assert result.status == STATUS_EXECUTED


# ---------------------------------------------------------------------------
# 5. Defaults (disabled) — never blocks
# ---------------------------------------------------------------------------
def test_defaults_disabled_never_block():
    pipeline = _pipeline()  # 0.0 / 0.0 -> both guards off

    first = _run(pipeline)
    second = _run(pipeline)

    assert first.status == STATUS_EXECUTED
    assert second.status == STATUS_EXECUTED


# ---------------------------------------------------------------------------
# 6. ATR unavailable — distance skipped, cooldown still enforced
# ---------------------------------------------------------------------------
def test_atr_unavailable_skips_distance_but_enforces_cooldown():
    pipeline = _pipeline(entry_cooldown_s=900.0, entry_min_distance_atr=2.0)

    first = _run(pipeline, entry=1.1000, atr=0.0)
    assert first.status == STATUS_EXECUTED

    # Same/close price but no ATR: distance check must be skipped, yet the
    # time cooldown still blocks the immediate second entry (no crash).
    second = _run(pipeline, entry=1.1001, atr=0.0)
    assert second.status == STATUS_BLOCKED
    assert _stage(second, "entry_cooldown") is not None


def test_atr_unavailable_no_crash_when_cooldown_off():
    pipeline = _pipeline(entry_cooldown_s=0.0, entry_min_distance_atr=2.0)

    first = _run(pipeline, entry=1.1000, atr=0.0)
    second = _run(pipeline, entry=1.1001, atr=0.0)

    assert first.status == STATUS_EXECUTED
    assert second.status == STATUS_EXECUTED
