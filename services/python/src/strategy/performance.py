# -*- coding: utf-8 -*-
"""Real strategy performance — compute metrics from actual closed trades.

FOKUS #4 (Pusat Strategi):
    The Strategy Center showed ``—`` for WIN RATE / PROFIT FACTOR / SHARPE /
    MAX DD because ``VersionedStrategy.metrics_summary`` was never populated:
    the auto-registered live strategy had empty metrics, and nothing bridged the
    real trade outcomes into the registry.

    This module computes those metrics from the **real** closed-trade record
    (the learning lesson store, which carries per-trade ``pnl`` written by the
    review/close path) and a bridge that writes them into the active strategy.
    It is honest: with no closed trades it returns ``status="NO_DATA"`` (never
    fabricated numbers), and it flags small samples as ``low_sample``.

Metric definitions (per-trade PnL in account currency):
    * win_rate      — winning trades / total trades * 100
    * profit_factor — gross profit / gross loss (inf when no losses)
    * sharpe        — mean(pnl) / stdev(pnl) * sqrt(N) (trade-level Sharpe proxy)
    * max_dd        — maximum peak-to-trough drawdown of the cumulative PnL curve
    * expectancy    — mean PnL per trade
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["compute_performance", "apply_performance_to_registry"]

# Below this many closed trades the metrics are flagged low-sample (advisory).
MIN_RELIABLE_SAMPLE = 30


def _extract_pnls(lessons: Any) -> list[float]:
    """Pull numeric per-trade PnL from lesson records (fail-safe).

    Accepts the list returned by ``get_lesson_store().all_lessons()``. Only
    records with a finite numeric ``pnl`` are used; a lesson without PnL (e.g. a
    pattern/hypothesis entry) is skipped so it cannot skew the stats.
    """
    pnls: list[float] = []
    if not isinstance(lessons, list):
        return pnls
    for lesson in lessons:
        if not isinstance(lesson, dict):
            continue
        raw = lesson.get("pnl")
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            pnls.append(value)
    return pnls


def _max_drawdown(equity_curve: list[float]) -> float:
    """Return the max peak-to-trough drawdown of an equity curve (>= 0)."""
    peak = float("-inf")
    max_dd = 0.0
    for value in equity_curve:
        if value > peak:
            peak = value
        if peak > float("-inf"):
            dd = peak - value
            if dd > max_dd:
                max_dd = dd
    return max_dd


def _stdev(values: list[float]) -> float:
    """Population standard deviation (0 when fewer than 2 values)."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def compute_performance(pnls: list[float]) -> dict[str, Any]:
    """Compute the strategy performance summary from per-trade PnL values.

    Returns a dict with ``win_rate``, ``profit_factor``, ``sharpe``,
    ``max_dd``, ``expectancy``, ``trades`` and a ``status``. With no trades it
    returns ``status="NO_DATA"`` and omits the metric keys (so the UI renders
    ``—`` rather than a fabricated 0).
    """
    count = len(pnls)
    if count == 0:
        return {"trades": 0, "status": "NO_DATA"}

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    win_rate = len(wins) / count * 100.0

    if gross_loss > 0:
        profit_factor: Optional[float] = gross_profit / gross_loss
    else:
        profit_factor = float("inf") if gross_profit > 0 else 0.0

    std = _stdev(pnls)
    mean = sum(pnls) / count
    sharpe = (mean / std * math.sqrt(count)) if std > 0 else 0.0

    # Cumulative PnL curve → max drawdown.
    equity = []
    running = 0.0
    for pnl in pnls:
        running += pnl
        equity.append(running)
    max_dd = _max_drawdown(equity)

    sharpe_out = round(sharpe, 4)
    pf_out = round(profit_factor, 4) if math.isfinite(profit_factor) else profit_factor

    return {
        "trades": count,
        "wins": len(wins),
        "losses": len(losses),
        # Canonical keys consumed by the Node strategy mapper
        # (apps/api/src/index.ts: metrics_summary.{win_rate, profit_factor,
        # sharpe_ratio, max_drawdown}).
        "win_rate": round(win_rate, 2),
        "profit_factor": pf_out,
        "sharpe_ratio": sharpe_out,
        "max_drawdown": round(max_dd, 2),
        # Aliases kept so any consumer reading the short names also works.
        "sharpe": sharpe_out,
        "max_dd": round(max_dd, 2),
        "expectancy": round(mean, 4),
        "total_pnl": round(sum(pnls), 2),
        "status": "OK" if count >= MIN_RELIABLE_SAMPLE else "LOW_SAMPLE",
    }


def apply_performance_to_registry(registry: Any, lessons: Any = None) -> dict[str, Any]:
    """Compute real metrics and write them onto the active live strategy.

    Reads closed-trade PnL from ``lessons`` (defaults to the process-wide lesson
    store), computes the summary and stores it in the active strategy's
    ``metrics_summary`` so the Strategy Center shows real numbers. Fail-safe:
    any error is swallowed and an ``{"status": "ERROR"}`` summary returned.

    Returns the computed performance dict.
    """
    try:
        if lessons is None:
            from agents.analysts.review_agent import get_lesson_store

            lessons = get_lesson_store().all_lessons()

        pnls = _extract_pnls(lessons)
        perf = compute_performance(pnls)
    except Exception as exc:  # noqa: BLE001 - never break the caller
        logger.warning("Strategy performance computation failed: %s", exc)
        return {"status": "ERROR", "reason": str(exc)}

    try:
        # Prefer the explicit live strategy; else the first ACTIVE one.
        target = None
        try:
            from .endpoints import _LIVE_NAME, _LIVE_VERSION

            target = registry.get(_LIVE_NAME, _LIVE_VERSION)
        except Exception:  # noqa: BLE001 - endpoints import is optional
            target = None
        if target is None:
            for strategy in registry.list_all():
                if getattr(strategy.status, "value", "") == "ACTIVE":
                    target = strategy
                    break
        if target is not None:
            target.metrics_summary = perf
            logger.info(
                "Strategy performance updated: %s trades=%s status=%s",
                getattr(target, "name", "?"),
                perf.get("trades"),
                perf.get("status"),
            )
    except Exception as exc:  # noqa: BLE001 - registry write must never crash
        logger.warning("Could not attach performance to strategy: %s", exc)

    return perf
