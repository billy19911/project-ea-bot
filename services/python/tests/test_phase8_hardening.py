# -*- coding: utf-8 -*-
"""Phase 8 — operational hardening tests: fault injection, restart,
concurrency, alert storm, bounds, recovery, invariants (§34–§36)."""

from __future__ import annotations

import threading

import pytest

# ── Alert storm control (CASE: 1000 identical alerts) ───────────────────


def test_alert_storm_bounded_history_and_cooldown():
    from src.observability.alerts import AlertManager

    mgr = AlertManager(max_history=50, cooldown_s=3600.0)
    mgr.add_rule("q-depth", "queue_depth", 10.0, comparison="above", severity="warning")
    # 1000 identical breach evaluations while firing → history stays bounded.
    for _ in range(1000):
        mgr.evaluate({"queue_depth": 500.0})
    assert len(mgr.history()) <= 50
    # Flip a resolve then re-breach inside cooldown → suppressed, counted.
    mgr.evaluate({"queue_depth": 1.0})  # resolve
    for _ in range(100):
        mgr.evaluate({"queue_depth": 500.0})
    assert mgr.suppressed_counts().get("q-depth", 0) >= 99


def test_alert_resolve_still_works():
    from src.observability.alerts import AlertManager

    mgr = AlertManager(max_history=50, cooldown_s=0.0)
    mgr.add_rule("r", "m", 10.0, comparison="above", severity="warning")
    assert len(mgr.evaluate({"m": 99.0})) == 1
    assert len(mgr.evaluate({"m": 1.0})) == 1  # resolve event
    assert mgr.active_alerts() == []


# ── Bounded observability stores ─────────────────────────────────────────


def test_metrics_histograms_bounded():
    from src.observability.metrics import MetricsRegistry

    reg = MetricsRegistry()
    for i in range(5000):
        reg.observe("lat", float(i))
    assert len(reg._histograms["lat"][()]) <= MetricsRegistry.MAX_HISTOGRAM_SAMPLES


def test_execution_quality_bounded():
    from src.observability.execution_quality import ExecutionQualityAnalytics, ExecutionRecord

    aq = ExecutionQualityAnalytics()
    aq.max_records = 100
    for i in range(300):
        aq.record(ExecutionRecord(requested_entry=1.0, actual_fill=1.0, direction=1))
    assert len(aq._records) <= 100


def test_slo_samples_bounded():
    from src.monitoring.slo import SLOTracker

    ev = SLOTracker()
    ev.max_samples_per_sli = 50
    for i in range(200):
        ev.record("cycle_latency", float(i))
    assert len(ev._samples["cycle_latency"]) <= 50


# ── CASE A: crash after submit → restart → adopt, no duplicate ───────────


def test_case_a_crash_after_submit_no_duplicate():
    from src.execution.engine import ExecutionEngine, OrderRequest

    placed: list[dict] = []

    class _Flaky:
        def order_send(self, payload):
            placed.append(payload)
            # "connection" keyword → transient → triggers the adopt-before-retry
            # path (mirrors a real lost-response timeout).
            raise ConnectionError("connection lost after send")

        def get_symbol_info(self, s):
            return {"symbol": s, "volume_min": 0.01, "volume_max": 100.0}

        def positions(self):
            return [
                {
                    "ticket": 4242,
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
        OrderRequest(symbol="XAUUSD", order_type="BUY", volume=0.1, idempotency_key="case-a-1")
    )
    assert res.success is True and res.ticket == 4242
    assert len(placed) == 1  # one broker position, adopted on restart-path


# ── CASE D: store corruption → detected, fail-safe ───────────────────────


def test_case_d_corrupt_jsonl_skipped(tmp_path):
    from src.learning.review_store import CanonicalStore

    p = tmp_path / "c.jsonl"
    p.write_text(
        '{"kind": "TradeReview", "identity": "T1", "net_pnl": 1}\n'
        "THIS IS NOT JSON\n"
        '{"kind": "TradeReview", "identity": "T2", "net_pnl": 2}\n',
        encoding="utf-8",
    )
    s = CanonicalStore(path=str(p))
    assert s.count("TradeReview") == 2  # corrupt line skipped, valid kept


def test_case_d_partial_last_record_safe(tmp_path):
    from src.persistence.order_state_store import OrderStateStore

    p = tmp_path / "o.jsonl"
    p.write_text(
        '{"intent_id": "k1", "state": "submitted"}\n{"intent_id": "k2", "sta', encoding="utf-8"
    )
    store = OrderStateStore(path=str(p))
    assert store.get_order("k1") is not None
    assert store.get_order("k2") is None  # partial line never fabricated


# ── CASE E: 100 duplicate TRADE_CLOSE → one review ───────────────────────


def test_case_e_duplicate_close_one_review(tmp_path):
    from src.learning.review_store import CanonicalStore, ReviewBuilder

    store = CanonicalStore(path=str(tmp_path / "e.jsonl"))
    for _ in range(100):
        r = ReviewBuilder().build_trade_review(
            review_id="rev-e",
            trade_id="T-E",
            direction="BUY",
            entry_price=10.0,
            exit_price=10.5,
            stop_loss=9.5,
            net_pnl=5.0,
        )
        store.write("TradeReview", r.trade_id, r.to_dict())
    assert store.count("TradeReview") == 1


# ── CASE F/G: terminal states survive ────────────────────────────────────


def test_case_f_expired_stays_expired():
    from src.trading.entry_lifecycle import EntryLifecycleManager

    mgr = EntryLifecycleManager()
    mgr.register("s-f", "XAUUSD", "LONG", expires_ts=1000.0)
    status, _ = mgr.evaluate_lifecycle("s-f", close_price=10.0, now_ts=2000.0)
    assert status == "EXPIRED"
    status2, _ = mgr.evaluate_lifecycle("s-f", close_price=10.0, now_ts=1500.0)
    assert status2 == "EXPIRED"


def test_case_g_candidate_never_auto_active():
    from src.learning.canonical import StrategyCandidateRecord
    from src.learning.research_phase5 import PromotionGate

    cand = StrategyCandidateRecord(
        candidate_id="g",
        backtest_results={
            "trade_count": 99,
            "expectancy": 0.9,
            "max_drawdown": 0.01,
            "profit_factor": 3.0,
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
    assert promo.decision == "PENDING"
    assert cand.to_dict()["activation"] == "PROPOSAL_ONLY"


# ── CASE I: budget exhaustion + provider outage → safety remains ─────────


def test_case_i_budget_plus_outage_safety_intact():
    from src.llm.canonical import ModelRequest
    from src.llm.router import CanonicalModelRouter

    r = CanonicalModelRouter()
    ledger = r.budget_for_cycle("case-i")
    ledger.max_tokens = 1
    rec, out = r.execute(
        ModelRequest(request_id="ci", task_type="FAST_CLASSIFICATION", cycle_id="case-i"),
        route_through=lambda m, p, **k: (_ for _ in ()).throw(ConnectionError("provider down")),
    )
    assert rec.output_status == "FAILED" and out is None
    # Deterministic safety untouched: gate still validates independently.
    from src.risk.engine import RiskEngine

    eng = RiskEngine()
    assert eng.check_projected_exposure([], {"equity": 10_000.0}, None, 0.3)[0] is True


# ── Invariants: terminal resurrection, future leakage, concurrency ───────


def test_invariant_no_terminal_resurrection():
    from src.trading.signal_state_machine import Signal, SignalState

    s = Signal(signal_id="inv")
    assert s.transition("REJECTED") is True
    assert s.transition("EXECUTING") is False  # terminal stays terminal
    assert s.state == SignalState.REJECTED


def test_invariant_no_future_leakage_in_trigger():
    from src.trading.trigger_engine import evaluate_triggers

    flat_o = [10.0] * 12
    flat = dict(opens=flat_o, highs=[10.2] * 12, lows=[9.8] * 12, closes=[10.0] * 12)
    trunc = evaluate_triggers(
        direction="LONG", zone_top=999, zone_bottom=998, atr=0.5, is_closed=True, **flat
    )
    assert trunc.conditions_met["micro_bos"] is False


def test_invariant_concurrent_claims_once():
    from src.trading.entry_lifecycle import EntryLifecycleManager

    mgr = EntryLifecycleManager()
    mgr.register("s-inv", "XAUUSD", "LONG")
    wins: list[bool] = []
    barrier = threading.Barrier(10)

    def worker():
        barrier.wait()
        wins.append(mgr.claim_entry("s-inv", trigger_id="t", candle_ts=1.0))

    ts = [threading.Thread(target=worker) for _ in range(10)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert wins.count(True) == 1


def test_startup_safety_gate_clamps():
    from src.system.startup_checks import run_startup_safety_gate

    report = run_startup_safety_gate()
    assert "summary" in report and "corrections" in report


def test_execution_recovery_flags_pending(tmp_path, monkeypatch):
    monkeypatch.setenv("ORDER_STATE_PATH", str(tmp_path / "o.jsonl"))
    from src.execution.state_machine import OrderState, reset_store, set_order, set_store
    from src.persistence.order_state_store import OrderStateStore
    from src.system.startup_checks import run_execution_recovery

    reset_store()
    store = OrderStateStore(path=str(tmp_path / "o.jsonl"))
    set_store(store)
    try:
        set_order("rec-1", OrderState.SUBMITTING, {"ticket": 1})
        report = run_execution_recovery()
        assert "rec-1" in report["flagged"]
    finally:
        set_store(None)
        reset_store()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
