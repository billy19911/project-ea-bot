# -*- coding: utf-8 -*-
"""Tests for advanced trade review — root-cause, pattern extraction,
session analysis, counterfactual, committee quality, learning journal.

Covers EPIC 11.07–11.14.
"""

from __future__ import annotations

import pytest

from review.advanced_review import (
    AttributionResult,
    CommitteeQuality,
    CounterfactualReview,
    JournalEntry,
    LearningJournal,
    RootCauseClassification,
    SessionAnalysis,
    analyze_by_time,
    attribute_strategy_vs_execution,
    classify_root_cause,
    evaluate_committee_quality,
    extract_patterns,
    review_no_trade,
)

# ---------------------------------------------------------------------------
# 11.07 Root-cause classification
# ---------------------------------------------------------------------------


class TestClassifyRootCause:
    """Tests for classify_root_cause."""

    def test_win_with_high_decision_quality(self) -> None:
        """WIN + high decision quality → analytical_error."""
        result = classify_root_cause(
            {"outcome": "WIN", "decision_quality_score": 80.0},
        )
        assert isinstance(result, RootCauseClassification)
        assert result.primary_cause == "analytical_error"
        assert result.confidence >= 0.5

    def test_loss_with_high_impact_news(self) -> None:
        """LOSS + high-impact news → news_impact."""
        result = classify_root_cause(
            {
                "outcome": "LOSS",
                "decision_quality_score": 60.0,
                "execution_quality_score": 90.0,
                "timing_score": 60.0,
            },
            news_events=[{"impact": "high"}],
        )
        assert result.primary_cause == "news_impact"
        assert result.confidence >= 0.85
        assert "normal_loss" in result.secondary_causes

    def test_loss_regime_mismatch(self) -> None:
        """Regime change during trade → regime_mismatch."""
        result = classify_root_cause(
            {
                "outcome": "LOSS",
                "decision_quality_score": 50.0,
                "execution_quality_score": 90.0,
                "timing_score": 50.0,
            },
            regime_at_entry="trend_up",
            regime_at_exit="range_bound",
        )
        assert result.primary_cause == "regime_mismatch"
        assert "analytical_error" in result.secondary_causes

    def test_loss_execution_slippage(self) -> None:
        """Low execution quality → execution_slippage."""
        result = classify_root_cause(
            {
                "outcome": "LOSS",
                "decision_quality_score": 70.0,
                "execution_quality_score": 40.0,
                "timing_score": 50.0,
            },
        )
        assert result.primary_cause == "execution_slippage"

    def test_loss_timing_error(self) -> None:
        """Low timing quality → timing_error."""
        result = classify_root_cause(
            {
                "outcome": "LOSS",
                "decision_quality_score": 70.0,
                "execution_quality_score": 85.0,
                "timing_score": 30.0,
            },
        )
        assert result.primary_cause == "timing_error"

    def test_loss_analytical_error(self) -> None:
        """Low decision quality → analytical_error."""
        result = classify_root_cause(
            {
                "outcome": "LOSS",
                "decision_quality_score": 25.0,
                "execution_quality_score": 95.0,
                "timing_score": 55.0,
            },
        )
        assert result.primary_cause == "analytical_error"

    def test_normal_loss_default(self) -> None:
        """No special conditions → normal_loss."""
        result = classify_root_cause(
            {
                "outcome": "LOSS",
                "decision_quality_score": 55.0,
                "execution_quality_score": 88.0,
                "timing_score": 52.0,
            },
        )
        assert result.primary_cause == "normal_loss"

    def test_risk_issue_secondary_for_large_mae(self) -> None:
        """Large MAE relative to MFE adds risk_issue secondary cause."""
        result = classify_root_cause(
            {
                "outcome": "LOSS",
                "mae": 9.0,
                "mfe": 2.0,
                "decision_quality_score": 55.0,
                "execution_quality_score": 88.0,
                "timing_score": 52.0,
            },
        )
        assert "risk_issue" in result.secondary_causes

    def test_result_has_explanation(self) -> None:
        """Every classification has a non-empty explanation."""
        result = classify_root_cause({"outcome": "WIN"})
        assert len(result.explanation) > 0

    def test_confidence_in_valid_range(self) -> None:
        """Confidence always between 0 and 1."""
        for outcome in ("WIN", "LOSS"):
            for dq in (30.0, 55.0, 80.0):
                result = classify_root_cause({"outcome": outcome, "decision_quality_score": dq})
                assert 0.0 <= result.confidence <= 1.0


# ---------------------------------------------------------------------------
# 11.08 Strategy-vs-execution attribution
# ---------------------------------------------------------------------------


class TestAttributeStrategyVsExecution:
    """Tests for attribute_strategy_vs_execution."""

    def test_dominant_strategy_when_decision_low(self) -> None:
        """Low decision quality → strategy dominant."""
        result = attribute_strategy_vs_execution(
            {
                "decision_quality_score": 20.0,
                "execution_quality_score": 100.0,
                "pnl": -50.0,
            }
        )
        assert isinstance(result, AttributionResult)
        assert result.dominant_factor == "strategy"
        assert result.strategy_attribution < -0.5

    def test_dominant_execution_when_slippage_high(self) -> None:
        """Low execution quality → execution dominant."""
        result = attribute_strategy_vs_execution(
            {
                "decision_quality_score": 50.0,
                "execution_quality_score": 30.0,
                "pnl": -10.0,
            }
        )
        assert result.dominant_factor == "execution"
        assert result.execution_attribution < -0.3

    def test_balanced_when_both_neutral(self) -> None:
        """Neutral scores → balanced attribution."""
        result = attribute_strategy_vs_execution(
            {
                "decision_quality_score": 50.0,
                "execution_quality_score": 100.0,
                "pnl": 0.0,
            }
        )
        assert result.dominant_factor == "balanced"
        assert abs(result.strategy_attribution) <= 0.01

    def test_positive_pnl_reflected(self) -> None:
        """Positive PnL with good scores shows positive attribution."""
        result = attribute_strategy_vs_execution(
            {
                "decision_quality_score": 85.0,
                "execution_quality_score": 98.0,
                "pnl": 120.0,
            }
        )
        assert result.strategy_attribution > 0.6
        assert result.execution_attribution >= -0.05

    def test_result_has_explanation(self) -> None:
        """Attribution includes non-empty explanation."""
        result = attribute_strategy_vs_execution(
            {
                "decision_quality_score": 60.0,
                "execution_quality_score": 80.0,
                "pnl": 10.0,
            }
        )
        assert len(result.explanation) > 0


# ---------------------------------------------------------------------------
# 11.09 / 11.10 Winning / losing pattern extraction
# ---------------------------------------------------------------------------


class TestExtractPatterns:
    """Tests for extract_patterns."""

    @staticmethod
    def _make_trades() -> list[dict]:
        return [
            {
                "trade_id": "t1",
                "outcome": "WIN",
                "pnl": 50.0,
                "symbol": "EURUSD",
                "session": "London",
                "regime": "trend_up",
                "setup": "breakout",
                "hour": 9,
                "direction": "BUY",
            },
            {
                "trade_id": "t2",
                "outcome": "WIN",
                "pnl": 30.0,
                "symbol": "EURUSD",
                "session": "London",
                "regime": "trend_up",
                "setup": "breakout",
                "hour": 10,
                "direction": "BUY",
            },
            {
                "trade_id": "t3",
                "outcome": "LOSS",
                "pnl": -20.0,
                "symbol": "GBPUSD",
                "session": "NY",
                "regime": "range_bound",
                "setup": "mean_revert",
                "hour": 15,
                "direction": "SELL",
            },
            {
                "trade_id": "t4",
                "outcome": "WIN",
                "pnl": 40.0,
                "symbol": "EURUSD",
                "session": "London",
                "regime": "trend_up",
                "setup": "breakout",
                "hour": 8,
                "direction": "BUY",
            },
            {
                "trade_id": "t5",
                "outcome": "LOSS",
                "pnl": -15.0,
                "symbol": "GBPUSD",
                "session": "NY",
                "regime": "range_bound",
                "setup": "mean_revert",
                "hour": 16,
                "direction": "SELL",
            },
        ]

    def test_extract_winning_patterns(self) -> None:
        """Extract patterns from winning trades (11.09)."""
        trades = self._make_trades()
        patterns = extract_patterns(trades, outcome_filter="WIN")
        assert len(patterns) > 0
        # EURUSD appears 3 times in wins
        eur_patterns = [p for p in patterns if "EURUSD" in p.label]
        assert len(eur_patterns) == 1
        assert eur_patterns[0].frequency == 3

    def test_extract_losing_patterns(self) -> None:
        """Extract patterns from losing trades (11.10)."""
        trades = self._make_trades()
        patterns = extract_patterns(trades, outcome_filter="LOSS")
        gbp_patterns = [p for p in patterns if "GBPUSD" in p.label]
        assert len(gbp_patterns) == 1
        assert gbp_patterns[0].frequency == 2

    def test_min_frequency_filter(self) -> None:
        """Patterns below min_frequency are excluded."""
        trades = [
            {
                "trade_id": "t1",
                "outcome": "WIN",
                "pnl": 10.0,
                "symbol": "EURUSD",
                "session": "Tokyo",
                "regime": "unknown",
                "setup": "s1",
                "hour": 1,
                "direction": "BUY",
            },
        ]
        patterns = extract_patterns(trades, outcome_filter="WIN", min_frequency=2)
        assert len(patterns) == 0

    def test_empty_trades_returns_empty(self) -> None:
        """Empty trade list returns no patterns."""
        assert extract_patterns([]) == []

    def test_no_matching_outcome_returns_empty(self) -> None:
        """If no trades match outcome filter, return empty."""
        trades = [{"outcome": "WIN", "pnl": 10}]
        assert extract_patterns(trades, outcome_filter="LOSS") == []

    def test_pattern_sorted_by_frequency_descending(self) -> None:
        """Patterns are sorted by frequency descending."""
        trades = self._make_trades()
        patterns = extract_patterns(trades, outcome_filter="WIN")
        if len(patterns) >= 2:
            for i in range(len(patterns) - 1):
                assert patterns[i].frequency >= patterns[i + 1].frequency

    def test_pattern_has_conditions_and_examples(self) -> None:
        """Each pattern has conditions dict and example trade IDs."""
        trades = self._make_trades()
        patterns = extract_patterns(trades, outcome_filter="WIN")
        if patterns:
            p = patterns[0]
            assert isinstance(p.conditions, dict)
            assert len(p.examples) > 0

    def test_win_rate_calculated_correctly(self) -> None:
        """Win rate is 100% for filtered winning trades."""
        trades = [
            {
                "trade_id": "t1",
                "outcome": "WIN",
                "pnl": 10.0,
                "symbol": "X",
                "session": "S",
                "regime": "R",
                "setup": "A",
                "hour": 1,
                "direction": "BUY",
            },
            {
                "trade_id": "t2",
                "outcome": "WIN",
                "pnl": 5.0,
                "symbol": "X",
                "session": "S",
                "regime": "R",
                "setup": "A",
                "hour": 2,
                "direction": "BUY",
            },
            {
                "trade_id": "t3",
                "outcome": "LOSS",
                "pnl": -5.0,
                "symbol": "Y",
                "session": "T",
                "regime": "Q",
                "setup": "B",
                "hour": 4,
                "direction": "SELL",
            },
        ]
        patterns = extract_patterns(trades, outcome_filter="WIN")
        sym_pats = [p for p in patterns if "symbol=X" in p.label]
        assert len(sym_pats) == 1
        # All filtered trades are WIN, so win_rate = 100%
        assert sym_pats[0].win_rate == 100.0


# ---------------------------------------------------------------------------
# 11.11 Time / session analysis
# ---------------------------------------------------------------------------


class TestAnalyzeByTime:
    """Tests for analyze_by_time."""

    @staticmethod
    def _make_trades() -> list[dict]:
        return [
            {
                "trade_id": "t1",
                "pnl": 50.0,
                "outcome": "WIN",
                "hour": 9,
                "session": "London",
                "day": "Mon",
            },
            {
                "trade_id": "t2",
                "pnl": -20.0,
                "outcome": "LOSS",
                "hour": 9,
                "session": "London",
                "day": "Mon",
            },
            {
                "trade_id": "t3",
                "pnl": 30.0,
                "outcome": "WIN",
                "hour": 15,
                "session": "NY",
                "day": "Tue",
            },
            {
                "trade_id": "t4",
                "pnl": 10.0,
                "outcome": "WIN",
                "hour": 15,
                "session": "NY",
                "day": "Tue",
            },
            {
                "trade_id": "t5",
                "pnl": -5.0,
                "outcome": "LOSS",
                "hour": 1,
                "session": "Tokyo",
                "day": "Wed",
            },
        ]

    def test_returns_session_analysis_objects(self) -> None:
        """Returns list of SessionAnalysis objects."""
        results = analyze_by_time(self._make_trades())
        assert all(isinstance(r, SessionAnalysis) for r in results)

    def test_hour_breakdown_exists(self) -> None:
        """Hour dimension produces breakdown when data present."""
        results = analyze_by_time(self._make_trades())
        hour_results = [r for r in results if r.dimension == "hour"]
        assert len(hour_results) == 1
        assert "9" in hour_results[0].breakdown

    def test_session_breakdown_exists(self) -> None:
        """Session dimension produces breakdown when data present."""
        results = analyze_by_time(self._make_trades())
        session_results = [r for r in results if r.dimension == "session"]
        assert len(session_results) == 1
        assert "London" in session_results[0].breakdown

    def test_day_breakdown_exists(self) -> None:
        """Day dimension produces breakdown when data present."""
        results = analyze_by_time(self._make_trades())
        day_results = [r for r in results if r.dimension == "day"]
        assert len(day_results) == 1

    def test_empty_trades_returns_empty_list(self) -> None:
        """Empty trades returns empty list."""
        assert analyze_by_time([]) == []

    def test_no_dimension_keys_returns_unknown_groups(self) -> None:
        """Trades without hour/session/day keys group under 'unknown'."""
        trades = [{"trade_id": "t1", "pnl": 10.0, "outcome": "WIN"}]
        results = analyze_by_time(trades)
        # Each dimension creates an 'unknown' group
        assert len(results) == 3
        for r in results:
            assert "unknown" in r.breakdown

    def test_hour_9_metrics(self) -> None:
        """Hour 9: 2 trades, 50% WR, avg PnL=15."""
        results = analyze_by_time(self._make_trades())
        hour_results = [r for r in results if r.dimension == "hour"]
        h9 = hour_results[0].breakdown["9"]
        assert h9["count"] == 2.0
        assert h9["win_rate"] == pytest.approx(50.0)
        assert h9["avg_pnl"] == pytest.approx(15.0)

    def test_ny_session_metrics(self) -> None:
        """NY session: 2 trades, 100% WR, avg PnL=20."""
        results = analyze_by_time(self._make_trades())
        sess_results = [r for r in results if r.dimension == "session"]
        ny = sess_results[0].breakdown["NY"]
        assert ny["count"] == 2.0
        assert ny["win_rate"] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# 11.12 No-trade / counterfactual review
# ---------------------------------------------------------------------------


class TestReviewNoTrade:
    """Tests for review_no_trade."""

    def test_avoided_adverse_move(self) -> None:
        """Negative subsequent move → avoided adverse."""
        result = review_no_trade("d1", "WAIT", -150.0)
        assert isinstance(result, CounterfactualReview)
        assert result.avoided_adverse is True
        assert result.missed_opportunity is False

    def test_missed_opportunity(self) -> None:
        """Positive subsequent move → missed opportunity."""
        result = review_no_trade("d2", "NO_TRADE", 200.0)
        assert result.avoided_adverse is False
        assert result.missed_opportunity is True

    def test_neutral_near_zero(self) -> None:
        """Near-zero move is still missed opportunity (positive)."""
        result = review_no_trade("d3", "WAIT", 0.001)
        assert result.avoided_adverse is False
        assert result.missed_opportunity is True  # > 0 threshold

    def test_custom_threshold(self) -> None:
        """Custom threshold changes avoidance boundary."""
        result = review_no_trade("d4", "WAIT", 5.0, threshold=10.0)
        assert result.avoided_adverse is True  # 5 < 10

    def test_counterfactual_pnl_preserved(self) -> None:
        """Subsequent price move stored as counterfactual PnL."""
        result = review_no_trade("d5", "NO_TRADE", 42.0)
        assert result.counterfactual_pnl == 42.0

    def test_explanation_non_empty(self) -> None:
        """Every review has a non-empty explanation."""
        result = review_no_trade("d6", "WAIT", -99.0)
        assert len(result.explanation) > 0

    def test_decision_preserved(self) -> None:
        """Decision string is preserved."""
        result = review_no_trade("d7", "NO_TRADE", 0.0)
        assert result.decision == "NO_TRADE"


# ---------------------------------------------------------------------------
# 11.13 Committee decision quality
# ---------------------------------------------------------------------------


class TestEvaluateCommitteeQuality:
    """Tests for evaluate_committee_quality."""

    def test_buy_signal_with_win_is_directionally_correct(self) -> None:
        """BUY signal that resulted in WIN is directionally correct."""
        result = evaluate_committee_quality(
            {"signal": "BUY", "consensus_pct": 80.0, "confidence": 0.8},
            "WIN",
        )
        assert isinstance(result, CommitteeQuality)
        assert result.directionally_correct is True

    def test_sell_signal_with_loss_not_directionally_correct(self) -> None:
        """SELL signal that resulted in LOSS is not correct."""
        result = evaluate_committee_quality(
            {"signal": "SELL", "consensus_pct": 70.0, "confidence": 0.6},
            "LOSS",
        )
        assert result.directionally_correct is False

    def test_hold_signal_never_directionally_correct(self) -> None:
        """HOLD signal cannot be directionally correct."""
        result = evaluate_committee_quality(
            {"signal": "HOLD", "consensus_pct": 90.0, "confidence": 0.9},
            "WIN",
        )
        assert result.directionally_correct is False

    def test_tactical_score_range(self) -> None:
        """Tactical score always between 0 and 100."""
        for sig in ("BUY", "SELL", "HOLD"):
            for out in ("WIN", "LOSS"):
                result = evaluate_committee_quality(
                    {"signal": sig, "consensus_pct": 50.0, "confidence": 0.5},
                    out,
                )
                assert 0.0 <= result.tactical_score <= 100.0

    def test_consensus_strength_matches_input(self) -> None:
        """Consensus strength equals consensus_pct / 100."""
        result = evaluate_committee_quality(
            {"signal": "BUY", "consensus_pct": 75.0, "confidence": 0.6},
            "WIN",
        )
        assert result.consensus_strength == pytest.approx(0.75)

    def test_high_consensus_boosts_tactical_score(self) -> None:
        """Higher consensus yields higher tactical score for WIN."""
        low = evaluate_committee_quality(
            {"signal": "BUY", "consensus_pct": 40.0, "confidence": 0.5},
            "WIN",
        )
        high = evaluate_committee_quality(
            {"signal": "BUY", "consensus_pct": 95.0, "confidence": 0.5},
            "WIN",
        )
        assert high.tactical_score > low.tactical_score

    def test_explanation_non_empty(self) -> None:
        """Result includes non-empty explanation."""
        result = evaluate_committee_quality(
            {"signal": "BUY", "consensus_pct": 60.0, "confidence": 0.7},
            "LOSS",
        )
        assert len(result.explanation) > 0


# ---------------------------------------------------------------------------
# 11.14 Learning journal
# ---------------------------------------------------------------------------


class TestLearningJournal:
    """Tests for LearningJournal."""

    def _make_journal(self) -> LearningJournal:
        return LearningJournal()

    def test_add_entry_returns_journal_entry(self) -> None:
        """add_entry returns a JournalEntry instance."""
        j = self._make_journal()
        entry = j.add_entry("t1", "Lesson text")
        assert isinstance(entry, JournalEntry)
        assert entry.lesson == "Lesson text"
        assert entry.trade_id == "t1"

    def test_entry_auto_incrementing_id(self) -> None:
        """Entry IDs auto-increment LJ-0001, LJ-0002, ..."""
        j = self._make_journal()
        e1 = j.add_entry("t1", "A")
        e2 = j.add_entry("t2", "B")
        assert e1.id == "LJ-0001"
        assert e2.id == "LJ-0002"

    def test_get_entry_by_id(self) -> None:
        """Retrieve entry by ID returns same object."""
        j = self._make_journal()
        entry = j.add_entry("t1", "Test")
        retrieved = j.get_entry(entry.id)
        assert retrieved is entry

    def test_get_entry_unknown_returns_none(self) -> None:
        """Unknown ID returns None."""
        j = self._make_journal()
        assert j.get_entry("LJ-9999") is None

    def test_get_by_trade_filters_correctly(self) -> None:
        """get_by_trade returns only entries for given trade."""
        j = self._make_journal()
        j.add_entry("t1", "A")
        j.add_entry("t2", "B")
        j.add_entry("t1", "C")
        t1_entries = j.get_by_trade("t1")
        assert len(t1_entries) == 2
        assert all(e.trade_id == "t1" for e in t1_entries)

    def test_get_by_tag_filters_correctly(self) -> None:
        """get_by_tag returns entries with matching tag."""
        j = self._make_journal()
        j.add_entry("t1", "A", tags=["risk"])
        j.add_entry("t2", "B", tags=["timing"])
        j.add_entry("t3", "C", tags=["risk", "entry"])
        risk_entries = j.get_by_tag("risk")
        assert len(risk_entries) == 2

    def test_all_entries_sorted_by_timestamp(self) -> None:
        """all_entries returns entries sorted chronologically."""
        import time

        j = self._make_journal()
        e1 = j.add_entry("t1", "First")
        time.sleep(0.05)
        e2 = j.add_entry("t2", "Second")
        entries = j.all_entries()
        assert entries[0] is e1
        assert entries[1] is e2

    def test_to_dict_serializes_all_entries(self) -> None:
        """to_dict returns list of dicts with expected keys."""
        j = self._make_journal()
        j.add_entry("t1", "Lesson", evidence=["e1"], linked_hypothesis="h1", tags=["tag"])
        data = j.to_dict()
        assert len(data) == 1
        d = data[0]
        assert set(d.keys()) >= {
            "id",
            "trade_id",
            "timestamp",
            "lesson",
            "evidence",
            "linked_hypothesis",
            "tags",
        }

    def test_linked_hypothesis_stored(self) -> None:
        """Linked hypothesis ID is preserved."""
        j = self._make_journal()
        entry = j.add_entry("t1", "L", linked_hypothesis="hyp-123")
        assert entry.linked_hypothesis == "hyp-123"

    def test_evidence_list_stored(self) -> None:
        """Evidence strings are preserved."""
        j = self._make_journal()
        ev = ["MAE too large", "SL hit early"]
        entry = j.add_entry("t1", "L", evidence=ev)
        assert entry.evidence == ev

    def test_timestamp_has_timezone_info(self) -> None:
        """Journal entry timestamps are timezone-aware."""
        j = self._make_journal()
        entry = j.add_entry("t1", "L")
        assert entry.timestamp.tzinfo is not None
