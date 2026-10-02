# -*- coding: utf-8 -*-
"""Phase 7 — Observability IDs + dashboard explainability acceptance tests.

* Every decision cycle must carry the full correlation chain:
  trace_id, market_event_id, analysis_id, setup_id, decision_id,
  risk_decision_id, execution_id, position_id, review_id.
* The dashboard trace must explain WHY entered / WHY not, surfacing committee
  evidence, conflicts, challenge result, setup/trigger, risk calc, execution
  result, and the position timeline.
* Missing data is UNKNOWN — never fabricated.
"""

from __future__ import annotations

import importlib
import types

import pytest

pipeline_mod = importlib.import_module("orchestration.pipeline")
ops_trace = importlib.import_module("ops.trace")

PHASE7_IDS = (
    "trace_id",
    "market_event_id",
    "analysis_id",
    "setup_id",
    "decision_id",
    "risk_decision_id",
    "execution_id",
    "position_id",
    "review_id",
)


class _StubSupervisor:
    def analyze(self, context):
        return {
            "overall_confidence": 0.9,
            "summary": "stub",
            "agent_results": {
                "structure_analyst": {
                    "signal": "BULLISH",
                    "confidence": 0.8,
                    "domain": "structure",
                },
                "momentum_analyst": {"signal": "BULLISH", "confidence": 0.7, "domain": "momentum"},
            },
            "proposal": {
                "symbol": "XAUUSD",
                "direction": "BUY",
                "confidence": 0.9,
                "entry_price": 2500.0,
                "stop_loss": 2495.0,
                "take_profit": 2510.0,
                "size": 0.1,
            },
        }


class _FakeEngine:
    def execute_order(self, request):
        return types.SimpleNamespace(success=True, ticket=555, error_code=0, error_message="")


def _gate():
    from risk import MoneyManager, RiskEngine, RiskGate
    from risk.base import RiskThreshold

    engine = RiskEngine()
    engine.set_threshold(RiskThreshold.MAX_EXPOSURE, 0.9)
    engine.set_threshold(RiskThreshold.MAX_POSITION_SIZE, 0.9)
    return RiskGate(engine, MoneyManager(), max_spread_pips=50_000.0, min_rr=1.0)


def _run():
    pipe = pipeline_mod.TradingPipeline(
        supervisor=_StubSupervisor(),
        risk_gate=_gate(),
        execution_engine=_FakeEngine(),
        single_entry_policy=False,
        max_lot_per_trade=1.0,
        force_risk_sizing=False,
    )
    return pipe.run(
        {"event_id": "evt-1", "event_type": "TREND_BULLISH"},
        {
            "symbol": "XAUUSD",
            "account_state": {
                "equity": 10_000.0,
                "balance": 10_000.0,
                "peak_equity": 10_000.0,
                "daily_pnl": 0.0,
                "used_margin": 0.0,
            },
            "current_positions": [],
            "market_info": {
                "spread_pips": 1.0,
                "contract_size": 1.0,
                "bid": 2500.0,
                "ask": 2500.1,
            },
        },
    )


# ── correlation chain ──────────────────────────────────────────────────
def test_phase7_id_chain_is_present_on_result() -> None:
    result = _run()
    payload = result.to_dict()
    assert "correlation" in payload, "result must expose a correlation id block"
    correlation = payload["correlation"]
    for key in PHASE7_IDS:
        assert key in correlation, f"missing correlation id: {key}"


def test_core_ids_are_populated_on_a_trade() -> None:
    result = _run()
    correlation = result.to_dict()["correlation"]
    assert correlation["trace_id"]
    assert correlation["market_event_id"] == "evt-1"
    assert correlation["decision_id"]
    assert correlation["risk_decision_id"]
    assert correlation["execution_id"]
    assert correlation["analysis_id"]


def test_missing_ids_are_unknown_not_fabricated() -> None:
    result = _run()
    correlation = result.to_dict()["correlation"]
    # review/position happen downstream — here they must be UNKNOWN, not invented.
    assert correlation["review_id"] in ("", "UNKNOWN")


# ── dashboard explainability ───────────────────────────────────────────
def test_decision_trace_exposes_why_fields() -> None:
    trace = ops_trace.decision_trace(decision_id="nonexistent")
    for key in ("key", "nodes", "complete"):
        assert key in trace


def test_explain_non_trade_exposes_blocking_and_reason() -> None:
    explanation = ops_trace.explain_non_trade(setup_id="nonexistent")
    for key in ("state", "blocking_conditions", "missing_conditions", "reason_codes"):
        assert key in explanation


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
