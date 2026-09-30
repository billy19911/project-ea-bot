# -*- coding: utf-8 -*-
"""Phase 4 — entry safety tests (§30–§36, §50, TEST 8/9/18–20 + invariants)."""

from __future__ import annotations

import pytest

from src.agents.roles import EntryRole
from src.risk.base import RiskThreshold
from src.risk.engine import RiskEngine
from src.risk.gate import RiskGate
from src.risk.money_management import MoneyManager
from src.trading.trigger_engine import evaluate_triggers


def _gate() -> RiskGate:
    eng = RiskEngine()
    eng.set_threshold(RiskThreshold.MAX_DRAWDOWN, 0.2)
    eng.set_threshold(RiskThreshold.DAILY_LOSS_LIMIT, 0.1)
    eng.set_threshold(RiskThreshold.MAX_POSITIONS, 5)
    eng.set_threshold(RiskThreshold.MAX_EXPOSURE, 0.3)
    return RiskGate(eng, MoneyManager(), max_spread_pips=5.0)


def _acct() -> dict:
    return {
        "equity": 10_000.0,
        "balance": 10_000.0,
        "peak_equity": 10_000.0,
        "daily_pnl": 0.0,
        "used_margin": 0.0,
        "margin_call_level": 500.0,
    }


# TEST 8 — wide spread blocks even a confirmed trigger.
def test_wide_spread_blocks_trigger():
    r = evaluate_triggers(
        direction="LONG",
        zone_top=10.3,
        zone_bottom=10.2,
        opens=[10.4, 10.45, 10.5],
        highs=[10.5, 10.55, 10.7],
        lows=[10.3, 10.35, 10.15],
        closes=[10.42, 10.5, 10.6],
        atr=0.2,
        is_closed=True,
        spread_atr=1.0,  # 1.0 ATR > 0.25 max
    )
    assert "spread_too_wide" in r.blocking


# TEST 9 — stale/inverted spread data blocks at the gate.
def test_stale_spread_blocks_at_gate():
    gate = _gate()
    d = gate.validate_proposal(
        {
            "symbol": "EURUSD",
            "direction": "BUY",
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "take_profit": 115.0,
            "size": 0.1,
        },
        _acct(),
        [],
        {},  # empty market_info → spread unknown
    )
    assert d.checks_passed["spread"] is False
    assert d.approved is False


# TEST 18 / INVARIANT F — AI cannot force ENTRY_READY.
def test_ai_cannot_force_entry_ready():
    out = EntryRole().analyze(
        {
            "setup": {"direction": "BUY", "missing_conditions": []},
            "trigger_confirmed": True,  # AI asserts ready...
            "trigger_result": {  # ...but deterministic engine says otherwise.
                "conditions_met": {
                    "zone_touch": True,
                    "rejection": False,
                    "micro_bos": False,
                    "candle_close": True,
                },
                "blocking": [],
            },
            "required_triggers": ("zone_touch", "rejection", "micro_bos"),
        }
    )
    assert out.signal == "WAIT_TRIGGER"
    assert "micro_bos" in out.role_specific["missing_triggers"]


# TEST 19 / INVARIANT H — RiskGate rejects even ENTRY_READY.
def test_risk_gate_rejects_ready_entry():
    gate = _gate()
    d = gate.validate_proposal(
        {
            "symbol": "EURUSD",
            "direction": "BUY",
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "take_profit": 115.0,
            "size": 500.0,
        },
        _acct(),
        [],
        {"spread_pips": 1.0, "bid": 100.0, "ask": 100.0, "price": 100.0},
    )
    assert d.approved is False


# TEST 20 — final volume stays deterministic.
def test_ai_volume_never_authoritative():
    from src.orchestration.pipeline import TradingPipeline

    pipe = TradingPipeline(supervisor=None, risk_gate=None, execution_engine=None)
    pipe.max_lot_per_trade = 0.05
    proposal = {"symbol": "EURUSD", "size": 25.0}
    pipe._cap_lot(proposal)
    assert proposal["size"] == 0.05


# INVARIANT A/D — zone touch ≠ entry; stale trigger ≠ entry.
def test_entry_role_reports_wait_on_touch_only():
    out = EntryRole().analyze(
        {"setup": {"direction": "BUY", "missing_conditions": []}, "zone_touched": True}
    )
    assert out.signal == "WAIT_TRIGGER"


def test_trigger_result_without_zone_touch_not_ready():
    out = EntryRole().analyze(
        {
            "setup": {"direction": "BUY", "missing_conditions": []},
            "trigger_result": {
                "conditions_met": {"zone_touch": False, "rejection": True},
                "blocking": [],
            },
            "required_triggers": ("zone_touch", "rejection"),
        }
    )
    assert out.signal == "WAIT_TRIGGER"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
