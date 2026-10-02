# -*- coding: utf-8 -*-
"""Phase 5 (audit plan) — Learning & Research acceptance tests.

Every completed trade must record setup identity + quality dimensions
(separated from outcome), and WAIT/REJECT decisions must also be recorded
(counterfactual learning). Setup identity is structured:

    SYMBOL / TF_SETUP / TF_ZONE / TF_TRIGGER / SETUP_TYPE / REGIME / SESSION
"""

from __future__ import annotations

import pytest

from learning import review_bridge as bridge_mod
from learning import review_store as store_mod


def _trade_record(**overrides):
    base = {
        "trade_id": "t1",
        "setup_id": "setup_1",
        "trigger_id": "trig_1",
        "strategy_version": "v1",
        "entry_price": 2500.0,
        "exit_price": 2510.0,
        "stop_loss": 2495.0,
        "direction": "BUY",
        "gross_pnl": 100.0,
        "net_pnl": 95.0,
        "commission": 3.0,
        "spread_cost": 2.0,
        "slippage": 0.5,
        "mae": 4.0,
        "mfe": 12.0,
        "regime": "TRENDING",
        "session": "LONDON",
        "zone_type": "ORDER_BLOCK",
        "trigger_type": "DISPLACEMENT",
        "decision_quality": 0.8,
        "entry_quality": 0.7,
        "risk_quality": 0.9,
        "execution_quality": 0.6,
    }
    base.update(overrides)
    return base


# ── setup identity ─────────────────────────────────────────────────────
def test_setup_identity_is_structured() -> None:
    identity = store_mod.build_setup_identity(
        symbol="XAUUSD",
        setup_timeframe="M15",
        zone_timeframe="M5",
        trigger_timeframe="M1",
        setup_type="BOS_RETEST",
        regime="TRENDING",
        session="LONDON",
    )
    assert identity == "XAUUSD/M15/M5/M1/BOS_RETEST/TRENDING/LONDON"


def test_trade_review_carries_setup_identity_and_quality_dims() -> None:
    builder = store_mod.ReviewBuilder()
    review = builder.build_trade_review(
        review_id="rev-t1",
        setup_identity="XAUUSD/M15/M5/M1/BOS_RETEST/TRENDING/LONDON",
        **_trade_record(),
    )
    assert review.setup_identity == "XAUUSD/M15/M5/M1/BOS_RETEST/TRENDING/LONDON"
    # Quality dimensions are independent — never collapsed into one number.
    assert review.decision_quality == pytest.approx(0.8)
    assert review.entry_quality == pytest.approx(0.7)
    assert review.risk_quality == pytest.approx(0.9)
    assert review.execution_quality == pytest.approx(0.6)
    # Outcome is recorded separately from process quality.
    assert review.outcome_class == "GOOD_DECISION_WIN"
    assert review.mae == pytest.approx(4.0)
    assert review.mfe == pytest.approx(12.0)


def test_loss_is_not_automatically_bad_process() -> None:
    builder = store_mod.ReviewBuilder()
    review = builder.build_trade_review(
        review_id="rev-t2",
        **_trade_record(trade_id="t2", net_pnl=-50.0, gross_pnl=-50.0),
    )
    assert review.outcome_class == "GOOD_DECISION_LOSS"


# ── counterfactual: WAIT/REJECT decisions are also recorded ─────────────
def test_wait_decision_is_bridged_as_counterfactual() -> None:
    status = bridge_mod.bridge_review_record(
        {
            "event_id": "e1",
            "decision_state": "WAIT",
            "direction": "BUY",
            "setup_id": "setup_1",
            "reason_codes": ["HTF_VETO"],
            "strategy_version": "v1",
        }
    )
    assert status["bridged"] is True
    assert status["kind"] == "DecisionReview"


def test_decision_review_carries_setup_identity() -> None:
    builder = store_mod.ReviewBuilder()
    review = builder.build_decision_review(
        review_id="drev-e1",
        event_id="e1",
        decision_timestamp="2026-10-02T00:00:00+00:00",
        decision_state="WAIT",
        setup_identity="XAUUSD/M15/M5/M1/BOS_RETEST/TRENDING/LONDON",
    )
    assert review.setup_identity == "XAUUSD/M15/M5/M1/BOS_RETEST/TRENDING/LONDON"


# ── regime matrix ──────────────────────────────────────────────────────
def test_regime_matrix_groups_by_setup_regime_session() -> None:
    rows = [
        {"setup_identity": "XAUUSD/M15/M5/M1/BOS_RETEST/TRENDING/LONDON", "net_pnl": 100.0},
        {"setup_identity": "XAUUSD/M15/M5/M1/BOS_RETEST/TRENDING/LONDON", "net_pnl": -20.0},
        {"setup_identity": "XAUUSD/M15/M5/M1/RANGE_FADE/RANGING/ASIA", "net_pnl": 10.0},
    ]
    matrix = store_mod.regime_matrix(rows)
    trending = matrix["XAUUSD/M15/M5/M1/BOS_RETEST/TRENDING/LONDON"]
    assert trending["sample_size"] == 2
    assert trending["total_pnl"] == pytest.approx(80.0)
    assert matrix["XAUUSD/M15/M5/M1/RANGE_FADE/RANGING/ASIA"]["sample_size"] == 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
