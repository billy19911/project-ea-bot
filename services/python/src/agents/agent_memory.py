# -*- coding: utf-8 -*-
"""Agent Pattern Memory — per-agent learned reasoning (PRD_V2 §43/§54).

Each analyst agent can learn *which of its own signals were right*. This gives
the committee evidence-backed reasoning ("this agent's BULLISH calls in
ranging regimes have been wrong 70% of the time") instead of a raw number.

Design rules (mirrors the rest of the learning stack):

* **Deterministic** — weighted statistics, no LLM.
* **Evidence-gated** — an agent's record is only *actionable* once it has
  enough samples; below that it reports ``INSUFFICIENT_SAMPLE``.
* **Advisory** — memory shapes the agent's confidence and reasoning text; it
  never flips a signal on its own or creates an order.
* **Fail-safe** — a memory problem never breaks analysis.
* **Scoped** — every record is keyed by ``(agent, regime, direction)`` so a
  trend-following agent is not judged on its ranging-regime calls.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "AgentOutcome",
    "AgentSkill",
    "AgentPatternMemory",
    "get_agent_memory",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AgentOutcome:
    """One observed (agent signal → realised outcome) sample."""

    agent: str
    regime: str
    direction: str  # BULLISH | BEARISH | NEUTRAL
    correct: bool
    confidence: float = 0.0
    symbol: str = ""
    timestamp: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "regime": self.regime,
            "direction": self.direction,
            "correct": self.correct,
            "confidence": self.confidence,
            "symbol": self.symbol,
            "timestamp": self.timestamp,
        }


@dataclass
class AgentSkill:
    """Aggregated skill record for ``(agent, regime)``."""

    agent: str
    regime: str
    total: int = 0
    correct: int = 0
    reliable: bool = False
    status: str = "INSUFFICIENT_SAMPLE"
    accuracy: float = 0.0
    bias: str = "NEUTRAL"

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "regime": self.regime,
            "total": self.total,
            "correct": self.correct,
            "reliable": self.reliable,
            "status": self.status,
            "accuracy": round(self.accuracy, 4),
            "bias": self.bias,
        }


class AgentPatternMemory:
    """In-memory (bounded) skill tracker for analyst agents.

    Args:
        min_samples: Samples required before a skill record is actionably
            reliable (per ``agent`` + ``regime``).
        max_records: Bounded ring of raw outcomes (oldest evicted).
    """

    def __init__(self, min_samples: int = 8, max_records: int = 5000) -> None:
        self.min_samples = min_samples
        self.max_records = max_records
        self._lock = threading.Lock()
        self._outcomes: list[AgentOutcome] = []

    # -- ingestion ---------------------------------------------------------
    def record(self, outcome: AgentOutcome) -> AgentOutcome:
        with self._lock:
            self._outcomes.append(outcome)
            if len(self._outcomes) > self.max_records:
                self._outcomes = self._outcomes[-self.max_records :]
        return outcome

    def record_outcome(
        self,
        agent: str,
        direction: str,
        correct: bool,
        regime: str = "unknown",
        confidence: float = 0.0,
        symbol: str = "",
    ) -> AgentOutcome:
        return self.record(
            AgentOutcome(
                agent=agent,
                regime=regime or "unknown",
                direction=(direction or "NEUTRAL").upper(),
                correct=bool(correct),
                confidence=float(confidence),
                symbol=symbol,
            )
        )

    # -- aggregation -------------------------------------------------------
    def outcomes(self) -> list[AgentOutcome]:
        with self._lock:
            return list(self._outcomes)

    def skills(self, agent: Optional[str] = None) -> list[AgentSkill]:
        """Return per-(agent, regime) skill records, optionally for one agent."""
        with self._lock:
            rows = list(self._outcomes)
        if agent:
            rows = [r for r in rows if r.agent == agent]

        buckets: dict[tuple[str, str], AgentSkill] = {}
        for r in rows:
            key = (r.agent, r.regime)
            skill = buckets.get(key)
            if skill is None:
                skill = AgentSkill(agent=r.agent, regime=r.regime)
                buckets[key] = skill
            skill.total += 1
            if r.correct:
                skill.correct += 1

        for skill in buckets.values():
            skill.accuracy = skill.correct / skill.total if skill.total else 0.0
            skill.reliable = skill.total >= self.min_samples
            skill.status = "RELIABLE" if skill.reliable else "INSUFFICIENT_SAMPLE"
            if skill.accuracy >= 0.55:
                skill.bias = "TRUSTED"
            elif skill.accuracy <= 0.45:
                skill.bias = "WEAK"
            else:
                skill.bias = "NEUTRAL"
        out = sorted(buckets.values(), key=lambda s: (-s.total, s.agent, s.regime))
        return out

    def skill_for(self, agent: str, regime: str) -> Optional[AgentSkill]:
        for skill in self.skills(agent=agent):
            if skill.regime == regime:
                return skill
        return None

    def adjust_confidence(self, agent: str, regime: str, base: float) -> tuple[float, str]:
        """Return ``(adjusted_confidence, note)`` for the agent in this regime.

        Only a *reliable* skill record nudges confidence, and only mildly
        (±0.15 max) — memory informs, it does not dominate. When there is not
        enough evidence, confidence is returned unchanged with an
        ``INSUFFICIENT_SAMPLE`` note.
        """
        skill = self.skill_for(agent, regime)
        if skill is None:
            return base, "no prior record for this regime"
        if not skill.reliable:
            return base, (
                f"{skill.total} prior sample(s) in {regime} "
                f"(need >= {self.min_samples}) — insufficient"
            )
        # Map accuracy 0..1 to a -0.15..+0.15 nudge around 0.5.
        nudge = (skill.accuracy - 0.5) * 0.3
        adjusted = max(0.0, min(1.0, base + nudge))
        note = (
            f"{skill.agent} historically {skill.accuracy:.0%} correct in "
            f"{regime} ({skill.total} cases) — confidence {nudge:+.2f}"
        )
        return adjusted, note


_INSTANCE: Optional[AgentPatternMemory] = None
_SHARED_KEY = "_ea_shared_agent_memory"


def get_agent_memory() -> AgentPatternMemory:
    """Return the process-wide agent pattern memory (lazy singleton).

    Stored on a process-global slot so the ``src.agents.*`` / ``agents.*``
    import identities share ONE store.
    """
    global _INSTANCE
    if _INSTANCE is None:
        import builtins

        shared = getattr(builtins, _SHARED_KEY, None)
        if shared is not None:
            _INSTANCE = shared
        else:
            _INSTANCE = AgentPatternMemory()
            setattr(builtins, _SHARED_KEY, _INSTANCE)
    return _INSTANCE
