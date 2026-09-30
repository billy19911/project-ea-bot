# -*- coding: utf-8 -*-
"""Phase 1 Hardening — regression, symbol-spec, commission, volume, adversarial.

Complements ``test_phase1_safety.py`` with the hardening requirements:
§2 deterministic final volume, §3 commission policy, §4 symbol spec,
§5 spread units + stale/missing fail-closed, §8 concurrency,
§11 adversarial AI proposals.
"""

from __future__ import annotations

import threading

import pytest

from src.market.symbol_spec import (
    COMMISSION_SOURCE_UNKNOWN,
    SymbolSpecification,
    classify_asset_class,
    get_symbol_specification,
)
from src.risk.base import RiskThreshold
from src.risk.engine import RiskEngine
from src.risk.gate import RiskGate
from src.risk.money_management import MoneyManager

# ── §4 symbol specification abstraction ─────────────────────────────────


def test_asset_class_classification() -> None:
    assert classify_asset_class("XAUUSD") == "XAU"
    assert classify_asset_class("GOLD") == "XAU"
    assert classify_asset_class("BTCUSD") == "BTC"
    assert classify_asset_class("EURUSD") == "FX"
    assert classify_asset_class("GBPJPY") == "FX"


def test_symbol_spec_defaults_fall_back_labelled() -> None:
    """No live MT5 → fallback spec, never claimed as a broker spec."""
    spec = get_symbol_specification("XAUUSD")
    assert spec.source in ("broker", "fallback")
    assert spec.symbol == "XAUUSD"
    assert spec.asset_class == "XAU"
    # Fallback point must be 0.0 (never an invented broker value).
    if spec.source == "fallback":
        assert spec.point == 0.0


def test_symbol_spec_config_override_commission() -> None:
    spec = get_symbol_specification("XAUUSD", config={"commission": 7.0})
    if spec.source == "fallback":
        assert spec.commission == 7.0
        assert spec.commission_source == "CONFIG"
    else:  # broker spec present (no MT5 in tests → unlikely)
        assert spec.commission >= 0.0


def test_symbol_spec_frozen_and_serialisable() -> None:
    spec = SymbolSpecification(symbol="BTCUSD", asset_class="BTC", source="fallback")
    data = spec.to_dict()
    assert data["symbol"] == "BTCUSD"
    assert data["commission_source"] == COMMISSION_SOURCE_UNKNOWN
    with pytest.raises(Exception):
        spec.symbol = "X"  # frozen dataclass


# ── §2 deterministic final volume ───────────────────────────────────────


def _pipe():
    from src.orchestration.pipeline import TradingPipeline

    return TradingPipeline(supervisor=None, risk_gate=None, execution_engine=None)


def test_cap_lot_huge_ai_volume_capped() -> None:
    pipe = _pipe()
    pipe.max_lot_per_trade = 0.05
    proposal = {"symbol": "EURUSD", "size": 9999.0}
    pipe._cap_lot(proposal)
    assert proposal["size"] <= 0.05


def test_cap_lot_invalid_volume_becomes_zero() -> None:
    pipe = _pipe()
    for bad in (0.0, -3.0, float("nan"), float("inf")):
        proposal = {"symbol": "EURUSD", "size": bad}
        pipe._cap_lot(proposal)
        assert proposal["size"] == 0.0


def test_cap_lot_respects_broker_max(monkeypatch) -> None:
    """Broker max_volume always wins over an operator-higher cap."""
    pipe = _pipe()
    pipe.max_lot_per_trade = 10.0
    fake = SymbolSpecification(
        symbol="EURUSD",
        asset_class="FX",
        min_volume=0.01,
        max_volume=0.5,
        volume_step=0.01,
        source="broker",
    )
    monkeypatch.setattr(
        "src.market.symbol_spec.get_symbol_specification", lambda s, config=None: fake
    )
    proposal = {"symbol": "EURUSD", "size": 5.0}
    pipe._cap_lot(proposal)
    assert proposal["size"] == pytest.approx(0.5)


def test_cap_lot_respects_broker_step_and_min(monkeypatch) -> None:
    pipe = _pipe()
    pipe.max_lot_per_trade = 10.0
    fake = SymbolSpecification(
        symbol="EURUSD",
        asset_class="FX",
        min_volume=0.1,
        max_volume=100.0,
        volume_step=0.1,
        source="broker",
    )
    monkeypatch.setattr(
        "src.market.symbol_spec.get_symbol_specification", lambda s, config=None: fake
    )
    # 0.37 → snap DOWN to 0.3 (never up).
    p1 = {"symbol": "EURUSD", "size": 0.37}
    pipe._cap_lot(p1)
    assert p1["size"] == pytest.approx(0.3)
    # Below broker min → rejected to 0 (never lifted to min).
    p2 = {"symbol": "EURUSD", "size": 0.05}
    pipe._cap_lot(p2)
    assert p2["size"] == 0.0


def test_cap_lot_missing_broker_spec_keeps_operator_cap() -> None:
    """No broker spec → operator cap only; never invents broker values."""
    pipe = _pipe()
    pipe.max_lot_per_trade = 0.05
    proposal = {"symbol": "UNKNOWNSYM", "size": 1.0}
    pipe._cap_lot(proposal)
    assert proposal["size"] == pytest.approx(0.05)


# ── §3 commission policy ────────────────────────────────────────────────


def test_cost_allowances_broker_commission() -> None:
    pipe = _pipe()
    spread, commission = pipe._cost_allowances(
        {"symbol": "EURUSD"},
        {"spread_price": 0.0002, "contract_size": 100000.0, "commission_per_lot": 7.0},
        entry=1.1,
        sl_pips=10.0,
        point_value=0.0001,
        contract_size=100000.0,
    )
    assert commission == pytest.approx(7.0)
    assert spread == pytest.approx(20.0)


def test_cost_allowances_config_commission() -> None:
    pipe = _pipe()
    _spread, commission = pipe._cost_allowances(
        {"symbol": "EURUSD", "commission_per_lot": 3.5},
        {"spread_price": 0.0, "contract_size": 100000.0},
        entry=1.1,
        sl_pips=10.0,
        point_value=0.0001,
        contract_size=100000.0,
    )
    assert commission == pytest.approx(3.5)
    assert pipe  # noqa: B018


def test_cost_allowances_unknown_commission_recorded() -> None:
    pipe = _pipe()
    proposal = {"symbol": "UNK"}
    _spread, commission = pipe._cost_allowances(
        proposal,
        {"spread_price": 0.0},
        entry=1.0,
        sl_pips=1.0,
        point_value=0.0001,
        contract_size=100000.0,
    )
    assert commission == 0.0
    assert proposal["commission_source"] == "UNKNOWN"  # recorded, not silent


def test_cost_allowances_zero_is_legitimate_broker_value() -> None:
    pipe = _pipe()
    proposal = {"symbol": "EURUSD"}
    _spread, commission = pipe._cost_allowances(
        proposal,
        {"spread_price": 0.0, "commission_per_lot": 0.0},
        entry=1.1,
        sl_pips=10.0,
        point_value=0.0001,
        contract_size=100000.0,
    )
    assert commission == 0.0
    assert proposal["commission_source"] == "BROKER"  # explicit zero, not unknown


def test_sizing_reduces_lot_with_commission() -> None:
    mm = MoneyManager()
    no_cost = mm.calculate_lot_size(10_000.0, 0.01, 100.0, 0.01, 100)
    with_cost = mm.calculate_lot_size(
        10_000.0, 0.01, 100.0, 0.01, 100, commission_per_lot=10.0, spread_cost_per_lot=5.0
    )
    assert with_cost.lot_size < no_cost.lot_size


# ── §5 spread units + fail-closed ───────────────────────────────────────


def _spread_gate(symbol_limits=None, global_limit=999999.0) -> RiskGate:
    engine = RiskEngine()
    for t in (RiskThreshold.MAX_DRAWDOWN, RiskThreshold.DAILY_LOSS_LIMIT):
        engine.set_threshold(t, 0.99)
    engine.set_threshold(RiskThreshold.MAX_POSITIONS, 50)
    engine.set_threshold(RiskThreshold.MAX_EXPOSURE, 0.99)
    engine.set_threshold(RiskThreshold.MAX_POSITION_SIZE, 0.99)
    return RiskGate(
        engine,
        MoneyManager(),
        max_spread_pips=global_limit,
        symbol_spread_limits=symbol_limits or {},
    )


def _spread_proposal(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "direction": "BUY",
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "take_profit": 120.0,
        "size": 0.01,
    }


def _spread_account() -> dict:
    return {
        "equity": 10_000.0,
        "balance": 10_000.0,
        "peak_equity": 10_000.0,
        "daily_pnl": 0.0,
        "used_margin": 0.0,
    }


def test_spread_derived_from_bid_ask_when_pips_missing() -> None:
    gate = _spread_gate(symbol_limits={"FX": 5.0})
    # spread_pips absent; derived: (1.10020 - 1.10000) / (0.00001*10) = 2 pips.
    decision = gate.validate_proposal(
        _spread_proposal("EURUSD"),
        _spread_account(),
        [],
        {"bid": 1.10000, "ask": 1.10020, "point_value": 0.00001},
    )
    assert decision.checks_passed["spread"] is True
    assert decision.metrics_snapshot["spread_known"] is True


def test_spread_missing_market_data_fails_closed() -> None:
    gate = _spread_gate()
    decision = gate.validate_proposal(_spread_proposal("EURUSD"), _spread_account(), [], {})
    assert decision.checks_passed["spread"] is False
    assert decision.approved is False


def test_spread_stale_or_inverted_bid_ask_fails_closed() -> None:
    gate = _spread_gate()
    # ask < bid (inverted/stale) → cannot compute a sane spread → blocked.
    decision = gate.validate_proposal(
        _spread_proposal("EURUSD"),
        _spread_account(),
        [],
        {"bid": 1.10020, "ask": 1.10000, "point_value": 0.00001},
    )
    assert decision.checks_passed["spread"] is False


def test_spread_over_symbol_limit_rejected() -> None:
    gate = _spread_gate(symbol_limits={"BTC": 8000.0})
    decision = gate.validate_proposal(
        _spread_proposal("BTCUSD"),
        _spread_account(),
        [],
        {"spread_pips": 10000.0, "point_value": 0.001, "contract_size": 1},
    )
    assert decision.checks_passed["spread"] is False


# ── §2/§11 adversarial AI proposals ─────────────────────────────────────


def _strict_gate() -> RiskGate:
    engine = RiskEngine()
    engine.set_threshold(RiskThreshold.MAX_DRAWDOWN, 0.2)
    engine.set_threshold(RiskThreshold.DAILY_LOSS_LIMIT, 0.1)
    engine.set_threshold(RiskThreshold.MAX_POSITIONS, 5)
    engine.set_threshold(RiskThreshold.MAX_EXPOSURE, 0.3)
    return RiskGate(engine, MoneyManager(), max_spread_pips=5.0, symbol_spread_limits={"FX": 5.0})


def _acc() -> dict:
    return {
        "equity": 10_000.0,
        "balance": 10_000.0,
        "peak_equity": 10_000.0,
        "daily_pnl": 0.0,
        "used_margin": 0.0,
        "margin_call_level": 0.3,
        "free_margin": 9800.0,
    }


def test_adversarial_huge_lot_blocked() -> None:
    gate = _strict_gate()
    d = gate.validate_proposal(
        {
            "symbol": "EURUSD",
            "direction": "BUY",
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "take_profit": 120.0,
            "size": 1_000_000.0,
        },
        _acc(),
        [],
        {"spread_pips": 1.0, "bid": 100.0, "ask": 100.0},
    )
    assert d.approved is False
    assert d.checks_passed["max_position_size"] is False


def test_adversarial_invalid_sl_blocked() -> None:
    gate = _strict_gate()
    d = gate.validate_proposal(
        {
            "symbol": "EURUSD",
            "direction": "BUY",
            "entry_price": 100.0,
            "stop_loss": 0.0,
            "take_profit": 120.0,
            "size": 0.1,
        },
        _acc(),
        [],
        {"spread_pips": 1.0, "bid": 100.0, "ask": 100.0},
    )
    assert d.approved is False
    assert d.checks_passed["stop_loss"] is False


def test_adversarial_sl_equals_entry_blocked() -> None:
    gate = _strict_gate()
    d = gate.validate_proposal(
        {
            "symbol": "EURUSD",
            "direction": "BUY",
            "entry_price": 100.0,
            "stop_loss": 100.0,
            "take_profit": 120.0,
            "size": 0.1,
        },
        _acc(),
        [],
        {"spread_pips": 1.0, "bid": 100.0, "ask": 100.0},
    )
    assert d.approved is False
    assert d.checks_passed["stop_loss"] is False


def test_adversarial_missing_risk_data_fails_closed() -> None:
    gate = _strict_gate()
    # Empty proposal + empty account: nothing can be proven safe.
    d = gate.validate_proposal({}, {}, [], {})
    assert d.approved is False


def test_adversarial_bad_rr_blocked() -> None:
    gate = _strict_gate()
    d = gate.validate_proposal(
        {
            "symbol": "EURUSD",
            "direction": "BUY",
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "take_profit": 100.5,
            "size": 0.1,
        },
        _acc(),
        [],
        {"spread_pips": 1.0, "bid": 100.0, "ask": 100.0},
    )
    assert d.approved is False
    assert d.checks_passed["risk_reward"] is False


# ── §8 durable idempotency concurrency ──────────────────────────────────


def test_duplicate_detection_is_concurrency_safe() -> None:
    """Two concurrent submits with the same key — at most one may proceed."""
    from src.execution.engine import ExecutionEngine

    results: list[bool] = []
    barrier = threading.Barrier(2)

    class _Conn:
        def get_symbol_info(self, symbol):
            return {"symbol": symbol, "volume_min": 0.01, "volume_max": 100.0}

    engine = ExecutionEngine(
        mt5_connector=_Conn(), simulation_mode=True, max_retries=0, retry_delay=0.0
    )

    def worker():
        barrier.wait()
        with engine._registry_lock:
            dup = engine._is_duplicate("conc-key")
            if not dup:
                engine._record_pending("conc-key")
            results.append(dup)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Exactly one worker observes "not duplicate" (0 True values for it).
    assert results.count(False) == 1
    assert results.count(True) == 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
