# -*- coding: utf-8 -*-
"""System SLO / Health Target — PRD_V2 §56.

Tracks the internal SLIs the PRD names and evaluates them against targets.
Percentiles (p50 / p95 / p99) are reported — never just an average — so tail
latency is visible.

SLIs (PRD §56)::

    MT5 detection success, market feed freshness, execution confirmation
    latency, reconciliation freshness, API availability, scheduler health,
    LLM availability
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

__all__ = [
    "SLIName",
    "SLO",
    "SLIStats",
    "SLOTracker",
]


class SLIName:
    """Canonical SLI names (PRD §56)."""

    MT5_DETECTION_SUCCESS = "mt5_detection_success"
    MARKET_FEED_FRESHNESS = "market_feed_freshness"
    EXECUTION_CONFIRM_LATENCY = "execution_confirm_latency"
    RECONCILIATION_FRESHNESS = "reconciliation_freshness"
    API_AVAILABILITY = "api_availability"
    SCHEDULER_HEALTH = "scheduler_health"
    LLM_AVAILABILITY = "llm_availability"


ALL_SLIS: tuple[str, ...] = (
    SLIName.MT5_DETECTION_SUCCESS,
    SLIName.MARKET_FEED_FRESHNESS,
    SLIName.EXECUTION_CONFIRM_LATENCY,
    SLIName.RECONCILIATION_FRESHNESS,
    SLIName.API_AVAILABILITY,
    SLIName.SCHEDULER_HEALTH,
    SLIName.LLM_AVAILABILITY,
)


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    frac = rank - low
    return sorted_values[low] * (1 - frac) + sorted_values[high] * frac


@dataclass(frozen=True)
class SLO:
    """A service-level objective for one SLI.

    Args:
        sli: The SLI name.
        target: The objective value (percentile value or ratio depending on kind).
        percentile: Which percentile the target applies to (e.g. 95).
        kind: ``"latency"`` (lower is better) or ``"ratio"`` (higher is better).
    """

    sli: str
    target: float
    percentile: int = 95
    kind: str = "latency"

    def to_dict(self) -> dict[str, Any]:
        return {
            "sli": self.sli,
            "target": self.target,
            "percentile": self.percentile,
            "kind": self.kind,
        }


# Default internal targets (PRD §56) — conservative, deterministic.
DEFAULT_SLOS: tuple[SLO, ...] = (
    SLO(SLIName.MT5_DETECTION_SUCCESS, 0.99, kind="ratio"),
    SLO(SLIName.MARKET_FEED_FRESHNESS, 5.0, percentile=95, kind="latency"),
    SLO(SLIName.EXECUTION_CONFIRM_LATENCY, 2.0, percentile=95, kind="latency"),
    SLO(SLIName.RECONCILIATION_FRESHNESS, 60.0, percentile=95, kind="latency"),
    SLO(SLIName.API_AVAILABILITY, 0.999, kind="ratio"),
    SLO(SLIName.SCHEDULER_HEALTH, 0.99, kind="ratio"),
    SLO(SLIName.LLM_AVAILABILITY, 0.95, kind="ratio"),
)


@dataclass
class SLIStats:
    """Computed statistics for an SLI over a set of samples."""

    sli: str
    count: int
    p50: float
    p95: float
    p99: float
    average: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "sli": self.sli,
            "count": self.count,
            "p50": self.p50,
            "p95": self.p95,
            "p99": self.p99,
            "average": self.average,
        }


@dataclass
class SLOTracker:
    """Records SLI samples and evaluates them against SLOs (PRD §56)."""

    slos: tuple[SLO, ...] = DEFAULT_SLOS
    _samples: dict[str, list[float]] = field(default_factory=dict, repr=False)

    def record(self, sli: str, value: float) -> None:
        """Record a single SLI observation."""
        self._samples.setdefault(sli, []).append(float(value))

    def samples(self, sli: str) -> list[float]:
        return list(self._samples.get(sli, []))

    def stats(self, sli: str) -> Optional[SLIStats]:
        values = self._samples.get(sli)
        if not values:
            return None
        ordered = sorted(values)
        return SLIStats(
            sli=sli,
            count=len(values),
            p50=_percentile(ordered, 50.0),
            p95=_percentile(ordered, 95.0),
            p99=_percentile(ordered, 99.0),
            average=sum(values) / len(values),
        )

    def evaluate(self, sli: str, slo: Optional[SLO] = None) -> dict[str, Any]:
        """Evaluate an SLI against its SLO. Returns a deterministic verdict."""
        target = slo or next((s for s in self.slos if s.sli == sli), None)
        stats = self.stats(sli)
        if stats is None:
            return {
                "sli": sli,
                "status": "NO_DATA",
                "breach": False,
            }
        if target is None:
            return {"sli": sli, "status": "NO_SLO", "breach": False, "stats": stats.to_dict()}

        if target.kind == "latency":
            observed = (
                stats.p95
                if target.percentile == 95
                else _percentile(sorted(self._samples[sli]), float(target.percentile))
            )
            breach = observed > target.target
        else:  # ratio — value recorded is the success ratio/average
            observed = stats.average
            breach = observed < target.target

        return {
            "sli": sli,
            "status": "BREACH" if breach else "OK",
            "breach": breach,
            "observed": observed,
            "target": target.target,
            "stats": stats.to_dict(),
        }

    def evaluate_all(self) -> list[dict[str, Any]]:
        return [self.evaluate(s.sli, s) for s in self.slos]

    def breaching(self) -> list[dict[str, Any]]:
        return [r for r in self.evaluate_all() if r["breach"]]

    def report(self) -> dict[str, Any]:
        return {
            "slos": [s.to_dict() for s in self.slos],
            "evaluations": self.evaluate_all(),
            "breaching": [r["sli"] for r in self.breaching()],
        }
