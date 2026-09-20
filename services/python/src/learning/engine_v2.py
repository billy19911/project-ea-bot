# -*- coding: utf-8 -*-
"""Learning Engine 2.0 — PRD_V2 §43.

Layered learning pipeline that turns trades into *validated findings* through a
strict, evidence-gated progression. The core rule (PRD §43):

    **One trade does not create a strategy change.**

Every artefact carries an explicit :class:`EvidenceLevel`:

    OBSERVATION → HYPOTHESIS → EVIDENCE → VALIDATED_FINDING

Signals / confidence are NEVER modified directly by a lesson — a lesson only
ever feeds the research pipeline (hypothesis → experiment → backtest →
walk-forward → paper → demo → candidate). Promotion of a candidate to the live
strategy is a separate, human-gated step and is not performed here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

__all__ = [
    "EvidenceLevel",
    "LessonCategory",
    "Confidence",
    "Lesson",
    "PatternAggregate",
    "LearningEngineV2",
]


class EvidenceLevel(str, Enum):
    """Maturity of a learning artefact (PRD §43)."""

    OBSERVATION = "OBSERVATION"
    HYPOTHESIS = "HYPOTHESIS"
    EVIDENCE = "EVIDENCE"
    VALIDATED_FINDING = "VALIDATED_FINDING"


class LessonCategory(str, Enum):
    """Lesson categories (PRD §43 example: ENTRY_TIMING)."""

    ENTRY_TIMING = "ENTRY_TIMING"
    EXIT_TIMING = "EXIT_TIMING"
    POSITION_SIZING = "POSITION_SIZING"
    RISK_MANAGEMENT = "RISK_MANAGEMENT"
    REGIME_FIT = "REGIME_FIT"
    EXECUTION_QUALITY = "EXECUTION_QUALITY"
    OTHER = "OTHER"


class Confidence(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Lesson:
    """A single lesson derived from a trade (PRD §43 lesson structure)."""

    lesson_id: str
    trade_id: str
    symbol: str
    strategy_version: str
    category: str
    outcome: str
    context: dict[str, Any] = field(default_factory=dict)
    lesson: str = ""
    confidence: str = Confidence.LOW.value
    sample_size: int = 1
    created_at: str = field(default_factory=_now)
    evidence_level: str = EvidenceLevel.OBSERVATION.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "lesson_id": self.lesson_id,
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "strategy_version": self.strategy_version,
            "category": self.category,
            "outcome": self.outcome,
            "context": dict(self.context),
            "lesson": self.lesson,
            "confidence": self.confidence,
            "sample_size": self.sample_size,
            "created_at": self.created_at,
            "evidence_level": self.evidence_level,
        }


@dataclass
class PatternAggregate:
    """An aggregation of same-category lessons into a pattern (PRD §43)."""

    key: str
    category: str
    sample_size: int
    wins: int
    losses: int
    evidence_level: str = EvidenceLevel.HYPOTHESIS.value

    @property
    def win_rate(self) -> float:
        return (self.wins / self.sample_size * 100.0) if self.sample_size else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "category": self.category,
            "sample_size": self.sample_size,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate, 2),
            "evidence_level": self.evidence_level,
        }


# Minimum sample sizes for each evidence promotion (deterministic rules).
_MIN_PATTERN_SAMPLE = 10
_MIN_EVIDENCE_SAMPLE = 30
_MIN_VALIDATED_SAMPLE = 100


class LearningEngineV2:
    """Layered learning engine with evidence-gated promotion (PRD §43).

    Args:
        min_pattern_sample: Trades required to form a pattern (HYPOTHESIS).
        min_evidence_sample: Trades required to call it EVIDENCE.
        min_validated_sample: Trades required to call it a VALIDATED_FINDING.
    """

    def __init__(
        self,
        min_pattern_sample: int = _MIN_PATTERN_SAMPLE,
        min_evidence_sample: int = _MIN_EVIDENCE_SAMPLE,
        min_validated_sample: int = _MIN_VALIDATED_SAMPLE,
    ) -> None:
        self.min_pattern_sample = min_pattern_sample
        self.min_evidence_sample = min_evidence_sample
        self.min_validated_sample = min_validated_sample
        self._lessons: list[Lesson] = []

    # ------------------------------------------------------------------
    # Lesson ingestion
    # ------------------------------------------------------------------
    def record_lesson(self, lesson: Lesson) -> Lesson:
        """Record a single lesson — always an OBSERVATION (PRD §43).

        A single trade can never promote beyond OBSERVATION: promotion happens
        only through pattern aggregation across many lessons.
        """
        # Force evidence level to OBSERVATION on ingestion regardless of input.
        stored = Lesson(
            lesson_id=lesson.lesson_id,
            trade_id=lesson.trade_id,
            symbol=lesson.symbol,
            strategy_version=lesson.strategy_version,
            category=lesson.category,
            outcome=lesson.outcome,
            context=lesson.context,
            lesson=lesson.lesson,
            confidence=lesson.confidence,
            sample_size=max(1, lesson.sample_size),
            created_at=lesson.created_at,
            evidence_level=EvidenceLevel.OBSERVATION.value,
        )
        self._lessons.append(stored)
        return stored

    def lessons(self) -> list[Lesson]:
        return list(self._lessons)

    # ------------------------------------------------------------------
    # Pattern aggregation
    # ------------------------------------------------------------------
    def aggregate_patterns(self) -> list[PatternAggregate]:
        """Aggregate lessons by (category, symbol) into patterns (PRD §43).

        The evidence level is assigned by the deterministic promotion rules:
        below ``min_pattern_sample`` the aggregate stays an OBSERVATION; at or
        above it becomes a HYPOTHESIS; at/above the evidence threshold it
        becomes EVIDENCE; at/above the validated threshold it becomes a
        VALIDATED_FINDING.
        """
        groups: dict[tuple[str, str], PatternAggregate] = {}
        for lesson in self._lessons:
            key = f"{lesson.category}:{lesson.symbol}"
            agg = groups.get((lesson.category, lesson.symbol))
            if agg is None:
                agg = PatternAggregate(
                    key=key,
                    category=lesson.category,
                    sample_size=0,
                    wins=0,
                    losses=0,
                )
                groups[(lesson.category, lesson.symbol)] = agg
            agg.sample_size += 1
            if str(lesson.outcome).upper() == "WIN":
                agg.wins += 1
            else:
                agg.losses += 1

        aggregates = list(groups.values())
        for agg in aggregates:
            agg.evidence_level = self._classify_evidence(agg.sample_size)
        aggregates.sort(key=lambda a: (-a.sample_size, a.key))
        return aggregates

    def _classify_evidence(self, sample_size: int) -> str:
        if sample_size >= self.min_validated_sample:
            return EvidenceLevel.VALIDATED_FINDING.value
        if sample_size >= self.min_evidence_sample:
            return EvidenceLevel.EVIDENCE.value
        if sample_size >= self.min_pattern_sample:
            return EvidenceLevel.HYPOTHESIS.value
        return EvidenceLevel.OBSERVATION.value

    # ------------------------------------------------------------------
    # Guardrails
    # ------------------------------------------------------------------
    def can_promote_to_candidate(self, aggregate: PatternAggregate) -> tuple[bool, str]:
        """Return ``(allowed, reason)`` for promoting a pattern to CANDIDATE.

        Only a VALIDATED_FINDING may become a candidate. Anything weaker is
        rejected — this is the guardrail that stops a single trade (or a small
        sample) from ever changing strategy behaviour.
        """
        if aggregate.evidence_level == EvidenceLevel.VALIDATED_FINDING.value:
            return True, "validated finding meets candidate threshold"
        return (
            False,
            f"evidence level {aggregate.evidence_level} is below "
            f"{EvidenceLevel.VALIDATED_FINDING.value}",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "lessons": [lesson.to_dict() for lesson in self._lessons],
            "patterns": [agg.to_dict() for agg in self.aggregate_patterns()],
        }
