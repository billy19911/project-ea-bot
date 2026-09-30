# -*- coding: utf-8 -*-
"""Phase 1 — Risk & Execution Safety acceptance tests.

Covers AUDIT_AND_REFACTOR_PLAN Phase 1 items 1-6:
1. Projected exposure (existing + proposed <= max, real equity source).
2. Max position size enforcement in the Risk Gate.
3. Money-risk sizing honours commission/spread allowances.
4. Symbol-aware spread limits (XAU/BTC/FX).
5. Execution UNKNOWN/adversarial path stays duplicate-safe (order_locator).
6. Persistent idempotency survives a restart (durable ledger).
"""

from __future__ import annotations

import pytest

from execution.engine import ExecutionEngine, OrderRequest
from execution.state_machine import OrderState, reset_store, set_order, set_store
from persistence import OrderStateStore
from risk.base import RiskThreshold
from risk.engine import RiskEngine
from risk.gate import RiskGate
from risk.money_management import MoneyManager

# ── Item #1: projected exposure ─────────────────────────────────────────


def test_projected_exposure_zero_positions() -> None:
    engine = RiskEngine(max_exposure=0.30)
    ok, current, projected = engine.check_projected_exposure(
        positions=[],
        account_state={"equity": 10_000.0},
        proposed_trade={"size": 1.0, "current_price": 100.0},
        max_exposure=0.30,
    )
    assert current == 0.0
    assert projected == pytest.approx(0.01)
    assert ok is True


def test_projected_exposure_single_and_multiple() -> None:
    engine = RiskEngine(max_exposure=0.30)
    existing = [
        {"size": 1.0, "current_price": 100.0},
        {"size": 2.0, "current_price": 100.0},
    ]
    ok, current, projected = engine.check_projected_exposure(
        positions=existing,
        account_state={"equity": 10_000.0},
        proposed_trade={"size": 1.0, "current_price": 100.0},
        max_exposure=0.30,
    )
    assert current == pytest.approx(0.03)
    assert projected == pytest.approx(0.04)
    assert ok is True


def test_projected_exposure_over_limit_rejected() -> None:
    engine = RiskEngine(max_exposure=0.30)
    existing = [{"size": 20.0, "current_price": 100.0}]  # 20% current
    ok, current, projected = engine.check_projected_exposure(
        positions=existing,
        account_state={"equity": 10_000.0},
        proposed_trade={"size": 15.0, "current_price": 100.0},  # +15% → 35%
        max_exposure=0.30,
    )
    assert current == pytest.approx(0.20)
    assert projected == pytest.approx(0.35)
    assert ok is False


def test_projected_exposure_exact_limit_allowed() -> None:
    engine = RiskEngine(max_exposure=0.30)
    existing = [{"size": 20.0, "current_price": 100.0}]
    ok, _, projected = engine.check_projected_exposure(
        positions=existing,
        account_state={"equity": 10_000.0},
        proposed_trade={"size": 10.0, "current_price": 100.0},  # → exactly 30%
        max_exposure=0.30,
    )
    assert projected == pytest.approx(0.30)
    assert ok is True


def test_projected_exposure_invalid_account_rejected() -> None:
    engine = RiskEngine(max_exposure=0.30)
    for bad in ({"equity": 0.0}, {"equity": -5.0}, {}):
        ok, current, projected = engine.check_projected_exposure(
            positions=[],
            account_state=bad,
            proposed_trade={"size": 1.0, "current_price": 100.0},
            max_exposure=0.30,
        )
        assert ok is False
        assert current == 0.0
        assert projected == 0.0


def test_gate_uses_real_equity_not_position_derived() -> None:
    """The gate must use account_state.equity even when positions disagree."""
    gate = RiskGate(RiskEngine(max_exposure=0.30), MoneyManager())
    proposal = {
        "symbol": "EURUSD",
        "direction": "BUY",
        "entry_price": 100.0,
        "stop_loss": 90.0,
        "take_profit": 115.0,
        "size": 1.0,
    }
    # Position claims a fake, huge equity — gate must ignore it and use the
    # real account equity (10k) for the projection.
    positions = [{"size": 1.0, "current_price": 100.0, "account_equity": 1_000_000.0}]
    decision = gate.validate_proposal(
        proposal,
        {
            "equity": 10_000.0,
            "balance": 10_000.0,
            "peak_equity": 10_000.0,
            "daily_pnl": 0.0,
            "used_margin": 0.0,
        },
        positions,
        {"spread_pips": 1.0, "bid": 100.0, "ask": 100.0},
    )
    assert "projected_exposure_pct" in decision.metrics_snapshot
    assert decision.metrics_snapshot["projected_exposure_pct"] == pytest.approx(0.02)


# ── Item #2: max position size ──────────────────────────────────────────


def _base_gate() -> RiskGate:
    engine = RiskEngine()
    engine.set_threshold(RiskThreshold.MAX_DRAWDOWN, 0.2)
    engine.set_threshold(RiskThreshold.DAILY_LOSS_LIMIT, 0.1)
    engine.set_threshold(RiskThreshold.MAX_POSITIONS, 5)
    engine.set_threshold(RiskThreshold.MAX_EXPOSURE, 0.9)
    return RiskGate(engine, MoneyManager(), max_spread_pips=5000.0)


def _safe_account() -> dict:
    return {
        "equity": 10_000.0,
        "balance": 10_000.0,
        "peak_equity": 10_000.0,
        "daily_pnl": 0.0,
        "used_margin": 0.0,
        "margin_call_level": 0.3,
        "free_margin": 9800.0,
    }


def test_gate_rejects_oversize_position() -> None:
    gate = _base_gate()
    decision = gate.validate_proposal(
        {
            "symbol": "EURUSD",
            "direction": "BUY",
            "entry_price": 100.0,
            "stop_loss": 90.0,
            "take_profit": 115.0,
            "size": 50.0,
        },
        _safe_account(),
        [],
        {"spread_pips": 1.0, "bid": 100.0, "ask": 100.0, "price": 100.0},
    )
    assert decision.checks_passed.get("max_position_size") is False
    assert decision.approved is False


def test_gate_accepts_size_under_ceiling() -> None:
    gate = _base_gate()
    decision = gate.validate_proposal(
        {
            "symbol": "EURUSD",
            "direction": "BUY",
            "entry_price": 100.0,
            "stop_loss": 90.0,
            "take_profit": 115.0,
            "size": 1.0,
        },
        _safe_account(),
        [],
        {"spread_pips": 1.0, "bid": 100.0, "ask": 100.0, "price": 100.0},
    )
    assert decision.checks_passed.get("max_position_size") is True


# ── Item #3: cost-aware sizing ──────────────────────────────────────────


def test_sizing_includes_cost_allowances() -> None:
    mm = MoneyManager()
    plain = mm.calculate_lot_size(
        balance=10_000.0,
        risk_pct=0.01,
        sl_pips=100.0,
        point_value=0.01,
        contract_size=100,
    )
    with_costs = mm.calculate_lot_size(
        balance=10_000.0,
        risk_pct=0.01,
        sl_pips=100.0,
        point_value=0.01,
        contract_size=100,
        commission_per_lot=7.0,
        spread_cost_per_lot=3.0,
    )
    assert with_costs.lot_size < plain.lot_size
    assert with_costs.lot_size > 0


def test_pipeline_cost_allowances_helper() -> None:
    from orchestration.pipeline import TradingPipeline

    pipe = TradingPipeline(supervisor=None, risk_gate=None, execution_engine=None)
    spread, commission = pipe._cost_allowances(
        {"symbol": "XAUUSD"},
        {"spread_price": 0.30, "contract_size": 100.0, "commission_per_lot": 7.0},
        entry=2000.0,
        sl_pips=100.0,
        point_value=0.01,
        contract_size=100.0,
    )
    assert spread == pytest.approx(30.0)
    assert commission == pytest.approx(7.0)


# ── Item #4: symbol-aware spread ────────────────────────────────────────


def test_symbol_spread_limits() -> None:
    engine = RiskEngine()
    engine.set_threshold(RiskThreshold.MAX_DRAWDOWN, 0.99)
    engine.set_threshold(RiskThreshold.DAILY_LOSS_LIMIT, 0.99)
    engine.set_threshold(RiskThreshold.MAX_POSITIONS, 50)
    engine.set_threshold(RiskThreshold.MAX_EXPOSURE, 0.99)
    gate = RiskGate(
        engine,
        MoneyManager(),
        max_spread_pips=999999.0,
        symbol_spread_limits={"BTC": 8000.0, "XAU": 200.0, "FX": 5.0},
    )
    assert gate._max_spread_for_symbol("BTCUSDT") == 8000.0
    assert gate._max_spread_for_symbol("XAUUSD") == 200.0
    assert gate._max_spread_for_symbol("UNKNOWN") == 999999.0

    def _proposal(symbol: str) -> dict:
        return {
            "symbol": symbol,
            "direction": "BUY",
            "entry_price": 100.0,
            "stop_loss": 90.0,
            "take_profit": 115.0,
            "size": 0.01,
        }

    # FX-like spread 100 pips: XAU allowed, EURUSD (no match → global is huge here
    # so we instead check per-symbol FX explicitly) — use tight global for FX test.
    gate_fx = RiskGate(
        engine,
        MoneyManager(),
        max_spread_pips=5.0,
        symbol_spread_limits={"BTC": 8000.0, "XAU": 200.0},
    )
    ok_xau = gate_fx.validate_proposal(
        _proposal("XAUUSD"),
        _safe_account(),
        [],
        {"spread_pips": 100.0, "bid": 100.0, "ask": 100.0, "price": 100.0},
    )
    assert ok_xau.checks_passed["spread"] is True
    bad_fx = gate_fx.validate_proposal(
        _proposal("EURUSD"),
        _safe_account(),
        [],
        {"spread_pips": 100.0, "bid": 100.0, "ask": 100.0, "price": 100.0},
    )
    assert bad_fx.checks_passed["spread"] is False


# ── Item #5: UNKNOWN-state duplicate safety ────────────────────────────


def test_timeout_plus_exists_adopts_not_duplicates() -> None:
    placed: list[dict] = []

    class _FlakyConnector:
        def __init__(self) -> None:
            self.calls = 0

        def order_send(self, payload):
            self.calls += 1
            placed.append(payload)
            raise ConnectionError("connection lost after send")

        def get_symbol_info(self, symbol):
            return {"symbol": symbol, "volume_min": 0.01, "volume_max": 100.0}

        def positions(self):
            return [
                {
                    "ticket": 555,
                    "symbol": p["symbol"],
                    "side": "BUY",
                    "volume": p["volume"],
                    "price_open": 1.1,
                    "profit": 0.0,
                }
                for p in placed
            ]

    conn = _FlakyConnector()

    def _locator(request):
        for pos in conn.positions():
            if pos["symbol"] == request.symbol and abs(pos["volume"] - request.volume) < 1e-9:
                return {"ticket": pos["ticket"]}
        return None

    engine = ExecutionEngine(
        mt5_connector=conn, max_retries=3, retry_delay=0.0, order_locator=_locator
    )
    result = engine.execute_order(
        OrderRequest(symbol="EURUSD", order_type="BUY", volume=1.0, idempotency_key="p1-5-exists")
    )
    assert result.success is True
    assert result.ticket == 555
    assert conn.calls == 1  # adopted, not re-sent


def test_timeout_plus_missing_retries_then_fails_honestly() -> None:
    class _DeadConnector:
        def __init__(self) -> None:
            self.calls = 0

        def order_send(self, payload):
            self.calls += 1
            raise ConnectionError("timeout")

        def get_symbol_info(self, symbol):
            return {"symbol": symbol, "volume_min": 0.01, "volume_max": 100.0}

    conn = _DeadConnector()
    engine = ExecutionEngine(
        mt5_connector=conn, max_retries=2, retry_delay=0.0, order_locator=lambda req: None
    )
    result = engine.execute_order(
        OrderRequest(symbol="EURUSD", order_type="BUY", volume=1.0, idempotency_key="p1-5-missing")
    )
    assert result.success is False
    assert conn.calls == 3  # initial + 2 retries, nothing landed


# ── Item #6: persistent idempotency across restart ──────────────────────


def test_restart_does_not_forget_submitted_order(tmp_path) -> None:
    reset_store()
    path = tmp_path / "order_state.jsonl"
    store = OrderStateStore(path=str(path))
    set_store(store)
    try:
        engine = ExecutionEngine(mt5_connector=None, simulation_mode=False)
        # Simulate a dispatched order persisted BEFORE the "restart".
        set_order("persist-1", OrderState.SUBMITTED, {"ticket": 4242})
        assert engine._is_duplicate("persist-1") is True

        # Simulate restart: fresh engine instance, same durable ledger.
        engine2 = ExecutionEngine(mt5_connector=None, simulation_mode=False)
        set_store(store)  # re-attach after restart
        assert engine2._is_duplicate("persist-1") is True

        # Fresh key is not blocked.
        assert engine2._is_duplicate("never-seen") is False
    finally:
        set_store(None)
        reset_store()
