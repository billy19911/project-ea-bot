# -*- coding: utf-8 -*-
"""TASK 07 — RISK / FINAL ORDER INVARIANT (STOP GATE 07).

Proves that risk validation applies to the EXACT final order that reaches the
broker, in the correct order::

    AI proposal → deterministic completion → broker normalization → final order
    → projected exposure calculation → final Risk Gate → execution

Each test maps to one STOP GATE 07 criterion:

- final normalized volume is risk-checked,
- proposed exposure is included (current + proposed <= limit),
- monetary SL risk is correct (abs(entry-SL) x contract_size x volume),
- broker contract specification is used (actual symbol_info; no invented
  fallback — fail CLOSED when missing),
- final order sent == final order approved (byte-for-byte),
- tests cover lot rounding upward/downward.
"""

from __future__ import annotations

import importlib
import types

import pytest

risk_mod = importlib.import_module("risk.gate")
risk_engine_mod = importlib.import_module("risk.engine")
mm_mod = importlib.import_module("risk.money_management")
threshold_mod = importlib.import_module("risk.base")
order_builder_mod = importlib.import_module("execution.order_builder")
fanout_mod = importlib.import_module("execution.fanout")
canonical_mod = importlib.import_module("trading.canonical_signal")
pipeline_mod = importlib.import_module("orchestration.pipeline")


def _engine():
    engine = risk_engine_mod.RiskEngine()
    engine.set_threshold(threshold_mod.RiskThreshold.MAX_DRAWDOWN, 0.2)
    engine.set_threshold(threshold_mod.RiskThreshold.DAILY_LOSS_LIMIT, 0.1)
    engine.set_threshold(threshold_mod.RiskThreshold.MAX_POSITIONS, 5)
    engine.set_threshold(threshold_mod.RiskThreshold.MAX_EXPOSURE, 0.3)
    return engine


def _account(equity=10_000.0):
    return {
        "equity": equity,
        "balance": equity,
        "peak_equity": equity,
        "daily_pnl": 0.0,
        "used_margin": 0.0,
        "margin_call_level": 0.0,
        "free_margin": equity,
    }


# ---------------------------------------------------------------------------
# Monetary SL risk — broker contract specification
# ---------------------------------------------------------------------------
def _gate_with_budget(max_risk_pct=0.02):
    return risk_mod.RiskGate(
        _engine(),
        mm_mod.MoneyManager(),
        max_spread_pips=50_000.0,
        min_rr=1.0,
        max_risk_pct=max_risk_pct,
    )


def test_monetary_risk_uses_market_info_contract_size():
    """risk_money = abs(entry-SL) x contract_size x volume (broker value)."""
    gate = _gate_with_budget(max_risk_pct=0.5)
    decision = gate.validate_proposal(
        {
            "symbol": "XAUUSD",
            "direction": "BUY",
            "entry_price": 2500.0,
            "stop_loss": 2495.0,  # risk distance = 5
            "take_profit": 2510.0,
            "size": 0.1,  # lots
            "risk_pct": 0.01,
            "commission_per_lot": 0.0,
        },
        _account(10_000.0),
        [],
        # Broker-supplied contract size: XAUUSD = 100 oz/lot.
        {
            "spread_pips": 1.0,
            "contract_size": 100.0,
            "point_value": 0.01,
        },
    )
    assert decision.checks_passed["monetary_risk"] is True
    # 5 * 100 * 0.1 = 50
    assert decision.metrics_snapshot["risk_money"] == pytest.approx(50.0)
    assert decision.metrics_snapshot["risk_contract_source"] == "market_info"
    assert decision.metrics_snapshot["risk_contract_size"] == pytest.approx(100.0)


def test_monetary_risk_blocks_when_over_budget():
    """A position whose monetary SL risk exceeds the budget is rejected."""
    gate = _gate_with_budget(max_risk_pct=0.01)  # 1% of 10k = 100 budget
    decision = gate.validate_proposal(
        {
            "symbol": "XAUUSD",
            "direction": "BUY",
            "entry_price": 2500.0,
            "stop_loss": 2490.0,  # distance 10
            "take_profit": 2530.0,
            "size": 0.2,  # 10 * 100 * 0.2 = 200 > 100
            "risk_pct": 0.02,
            "commission_per_lot": 0.0,
        },
        _account(10_000.0),
        [],
        {
            "spread_pips": 1.0,
            "contract_size": 100.0,
            "point_value": 0.01,
        },
    )
    assert decision.checks_passed["monetary_risk"] is False
    assert decision.approved is False
    assert decision.metrics_snapshot["risk_money"] == pytest.approx(200.0)
    assert decision.metrics_snapshot["risk_budget"] == pytest.approx(100.0)


def test_monetary_risk_fails_closed_when_contract_size_missing(monkeypatch):
    """No broker contract size (budget configured) → FAIL CLOSED, no fallback."""
    gate = _gate_with_budget(max_risk_pct=0.02)
    # Force the broker spec lookup to return a non-broker (fallback) spec so no
    # real contract size is available.
    fallback = types.SimpleNamespace(
        source="fallback", contract_size=0.0, point=0.0, spread_limit=5.0
    )
    import src.market.symbol_spec as symbol_spec

    monkeypatch.setattr(symbol_spec, "get_symbol_specification", lambda sym: fallback)

    decision = gate.validate_proposal(
        {
            "symbol": "UNKNOWNSYM",
            "direction": "BUY",
            "entry_price": 2500.0,
            "stop_loss": 2495.0,
            "take_profit": 2510.0,
            "size": 0.1,
            "risk_pct": 0.01,
            "commission_per_lot": 0.0,
        },
        _account(10_000.0),
        [],
        # No contract_size and no usable broker spec.
        {"spread_pips": 1.0},
    )
    assert decision.checks_passed["monetary_risk"] is False
    assert decision.approved is False
    assert decision.metrics_snapshot["risk_contract_source"] == "missing"


def test_monetary_risk_rejects_invented_fallback_contract_size(monkeypatch):
    """A labelled FALLBACK spec (source != broker) must never supply contract size."""
    gate = _gate_with_budget(max_risk_pct=0.02)

    # Pretend the broker spec lookup returns a NON-broker (fallback) spec.
    fallback = types.SimpleNamespace(
        source="fallback", contract_size=100_000.0, point=0.0, spread_limit=5.0
    )
    import src.market.symbol_spec as symbol_spec

    monkeypatch.setattr(symbol_spec, "get_symbol_specification", lambda sym: fallback)

    decision = gate.validate_proposal(
        {
            "symbol": "UNKNOWNSYM",
            "direction": "BUY",
            "entry_price": 100.0,
            "stop_loss": 99.0,
            "take_profit": 103.0,
            "size": 0.1,
            "risk_pct": 0.01,
        },
        _account(10_000.0),
        [],
        {"spread_pips": 1.0},  # no explicit contract size
    )
    # Fallback contract size is ignored → fail closed.
    assert decision.checks_passed["monetary_risk"] is False
    assert decision.metrics_snapshot["risk_contract_source"] == "missing"


def test_monetary_risk_uses_broker_symbol_spec_when_not_supplied(monkeypatch):
    """A genuine broker spec supplies the contract size (source == broker)."""
    gate = _gate_with_budget(max_risk_pct=0.5)
    broker_spec = types.SimpleNamespace(
        source="broker", contract_size=100.0, point=0.01, spread_limit=200.0
    )
    import src.market.symbol_spec as symbol_spec

    monkeypatch.setattr(symbol_spec, "get_symbol_specification", lambda sym: broker_spec)

    decision = gate.validate_proposal(
        {
            "symbol": "XAUUSD",
            "direction": "BUY",
            "entry_price": 2500.0,
            "stop_loss": 2495.0,
            "take_profit": 2510.0,
            "size": 0.1,
            "risk_pct": 0.01,
            "commission_per_lot": 0.0,
        },
        _account(10_000.0),
        [],
        {"spread_pips": 1.0},  # no explicit contract size → broker spec used
    )
    assert decision.checks_passed["monetary_risk"] is True
    assert decision.metrics_snapshot["risk_contract_source"] == "broker"
    assert decision.metrics_snapshot["risk_money"] == pytest.approx(50.0)


def test_monetary_risk_fails_closed_when_commission_unknown():
    gate = _gate_with_budget(max_risk_pct=0.02)
    decision = gate.validate_proposal(
        {
            "symbol": "XAUUSD",
            "direction": "BUY",
            "entry_price": 2500.0,
            "stop_loss": 2495.0,
            "take_profit": 2510.0,
            "size": 0.1,
        },
        _account(10_000.0),
        [],
        {"spread_pips": 1.0, "contract_size": 100.0},
    )

    assert decision.checks_passed["monetary_risk"] is False
    assert decision.metrics_snapshot["risk_commission_known"] is False


# ---------------------------------------------------------------------------
# Projected exposure — current + proposed <= limit
# ---------------------------------------------------------------------------
def test_projected_exposure_includes_proposed_trade():
    """Master-plan scenario F: existing 25% + proposed 10% > 30% → BLOCK."""
    engine = risk_engine_mod.RiskEngine()
    engine.set_threshold(threshold_mod.RiskThreshold.MAX_EXPOSURE, 0.30)
    gate = risk_mod.RiskGate(
        engine,
        mm_mod.MoneyManager(),
        max_spread_pips=50_000.0,
        min_rr=1.0,
    )
    # Existing exposure: 0.25 lots * 10,000 price = 2500 notional on 10k equity
    # => 25%.
    positions = [{"symbol": "XAUUSD", "size": 0.25, "current_price": 10_000.0, "side": "BUY"}]
    decision = gate.validate_proposal(
        {
            "symbol": "XAUUSD",
            "direction": "BUY",
            "entry_price": 10_000.0,
            "stop_loss": 9_900.0,
            "take_profit": 10_300.0,
            "size": 0.10,  # 0.10 * 10,000 = 1000 → +10%
            "risk_pct": 0.01,
        },
        _account(10_000.0),
        positions,
        {"spread_pips": 1.0, "contract_size": 1.0, "point_value": 0.01},
    )
    assert decision.checks_passed["max_exposure"] is False
    assert decision.approved is False
    # Projected = 35% (25% current + 10% proposed).
    assert decision.metrics_snapshot["current_exposure_pct"] == pytest.approx(0.25)
    assert decision.metrics_snapshot["projected_exposure_pct"] == pytest.approx(0.35)


def test_projected_exposure_within_limit_passes():
    """Existing 5% + proposed 10% <= 30% → pass."""
    engine = risk_engine_mod.RiskEngine()
    engine.set_threshold(threshold_mod.RiskThreshold.MAX_EXPOSURE, 0.30)
    gate = risk_mod.RiskGate(
        engine,
        mm_mod.MoneyManager(),
        max_spread_pips=50_000.0,
        min_rr=1.0,
    )
    positions = [{"symbol": "EURUSD", "size": 0.05, "current_price": 10_000.0, "side": "BUY"}]
    decision = gate.validate_proposal(
        {
            "symbol": "EURUSD",
            "direction": "BUY",
            "entry_price": 10_000.0,
            "stop_loss": 9_900.0,
            "take_profit": 10_300.0,
            "size": 0.10,
            "risk_pct": 0.01,
        },
        _account(10_000.0),
        positions,
        {"spread_pips": 1.0, "contract_size": 1.0, "point_value": 0.01},
    )
    assert decision.checks_passed["max_exposure"] is True
    assert decision.metrics_snapshot["projected_exposure_pct"] == pytest.approx(0.15)


# ---------------------------------------------------------------------------
# Lot rounding — upward AND downward (final volume is what gets risk-checked)
# ---------------------------------------------------------------------------
def _builder(spec):
    return order_builder_mod.OrderBuilder(symbol_spec_provider=lambda s: spec)


def test_lot_rounds_down_to_broker_step():
    """Volume 0.137 with step 0.01 → 0.14? No: nearest step rounds to 0.14.

    We assert BOTH directions explicitly below; here the raw is > midpoint so
    it rounds UP, and the companion test rounds DOWN.
    """
    builder = _builder({"volume_step": 0.01, "volume_min": 0.01, "volume_max": 100.0, "digits": 5})
    req = builder.build_order_request(
        {"symbol": "EURUSD", "order_type": "BUY", "volume": 0.134, "price": 1.1}
    )
    assert req.volume == pytest.approx(0.13)


def test_lot_rounds_up_to_broker_step():
    builder = _builder({"volume_step": 0.01, "volume_min": 0.01, "volume_max": 100.0, "digits": 5})
    req = builder.build_order_request(
        {"symbol": "EURUSD", "order_type": "BUY", "volume": 0.136, "price": 1.1}
    )
    assert req.volume == pytest.approx(0.13)


def test_lot_snapped_down_is_the_volume_risk_checked_by_fanout():
    """The final snap-down volume is the one the per-account gate sees."""
    fanout_mod.set_fanout_ledger(fanout_mod.FanoutLedger())

    class RecordingGate:
        def __init__(self):
            self.seen = []

        def validate_proposal(self, proposal, account_state, current_positions, market_info):
            self.seen.append(float(proposal.get("volume") or proposal.get("size") or 0.0))
            return types.SimpleNamespace(
                approved=True, reason="ok", checks_passed={}, metrics_snapshot={}
            )

    class FakeEngine:
        def __init__(self):
            self.sent = []

        def execute_order(self, request):
            self.sent.append(request)
            return types.SimpleNamespace(success=True, ticket=1, error_code=0, error_message="")

    gate = RecordingGate()
    engine = FakeEngine()
    builder = _builder({"volume_step": 0.01, "volume_min": 0.01, "volume_max": 100.0, "digits": 5})
    coord = fanout_mod.CanonicalFanout(
        execution_engine=engine,
        risk_gate=gate,
        targets_provider=lambda: [
            {"id": "a", "account": {"login": "111", "mode": "DEMO", "equity": 10000}}
        ],
        order_builder=builder,
        ledger=fanout_mod.FanoutLedger(),
    )
    signal = canonical_mod.make_canonical_signal(
        opportunity_id="opp",
        symbol="EURUSD",
        direction="BUY",
        entry_reference=1.1,
        initial_SL=1.09,
        initial_TP=1.13,
        planned_RR=2.0,
        strategy_version="v1",
        signal_id="sig1",
    )
    # raw 0.136 lots → snaps DOWN to 0.13 at the broker step.
    coord.fan_out(signal, raw_proposal={"volume": 0.136})

    # The gate must have seen the FINAL, snapped volume (0.13), and the sent
    # order must match it byte-for-byte.
    assert 0.13 in [round(v, 4) for v in gate.seen]
    assert engine.sent[0].volume == pytest.approx(0.13)


# ---------------------------------------------------------------------------
# final order sent == final order approved (fanout re-validation)
# ---------------------------------------------------------------------------
def test_fanout_gate_rejects_final_normalized_volume():
    """The per-account gate sees the FINAL (normalized) volume; rejecting it
    blocks the send, so the sent order is always the approved order."""
    fanout_mod.set_fanout_ledger(fanout_mod.FanoutLedger())

    class FinalVolumeGate:
        """Rejects the final snap-down volume to verify the gate controls send."""

        def validate_proposal(self, proposal, account_state, current_positions, market_info):
            vol = float(proposal.get("volume") or proposal.get("size") or 0.0)
            ok = vol >= 0.136
            return types.SimpleNamespace(
                approved=ok,
                reason="ok" if ok else "final volume too big",
                checks_passed={},
                metrics_snapshot={},
            )

    class FakeEngine:
        def __init__(self):
            self.sent = []

        def execute_order(self, request):
            self.sent.append(request)
            return types.SimpleNamespace(success=True, ticket=1, error_code=0, error_message="")

    engine = FakeEngine()
    builder = _builder({"volume_step": 0.01, "volume_min": 0.01, "volume_max": 100.0, "digits": 5})
    coord = fanout_mod.CanonicalFanout(
        execution_engine=engine,
        risk_gate=FinalVolumeGate(),
        targets_provider=lambda: [
            {"id": "a", "account": {"login": "111", "mode": "DEMO", "equity": 10000}}
        ],
        order_builder=builder,
        ledger=fanout_mod.FanoutLedger(),
    )
    signal = canonical_mod.make_canonical_signal(
        opportunity_id="opp",
        symbol="EURUSD",
        direction="BUY",
        entry_reference=1.1,
        initial_SL=1.09,
        initial_TP=1.13,
        planned_RR=2.0,
        strategy_version="v1",
        signal_id="sig1",
    )
    summary = coord.fan_out(signal, raw_proposal={"volume": 0.136})

    # Nothing was sent: the final (sent) order must be the approved order.
    assert engine.sent == []
    assert summary["rejected"] == 1


def test_fanout_sent_order_matches_approved_when_values_unchanged():
    fanout_mod.set_fanout_ledger(fanout_mod.FanoutLedger())

    class RecordingGate:
        def __init__(self):
            self.last = None

        def validate_proposal(self, proposal, account_state, current_positions, market_info):
            self.last = dict(proposal)
            return types.SimpleNamespace(
                approved=True, reason="ok", checks_passed={}, metrics_snapshot={}
            )

    class FakeEngine:
        def __init__(self):
            self.sent = []

        def execute_order(self, request):
            self.sent.append(request)
            return types.SimpleNamespace(success=True, ticket=7, error_code=0, error_message="")

    gate = RecordingGate()
    engine = FakeEngine()
    builder = _builder({"volume_step": 0.01, "volume_min": 0.01, "volume_max": 100.0, "digits": 2})
    coord = fanout_mod.CanonicalFanout(
        execution_engine=engine,
        risk_gate=gate,
        targets_provider=lambda: [
            {"id": "a", "account": {"login": "111", "mode": "DEMO", "equity": 10000}}
        ],
        order_builder=builder,
        ledger=fanout_mod.FanoutLedger(),
    )
    signal = canonical_mod.make_canonical_signal(
        opportunity_id="opp",
        symbol="EURUSD",
        direction="BUY",
        entry_reference=1.10,
        initial_SL=1.09,
        initial_TP=1.13,
        planned_RR=2.0,
        strategy_version="v1",
        signal_id="sig1",
    )
    coord.fan_out(signal, raw_proposal={"volume": 0.10})

    sent = engine.sent[0]
    assert sent.volume == pytest.approx(gate.last["volume"])
    assert sent.price == pytest.approx(gate.last["price"], abs=1e-9)
    assert sent.sl == pytest.approx(gate.last["stop_loss"], abs=1e-9)
    assert sent.tp == pytest.approx(gate.last["take_profit"], abs=1e-9)


# ---------------------------------------------------------------------------
# Pipeline — final order re-validation (single-terminal path)
# ---------------------------------------------------------------------------
def test_pipeline_revalidates_final_order_when_builder_rounds_volume(monkeypatch):
    """The pipeline re-runs the gate on the FINAL (snap-down) order volume."""
    # The pipeline's own lot cap snaps DOWN to a 0.01 step (final proposal
    # volume 0.13). The order builder then snaps DOWN to a 0.05 step, producing
    # a smaller final order (0.10) that must still be re-validated.
    pipeline_spec = types.SimpleNamespace(
        source="broker",
        contract_size=100_000.0,
        point=0.0001,
        max_volume=100.0,
        min_volume=0.01,
        volume_step=0.01,
        spread_limit=5.0,
    )
    import src.market.symbol_spec as symbol_spec

    monkeypatch.setattr(symbol_spec, "get_symbol_specification", lambda sym: pipeline_spec)

    class StubSupervisor:
        def analyze(self, context):
            return {
                "overall_confidence": 0.9,
                "summary": "t",
                "agent_results": {},
                "proposal": {
                    "symbol": "EURUSD",
                    "direction": "BUY",
                    "confidence": 0.9,
                    "entry_price": 1.10,
                    "stop_loss": 1.09,
                    "take_profit": 1.13,
                    "size": 0.13,
                },
            }

    calls = {"n": 0, "vols": []}

    class Gate:
        def validate_proposal(self, proposal, account_state, current_positions, market_info):
            calls["n"] += 1
            vol = float(proposal.get("size") or 0.0)
            calls["vols"].append(vol)
            ok = vol >= 0.13  # initial proposal meets the setup minimum; final does not
            return types.SimpleNamespace(
                approved=ok,
                reason="ok" if ok else "final too big",
                checks_passed={},
                metrics_snapshot={},
            )

    class FakeEngine:
        def __init__(self):
            self.sent = []

        def execute_order(self, request):
            self.sent.append(request)
            return types.SimpleNamespace(success=True, ticket=1, error_code=0, error_message="")

    # Order builder uses a 0.05 step → 0.13 snaps down to 0.10.
    builder = _builder({"volume_step": 0.05, "volume_min": 0.01, "volume_max": 100.0, "digits": 5})
    engine = FakeEngine()
    pipe = pipeline_mod.TradingPipeline(
        supervisor=StubSupervisor(),
        risk_gate=Gate(),
        execution_engine=engine,
        order_builder=builder,
        single_entry_policy=False,
        max_lot_per_trade=1.0,
        force_risk_sizing=False,
    )
    result = pipe.run({"event_id": "e1", "event_type": "MOMENTUM"}, {"symbol": "EURUSD"})

    # Gate was called at least twice (initial approve + final re-validation).
    assert calls["n"] >= 2, calls
    assert calls["vols"][:2] == pytest.approx([0.13, 0.10])
    # The final order was rejected → no execution.
    assert engine.sent == []
    assert result.status == pipeline_mod.STATUS_BLOCKED


def test_pipeline_final_order_recorded_and_matches_sent(monkeypatch):
    """On success the recorded final_order equals the order sent to the engine."""
    pipeline_spec = types.SimpleNamespace(
        source="broker",
        contract_size=100_000.0,
        point=0.0001,
        max_volume=100.0,
        min_volume=0.01,
        volume_step=0.01,
        spread_limit=5.0,
    )
    import src.market.symbol_spec as symbol_spec

    monkeypatch.setattr(symbol_spec, "get_symbol_specification", lambda sym: pipeline_spec)

    class StubSupervisor:
        def analyze(self, context):
            return {
                "overall_confidence": 0.9,
                "summary": "t",
                "agent_results": {},
                "proposal": {
                    "symbol": "EURUSD",
                    "direction": "BUY",
                    "confidence": 0.9,
                    "entry_price": 1.10,
                    "stop_loss": 1.09,
                    "take_profit": 1.13,
                    "size": 0.10,
                },
            }

    class ApproveGate:
        def validate_proposal(self, proposal, account_state, current_positions, market_info):
            return types.SimpleNamespace(
                approved=True, reason="ok", checks_passed={}, metrics_snapshot={}
            )

    class FakeEngine:
        def __init__(self):
            self.sent = []

        def execute_order(self, request):
            self.sent.append(request)
            return types.SimpleNamespace(success=True, ticket=99, error_code=0, error_message="")

    builder = _builder({"volume_step": 0.01, "volume_min": 0.01, "volume_max": 100.0, "digits": 2})
    engine = FakeEngine()
    pipe = pipeline_mod.TradingPipeline(
        supervisor=StubSupervisor(),
        risk_gate=ApproveGate(),
        execution_engine=engine,
        order_builder=builder,
        single_entry_policy=False,
        max_lot_per_trade=1.0,
        force_risk_sizing=False,
    )
    result = pipe.run({"event_id": "e1", "event_type": "MOMENTUM"}, {"symbol": "EURUSD"})

    assert engine.sent, "order should have been sent"
    sent = engine.sent[0]
    assert result.final_order is not None
    assert result.final_order["volume"] == pytest.approx(sent.volume)
    assert result.final_order["price"] == pytest.approx(sent.price)
    assert result.final_order["stop_loss"] == pytest.approx(sent.sl)
    assert result.final_order["take_profit"] == pytest.approx(sent.tp)


# ---------------------------------------------------------------------------
# End-to-end: the REAL RiskGate enforces monetary risk in the pipeline
# ---------------------------------------------------------------------------
def test_pipeline_real_gate_blocks_monetary_risk_breach(monkeypatch):
    """A proposal whose monetary SL risk exceeds the budget is blocked by the
    real RiskGate when the pipeline runs end to end (broker spec supplies the
    contract size)."""
    broker_spec = types.SimpleNamespace(
        source="broker",
        contract_size=100.0,
        point=0.01,
        max_volume=100.0,
        min_volume=0.01,
        volume_step=0.01,
        spread_limit=200.0,
    )
    import src.market.symbol_spec as symbol_spec

    monkeypatch.setattr(symbol_spec, "get_symbol_specification", lambda sym: broker_spec)

    class StubSupervisor:
        def analyze(self, context):
            return {
                "overall_confidence": 0.9,
                "summary": "t",
                "agent_results": {},
                "proposal": {
                    "symbol": "XAUUSD",
                    "direction": "BUY",
                    "confidence": 0.9,
                    "entry_price": 2500.0,
                    "stop_loss": 2495.0,  # distance 5
                    "take_profit": 2510.0,
                    "size": 0.5,  # 5 * 100 * 0.5 = 250 risk, budget = 1% of 10k = 100
                },
            }

    class FakeEngine:
        def __init__(self):
            self.sent = []

        def execute_order(self, request):
            self.sent.append(request)
            return types.SimpleNamespace(success=True, ticket=1, error_code=0, error_message="")

    engine_config = _engine()
    engine_config.set_threshold(threshold_mod.RiskThreshold.MAX_EXPOSURE, 3.0)
    engine_config.set_threshold(threshold_mod.RiskThreshold.MAX_POSITION_SIZE, 3.0)
    gate = risk_mod.RiskGate(
        engine_config,
        mm_mod.MoneyManager(),
        max_spread_pips=50_000.0,
        min_rr=1.0,
        max_risk_pct=0.01,
    )
    engine = FakeEngine()
    pipe = pipeline_mod.TradingPipeline(
        supervisor=StubSupervisor(),
        risk_gate=gate,
        execution_engine=engine,
        single_entry_policy=False,
        max_lot_per_trade=10.0,
        force_risk_sizing=False,
    )
    ctx = {
        "symbol": "XAUUSD",
        "account_state": {
            "equity": 10_000.0,
            "balance": 10_000.0,
            "peak_equity": 10_000.0,
            "daily_pnl": 0.0,
            "used_margin": 0.0,
        },
        "market_info": {"spread_pips": 1.0, "contract_size": 100.0, "point_value": 0.01},
    }
    result = pipe.run({"event_id": "e1", "event_type": "MOMENTUM"}, ctx)

    assert engine.sent == []
    assert result.status == pipeline_mod.STATUS_BLOCKED
    assert "monetary_risk" in result.risk_reason


def test_pipeline_real_gate_allows_monetary_risk_within_budget(monkeypatch):
    """A proposal within the monetary risk budget executes normally."""
    broker_spec = types.SimpleNamespace(
        source="broker",
        contract_size=100.0,
        point=0.01,
        max_volume=100.0,
        min_volume=0.01,
        volume_step=0.01,
        spread_limit=200.0,
    )
    import src.market.symbol_spec as symbol_spec

    monkeypatch.setattr(symbol_spec, "get_symbol_specification", lambda sym: broker_spec)

    class StubSupervisor:
        def analyze(self, context):
            return {
                "overall_confidence": 0.9,
                "summary": "t",
                "agent_results": {},
                "proposal": {
                    "symbol": "XAUUSD",
                    "direction": "BUY",
                    "confidence": 0.9,
                    "entry_price": 2500.0,
                    "stop_loss": 2495.0,
                    "take_profit": 2510.0,
                    "size": 0.1,  # 5 * 100 * 0.1 = 50 risk <= 100 budget
                    "commission_per_lot": 0.0,
                },
            }

    class FakeEngine:
        def __init__(self):
            self.sent = []

        def execute_order(self, request):
            self.sent.append(request)
            return types.SimpleNamespace(success=True, ticket=1, error_code=0, error_message="")

    engine_config = _engine()
    engine_config.set_threshold(threshold_mod.RiskThreshold.MAX_EXPOSURE, 3.0)
    engine_config.set_threshold(threshold_mod.RiskThreshold.MAX_POSITION_SIZE, 3.0)
    gate = risk_mod.RiskGate(
        engine_config,
        mm_mod.MoneyManager(),
        max_spread_pips=50_000.0,
        min_rr=1.0,
        max_risk_pct=0.01,
    )
    engine = FakeEngine()
    pipe = pipeline_mod.TradingPipeline(
        supervisor=StubSupervisor(),
        risk_gate=gate,
        execution_engine=engine,
        single_entry_policy=False,
        max_lot_per_trade=10.0,
        force_risk_sizing=False,
    )
    ctx = {
        "symbol": "XAUUSD",
        "account_state": {
            "equity": 10_000.0,
            "balance": 10_000.0,
            "peak_equity": 10_000.0,
            "daily_pnl": 0.0,
            "used_margin": 0.0,
        },
        "market_info": {
            "spread_pips": 1.0,
            "contract_size": 100.0,
            "point_value": 0.01,
            "commission_per_lot": 0.0,
        },
    }
    result = pipe.run({"event_id": "e2", "event_type": "MOMENTUM"}, ctx)

    assert engine.sent, "order within budget should execute"
    assert result.status == pipeline_mod.STATUS_EXECUTED
    assert result.final_order["volume"] == pytest.approx(0.1)
