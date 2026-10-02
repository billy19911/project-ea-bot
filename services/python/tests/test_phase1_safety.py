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
from execution.state_machine import OrderState, get_order, reset_store, set_order, set_store
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


def test_projected_exposure_uses_broker_contract_notional() -> None:
    engine = RiskEngine(max_exposure=0.30)
    current = [
        {
            "size": 0.01,
            "current_price": 2510.0,
            "contract_size": 100.0,
            "notional_value": 2510.0,
            "_notional_valid": True,
        }
    ]
    ok, current_pct, projected_pct = engine.check_projected_exposure(
        positions=current,
        account_state={"equity": 10_000.0},
        proposed_trade={
            "size": 0.01,
            "current_price": 2510.0,
            "contract_size": 100.0,
            "notional_value": 2510.0,
        },
        max_exposure=0.30,
    )

    assert current_pct == pytest.approx(0.251)
    assert projected_pct == pytest.approx(0.502)
    assert ok is False


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
        {"spread_pips": 1.0, "bid": 100.0, "ask": 100.0, "contract_size": 1.0},
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
        {
            "spread_pips": 1.0,
            "bid": 100.0,
            "ask": 100.0,
            "price": 100.0,
            "contract_size": 1.0,
        },
    )
    assert decision.checks_passed.get("max_position_size") is True


def test_gate_max_position_size_uses_broker_contract_size() -> None:
    gate = _base_gate()
    decision = gate.validate_proposal(
        {
            "symbol": "XAUUSD",
            "direction": "BUY",
            "entry_price": 2510.0,
            "stop_loss": 2500.0,
            "take_profit": 2530.0,
            "size": 0.01,
        },
        _safe_account(),
        [],
        {
            "spread_pips": 1.0,
            "bid": 2510.0,
            "ask": 2510.1,
            "price": 2510.0,
            "contract_size": 100.0,
        },
    )

    assert decision.metrics_snapshot["position_size_pct"] == pytest.approx(0.251)
    assert decision.checks_passed["max_position_size"] is False


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


def test_risk_sizing_does_not_round_volume_up() -> None:
    from types import SimpleNamespace

    from orchestration.pipeline import TradingPipeline

    pipeline = TradingPipeline(
        supervisor=None,
        risk_gate=None,
        execution_engine=None,
        default_risk_pct=0.01,
        max_lot_per_trade=1.0,
        force_risk_sizing=True,
    )
    pipeline._resolve_point_contract = lambda proposal, market: (1.0, 1.0)
    pipeline.money_manager.calculate_lot_size = lambda **kwargs: SimpleNamespace(lot_size=0.009)
    proposal = {"symbol": "EURUSD", "size": 0.5}

    pipeline._size_proposal(
        proposal,
        entry=1.0,
        sl=0.9,
        account_state={"equity": 10_000.0},
        market_info={},
    )

    assert proposal["size"] <= 0.009


def test_risk_sizing_uses_broker_tick_value_in_account_currency() -> None:
    from orchestration.pipeline import TradingPipeline

    pipeline = TradingPipeline(
        supervisor=None,
        risk_gate=None,
        execution_engine=None,
        default_risk_pct=0.01,
        max_lot_per_trade=1.0,
        force_risk_sizing=True,
    )
    pipeline._apply_broker_volume_constraints = lambda lot, symbol: lot
    proposal = {"symbol": "XAUUSD", "direction": "BUY", "size": 1.0}
    market_info = {
        "point_value": 0.01,
        "contract_size": 100.0,
        "tick_size": 0.05,
        "tick_value": 2.0,
        "spread_price": 0.1,
    }

    pipeline._size_proposal(
        proposal,
        entry=2510.0,
        sl=2505.0,
        account_state={"equity": 10_000.0},
        market_info=market_info,
    )

    # 100 risk budget / (5 price units * 40 account-currency/price + 4 spread cost).
    assert proposal["size"] == pytest.approx(100.0 / 204.0)


def test_forced_risk_sizing_clears_size_when_broker_spec_is_missing() -> None:
    from orchestration.pipeline import TradingPipeline

    pipeline = TradingPipeline(
        supervisor=None,
        risk_gate=None,
        execution_engine=None,
        default_risk_pct=0.01,
        max_lot_per_trade=1.0,
        force_risk_sizing=True,
    )
    pipeline._resolve_point_contract = lambda proposal, market: (0.0, 0.0)
    pipeline._apply_broker_volume_constraints = lambda lot, symbol: lot
    proposal = {"symbol": "XAUUSD", "direction": "BUY", "size": 0.1}

    pipeline._size_proposal(
        proposal,
        entry=2510.0,
        sl=2505.0,
        account_state={"equity": 10_000.0},
        market_info={},
    )

    assert proposal["size"] == 0.0
    assert proposal.get("risk_sizing_verified") is not True


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


def test_gate_records_normalized_spread_metrics() -> None:
    gate = _base_gate()
    decision = gate.validate_proposal(
        {
            "symbol": "XAUUSD",
            "direction": "BUY",
            "entry_price": 2510.0,
            "stop_loss": 2500.0,
            "take_profit": 2540.0,
            "size": 0.001,
        },
        _safe_account(),
        [],
        {
            "bid": 2510.0,
            "ask": 2510.1,
            "spread_price": 0.1,
            "spread_pips": 1.0,
            "point_value": 0.01,
            "tick_size": 0.05,
            "tick_value": 2.0,
            "contract_size": 100.0,
            "atr": 2.0,
            "spread_cost_per_lot": 4.0,
        },
    )

    assert decision.metrics_snapshot["spread_price"] == pytest.approx(0.1)
    assert decision.metrics_snapshot["spread_points"] == pytest.approx(10.0)
    assert decision.metrics_snapshot["spread_ticks"] == pytest.approx(2.0)
    assert decision.metrics_snapshot["spread_atr"] == pytest.approx(0.05)
    assert decision.metrics_snapshot["spread_cost_per_lot"] == pytest.approx(4.0)


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


def test_timeout_plus_missing_stays_unknown_without_retry() -> None:
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
    request = OrderRequest(
        symbol="EURUSD", order_type="BUY", volume=1.0, idempotency_key="p1-5-missing"
    )
    result = engine.execute_order(request)
    assert result.success is False
    assert conn.calls == 1
    assert get_order("p1-5-missing")["state"] == OrderState.UNKNOWN.value

    duplicate = engine.execute_order(request)
    assert duplicate.error_code == 409
    assert conn.calls == 1


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


def test_execution_refuses_when_durable_intent_cannot_be_written() -> None:
    from execution.state_machine import set_store

    class _FailedStore:
        def all_orders(self):
            return {}

        def get_order(self, intent_id):
            return None

        def set_order(self, intent_id, state, extra=None):
            return False

    class _RecordingConnector:
        def __init__(self):
            self.send_calls = 0

        def order_send(self, payload):
            self.send_calls += 1
            return {"success": True, "ticket": 1}

        def get_symbol_info(self, symbol):
            return {"symbol": symbol, "volume_min": 0.01, "volume_max": 100.0}

    connector = _RecordingConnector()
    set_store(_FailedStore())
    try:
        engine = ExecutionEngine(
            mt5_connector=connector,
            require_approval=True,
            require_durable_state=True,
        )
        result = engine.execute_order(
            OrderRequest(
                symbol="EURUSD",
                order_type="BUY",
                volume=0.1,
                idempotency_key="p1-store-failure",
                approval_token="risk-approved",
            )
        )

        assert result.success is False
        assert result.error_code == 503
        assert connector.send_calls == 0
    finally:
        set_store(None)
        reset_store()


def test_execution_persists_required_identity_before_and_after_send() -> None:
    from datetime import datetime, timezone

    from execution.state_machine import set_store

    class _Store:
        healthy = True

        def __init__(self):
            self.orders = {}

        def all_orders(self):
            return dict(self.orders)

        def get_order(self, intent_id):
            return self.orders.get(intent_id)

        def set_order(self, intent_id, state, extra=None):
            record = self.orders.setdefault(intent_id, {"intent_id": intent_id})
            record.update({"state": state, "timestamp": datetime.now(timezone.utc).isoformat()})
            record.update(extra or {})
            return True

    class _Connector:
        def order_send(self, payload):
            return {"success": True, "ticket": 777}

        def get_symbol_info(self, symbol):
            return {"symbol": symbol, "volume_min": 0.01, "volume_max": 100.0}

        def get_positions(self):
            return []

    store = _Store()
    reset_store()
    set_store(store)
    try:
        engine = ExecutionEngine(
            mt5_connector=_Connector(),
            require_approval=True,
            require_durable_state=True,
        )
        request = OrderRequest(
            symbol="EURUSD",
            order_type="BUY",
            volume=0.1,
            idempotency_key="p1-durable-metadata",
            approval_token="risk-approved",
            proposal_id="proposal-1",
            execution_id="execution-1",
            strategy_version="v2.4",
        )
        result = engine.execute_order(request)

        assert result.success is True
        record = store.get_order("p1-durable-metadata")
        assert record["proposal_id"] == "proposal-1"
        assert record["execution_id"] == "execution-1"
        assert record["client_order_id"] == "p1-durable-metadata"
        assert record["broker_order_id"] == 777
        assert record["symbol"] == "EURUSD"
        assert record["side"] == "BUY"
        assert record["volume"] == pytest.approx(0.1)
        assert record["strategy_version"] == "v2.4"
        assert record["retry_count"] == 0
        assert record["timestamp"]
    finally:
        set_store(None)
        reset_store()
