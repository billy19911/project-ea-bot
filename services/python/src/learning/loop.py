# -*- coding: utf-8 -*-
"""Learning loop orchestration — EPIC 14.

Connects trade review → pattern → hypothesis → experiment →
candidate → validation → approval without any automatic live
mutation (14.14). Also stores validated lessons (14.13) and
compares candidate vs current strategies (14.12).
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from .performance import PerformanceTracker
from .pipelines import PatternHypothesisPipeline

logger = logging.getLogger(__name__)


class LearningPhase(Enum):
    """Phases of the learning-by-doing loop (14.07)."""

    REVIEW = "REVIEW"
    PATTERN = "PATTERN"
    HYPOTHESIS = "HYPOTHESIS"
    EXPERIMENT = "EXPERIMENT"
    CANDIDATE = "CANDIDATE"
    VALIDATION = "VALIDATION"
    APPROVAL = "APPROVAL"


class LearningMemory:
    """Store validated lessons separately from raw trade history (14.13)."""

    def __init__(self) -> None:
        """Initialize empty lesson store."""
        self._lessons: list[dict[str, Any]] = []

    def add_lesson(self, lesson: dict[str, Any]) -> None:
        """Store a validated lesson."""
        self._lessons.append(dict(lesson))

    def all_lessons(self) -> list[dict[str, Any]]:
        """Return all stored lessons."""
        return list(self._lessons)

    def lessons_for(self, key: str, value: Any) -> list[dict[str, Any]]:
        """Filter lessons by a key/value pair."""
        return [ls for ls in self._lessons if ls.get(key) == value]

    def __len__(self) -> int:
        """Number of stored lessons."""
        return len(self._lessons)


class LearningLoop:
    """Orchestrate the learning-by-doing loop (14.01–14.14)."""

    def __init__(self) -> None:
        """Initialize loop at REVIEW phase."""
        self.current_phase = LearningPhase.REVIEW
        self.tracker = PerformanceTracker(min_sample_size=2)
        self.pipeline = PatternHypothesisPipeline()
        self.memory = LearningMemory()
        self._cycle: dict[str, list[Any]] = {}

    # -- Phase management (14.07) -----------------------------------------

    def advance_phase(self) -> LearningPhase:
        """Advance to the next loop phase, wrapping to REVIEW."""
        phases = list(LearningPhase)
        idx = phases.index(self.current_phase)
        self.current_phase = phases[(idx + 1) % len(phases)]
        return self.current_phase

    # -- Pipelines ---------------------------------------------------------

    def review_to_patterns(self, trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Review → pattern pipeline (14.01): group trades into patterns."""
        groups: dict[str, dict[str, Any]] = {}
        for trade in trades:
            symbol = trade.get("symbol", "UNKNOWN")
            key = f"symbol={symbol}"
            bucket = groups.setdefault(
                key,
                {"label": key, "frequency": 0, "wins": 0, "total_pnl": 0.0},
            )
            bucket["frequency"] += 1
            pnl = float(trade.get("pnl", 0.0))
            bucket["total_pnl"] += pnl
            if pnl > 0 or trade.get("outcome") == "WIN":
                bucket["wins"] += 1
        patterns = []
        for bucket in groups.values():
            freq = bucket["frequency"]
            bucket["win_rate"] = (bucket["wins"] / freq * 100.0) if freq else 0.0
            bucket["avg_pnl"] = bucket["total_pnl"] / freq if freq else 0.0
            patterns.append(bucket)
        return patterns

    def patterns_to_hypotheses(self, patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Pattern → hypothesis pipeline (14.02)."""
        hypotheses = []
        for pattern in patterns:
            hypothesis = self.pipeline.pattern_to_hypothesis(pattern)
            if hypothesis is not None:
                hypotheses.append(hypothesis)
        return hypotheses

    def hypotheses_to_experiments(self, hypotheses: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Hypothesis → experiment pipeline (14.03)."""
        return [
            {
                "experiment_id": f"exp-{i}",
                "hypothesis": h.get("description", ""),
                "status": "PENDING",
            }
            for i, h in enumerate(hypotheses)
        ]

    def results_to_candidates(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Experiment → candidate pipeline (14.04)."""
        return [
            {
                "candidate_id": f"cand-{i}",
                "source_experiment": r.get("experiment_id", f"exp-{i}"),
                "metrics": dict(r),
            }
            for i, r in enumerate(results)
        ]

    def validate_candidate(self, candidate: dict[str, Any]) -> bool:
        """Candidate → validation pipeline (14.05)."""
        backtest = float(candidate.get("backtest_pnl", 0.0))
        live = float(candidate.get("live_pnl", 0.0))
        if backtest <= 0:
            return False
        # Live performance must retain at least 50% of backtest edge
        return live >= backtest * 0.5

    def approve_validated(self, validated: dict[str, Any]) -> bool:
        """Validation → approval pipeline (14.06): recommendation only."""
        score = float(validated.get("score", 0.0))
        approved = score >= 70.0
        if approved:
            self.memory.add_lesson({"type": "APPROVED_CANDIDATE", "score": score})
        return approved

    def compare_candidates(
        self, current: dict[str, Any], candidate: dict[str, Any]
    ) -> dict[str, Any]:
        """Candidate strategy comparison using consistent metrics (14.12)."""
        metrics = ["win_rate", "profit_factor", "expectancy", "max_drawdown"]
        comparison = {}
        better = 0
        worse = 0
        for m in metrics:
            cur = float(current.get(m, 0.0))
            cand = float(candidate.get(m, 0.0))
            comparison[m] = {"current": cur, "candidate": cand}
            if m == "max_drawdown":
                # Lower drawdown is better
                if cand < cur:
                    better += 1
                elif cand > cur:
                    worse += 1
            else:
                if cand > cur:
                    better += 1
                elif cand < cur:
                    worse += 1
        comparison["recommend_promotion"] = better > worse
        comparison["better_count"] = better
        comparison["worse_count"] = worse
        return comparison
