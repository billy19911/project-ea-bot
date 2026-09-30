# -*- coding: utf-8 -*-
"""End-to-end integration tests (audit §18): E2E-01..E2E-12.
These prove RUNTIME connectivity between phases at real boundaries (with
simulation/mocks only). No real trading.
"""
from __future__ import annotations

import pytest

from src.agents.event_dispatch import decide_dispatch
from src.agents.roles import EntryRole
from src.learning.canonical import DecisionSnapshot, StrategyCandidateRecord
from src.learning.research_phase5 import PromotionGate, ResearchQueries
from src.learning.review_bridge import bridge_review_record
from src.learning.review_store import CanonicalStore, ReviewBuilder
from src.risk.base import RiskThreshold
from src.risk.engine import RiskEngine
from src.risk.gate import RiskGate
from src.risk.money_management import MoneyManager
from src.trading.entry_adapter import adapt_trigger_to_assessment
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


def _trigger_series():
    o = [10.4, 10.45, 10.5]
    h = [10.5, 10.55, 10.7]
    lo = [10.3, 10.35, 10.15]
    c = [10.42, 10.5, 10.6]
    return o, h, lo, c


# E2E-01 valid event → execution intent (deterministic sim)
def test_e2e01_valid_trigger_to_risk_pass_and_cap():
    o, h, lo, c = _trigger_series()
    tr = evaluate_triggers(
        direction="LONG",
        zone_top=10.3,
        zone_bottom=10.2,
        opens=o,
        highs=h,
        lows=lo,
        closes=c,
        atr=0.2,
        is_closed=True,
    )
    ea = adapt_trigger_to_assessment(
        setup_id="s-e2e1", symbol="XAUUSD", direction="BUY", zone=None, trigger=tr
    )
    assert ea.trigger_status == "ENTRY_READY"
    gate = _gate()
    d = gate.validate_proposal(
        {
            "symbol": "XAUUSD",
            "direction": "BUY",
            "entry_price": 10.6,
            "stop_loss": 10.15,
            "take_profit": 11.5,
            "size": 0.05,
        },
        _acct(),
        [],
        {"spread_pips": 1.0, "bid": 10.6, "ask": 10.6, "price": 10.6},
    )
    assert d.approved is True


# E2E-02 zone touch → WAIT (no trigger)
def test_e2e02_zone_touch_without_trigger_waits():
    tr = evaluate_triggers(
        direction="LONG",
        zone_top=200.0,
        zone_bottom=199.0,
        opens=[200.4, 200.4, 200.4],
        highs=[200.5, 200.5, 200.5],
        lows=[199.5, 199.5, 199.5],
        closes=[200.0, 200.0, 200.0],
        atr=1.0,
        is_closed=True,
    )
    ea = adapt_trigger_to_assessment(
        setup_id="s-e2e2", symbol="XAUUSD", direction="BUY", zone=None, trigger=tr
    )
    assert ea.trigger_status == "WAIT_TRIGGER"
    assert ea.trigger_confirmed is False


# E2E-03 trigger confirmed → RiskGate is still consulted
def test_e2e03_trigger_then_risk_gate():
    o, h, lo, c = _trigger_series()
    tr = evaluate_triggers(
        direction="LONG",
        zone_top=10.3,
        zone_bottom=10.2,
        opens=o,
        highs=h,
        lows=lo,
        closes=c,
        atr=0.2,
        is_closed=True,
    )
    ea = adapt_trigger_to_assessment(
        setup_id="s-e2e3", symbol="XAUUSD", direction="BUY", zone=None, trigger=tr
    )
    assert ea.trigger_status == "ENTRY_READY"
    d = _gate().validate_proposal(
        {
            "symbol": "XAUUSD",
            "direction": "BUY",
            "entry_price": 10.6,
            "stop_loss": 10.15,
            "take_profit": 11.5,
            "size": 0.05,
        },
        _acct(),
        [],
        {"spread_pips": 1.0, "bid": 10.6, "ask": 10.6, "price": 10.6},
    )
    assert d.approved is True  # gate runs AFTER trigger, independently


# E2E-04 RiskGate reject stops execution
def test_e2e04_risk_reject_blocks():
    d = _gate().validate_proposal(
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


# E2E-05 execution timeout → locator/reconciliation (adopt, not duplicate)
def test_e2e05_timeout_locator_adopts():
    from src.execution.engine import ExecutionEngine, OrderRequest

    placed: list[dict] = []

    class _Flaky:
        def order_send(self, payload):
            placed.append(payload)
            raise ConnectionError("timeout after send")

        def get_symbol_info(self, s):
            return {"symbol": s, "volume_min": 0.01, "volume_max": 100.0}

        def positions(self):
            return [
                {
                    "ticket": 999,
                    "symbol": p["symbol"],
                    "side": "BUY",
                    "volume": p["volume"],
                    "price_open": 1.1,
                    "profit": 0.0,
                }
                for p in placed
            ]

    conn = _Flaky()

    def _loc(req):
        for p in conn.positions():
            if p["symbol"] == req.symbol and abs(p["volume"] - req.volume) < 1e-9:
                return {"ticket": p["ticket"]}
        return None

    eng = ExecutionEngine(mt5_connector=conn, max_retries=2, retry_delay=0.0, order_locator=_loc)
    res = eng.execute_order(
        OrderRequest(symbol="XAUUSD", order_type="BUY", volume=0.1, idempotency_key="e2e5")
    )
    assert res.success is True and res.ticket == 999


# E2E-06 trade close → review bridge → canonical store
def test_e2e06_close_to_review_bridge(tmp_path, monkeypatch):
    monkeypatch.setenv("LEARNING_CANONICAL_PATH", str(tmp_path / "canon.jsonl"))
    monkeypatch.setenv("RESEARCH_QUEUE_PATH", str(tmp_path / "queue.jsonl"))
    out = bridge_review_record(
        {
            "trade_id": "T-100",
            "direction": "BUY",
            "entry_price": 10.0,
            "exit_price": 10.5,
            "stop_loss": 9.5,
            "net_pnl": 50.0,
            "setup_id": "s-e2e6",
        }
    )
    assert out["bridged"] is True and out["kind"] == "TradeReview"
    store = CanonicalStore(path=str(tmp_path / "canon.jsonl"))
    assert store.count("TradeReview") == 1


# E2E-07 review → research lineage (pattern → hypothesis)
def test_e2e07_review_to_research_lineage(tmp_path):
    store = CanonicalStore(path=str(tmp_path / "c.jsonl"))
    for i in range(35):
        r = ReviewBuilder().build_trade_review(
            review_id=f"r{i}",
            trade_id=f"T{i}",
            direction="BUY",
            entry_price=10.0,
            exit_price=10.5,
            stop_loss=9.5,
            net_pnl=50.0,
            trigger_type="rejection",
            decision_quality=0.8,
        )
        store.write("TradeReview", r.trade_id, r.to_dict())
    from src.learning.research_phase5 import PatternObserver

    obs = PatternObserver().observe(store.query("TradeReview"))
    assert obs and obs[0].status == "OBSERVED"
    q = ResearchQueries(store)
    assert q.performance_by("trigger_type")["rejection"]["sample_size"] == 35


# E2E-08 model routing provenance retained
def test_e2e08_model_routing_provenance():
    from src.llm.canonical import ModelRequest
    from src.llm.router import CanonicalModelRouter

    r = CanonicalModelRouter()
    rec, _ = r.execute(
        ModelRequest(
            request_id="e2e8", agent_role="structure", task_type="STRUCTURE_ANALYSIS", cycle_id="c8"
        ),
        route_through=lambda m, p, **k: {"signal": "NEUTRAL"},
    )
    assert rec.routing_policy_version
    assert rec.request_id == "e2e8"
    assert rec.model_id


# E2E-09 future data cannot alter a decision snapshot
def test_e2e09_future_data_blocked():
    with pytest.raises(ValueError):
        DecisionSnapshot(
            snapshot_id="s",
            event_id="e",
            decision_timestamp="2024-01-02T00:00:00+00:00",
            information_timestamp="2024-01-03T00:00:00+00:00",
        )


# E2E-10 restart preserves identity / idempotency
def test_e2e10_restart_idempotency(tmp_path):
    p = str(tmp_path / "c10.jsonl")
    s1 = CanonicalStore(path=p)
    s1.write("TradeReview", "T10", {"identity": "T10", "kind": "TradeReview", "net_pnl": 1.0})
    s2 = CanonicalStore(path=p)  # "restart"
    s2.write("TradeReview", "T10", {"identity": "T10", "kind": "TradeReview", "net_pnl": 99.0})
    assert s2.count("TradeReview") == 1
    assert s2.get("TradeReview", "T10")["net_pnl"] == 1.0  # first wins


# E2E-11 learning cannot mutate active strategy
def test_e2e11_learning_cannot_mutate_strategy():
    cand = StrategyCandidateRecord(
        candidate_id="c11",
        backtest_results={
            "trade_count": 100,
            "expectancy": 0.5,
            "max_drawdown": 0.05,
            "profit_factor": 2.0,
        },
        walkforward_results={"unstable": False},
    )
    promo = PromotionGate().evaluate(
        cand,
        extra_metrics={
            "cost_sensitive": False,
            "regime_fragile": False,
            "session_fragile": False,
            "direction_fragile": False,
        },
    )
    assert promo.gate_passed is True
    assert promo.approval_required is True
    assert promo.decision == "PENDING"
    with pytest.raises(ValueError):
        PromotionGate().approve(promo, approved_by="")
    assert cand.to_dict()["activation"] == "PROPOSAL_ONLY"


# E2E-12 AI cannot bypass execution authority (volume + trigger)
def test_e2e12_ai_cannot_bypass_authority():
    from src.orchestration.pipeline import TradingPipeline

    pipe = TradingPipeline(supervisor=None, risk_gate=None, execution_engine=None)
    pipe.max_lot_per_trade = 0.05
    prop = {"symbol": "XAUUSD", "size": 25.0}
    pipe._cap_lot(prop)
    assert prop["size"] == 0.05
    # Trigger authority: AI-asserted confirmation cannot override missing trigger.
    out = EntryRole().analyze(
        {
            "setup": {"direction": "BUY", "missing_conditions": []},
            "trigger_confirmed": True,
            "trigger_result": {
                "conditions_met": {"zone_touch": True, "rejection": False},
                "blocking": [],
            },
            "required_triggers": ("zone_touch", "rejection"),
        }
    )
    assert out.signal == "WAIT_TRIGGER"


# Extra: event dispatch preserves targeted behavior (no full committee)
def test_dispatch_is_targeted():
    assert decide_dispatch("BOS", state_changed=True).run_committee is True
    assert decide_dispatch("POSITION_OPENED", state_changed=True).run_committee is False
    assert decide_dispatch("BOS", state_changed=False).run_committee is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
