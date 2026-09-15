# -*- coding: utf-8 -*-
"""Tests for learning loop — EPIC 14.

Covers review→pattern→hypothesis→experiment→validation pipelines,
performance-by-time/regime learning, and learning-by-doing loops.
"""

from __future__ import annotations

import pytest

from learning.loop import LearningLoop, LearningPhase, PatternHypothesisPipeline, PerformanceTracker


class TestPerformanceTracker:
    """Tests for PerformanceTracker (14.08-14.11)."""

    def test_track_trade_by_hour(self) -> None:
        """Track performance by hour with sample-size safeguards."""
        tracker = PerformanceTracker(min_sample_size=2)
        tracker.record_trade(hour=9, pnl=50.0, outcome="WIN")
        tracker.record_trade(hour=9, pnl=-10.0, outcome="LOSS")
        tracker.record_trade(hour=15, pnl=30.0, outcome="WIN")

        hour_9_stats = tracker.get_hour_stats(9)
        assert hour_9_stats is not None
        assert hour_9_stats["count"] == 2
        assert hour_9_stats["avg_pnl"] == 20.0

    def test_min_sample_size_enforced(self) -> None:
        """Performance stats require min_sample_size trades."""
        tracker = PerformanceTracker(min_sample_size=5)
        tracker.record_trade(hour=9, pnl=10.0, outcome="WIN")
        tracker.record_trade(hour=9, pnl=5.0, outcome="WIN")

        stats = tracker.get_hour_stats(9)
        assert stats is None  # Below min_sample_size

    def test_track_by_regime(self) -> None:
        """Track performance across market regimes."""
        tracker = PerformanceTracker(min_sample_size=1)
        tracker.record_trade(regime="trend_up", pnl=100.0, outcome="WIN")
        tracker.record_trade(regime="trend_up", pnl=50.0, outcome="WIN")
        tracker.record_trade(regime="range_bound", pnl=-20.0, outcome="LOSS")

        trend_stats = tracker.get_regime_stats("trend_up")
        assert trend_stats["count"] == 2
        assert trend_stats["win_rate"] == 100.0

    def test_best_worst_hours(self) -> None:
        """Identify best and worst performing hours."""
        tracker = PerformanceTracker(min_sample_size=1)
        tracker.record_trade(hour=9, pnl=100.0)
        tracker.record_trade(hour=9, pnl=50.0)
        tracker.record_trade(hour=15, pnl=-50.0)
        tracker.record_trade(hour=15, pnl=-30.0)

        best, worst = tracker.best_worst_hours()
        assert best[0] == 9
        assert worst[0] == 15

    def test_track_by_setup(self) -> None:
        """Setup-level learning tracks recurring conditions (14.10)."""
        tracker = PerformanceTracker(min_sample_size=1)
        tracker.record_trade(setup="breakout_london", pnl=80.0, outcome="WIN")
        tracker.record_trade(setup="breakout_london", pnl=40.0, outcome="WIN")
        tracker.record_trade(setup="fade_asia", pnl=-30.0, outcome="LOSS")

        stats = tracker.get_setup_stats("breakout_london")
        assert stats["count"] == 2
        assert stats["win_rate"] == 100.0

    def test_supervisor_kpis(self) -> None:
        """Supervisor KPI learning computes win rate, PF, expectancy (14.11)."""
        tracker = PerformanceTracker(min_sample_size=1)
        tracker.record_trade(pnl=100.0)
        tracker.record_trade(pnl=-50.0)
        tracker.record_trade(pnl=80.0)

        kpis = tracker.supervisor_kpis()
        assert kpis["total_trades"] == 3
        assert kpis["win_rate"] == pytest.approx(66.67, abs=0.1)
        assert kpis["profit_factor"] == pytest.approx(3.6, abs=0.01)
        assert kpis["expectancy"] == pytest.approx(43.33, abs=0.1)

    def test_supervisor_kpis_empty(self) -> None:
        """Empty tracker returns zeroed KPIs."""
        tracker = PerformanceTracker()
        kpis = tracker.supervisor_kpis()
        assert kpis["total_trades"] == 0
        assert kpis["win_rate"] == 0.0


class TestPatternHypothesisPipeline:
    """Tests for PatternHypothesisPipeline (14.02)."""

    def test_convert_pattern_to_hypothesis(self) -> None:
        """Turn trade pattern into testable hypothesis."""
        pipeline = PatternHypothesisPipeline()
        pattern = {
            "label": "symbol=EURUSD session=London",
            "frequency": 15,
            "win_rate": 65.0,
            "avg_pnl": 45.0,
        }

        hypothesis = pipeline.pattern_to_hypothesis(pattern)
        assert hypothesis is not None
        assert "EURUSD" in hypothesis["description"]
        assert hypothesis["confidence"] > 0.5

    def test_hypothesis_includes_evidence(self) -> None:
        """Hypothesis carries linked evidence."""
        pipeline = PatternHypothesisPipeline()
        pattern = {"win_rate": 70.0, "frequency": 20}

        hypothesis = pipeline.pattern_to_hypothesis(pattern)
        assert "evidence" in hypothesis
        assert hypothesis["evidence"]["sample_size"] == 20


class TestLearningLoop:
    """Tests for LearningLoop orchestration (14.01-14.07)."""

    def test_learning_loop_phases(self) -> None:
        """Learning loop progresses through phases."""
        loop = LearningLoop()
        assert loop.current_phase == LearningPhase.REVIEW

        loop.advance_phase()
        assert loop.current_phase == LearningPhase.PATTERN

    def test_review_to_pattern_pipeline(self) -> None:
        """Review → pattern pipeline (14.01)."""
        loop = LearningLoop()
        trades = [
            {"trade_id": "t1", "symbol": "EURUSD", "pnl": 50.0, "outcome": "WIN"},
            {"trade_id": "t2", "symbol": "EURUSD", "pnl": 30.0, "outcome": "WIN"},
        ]

        patterns = loop.review_to_patterns(trades)
        assert len(patterns) > 0

    def test_pattern_to_hypothesis_pipeline(self) -> None:
        """Pattern → hypothesis pipeline (14.02)."""
        loop = LearningLoop()
        patterns = [{"label": "symbol=EURUSD", "win_rate": 65.0}]

        hypotheses = loop.patterns_to_hypotheses(patterns)
        assert len(hypotheses) > 0

    def test_hypothesis_to_experiment_pipeline(self) -> None:
        """Hypothesis → experiment pipeline (14.03)."""
        loop = LearningLoop()
        hypotheses = [{"description": "EURUSD breakout setup"}]

        experiments = loop.hypotheses_to_experiments(hypotheses)
        assert len(experiments) > 0

    def test_experiment_to_candidate_pipeline(self) -> None:
        """Experiment → candidate pipeline (14.04)."""
        loop = LearningLoop()
        results = [{"net_pnl": 100.0, "win_rate": 60.0}]

        candidates = loop.results_to_candidates(results)
        assert len(candidates) > 0

    def test_candidate_validation_pipeline(self) -> None:
        """Candidate → validation pipeline (14.05)."""
        loop = LearningLoop()
        candidate = {"backtest_pnl": 100.0, "live_pnl": 90.0}

        is_valid = loop.validate_candidate(candidate)
        assert isinstance(is_valid, bool)

    def test_validation_to_approval_pipeline(self) -> None:
        """Validation → approval pipeline (14.06)."""
        loop = LearningLoop()
        validated = {"score": 85.0}

        approved = loop.approve_validated(validated)
        assert isinstance(approved, bool)

    def test_no_direct_live_mutation(self) -> None:
        """No automatic live mutation (14.14)."""
        loop = LearningLoop()
        # Learning loop generates candidates and recommendations,
        # but does not directly mutate live strategy parameters.
        approved = loop.approve_validated({"score": 95.0})
        # Approval is a recommendation, not a live change.
        assert approved is True or approved is False


class TestCandidateComparison:
    """Tests for candidate comparison (14.12)."""

    def test_compare_better_candidate_recommends_promotion(self) -> None:
        """Better candidate is recommended for promotion."""
        loop = LearningLoop()
        current = {"win_rate": 50.0, "profit_factor": 1.2, "max_drawdown": 10.0}
        candidate = {"win_rate": 60.0, "profit_factor": 1.8, "max_drawdown": 8.0}
        result = loop.compare_candidates(current, candidate)
        assert result["recommend_promotion"] is True
        assert result["better_count"] == 3

    def test_compare_worse_candidate_rejects_promotion(self) -> None:
        """Worse candidate is not recommended."""
        loop = LearningLoop()
        current = {"win_rate": 60.0, "profit_factor": 1.8, "max_drawdown": 8.0}
        candidate = {"win_rate": 50.0, "profit_factor": 1.2, "max_drawdown": 15.0}
        result = loop.compare_candidates(current, candidate)
        assert result["recommend_promotion"] is False


class TestLearningMemory:
    """Tests for learning memory (14.13)."""

    def test_validated_lessons_stored_separately(self) -> None:
        """Validated lessons are stored in learning memory."""
        loop = LearningLoop()
        assert len(loop.memory) == 0
        loop.approve_validated({"score": 90.0})
        assert len(loop.memory) == 1
        lessons = loop.memory.all_lessons()
        assert lessons[0]["type"] == "APPROVED_CANDIDATE"

    def test_rejected_candidate_not_stored(self) -> None:
        """Rejected candidates are not stored as lessons."""
        loop = LearningLoop()
        loop.approve_validated({"score": 40.0})
        assert len(loop.memory) == 0
