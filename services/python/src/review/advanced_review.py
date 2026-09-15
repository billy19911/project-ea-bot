# -*- coding: utf-8 -*-
"""Advanced trade review — root-cause, pattern extraction, session analysis,
counterfactual, committee quality, and learning journal (EPIC 11.07–11.14).

Extends the base TradeReviewer with deeper post-trade analytics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 11.07 Root-cause classification
# ---------------------------------------------------------------------------

ROOT_CAUSE_CATEGORIES = [
    "analytical_error",
    "timing_error",
    "regime_mismatch",
    "news_impact",
    "execution_slippage",
    "risk_issue",
    "normal_loss",
]


@dataclass
class RootCauseClassification:
    """Result of root-cause analysis for a closed trade."""

    primary_cause: str
    secondary_causes: list[str] = field(default_factory=list)
    confidence: float = 0.0
    explanation: str = ""


def classify_root_cause(
    review_data: dict[str, Any],
    regime_at_entry: Optional[str] = None,
    regime_at_exit: Optional[str] = None,
    news_events: Optional[list[dict[str, Any]]] = None,
) -> RootCauseClassification:
    """Classify why a trade won or lost (11.07).

    Args:
        review_data: Dict with keys from TradeReviewResult plus
            ``decision_quality_score``, ``execution_quality_score``,
            ``timing_score``, ``mae``, ``mfe``.
        regime_at_entry: Market regime label at entry (e.g. "trend_up").
        regime_at_exit: Market regime label at exit.
        news_events: List of news event dicts with ``impact`` key
            (``high`` / ``medium`` / ``low``) during trade lifetime.

    Returns:
        RootCauseClassification with primary cause, secondary causes,
        confidence (0–1), and human-readable explanation.
    """
    outcome = review_data.get("outcome", "LOSS")
    decision_q = review_data.get("decision_quality_score", 50.0)
    execution_q = review_data.get("execution_quality_score", 100.0)
    timing_q = review_data.get("timing_score", 50.0)
    mae = review_data.get("mae", 0.0)
    mfe = review_data.get("mfe", 0.0)

    secondary: list[str] = []
    explanation_parts: list[str] = []

    # Check news impact first — high-impact news overrides other causes
    high_impact_news = False
    if news_events:
        for ev in news_events:
            if ev.get("impact", "low") == "high":
                high_impact_news = True
                break

    # Check regime mismatch
    regime_changed = (
        regime_at_entry is not None
        and regime_at_exit is not None
        and regime_at_entry != regime_at_exit
    )

    if outcome == "WIN":
        if decision_q >= 70:
            primary = "analytical_error"
            explanation_parts.append("Decision quality high — correct analysis.")
        elif mfe > mae * 2:
            primary = "normal_loss"
            explanation_parts.append("Favorable excursion dominated — normal win.")
        else:
            primary = "normal_loss"
            explanation_parts.append("Normal probabilistic win.")
    else:
        # LOSS — determine root cause
        if high_impact_news:
            primary = "news_impact"
            explanation_parts.append("High-impact news during trade lifetime.")
            secondary.append("normal_loss")
        elif regime_changed:
            primary = "regime_mismatch"
            explanation_parts.append(f"Regime changed {regime_at_entry} → {regime_at_exit}.")
            secondary.append("analytical_error")
        elif execution_q < 60:
            primary = "execution_slippage"
            explanation_parts.append(f"Execution quality low ({execution_q:.0f}).")
            secondary.append("timing_error")
        elif timing_q < 40:
            primary = "timing_error"
            explanation_parts.append(f"Timing quality low ({timing_q:.0f}).")
        elif decision_q < 40:
            primary = "analytical_error"
            explanation_parts.append(f"Decision quality low ({decision_q:.0f}).")
        else:
            primary = "normal_loss"
            explanation_parts.append("Normal probabilistic loss.")

    # Risk issue: large adverse excursion relative to MFE
    if outcome == "LOSS" and mae > 0 and mfe > 0 and mae > mfe * 3:
        if primary != "news_impact" and primary != "regime_mismatch":
            secondary.append("risk_issue")
        elif "risk_issue" not in secondary:
            secondary.insert(0, "risk_issue")

    confidence = 0.5
    if primary == "news_impact" and high_impact_news:
        confidence = 0.9
    elif primary == "regime_mismatch" and regime_changed:
        confidence = 0.85
    elif primary == "execution_slippage" and execution_q < 60:
        confidence = 0.8
    elif primary == "timing_error" and timing_q < 40:
        confidence = 0.75
    elif primary == "analytical_error" and decision_q < 40:
        confidence = 0.7
    elif primary == "normal_loss":
        confidence = 0.6
    else:
        confidence = 0.5

    explanation = " ".join(explanation_parts)

    logger.info(
        "Root-cause for trade %s: %s (conf=%.2f)",
        review_data.get("trade_id", "?"),
        primary,
        confidence,
    )

    return RootCauseClassification(
        primary_cause=primary,
        secondary_causes=secondary,
        confidence=round(confidence, 2),
        explanation=explanation,
    )


# ---------------------------------------------------------------------------
# 11.08 Strategy-vs-execution attribution
# ---------------------------------------------------------------------------


@dataclass
class AttributionResult:
    """Strategy vs execution attribution for a trade."""

    strategy_attribution: float  # -1..1, negative = strategy hurt
    execution_attribution: float  # -1..1, negative = execution hurt
    dominant_factor: str  # "strategy" | "execution" | "balanced"
    explanation: str = ""


def attribute_strategy_vs_execution(
    review_data: dict[str, Any],
) -> AttributionResult:
    """Attribute PnL to strategy vs execution factors (11.08).

    Args:
        review_data: Dict with ``decision_quality_score``,
            ``execution_quality_score``, ``pnl``, ``mae``, ``mfe``.

    Returns:
        AttributionResult with strategy/execution scores and dominant factor.
    """
    decision_q = review_data.get("decision_quality_score", 50.0)
    execution_q = review_data.get("execution_quality_score", 100.0)
    pnl = review_data.get("pnl", 0.0)

    # Normalize to -1..1 range (50 = neutral, 100 = perfect, 0 = worst)
    strategy_attr = (decision_q - 50.0) / 50.0
    execution_attr = (execution_q - 100.0) / 100.0

    abs_s = abs(strategy_attr)
    abs_e = abs(execution_attr)

    if abs_s > abs_e * 1.5:
        dominant = "strategy"
    elif abs_e > abs_s * 1.5:
        dominant = "execution"
    else:
        dominant = "balanced"

    explanation = (
        f"Strategy attr={strategy_attr:+.2f}, "
        f"Execution attr={execution_attr:+.2f}, "
        f"dominant={dominant}, PnL={pnl:.2f}."
    )

    return AttributionResult(
        strategy_attribution=round(strategy_attr, 3),
        execution_attribution=round(execution_attr, 3),
        dominant_factor=dominant,
        explanation=explanation,
    )


# ---------------------------------------------------------------------------
# 11.09 / 11.10 Winning / losing pattern extraction
# ---------------------------------------------------------------------------


@dataclass
class TradePattern:
    """Extracted pattern from a set of trades."""

    label: str
    frequency: int
    win_rate: float
    avg_pnl: float
    conditions: dict[str, Any] = field(default_factory=dict)
    examples: list[str] = field(default_factory=list)


def extract_patterns(
    trades: list[dict[str, Any]],
    outcome_filter: str = "WIN",
    min_frequency: int = 2,
) -> list[TradePattern]:
    """Extract recurring conditions from winning or losing trades (11.09/11.10).

    Args:
        trades: List of trade dicts with keys ``outcome``, ``pnl``,
            ``symbol``, ``direction``, ``session``, ``regime``,
            ``setup``, ``hour``.
        outcome_filter: ``"WIN"`` for winning patterns (11.09),
            ``"LOSS"`` for losing patterns (11.10).
        min_frequency: Minimum occurrences to report a pattern.

    Returns:
        List of TradePattern sorted by frequency (descending).
    """
    filtered = [t for t in trades if t.get("outcome") == outcome_filter]
    if not filtered:
        return []

    # Dimensions to group by
    dimensions = ["symbol", "session", "regime", "setup", "hour", "direction"]
    patterns: list[TradePattern] = []

    for dim in dimensions:
        groups: dict[str, list[dict[str, Any]]] = {}
        for t in filtered:
            val = str(t.get(dim, "unknown"))
            groups.setdefault(val, []).append(t)

        for label, group in groups.items():
            if len(group) < min_frequency:
                continue
            pnls = [g.get("pnl", 0.0) for g in group]
            wins = sum(1 for p in pnls if p > 0)
            win_rate = (wins / len(group) * 100.0) if group else 0.0
            avg_pnl = sum(pnls) / len(pnls) if pnls else 0.0

            patterns.append(
                TradePattern(
                    label=f"{dim}={label}",
                    frequency=len(group),
                    win_rate=round(win_rate, 2),
                    avg_pnl=round(avg_pnl, 2),
                    conditions={dim: label},
                    examples=[g.get("trade_id", "?") for g in group[:3]],
                )
            )

    patterns.sort(key=lambda p: p.frequency, reverse=True)
    return patterns


# ---------------------------------------------------------------------------
# 11.11 Time / session analysis
# ---------------------------------------------------------------------------


@dataclass
class SessionAnalysis:
    """Performance breakdown by time dimension."""

    dimension: str
    breakdown: dict[str, dict[str, float]] = field(default_factory=dict)


def analyze_by_time(
    trades: list[dict[str, Any]],
) -> list[SessionAnalysis]:
    """Measure performance by hour, session, and day (11.11).

    Args:
        trades: List of trade dicts with optional keys ``hour``,
            ``session``, ``day``, ``pnl``, ``outcome``.

    Returns:
        List of SessionAnalysis, one per dimension found in data.
    """
    results: list[SessionAnalysis] = []

    for dim in ("hour", "session", "day"):
        groups: dict[str, list[dict[str, Any]]] = {}
        for t in trades:
            val = str(t.get(dim, "unknown"))
            groups.setdefault(val, []).append(t)

        if not groups:
            continue

        breakdown: dict[str, dict[str, float]] = {}
        for label, group in groups.items():
            pnls = [g.get("pnl", 0.0) for g in group]
            wins = sum(1 for p in pnls if p > 0)
            total = len(group)
            breakdown[label] = {
                "count": float(total),
                "win_rate": round(wins / total * 100.0, 2) if total else 0.0,
                "avg_pnl": round(sum(pnls) / total, 2) if total else 0.0,
                "total_pnl": round(sum(pnls), 2),
            }

        results.append(SessionAnalysis(dimension=dim, breakdown=breakdown))

    return results


# ---------------------------------------------------------------------------
# 11.12 No-trade / counterfactual review
# ---------------------------------------------------------------------------


@dataclass
class CounterfactualReview:
    """Evaluation of WAIT/NO_TRADE decisions."""

    trade_id: str
    decision: str
    counterfactual_pnl: float
    avoided_adverse: bool
    missed_opportunity: bool
    explanation: str = ""


def review_no_trade(
    decision_id: str,
    decision: str,
    subsequent_price_move: float,
    threshold: float = 0.0,
) -> CounterfactualReview:
    """Evaluate whether WAIT/NO_TRADE avoided adverse outcomes (11.12).

    Args:
        decision_id: Identifier for the no-trade decision.
        decision: ``"WAIT"`` or ``"NO_TRADE"``.
        subsequent_price_move: Price change (in pips or %) after the
            decision that would have been the trade direction.
            Positive = favorable, negative = adverse.
        threshold: Breakeven threshold (default 0.0).

    Returns:
        CounterfactualReview with avoided_adverse and missed_opportunity flags.
    """
    avoided_adverse = subsequent_price_move < threshold
    missed_opportunity = subsequent_price_move > abs(threshold)

    if avoided_adverse:
        explanation = (
            f"{decision} was correct — subsequent move "
            f"{subsequent_price_move:+.2f} was adverse."
        )
    elif missed_opportunity:
        explanation = (
            f"{decision} missed opportunity — subsequent move "
            f"{subsequent_price_move:+.2f} was favorable."
        )
    else:
        explanation = (
            f"{decision} was neutral — subsequent move "
            f"{subsequent_price_move:+.2f} near threshold."
        )

    return CounterfactualReview(
        trade_id=decision_id,
        decision=decision,
        counterfactual_pnl=subsequent_price_move,
        avoided_adverse=avoided_adverse,
        missed_opportunity=missed_opportunity,
        explanation=explanation,
    )


# ---------------------------------------------------------------------------
# 11.13 Committee decision quality
# ---------------------------------------------------------------------------


@dataclass
class CommitteeQuality:
    """Quality assessment of committee/consensus decisions."""

    directionally_correct: bool
    tactical_score: float
    consensus_strength: float
    explanation: str = ""


def evaluate_committee_quality(
    committee_decision: dict[str, Any],
    actual_outcome: str,
) -> CommitteeQuality:
    """Measure whether consensus was directionally correct (11.13).

    Args:
        committee_decision: Dict with ``signal`` (BUY/SELL/HOLD/WAIT),
            ``consensus_pct`` (0–100), ``confidence`` (0–1).
        actual_outcome: ``"WIN"`` or ``"LOSS"``.

    Returns:
        CommitteeQuality with directional correctness and tactical score.
    """
    signal = committee_decision.get("signal", "HOLD").upper()
    consensus_pct = committee_decision.get("consensus_pct", 50.0)
    confidence = committee_decision.get("confidence", 0.5)

    # Directionally correct: non-HOLD signal that resulted in WIN
    directionally_correct = signal != "HOLD" and actual_outcome == "WIN"

    # Tactical score: weighted consensus and confidence, outcome-adjusted
    base = (consensus_pct / 100.0) * 50.0 + confidence * 30.0
    if directionally_correct:
        base += 20.0
    elif signal != "HOLD" and actual_outcome == "LOSS":
        base -= 20.0

    tactical_score = round(min(100.0, max(0.0, base)), 2)
    consensus_strength = round(consensus_pct / 100.0, 2)

    explanation = (
        f"Signal={signal}, consensus={consensus_pct:.0f}%, "
        f"outcome={actual_outcome}, "
        f"directionally_correct={directionally_correct}."
    )

    return CommitteeQuality(
        directionally_correct=directionally_correct,
        tactical_score=tactical_score,
        consensus_strength=consensus_strength,
        explanation=explanation,
    )


# ---------------------------------------------------------------------------
# 11.14 Learning journal
# ---------------------------------------------------------------------------


@dataclass
class JournalEntry:
    """A structured learning journal entry."""

    id: str
    trade_id: str
    timestamp: datetime
    lesson: str
    evidence: list[str] = field(default_factory=list)
    linked_hypothesis: Optional[str] = None
    tags: list[str] = field(default_factory=list)


class LearningJournal:
    """Persist structured trade reviews, lessons, and evidence (11.14)."""

    def __init__(self) -> None:
        """Initialize empty journal."""
        self._entries: dict[str, JournalEntry] = {}
        self._counter = 0

    def add_entry(
        self,
        trade_id: str,
        lesson: str,
        evidence: Optional[list[str]] = None,
        linked_hypothesis: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> JournalEntry:
        """Add a new learning journal entry.

        Args:
            trade_id: Trade this lesson is derived from.
            lesson: The lesson text.
            evidence: Supporting evidence strings.
            linked_hypothesis: Hypothesis ID this relates to.
            tags: Categorization tags.

        Returns:
            Created JournalEntry.
        """
        self._counter += 1
        entry_id = f"LJ-{self._counter:04d}"
        entry = JournalEntry(
            id=entry_id,
            trade_id=trade_id,
            timestamp=datetime.now(timezone.utc),
            lesson=lesson,
            evidence=evidence or [],
            linked_hypothesis=linked_hypothesis,
            tags=tags or [],
        )
        self._entries[entry_id] = entry
        logger.info("Journal entry %s added for trade %s", entry_id, trade_id)
        return entry

    def get_entry(self, entry_id: str) -> Optional[JournalEntry]:
        """Retrieve a journal entry by ID."""
        return self._entries.get(entry_id)

    def get_by_trade(self, trade_id: str) -> list[JournalEntry]:
        """Get all journal entries for a given trade."""
        return [e for e in self._entries.values() if e.trade_id == trade_id]

    def get_by_tag(self, tag: str) -> list[JournalEntry]:
        """Get all journal entries with a given tag."""
        return [e for e in self._entries.values() if tag in e.tags]

    def all_entries(self) -> list[JournalEntry]:
        """Return all journal entries, sorted by timestamp."""
        return sorted(self._entries.values(), key=lambda e: e.timestamp)

    def to_dict(self) -> list[dict[str, Any]]:
        """Serialize all entries to list of dicts."""
        return [
            {
                "id": e.id,
                "trade_id": e.trade_id,
                "timestamp": e.timestamp.isoformat(),
                "lesson": e.lesson,
                "evidence": e.evidence,
                "linked_hypothesis": e.linked_hypothesis,
                "tags": e.tags,
            }
            for e in self.all_entries()
        ]
