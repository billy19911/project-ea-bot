# -*- coding: utf-8 -*-
"""Tests for risk-% sizing, the lot cap, and the one-entry policy (FOKUS #3).

* Force sizing — ``force_risk_sizing=True`` recomputes the lot from the risk-%
  knob (equity 10 000 · 1% · SL distance 10 · point 0.01 · contract 100 →
  0.10 lot), then caps it via ``max_lot_per_trade``.
* Default mode — a proposal that already carries a size keeps it verbatim.
* Single-entry — while one of OUR positions (magic) is open the cycle is
  BLOCKED and the execution engine is never reached.
* Settings — the new knobs exist and ``_apply_to_runtime`` pushes them into
  the live pipeline.
* ``agent_results`` / ``supervisor_summary`` surface on the serialised result.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from risk.gate import GateDecision  # noqa: E402
from src.orchestration.pipeline import TradingPipeline  # noqa: E402
from src.system.settings_store import KNOBS  # noqa: E402


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------
class _FullSupervisor:
    """Supervisor stub returning a fully specified BUY proposal."""

    def __init__(self, size: float = 0.42) -> None:
        self.size = size

    def analyze(self, context):
        return {
            "overall_signal": "BUY",
            "overall_confidence": 0.9,
            "agent_results": {"technical": {"signal": "BUY", "confidence": 0.9}},
            "summary": "committee agrees",
            "proposal": {
                "symbol": "EURUSD",
                "direction": "BUY",
                "entry_price": 100.0,
                "stop_loss": 90.0,  # SL distance 10
                "take_profit": 110.0,
                "size": self.size,
                "risk_pct": 0.0,
            },
        }


class _ApproveGate:
    def __init__(self) -> None:
        self.seen = None

    def validate_proposal(
        self, proposal, account_state, current_positions, market_info
    ):
        self.seen = proposal
        return GateDecision(
            approved=True, reason="ok", checks_passed={}, metrics_snapshot={}
        )


class _RecordingEngine:
    def __init__(self) -> None:
        self.calls: list = []

    def execute_order(self, request):
        self.calls.append(request)

        class _Result:
            success = True
            ticket = 424242
            error_code = 0
            error_message = ""
            retries = 0
            position_opened = None

        return _Result()


def _context(**extra) -> dict:
    base = {
        "event_type": "BREAKOUT",
        "symbol": "EURUSD",
        "account_state": {
            "equity": 10_000.0,
            "balance": 10_000.0,
            "peak_equity": 10_000.0,
            "daily_pnl": 0.0,
            "used_margin": 0.0,
        },
        "current_positions": [],
        "market_info": {"spread_pips": 1.0, "point_value": 0.01, "contract_size": 100},
        "volatility": {"price": 100.0, "atr": 2.0},
    }
    base.update(extra)
    return base


def _pipeline(**kwargs) -> tuple[TradingPipeline, _ApproveGate, _RecordingEngine]:
    gate = _ApproveGate()
    engine = _RecordingEngine()
    pipeline = TradingPipeline(
        supervisor=_FullSupervisor(),
        risk_gate=gate,
        execution_engine=engine,
        **kwargs,
    )
    return pipeline, gate, engine


# ---------------------------------------------------------------------------
# Force risk-% sizing + lot cap
# ---------------------------------------------------------------------------
def test_force_risk_sizing_computes_lot_from_risk_pct() -> None:
    """equity 10 000 · 1% risk · SL 10 / point 0.01 · contract 100 → 0.10 lot."""
    pipeline, gate, _ = _pipeline(
        force_risk_sizing=True,
        default_risk_pct=1.0,  # UI knob unit: percent (1.0 = 1%)
        max_lot_per_trade=1.0,
    )
    pipeline.run({"event_type": "BREAKOUT", "symbol": "EURUSD"}, _context())

    assert gate.seen is not None
    assert gate.seen["size"] == 0.10
    assert gate.seen["risk_pct"] == 0.01


def test_force_risk_sizing_respects_lot_cap() -> None:
    pipeline, gate, _ = _pipeline(
        force_risk_sizing=True,
        default_risk_pct=1.0,
        max_lot_per_trade=0.05,
    )
    pipeline.run({"event_type": "BREAKOUT", "symbol": "EURUSD"}, _context())

    assert gate.seen is not None
    assert gate.seen["size"] == 0.05


def test_default_mode_never_overrides_provided_size() -> None:
    pipeline, gate, _ = _pipeline(force_risk_sizing=False, default_risk_pct=1.0)
    pipeline.run({"event_type": "BREAKOUT", "symbol": "EURUSD"}, _context())

    assert gate.seen is not None
    assert gate.seen["size"] == 0.42


# ---------------------------------------------------------------------------
# One-entry policy
# ---------------------------------------------------------------------------
def test_single_entry_blocks_when_own_position_open() -> None:
    pipeline, _, engine = _pipeline(single_entry_policy=True, entry_magic=70000)
    context = _context(
        current_positions=[{"ticket": 555, "symbol": "EURUSD", "magic": 70000}]
    )

    result = pipeline.run({"event_type": "BREAKOUT", "symbol": "EURUSD"}, context)

    assert result.status == "BLOCKED"
    assert "satu entry" in result.risk_reason
    assert "#555" in result.risk_reason
    stages = {(s["stage"], s["status"]) for s in result.trace}
    assert ("single_entry", "BLOCKED") in stages
    assert ("execution", "SKIPPED") in stages
    assert engine.calls == []  # execution never reached


def test_single_entry_allows_foreign_magic() -> None:
    pipeline, _, engine = _pipeline(single_entry_policy=True, entry_magic=70000)
    context = _context(
        current_positions=[{"ticket": 777, "symbol": "EURUSD", "magic": 999999}]
    )

    result = pipeline.run({"event_type": "BREAKOUT", "symbol": "EURUSD"}, context)

    assert result.status == "EXECUTED"
    assert len(engine.calls) == 1


def test_single_entry_off_executes_normally() -> None:
    pipeline, _, engine = _pipeline(single_entry_policy=False, entry_magic=70000)
    context = _context(
        current_positions=[{"ticket": 555, "symbol": "EURUSD", "magic": 70000}]
    )

    result = pipeline.run({"event_type": "BREAKOUT", "symbol": "EURUSD"}, context)

    assert result.status == "EXECUTED"
    assert len(engine.calls) == 1


# ---------------------------------------------------------------------------
# Settings knobs reach the live pipeline
# ---------------------------------------------------------------------------
def test_new_knobs_exist() -> None:
    keys = {k.key for k in KNOBS}
    assert "risk_per_trade_pct" in keys
    assert "max_lot_per_trade" in keys


def test_apply_to_runtime_pushes_risk_and_lot_knobs() -> None:
    from src.orchestration.runtime import get_runtime
    from src.system.endpoints import _apply_to_runtime

    runtime = get_runtime()
    original_risk = runtime.pipeline.default_risk_pct
    original_lot = runtime.pipeline.max_lot_per_trade
    try:
        pushed = _apply_to_runtime(
            {"risk_per_trade_pct": 2.0, "max_lot_per_trade": 0.2}
        )
        assert pushed["risk_per_trade_pct"] == 2.0
        assert pushed["max_lot_per_trade"] == 0.2
        assert runtime.pipeline.default_risk_pct == 2.0
        assert runtime.pipeline.max_lot_per_trade == 0.2
    finally:
        runtime.pipeline.default_risk_pct = original_risk
        runtime.pipeline.max_lot_per_trade = original_lot


# ---------------------------------------------------------------------------
# agent_results / supervisor_summary surface on the result
# ---------------------------------------------------------------------------
def test_agent_results_surface_on_result() -> None:
    pipeline, _, _ = _pipeline()
    result = pipeline.run({"event_type": "BREAKOUT", "symbol": "EURUSD"}, _context())

    payload = result.to_dict()
    assert payload["agent_results"] == {
        "technical": {"signal": "BUY", "confidence": 0.9}
    }
    assert payload["supervisor_summary"] == "committee agrees"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
