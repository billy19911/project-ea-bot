# -*- coding: utf-8 -*-
"""Tests for the Trade Review module (Phase 17)."""

import pytest

from src.review import TradeReviewer, TradeReviewResult


@pytest.fixture
def reviewer() -> TradeReviewer:
    return TradeReviewer()


@pytest.fixture
def winning_buy_trade() -> dict:
    return {
        "trade_id": "T001",
        "entry_price": 1.1000,
        "exit_price": 1.1100,
        "direction": "BUY",
        "pnl": 100.0,
        "agent_outputs": {"confidence": 0.8, "signal": "BUY"},
        "retries": 0,
        "slippage": 0.0,
    }


@pytest.fixture
def losing_buy_trade() -> dict:
    return {
        "trade_id": "T002",
        "entry_price": 1.1000,
        "exit_price": 1.0900,
        "direction": "BUY",
        "pnl": -100.0,
        "agent_outputs": {"confidence": 0.6, "signal": "BUY"},
        "retries": 2,
        "slippage": 0.05,
    }


@pytest.fixture
def winning_sell_trade() -> dict:
    return {
        "trade_id": "T003",
        "entry_price": 1.1000,
        "exit_price": 1.0900,
        "direction": "SELL",
        "pnl": 100.0,
        "agent_outputs": {"confidence": 0.7, "signal": "SELL"},
        "retries": 0,
        "slippage": 0.0,
    }


class TestMAEMFE:
    """Tests for Maximum Adverse/Favorable Excursion computation."""

    def test_mae_mfe_buy_trade(self, reviewer: TradeReviewer) -> None:
        # BUY trade: prices dip then rally
        entry = 1.1000
        prices = [1.0950, 1.0900, 1.0980, 1.1050, 1.1120]
        exit_price = 1.1100
        mae, mfe = reviewer.compute_mae_mfe(entry, prices, exit_price, "BUY")

        # MAE: entry=1.10, lowest=1.09 → adverse = (1.10-1.09)/1.10 = 0.909%
        assert mae == pytest.approx(0.91, abs=0.01)
        # MFE: highest=1.112 → favorable = (1.112-1.10)/1.10 = 1.09%
        assert mfe == pytest.approx(1.09, abs=0.01)

    def test_mae_mfe_sell_trade(self, reviewer: TradeReviewer) -> None:
        # SELL trade: prices rally then drop
        entry = 1.1000
        prices = [1.1050, 1.1100, 1.0980, 1.0900, 1.0880]
        exit_price = 1.0900
        mae, mfe = reviewer.compute_mae_mfe(entry, prices, exit_price, "SELL")

        # MAE: highest=1.110 → adverse = (1.110-1.10)/1.10 = 0.909%
        assert mae == pytest.approx(0.91, abs=0.01)
        # MFE: lowest=1.088 → favorable = (1.10-1.088)/1.10 = 1.09%
        assert mfe == pytest.approx(1.09, abs=0.01)

    def test_mae_mfe_empty_price_history(self, reviewer: TradeReviewer) -> None:
        entry = 1.1000
        exit_price = 1.1100
        mae, mfe = reviewer.compute_mae_mfe(entry, [], exit_price, "BUY")

        # Should fallback to [entry, exit]
        assert mae == pytest.approx(0.0, abs=0.01)
        assert mfe == pytest.approx(0.91, abs=0.01)

    def test_mae_mfe_zero_entry(self, reviewer: TradeReviewer) -> None:
        mae, mfe = reviewer.compute_mae_mfe(0.0, [1.0, 2.0], 1.5, "BUY")
        assert mae == 0.0
        assert mfe == 0.0

    def test_mae_mfe_invalid_direction(self, reviewer: TradeReviewer) -> None:
        mae, mfe = reviewer.compute_mae_mfe(1.1000, [1.0, 2.0], 1.5, "HOLD")
        assert mae == 0.0
        assert mfe == 0.0

    def test_mae_mfe_buy_no_drawdown(self, reviewer: TradeReviewer) -> None:
        # Prices only go up
        entry = 1.1000
        prices = [1.1050, 1.1100, 1.1150]
        exit_price = 1.1200
        mae, mfe = reviewer.compute_mae_mfe(entry, prices, exit_price, "BUY")

        # No adverse movement → MAE=0
        assert mae == pytest.approx(0.0, abs=0.01)
        # Best price = 1.1200 → MFE = (1.12-1.10)/1.10 = 1.818%
        assert mfe == pytest.approx(1.82, abs=0.01)


class TestWinLossClassification:
    """Tests for trade outcome classification."""

    def test_win_classification(self, reviewer: TradeReviewer) -> None:
        outcome, pnl = reviewer.analyze_win_loss(150.0)
        assert outcome == "WIN"
        assert pnl == 150.0

    def test_loss_classification(self, reviewer: TradeReviewer) -> None:
        outcome, pnl = reviewer.analyze_win_loss(-50.0)
        assert outcome == "LOSS"
        assert pnl == -50.0

    def test_breakeven_is_loss(self, reviewer: TradeReviewer) -> None:
        outcome, _ = reviewer.analyze_win_loss(0.0)
        assert outcome == "LOSS"


class TestTimingScore:
    """Tests for entry timing scoring."""

    def test_buy_near_support(self, reviewer: TradeReviewer) -> None:
        # Entry right at support → score should be high
        score = reviewer.score_timing(1.1000, support=1.1000, resistance=1.1200, direction="BUY")
        assert score == 100.0

    def test_buy_far_from_support(self, reviewer: TradeReviewer) -> None:
        # Entry far from support → score should be lower (close to neutral 50)
        score = reviewer.score_timing(1.1000, support=1.0000, resistance=1.1200, direction="BUY")
        # Distance to support = 0.10, support_range = 0.01, proximity = max(0, 1-0.10/0.01) = 0
        assert score == 50.0

    def test_sell_near_resistance(self, reviewer: TradeReviewer) -> None:
        score = reviewer.score_timing(1.1000, support=1.0800, resistance=1.1000, direction="SELL")
        assert score == 100.0

    def test_sell_far_from_resistance(self, reviewer: TradeReviewer) -> None:
        score = reviewer.score_timing(1.1000, support=1.0800, resistance=1.2000, direction="SELL")
        assert score == 50.0

    def test_no_support_or_resistance(self, reviewer: TradeReviewer) -> None:
        # Without S/R, should be neutral baseline
        score = reviewer.score_timing(1.1000, support=None, resistance=None, direction="BUY")
        assert score == 50.0

    def test_zero_entry_price(self, reviewer: TradeReviewer) -> None:
        score = reviewer.score_timing(0.0, support=1.0, resistance=1.2, direction="BUY")
        assert score == 0.0

    def test_unknown_direction(self, reviewer: TradeReviewer) -> None:
        score = reviewer.score_timing(1.1000, support=1.0, resistance=1.2, direction="HOLD")
        assert score == 50.0


class TestDecisionQuality:
    """Tests for agent decision quality scoring (process-only, outcome-independent).

    Audit P2-6: decision quality must NOT depend on the trade outcome, so the
    same agent inputs score identically for WIN and LOSS.
    """

    def test_win_with_buy_signal_high_confidence(self, reviewer: TradeReviewer) -> None:
        agent = {"confidence": 0.9, "signal": "BUY", "reasoning": "breakout"}
        score = reviewer.score_decision_quality(agent, "WIN")
        # base=0.9*60=54, signal_bonus=25, reasoning_bonus=15 → 94
        assert score == 94.0

    def test_loss_with_buy_signal(self, reviewer: TradeReviewer) -> None:
        agent = {"confidence": 0.6, "signal": "BUY", "reasoning": "x"}
        score = reviewer.score_decision_quality(agent, "LOSS")
        # base=0.6*60=36, signal_bonus=25, reasoning_bonus=15 → 76
        assert score == 76.0

    def test_outcome_does_not_change_the_score(self, reviewer: TradeReviewer) -> None:
        """A good process that lost must score the same as if it had won."""
        agent = {"confidence": 0.7, "signal": "BUY", "reasoning": "plan"}
        assert reviewer.score_decision_quality(agent, "WIN") == reviewer.score_decision_quality(
            agent, "LOSS"
        )

    def test_win_with_hold_signal(self, reviewer: TradeReviewer) -> None:
        agent = {"confidence": 0.5, "signal": "HOLD"}
        score = reviewer.score_decision_quality(agent, "WIN")
        # base=0.5*60=30, signal_bonus=0, reasoning_bonus=0 → 30
        assert score == 30.0

    def test_default_confidence_when_missing(self, reviewer: TradeReviewer) -> None:
        score = reviewer.score_decision_quality({}, "WIN")
        # base=0.5*60=30, signal_bonus=0 (HOLD default), reasoning_bonus=0 → 30
        assert score == 30.0


class TestExecutionQuality:
    """Tests for execution quality scoring."""

    def test_perfect_execution(self, reviewer: TradeReviewer) -> None:
        score = reviewer.score_execution_quality(retries=0, slippage=0.0)
        assert score == 100.0

    def test_retries_penalty(self, reviewer: TradeReviewer) -> None:
        score = reviewer.score_execution_quality(retries=2, slippage=0.0)
        # 100 - (2*10) = 80
        assert score == 80.0

    def test_slippage_penalty(self, reviewer: TradeReviewer) -> None:
        score = reviewer.score_execution_quality(retries=0, slippage=1.0)
        # 100 - (1.0*20) = 80
        assert score == 80.0

    def test_combined_penalty(self, reviewer: TradeReviewer) -> None:
        score = reviewer.score_execution_quality(retries=3, slippage=2.0)
        # 100 - 30 - 40 = 30
        assert score == 30.0

    def test_floor_at_zero(self, reviewer: TradeReviewer) -> None:
        score = reviewer.score_execution_quality(retries=10, slippage=10.0)
        assert score == 0.0


class TestReviewTrade:
    """Tests for the full review_trade pipeline."""

    def test_review_winning_buy_trade(
        self,
        reviewer: TradeReviewer,
        winning_buy_trade: dict,
    ) -> None:
        price_history = [1.0950, 1.0900, 1.0980, 1.1050, 1.1120]
        result = reviewer.review_trade(
            winning_buy_trade,
            price_history,
            support=1.1000,
            resistance=1.1200,
        )

        assert isinstance(result, TradeReviewResult)
        assert result.trade_id == "T001"
        assert result.outcome == "WIN"
        assert result.pnl == 100.0
        assert result.mae == pytest.approx(0.91, abs=0.01)
        assert result.mfe == pytest.approx(1.09, abs=0.01)
        assert result.timing_score == 100.0
        # Audit P2-6: process-only → base=0.8*60=48, signal=25, reasoning=0 → 73
        assert result.decision_quality_score == 73.0
        assert result.execution_quality_score == 100.0
        assert "T001" in result.summary
        assert "WIN" in result.summary

    def test_review_losing_buy_trade(
        self,
        reviewer: TradeReviewer,
        losing_buy_trade: dict,
    ) -> None:
        price_history = [1.1050, 1.0900, 1.0850, 1.0920]
        result = reviewer.review_trade(
            losing_buy_trade,
            price_history,
            support=1.0000,
            resistance=1.1200,
        )

        assert result.trade_id == "T002"
        assert result.outcome == "LOSS"
        assert result.pnl == -100.0
        # Decision: process-only base=0.6*60=36, signal=25, reasoning=0 → 61
        assert result.decision_quality_score == 61.0
        # Execution: 100 - 2*10 - 0.05*20 = 100 - 20 - 1 = 79
        assert result.execution_quality_score == 79.0
        assert "T002" in result.summary
        assert "LOSS" in result.summary

    def test_review_winning_sell_trade(
        self,
        reviewer: TradeReviewer,
        winning_sell_trade: dict,
    ) -> None:
        price_history = [1.1050, 1.1100, 1.0980, 1.0900, 1.0880]
        result = reviewer.review_trade(
            winning_sell_trade,
            price_history,
            support=1.0800,
            resistance=1.1000,
        )

        assert result.trade_id == "T003"
        assert result.outcome == "WIN"
        assert result.pnl == 100.0
        assert result.timing_score == 100.0
        # Decision: process-only base=0.7*60=42, signal=25, reasoning=0 → 67
        assert result.decision_quality_score == 67.0
        assert result.execution_quality_score == 100.0

    def test_review_without_sr_levels(
        self,
        reviewer: TradeReviewer,
        winning_buy_trade: dict,
    ) -> None:
        price_history = [1.1050, 1.1100, 1.1150]
        result = reviewer.review_trade(winning_buy_trade, price_history)

        # No S/R → timing_score falls back to neutral 50
        assert result.timing_score == 50.0

    def test_review_summary_format(
        self,
        reviewer: TradeReviewer,
        winning_buy_trade: dict,
    ) -> None:
        price_history = [1.1050, 1.1100]
        result = reviewer.review_trade(winning_buy_trade, price_history)
        # Summary should contain key metrics
        assert "MAE=" in result.summary
        assert "MFE=" in result.summary
        assert "Timing=" in result.summary
        assert "Decision=" in result.summary
        assert "Execution=" in result.summary

    def test_review_unknown_trade_id(
        self,
        reviewer: TradeReviewer,
    ) -> None:
        # Trade record without trade_id should default to "UNKNOWN"
        trade = {
            "entry_price": 1.1000,
            "exit_price": 1.1100,
            "direction": "BUY",
            "pnl": 100.0,
            "agent_outputs": {"confidence": 0.8, "signal": "BUY"},
            "retries": 0,
            "slippage": 0.0,
        }
        result = reviewer.review_trade(trade, [1.1050, 1.1100])
        assert result.trade_id == "UNKNOWN"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
