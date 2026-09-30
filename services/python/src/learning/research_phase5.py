# -*- coding: utf-8 -*-
"""Phase 5 research: pattern observations + deterministic queries + promotion gate.
* ``PatternObserver``: builds INSUFFICIENT_SAMPLE-aware PatternObservations from
  canonical reviews (§7–§9).
* ``ResearchQueries``: deterministic query surface over the canonical store
  (§23) — setup/trigger/regime/session/WAIT/reject performance with NO LLM.
* ``PromotionGate``: deterministic multi-metric gate (§17) producing a
  PromotionRecord that ALWAYS requires manual approval (§18). There is NO code
  path that auto-activates a strategy.
"""
from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from typing import Any, Optional

from .canonical import PatternObservation, PromotionRecord, StrategyCandidateRecord
from .review_store import MIN_PATTERN_SAMPLE, CanonicalStore, _new_id

logger = logging.getLogger(__name__)
__all__ = [
    "PatternObserver",
    "ResearchQueries",
    "PromotionGate",
]


# ----------------------------------------------------------------------
# Pattern observation (§7–§9)
# ----------------------------------------------------------------------
class PatternObserver:
    """Aggregate TradeReview records into statistical observations (no opinion)."""

    # Grouping dimensions (§7).
    DIMENSIONS = (
        "symbol",
        "direction",
        "zone_type",
        "trigger_type",
        "regime",
        "session",
        "volatility_state",
        "news_state",
    )

    def observe(
        self,
        reviews: list[dict[str, Any]],
        *,
        grouping: tuple[str, ...] = ("symbol", "direction", "trigger_type"),
        min_sample: int = MIN_PATTERN_SAMPLE,
    ) -> list[PatternObservation]:
        """Group reviews and compute deterministic stats per bucket."""
        buckets: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
        for r in reviews:
            if r.get("kind") != "TradeReview":
                continue
            key = tuple(str(r.get(d, "UNKNOWN") or "UNKNOWN") for d in grouping)
            buckets[key].append(r)
        out: list[PatternObservation] = []
        for key, rows in buckets.items():
            grouping_map = {d: key[i] for i, d in enumerate(grouping)}
            rs = [float(r.get("realized_r", 0.0) or 0.0) for r in rows]
            wins = sum(1 for x in rs if x > 0)
            losses = sum(1 for x in rs if x < 0)
            be = sum(1 for x in rs if x == 0)
            gains = sum(x for x in rs if x > 0)
            gross_loss = abs(sum(x for x in rs if x < 0))
            pf = (gains / gross_loss) if gross_loss > 0 else (float("inf") if gains > 0 else 0.0)
            expectancy = (sum(rs) / len(rs)) if rs else 0.0
            status = "OBSERVED" if len(rows) >= min_sample else "INSUFFICIENT_SAMPLE"
            out.append(
                PatternObservation(
                    pattern_id=_new_id("pat"),
                    grouping=grouping_map,
                    sample_size=len(rows),
                    wins=wins,
                    losses=losses,
                    breakevens=be,
                    average_r=round(expectancy, 4),
                    median_r=round(statistics.median(rs), 4) if rs else 0.0,
                    expectancy=round(expectancy, 4),
                    profit_factor=round(pf, 4) if pf != float("inf") else 999.0,
                    avg_mae=round(
                        sum(float(r.get("mae", 0.0) or 0.0) for r in rows) / len(rows), 4
                    ),
                    avg_mfe=round(
                        sum(float(r.get("mfe", 0.0) or 0.0) for r in rows) / len(rows), 4
                    ),
                    max_drawdown=0.0,
                    uncertainty=round(1.0 / (len(rows) ** 0.5), 4) if rows else 1.0,
                    status=status,
                )
            )
        return out

    @staticmethod
    def agent_reliability(
        reviews: list[dict[str, Any]],
        *,
        grouping: tuple[str, ...] = ("regime", "trigger_type"),
        min_sample: int = MIN_PATTERN_SAMPLE,
    ) -> dict[tuple, dict[str, Any]]:
        """Contextual reliability buckets (§9) — never a global agent win rate."""
        buckets: dict[tuple, list[float]] = defaultdict(list)
        for r in reviews:
            if r.get("kind") != "TradeReview":
                continue
            key = tuple(str(r.get(d, "UNKNOWN") or "UNKNOWN") for d in grouping)
            buckets[key].append(float(r.get("realized_r", 0.0) or 0.0))
        out: dict[tuple, dict[str, Any]] = {}
        for key, rs in buckets.items():
            reliable = len(rs) >= min_sample
            out[key] = {
                "sample_size": len(rs),
                "avg_r": round(sum(rs) / len(rs), 4) if rs else 0.0,
                "status": "RELIABLE" if reliable else "INSUFFICIENT_SAMPLE",
            }
        return out


# ----------------------------------------------------------------------
# Deterministic research queries (§23)
# ----------------------------------------------------------------------
class ResearchQueries:
    """Deterministic query surface over a CanonicalStore — no LLM required."""

    def __init__(self, store: CanonicalStore) -> None:
        self._store = store

    def _reviews(self) -> list[dict[str, Any]]:
        return self._store.query("TradeReview")

    def _decisions(self) -> list[dict[str, Any]]:
        return self._store.query("DecisionReview")

    def performance_by(self, dimension: str) -> dict[str, dict[str, Any]]:
        """Win/loss/expectancy grouped by a TradeReview dimension."""
        out: dict[str, list[float]] = defaultdict(list)
        for r in self._reviews():
            key = str(r.get(dimension, "UNKNOWN") or "UNKNOWN")
            out[key].append(float(r.get("realized_r", 0.0) or 0.0))
        return {
            k: {
                "sample_size": len(v),
                "wins": sum(1 for x in v if x > 0),
                "losses": sum(1 for x in v if x < 0),
                "expectancy": round(sum(v) / len(v), 4) if v else 0.0,
            }
            for k, v in out.items()
        }

    def decision_outcomes(self) -> dict[str, int]:
        """Counts of WAIT/NO_TRADE/REJECTED/EXPIRED/INVALIDATED decisions (§23)."""
        out: dict[str, int] = defaultdict(int)
        for r in self._decisions():
            out[str(r.get("decision_state", "UNKNOWN"))] += 1
        return dict(out)

    def risk_reject_reasons(self) -> dict[str, int]:
        """Histogram of RiskGate rejection / blocking reasons."""
        out: dict[str, int] = defaultdict(int)
        for r in self._decisions():
            for code in r.get("reason_codes", []) or []:
                out[str(code)] += 1
            for blk in r.get("blocking_conditions", []) or []:
                out[str(blk)] += 1
        return dict(out)


# ----------------------------------------------------------------------
# Promotion gate (§16–§18) — deterministic, MANUAL APPROVAL ONLY
# ----------------------------------------------------------------------
# Minimum thresholds the gate checks (all reported separately, never fused).
_GATE_THRESHOLDS = {
    "min_sample": 30,
    "min_net_expectancy": 0.0,
    "max_drawdown": 0.5,
}


class PromotionGate:
    """Deterministic multi-metric promotion gate (§17). NEVER auto-approves.
    Produces a PromotionRecord with ``approval_required=True`` always. The
    ``decision`` stays PENDING unless a human supplies ``approved_by``.
    """

    def evaluate(
        self,
        candidate: StrategyCandidateRecord,
        *,
        extra_metrics: Optional[dict[str, Any]] = None,
    ) -> PromotionRecord:
        metrics = self._collect_metrics(candidate, extra_metrics or {})
        checks = {
            "sample_size": metrics.get("sample_size", 0) >= _GATE_THRESHOLDS["min_sample"],
            "net_expectancy": float(metrics.get("net_expectancy", 0.0))
            >= _GATE_THRESHOLDS["min_net_expectancy"],
            "drawdown": float(metrics.get("max_drawdown", 1.0)) <= _GATE_THRESHOLDS["max_drawdown"],
            "walk_forward": not metrics.get("walk_forward_unstable", True),
            "cost_sensitivity": not metrics.get("cost_sensitive", True),
            "regime_robust": not metrics.get("regime_fragile", True),
            "session_robust": not metrics.get("session_fragile", True),
            "long_short_robust": not metrics.get("direction_fragile", True),
        }
        passed = all(checks.values())
        return PromotionRecord(
            promotion_id=_new_id("promo"),
            candidate_id=candidate.candidate_id,
            from_status=candidate.status,
            to_status="APPROVAL_REQUIRED",
            metrics=metrics,
            gate_passed=passed,
            approval_required=True,
            decision="PENDING",
            reason_codes=[f"{k}={'PASS' if v else 'FAIL'}" for k, v in checks.items()],
        )

    def approve(self, record: PromotionRecord, *, approved_by: str) -> PromotionRecord:
        """Human approval step — the ONLY way to move past APPROVAL_REQUIRED (§18).
        Refuses when the gate did not pass or no human identity is supplied.
        """
        if not approved_by or not str(approved_by).strip():
            raise ValueError("Manual approval requires a non-empty operator identity")
        if not record.gate_passed:
            raise RuntimeError("Cannot approve a candidate that failed the promotion gate")
        from dataclasses import replace

        return replace(record, decision="APPROVED", approved_by=str(approved_by))

    @staticmethod
    def _collect_metrics(
        candidate: StrategyCandidateRecord, extra: dict[str, Any]
    ) -> dict[str, Any]:
        bt = candidate.backtest_results or {}
        wf = candidate.walkforward_results or {}
        metrics = {
            "sample_size": bt.get("trade_count", extra.get("sample_size", 0)),
            "net_expectancy": bt.get("expectancy", extra.get("net_expectancy", 0.0)),
            "max_drawdown": bt.get("max_drawdown", extra.get("max_drawdown", 1.0)),
            "profit_factor": bt.get("profit_factor", 0.0),
            "walk_forward_unstable": wf.get("unstable", True),
        }
        metrics.update({k: v for k, v in extra.items() if k not in metrics})
        return metrics
