# -*- coding: utf-8 -*-
"""Trade Review — Post-trade analysis with MAE/MFE, quality scores, and outcome classification.

Phase 17 component for systematic review of closed trades.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class TradeReviewResult:
    """Result of post-trade analysis.

    Attributes:
        trade_id: Unique trade identifier.
        outcome: "WIN" if PnL > 0, "LOSS" if PnL <= 0.
        pnl: Profit/loss amount in account currency.
        mae: Maximum Adverse Excursion as percentage of entry price.
        mfe: Maximum Favorable Excursion as percentage of entry price.
        timing_score: Entry/exit timing quality (0-100), relative to S/R levels.
        decision_quality_score: Agent recommendation vs actual outcome (0-100).
        execution_quality_score: Execution quality based on retries/slippage (0-100).
        summary: Human-readable review summary.
    """

    trade_id: str
    outcome: str
    pnl: float
    mae: float
    mfe: float
    timing_score: float
    decision_quality_score: float
    execution_quality_score: float
    summary: str


class TradeReviewer:
    """Post-trade analyzer computing MAE/MFE, timing, decision, and execution quality."""

    def __init__(self) -> None:
        """Initialize the trade reviewer."""
        pass

    def compute_mae_mfe(
        self,
        entry_price: float,
        prices_history: list[float],
        exit_price: float,
        direction: str,
    ) -> tuple[float, float]:
        """Compute Maximum Adverse/Favorable Excursion as percentage of entry price.

        Args:
            entry_price: Trade entry price.
            prices_history: Sequence of prices during trade lifetime (chronological).
            exit_price: Trade exit price.
            direction: "BUY" or "SELL".

        Returns:
            Tuple of (mae_pct, mfe_pct) as percentages of entry price.
        """
        if entry_price <= 0:
            logger.warning("Entry price <= 0, cannot compute MAE/MFE")
            return (0.0, 0.0)

        if not prices_history:
            prices_history = [entry_price, exit_price]

        all_prices = [entry_price] + list(prices_history) + [exit_price]
        dir_upper = direction.upper()

        if dir_upper == "BUY":
            # MAE: worst drawdown (lowest price below entry)
            worst_price = min(all_prices)
            mae_pct = ((entry_price - worst_price) / entry_price) * 100.0

            # MFE: best runup (highest price above entry)
            best_price = max(all_prices)
            mfe_pct = ((best_price - entry_price) / entry_price) * 100.0

        elif dir_upper == "SELL":
            # MAE: worst drawdown (highest price above entry)
            worst_price = max(all_prices)
            mae_pct = ((worst_price - entry_price) / entry_price) * 100.0

            # MFE: best runup (lowest price below entry)
            best_price = min(all_prices)
            mfe_pct = ((entry_price - best_price) / entry_price) * 100.0

        else:
            logger.warning("Unknown direction '%s', returning 0 MAE/MFE", direction)
            return (0.0, 0.0)

        return (round(mae_pct, 2), round(mfe_pct, 2))

    def analyze_win_loss(self, pnl: float) -> tuple[str, float]:
        """Classify trade outcome as WIN or LOSS.

        Args:
            pnl: Trade profit/loss in account currency.

        Returns:
            Tuple of (outcome, pnl) where outcome is "WIN" or "LOSS".
        """
        outcome = "WIN" if pnl > 0 else "LOSS"
        return (outcome, pnl)

    def score_timing(
        self,
        entry_price: float,
        support: Optional[float],
        resistance: Optional[float],
        direction: str,
    ) -> float:
        """Score entry timing quality relative to support/resistance levels.

        Args:
            entry_price: Trade entry price.
            support: Nearest support level (None if unavailable).
            resistance: Nearest resistance level (None if unavailable).
            direction: "BUY" or "SELL".

        Returns:
            Timing score 0-100. Higher means better entry relative to S/R.
        """
        if entry_price <= 0:
            return 0.0

        dir_upper = direction.upper()
        score = 50.0  # Neutral baseline

        if dir_upper == "BUY":
            if support is not None and support > 0:
                # Good BUY: entry near support
                distance_to_support = abs(entry_price - support)
                support_range = max(support * 0.01, 0.0001)
                proximity = max(0.0, 1.0 - (distance_to_support / support_range))
                score = 50.0 + (proximity * 50.0)

        elif dir_upper == "SELL":
            if resistance is not None and resistance > 0:
                # Good SELL: entry near resistance
                distance_to_resistance = abs(entry_price - resistance)
                resistance_range = max(resistance * 0.01, 0.0001)
                proximity = max(0.0, 1.0 - (distance_to_resistance / resistance_range))
                score = 50.0 + (proximity * 50.0)

        return round(min(100.0, max(0.0, score)), 2)

    def score_decision_quality(
        self,
        agent_outputs: dict[str, Any],
        outcome: str,
    ) -> float:
        """Score the quality of the *decision process* (not the outcome).

        Audit P2-6: decision quality must be independent of the trade result so
        that a good decision that lost is not scored as a bad decision (and a
        lucky win is not scored as a good one). The ``outcome`` argument is kept
        for API compatibility but does NOT contribute to the score.

        Process signals used:
        * signal strength (non-HOLD) — a decision was actually taken,
        * confidence calibration — higher confidence scores higher, but capped,
        * reasoning presence — evidence was attached to the decision.

        Args:
            agent_outputs: Dictionary with agent recommendation data
                (``confidence`` 0-1, ``signal``, optional ``reasoning``).
            outcome: Kept for backwards compatibility; not used in the score.

        Returns:
            Decision quality score 0-100 reflecting the decision process only.
        """
        confidence = agent_outputs.get("confidence", 0.5)
        signal = agent_outputs.get("signal", "HOLD")
        reasoning = agent_outputs.get("reasoning")

        # Base: confidence calibration (0-1 → 0-60).
        try:
            base_score = float(confidence) * 60.0
        except (TypeError, ValueError):
            base_score = 0.0

        # A concrete decision (non-HOLD) is a positive process signal.
        signal_bonus = 25.0 if str(signal).upper() != "HOLD" else 0.0

        # Evidence attached to the decision (reasoning present) is a positive
        # process signal — independent of whether the trade won or lost.
        has_reasoning = bool(reasoning) if not isinstance(reasoning, list) else len(reasoning) > 0
        reasoning_bonus = 15.0 if has_reasoning else 0.0

        score = base_score + signal_bonus + reasoning_bonus
        return round(min(100.0, max(0.0, score)), 2)

    def score_execution_quality(
        self,
        retries: int,
        slippage: float,
    ) -> float:
        """Score execution quality based on retry count and slippage.

        Args:
            retries: Number of retry attempts during execution.
            slippage: Price slippage as percentage of entry price.

        Returns:
            Execution quality score 0-100. Perfect execution = 100.
        """
        # Start at 100, deduct for retries and slippage
        score = 100.0

        # Deduct 10 points per retry
        retry_penalty = retries * 10.0
        score -= retry_penalty

        # Deduct points for slippage (1% slippage = -20 points)
        slippage_penalty = abs(slippage) * 20.0
        score -= slippage_penalty

        return round(min(100.0, max(0.0, score)), 2)

    def review_trade(
        self,
        trade_memory_record: dict[str, Any],
        price_history: list[float],
        support: Optional[float] = None,
        resistance: Optional[float] = None,
    ) -> TradeReviewResult:
        """Perform comprehensive post-trade review.

        Args:
            trade_memory_record: Dict with keys:
                - trade_id: str
                - entry_price: float
                - exit_price: float
                - direction: str ("BUY" or "SELL")
                - pnl: float
                - agent_outputs: dict (with "confidence", "signal")
                - retries: int (default 0)
                - slippage: float (default 0.0)
            price_history: List of prices during trade lifetime.
            support: Optional support level for timing analysis.
            resistance: Optional resistance level for timing analysis.

        Returns:
            TradeReviewResult with all computed metrics.
        """
        trade_id = trade_memory_record.get("trade_id", "UNKNOWN")
        entry_price = trade_memory_record.get("entry_price", 0.0)
        exit_price = trade_memory_record.get("exit_price", 0.0)
        direction = trade_memory_record.get("direction", "BUY")
        pnl = trade_memory_record.get("pnl", 0.0)
        agent_outputs = trade_memory_record.get("agent_outputs", {})
        retries = trade_memory_record.get("retries", 0)
        slippage = trade_memory_record.get("slippage", 0.0)

        # Win/loss classification
        outcome, pnl_val = self.analyze_win_loss(pnl)

        # MAE/MFE
        mae, mfe = self.compute_mae_mfe(entry_price, price_history, exit_price, direction)

        # Timing score
        timing_score = self.score_timing(entry_price, support, resistance, direction)

        # Decision quality
        decision_quality_score = self.score_decision_quality(agent_outputs, outcome)

        # Execution quality
        execution_quality_score = self.score_execution_quality(retries, slippage)

        # Summary
        summary = (
            f"Trade {trade_id}: {outcome} (PnL={pnl_val:.2f}). "
            f"MAE={mae:.2f}%, MFE={mfe:.2f}%. "
            f"Timing={timing_score:.0f}, Decision={decision_quality_score:.0f}, "
            f"Execution={execution_quality_score:.0f}."
        )

        logger.info("Trade review complete: %s", summary)

        return TradeReviewResult(
            trade_id=trade_id,
            outcome=outcome,
            pnl=pnl_val,
            mae=mae,
            mfe=mfe,
            timing_score=timing_score,
            decision_quality_score=decision_quality_score,
            execution_quality_score=execution_quality_score,
            summary=summary,
        )
