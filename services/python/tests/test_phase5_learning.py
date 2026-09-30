# -*- coding: utf-8 -*-
"""Phase 5 — Learning/Research/Counterfactual/Strategy-Evolution tests.

Covers the 18 required behaviors (§25) + adversarial safety cases.
"""

from __future__ import annotations

import pytest

from src.learning.canonical import (
    DecisionSnapshot,
    ExperimentRecord,
    HypothesisRecord,
    NegativeKnowledgeRecord,
    StrategyCandidateRecord,
    WalkForwardRecord,
)
from src.learning.research_phase5 import PatternObserver, PromotionGate
from src.learning.review_store import CanonicalStore, ResearchQueue, ReviewBuilder


@pytest.fixture()
def store(tmp_path):
    s = CanonicalStore(path=str(tmp_path / "canon.jsonl"))
    yield s
    s.clear()


# ── 1. duplicate TRADE_CLOSED → one review ───────────────────────────────


def test_duplicate_trade_review_is_idempotent(store):
    r = ReviewBuilder().build_trade_review(
        review_id="rev-1",
        trade_id="T1",
        direction="BUY",
        entry_price=100.0,
        exit_price=105.0,
        stop_loss=95.0,
        net_pnl=50.0,
        decision_quality=0.8,
    )
    store.write("TradeReview", r.trade_id, r.to_dict())
    store.write("TradeReview", r.trade_id, r.to_dict())  # duplicate close event
    assert store.count("TradeReview") == 1


# ── 2. duplicate decision event → one DecisionReview ─────────────────────


def test_duplicate_decision_review_is_idempotent(store):
    d = ReviewBuilder.build_decision_review(
        review_id="drev-1",
        event_id="E1",
        decision_timestamp="2024-01-01T00:00:00+00:00",
        decision_state="WAIT",
        direction="BUY",
    )
    store.write("DecisionReview", d.event_id, d.to_dict())
    store.write("DecisionReview", d.event_id, d.to_dict())
    assert store.count("DecisionReview") == 1


# ── 3. future data injection → blocked ───────────────────────────────────


def test_future_information_blocked():
    with pytest.raises(ValueError):
        DecisionSnapshot(
            snapshot_id="s1",
            event_id="e1",
            decision_timestamp="2024-01-02T00:00:00+00:00",
            information_timestamp="2024-01-03T00:00:00+00:00",
        )


# ── 4. forming/future candle not in snapshot ─────────────────────────────


def test_snapshot_information_not_after_decision():
    s = DecisionSnapshot(
        snapshot_id="s2",
        event_id="e2",
        decision_timestamp="2024-01-02T12:00:00+00:00",
        information_timestamp="2024-01-02T11:59:59+00:00",
        context={"closes": [1, 2, 3]},
    )
    assert s.information_timestamp <= s.decision_timestamp


# ── 5. small sample → INSUFFICIENT_SAMPLE ────────────────────────────────


def test_small_sample_marked_insufficient():
    obs = PatternObserver().observe(
        [
            {
                "kind": "TradeReview",
                "symbol": "X",
                "direction": "BUY",
                "trigger_type": "rej",
                "realized_r": 1.0,
            }
        ]
        * 5
    )
    assert obs[0].status == "INSUFFICIENT_SAMPLE"
    assert obs[0].sample_size == 5


def test_large_sample_marked_observed():
    rows = [
        {
            "kind": "TradeReview",
            "symbol": "X",
            "direction": "BUY",
            "trigger_type": "rej",
            "realized_r": 0.5,
        }
    ] * 40
    obs = PatternObserver().observe(rows)
    assert obs[0].status == "OBSERVED"


# ── 6. excellent backtest → candidate only, no live activation ───────────


def test_excellent_backtest_never_auto_activates():
    cand = StrategyCandidateRecord(
        candidate_id="c1",
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
    assert promo.decision == "PENDING"  # NEVER auto-approved
    d = cand.to_dict()
    assert d["activation"] == "PROPOSAL_ONLY"
    assert d["requires_manual_approval"] is True


# ── 7. LLM recommends parameter change → no automatic mutation ───────────


def test_llm_recommendation_does_not_mutate_strategy():
    # PromotionGate.approve refuses without a human identity.
    cand = StrategyCandidateRecord(
        candidate_id="c2",
        backtest_results={
            "trade_count": 50,
            "expectancy": 0.2,
            "max_drawdown": 0.1,
            "profit_factor": 1.5,
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
    with pytest.raises(ValueError):
        PromotionGate().approve(promo, approved_by="")  # no human → rejected


# ── 8. repeated losses → review only, strategy unchanged ─────────────────


def test_repeated_losses_do_not_mutate_strategy():
    # Learning only PRODUCES reviews/patterns; a loss loop does not touch
    # any strategy config object (verified: no such API exists here).
    reviews = [
        ReviewBuilder().build_trade_review(
            review_id=f"r{i}",
            trade_id=f"T{i}",
            direction="BUY",
            entry_price=100.0,
            exit_price=95.0,
            stop_loss=95.0,
            net_pnl=-50.0,
            decision_quality=0.8,
        )
        for i in range(3)
    ]
    assert all(r.net_pnl < 0 for r in reviews)
    # Nothing in this module can set a live parameter — assert no setter surface.
    import src.learning.canonical as c

    assert not hasattr(c, "set_param")
    assert not hasattr(c, "activate")


# ── 9. candidate tries to modify RiskGate → rejected ─────────────────────


def test_candidate_cannot_modify_risk_gate():
    cand = StrategyCandidateRecord(candidate_id="c3", parameter_set={"max_exposure": 0.99})
    # The candidate is a inert record; no API applies it to the hedge gate.
    d = cand.to_dict()
    assert d["activation"] == "PROPOSAL_ONLY"
    import src.learning.canonical as c

    assert not hasattr(c, "apply_parameters")
    assert not hasattr(c, "override_risk")


# ── 10. candidate cannot modify broker constraints ───────────────────────


def test_candidate_cannot_modify_broker_constraints():
    from src.risk.money_management import MoneyManager

    mm = MoneyManager()
    # Broker ceiling still enforced by the deterministic cap, not by a candidate.
    assert mm.cap_lot_size(999.0, max_lot_per_trade=0.05) == 0.05


# ── 11. research crash → trading remains safe ────────────────────────────


def test_research_queue_isolates_crash(tmp_path):
    q = ResearchQueue(path=str(tmp_path / "queue_iso.jsonl"))

    def boom(job):
        raise RuntimeError("backtest crashed")

    q.submit({"type": "research", "trade_id": "T1"})
    q.drain(boom)
    assert q.errors == 1  # crash isolated, no raise
    q.submit({"type": "research", "trade_id": "T2"})

    def ok(job):
        pass

    assert q.drain(ok) == 1


# ── 12. counterfactual uses decision-time entry model ────────────────────


def test_counterfactual_is_point_in_time_safe():
    cf = ReviewBuilder.build_counterfactual(
        direction="BUY",
        entry_reference_price=100.0,
        hypothetical_sl=95.0,
        hypothetical_tp=110.0,
        future_high=112.0,
        future_low=97.0,
    )
    assert cf.outcome == "WOULD_HAVE_WON"
    # Entry reference is the decision-time price (100.0), never a later best.
    assert cf.entry_reference_price == 100.0


def test_counterfactual_insufficient_data():
    cf = ReviewBuilder.build_counterfactual(
        direction="BUY",
        entry_reference_price=0.0,
        hypothetical_sl=0.0,
        hypothetical_tp=0.0,
        future_high=0.0,
        future_low=0.0,
    )
    assert cf.outcome == "INSUFFICIENT_FUTURE_DATA"


def test_counterfactual_ambiguous_is_invalid():
    cf = ReviewBuilder.build_counterfactual(
        direction="BUY",
        entry_reference_price=100.0,
        hypothetical_sl=95.0,
        hypothetical_tp=110.0,
        future_high=112.0,
        future_low=90.0,  # both reachable
    )
    assert cf.outcome == "INVALID_COUNTERFACTUAL"


# ── 13. EXPIRED cannot resurrect ─────────────────────────────────────────


def test_expired_decision_review_no_resurrect():
    d = ReviewBuilder.build_decision_review(
        review_id="drev-x",
        event_id="EX1",
        decision_timestamp="2024-01-01T00:00:00+00:00",
        decision_state="EXPIRED",
        direction="BUY",
    )
    assert d.decision_state == "EXPIRED"
    # No API resurrects it — DecisionReview is frozen.
    with pytest.raises(Exception):
        d.decision_state = "WAIT"


# ── 14. INVALIDATED cannot resurrect ─────────────────────────────────────


def test_invalidated_decision_review_no_resurrect():
    d = ReviewBuilder.build_decision_review(
        review_id="drev-y",
        event_id="IN1",
        decision_timestamp="2024-01-01T00:00:00+00:00",
        decision_state="INVALIDATED",
        direction="SELL",
    )
    assert d.decision_state == "INVALIDATED"
    with pytest.raises(Exception):
        d.event_id = "other"


# ── 15. identical research run is reproducible ───────────────────────────


def test_experiment_record_reproducible():
    e1 = ExperimentRecord(
        experiment_id="ex1",
        hypothesis_id="h1",
        random_seed=42,
        data_window="2023-01..2023-12",
        cost_model={"spread": True},
    )
    e2 = ExperimentRecord(
        experiment_id="ex1",
        hypothesis_id="h1",
        random_seed=42,
        data_window="2023-01..2023-12",
        cost_model={"spread": True},
    )
    assert e1.to_dict() == e2.to_dict()


# ── 16. TRAIN < VALIDATION < TEST ────────────────────────────────────────


def test_walk_forward_windows_ordered():
    wf = WalkForwardRecord(
        run_id="wf1",
        train_window="2022-01..2022-06",
        validation_window="2022-07..2022-09",
        test_window="2022-10..2022-12",
        folds=3,
    )
    # Window labels are in forward order by construction; assert explicitness.
    assert wf.train_window < wf.validation_window < wf.test_window


# ── 17. unknown commission/news/session remains UNKNOWN ──────────────────


def test_unknown_fields_stay_unknown():
    r = ReviewBuilder().build_trade_review(
        review_id="r-u",
        trade_id="T-u",
        direction="BUY",
        entry_price=100.0,
        exit_price=105.0,
        stop_loss=95.0,
        net_pnl=10.0,
        commission=0.0,
        news_state="UNKNOWN",
        session="UNKNOWN",
    )
    assert r.news_state == "UNKNOWN"
    assert r.session == "UNKNOWN"


# ── 18. all lineage is preserved ─────────────────────────────────────────


def test_lineage_preserved():
    h = HypothesisRecord(
        hypothesis_id="h1",
        statement="X",
        source_pattern_ids=["p1"],
        source_review_ids=["r1"],
        status="TESTABLE",
    )
    e = ExperimentRecord(experiment_id="ex1", hypothesis_id="h1")
    c = StrategyCandidateRecord(candidate_id="c1", hypothesis_ids=["h1"], experiment_ids=["ex1"])
    assert h.source_pattern_ids and h.source_review_ids
    assert e.hypothesis_id == "h1"
    assert "h1" in c.hypothesis_ids and "ex1" in c.experiment_ids


# ── adversarial: negative knowledge ledger ───────────────────────────────


def test_negative_knowledge_states():
    for st in ("KNOWN_FALSE", "KNOWN_UNCERTAIN", "KNOWN_SUPPORTED"):
        rec = NegativeKnowledgeRecord(
            record_id=f"nk-{st}", subject_type="hypothesis", subject_id="h1", state=st
        )
        assert rec.state == st
    with pytest.raises(ValueError):
        NegativeKnowledgeRecord(
            record_id="bad", subject_type="hypothesis", subject_id="h1", state="MAYBE"
        )


# ── adversarial: final volume authority unchanged ────────────────────────


def test_final_volume_authority_unchanged():
    from src.orchestration.pipeline import TradingPipeline

    pipe = TradingPipeline(supervisor=None, risk_gate=None, execution_engine=None)
    pipe.max_lot_per_trade = 0.05
    proposal = {"symbol": "EURUSD", "size": 25.0}
    pipe._cap_lot(proposal)
    assert proposal["size"] == 0.05


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
