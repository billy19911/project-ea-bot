# -*- coding: utf-8 -*-
"""Pattern → hypothesis pipeline for learning loop — EPIC 14.02.

Converts recurring trade patterns into testable hypotheses with
linked evidence, and stores validated lessons (14.13).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Hypothesis:
    """A testable hypothesis derived from a trade pattern."""

    description: str
    confidence: float = 0.0
    evidence: dict[str, Any] = field(default_factory=dict)
    source_pattern: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize hypothesis."""
        return {
            "description": self.description,
            "confidence": round(self.confidence, 4),
            "evidence": dict(self.evidence),
            "source_pattern": self.source_pattern,
        }


class PatternHypothesisPipeline:
    """Turn trade patterns into testable hypotheses (14.02)."""

    MIN_CONFIDENCE = 0.5

    def pattern_to_hypothesis(self, pattern: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Convert a pattern dict into a hypothesis with evidence."""
        if not pattern:
            return None
        label = pattern.get("label", "")
        win_rate = float(pattern.get("win_rate", 0.0))
        frequency = int(pattern.get("frequency", 0))
        avg_pnl = float(pattern.get("avg_pnl", 0.0))

        # Confidence blends win rate and sample size (capped at 0.99)
        wr_component = max(0.0, min(win_rate / 100.0, 1.0))
        size_component = min(frequency / 30.0, 1.0)
        confidence = min(0.99, wr_component * 0.7 + size_component * 0.3)

        description = (
            f"Pattern '{label}' shows {win_rate:.1f}% win rate over "
            f"{frequency} trades; test whether it persists out-of-sample."
        )
        hypothesis = Hypothesis(
            description=description,
            confidence=confidence,
            evidence={
                "sample_size": frequency,
                "win_rate": win_rate,
                "avg_pnl": avg_pnl,
            },
            source_pattern=label,
        )
        return hypothesis.to_dict()
