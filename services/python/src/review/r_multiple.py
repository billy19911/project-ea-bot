# -*- coding: utf-8 -*-
"""R-multiple computation for closed trades.

An "R-multiple" expresses a trade's result in units of the INITIAL risk taken
(1R = the distance from entry to the original stop-loss). It is the natural
unit for comparing trades of different sizes / instruments and is the basis for
the per-day / per-week / per-month expectancy view.

This module is pure and I/O-free so it is trivially testable. The R is computed
from **prices** rather than absolute PnL so it does not depend on the broker's
contract-size / tick-value metadata (which the close path often lacks):

    BUY :  R = (exit - entry) / (entry - stop_loss)
    SELL:  R = (entry - exit) / (stop_loss - entry)

Both formulas use the *original* stop-loss, so a trailed stop does not shrink
the denominator. Any degenerate input (missing/zero risk, zero entry, unknown
direction) yields ``None`` rather than a fabricated number.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

__all__ = ["compute_r_multiple", "r_bucket_from_trades", "aggregate_r_by_period"]


def _f(value: Any) -> Optional[float]:
    """Coerce to float, or None when not a finite number."""
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN
        return None
    return out


def compute_r_multiple(
    *,
    direction: str,
    entry_price: Any,
    exit_price: Any,
    stop_loss: Any,
) -> Optional[float]:
    """Return the trade's R-multiple, or ``None`` when it cannot be computed.

    Args:
        direction: ``"buy"`` / ``"sell"`` (case-insensitive).
        entry_price: Fill/entry price of the position.
        exit_price: Close/exit price of the position.
        stop_loss: The ORIGINAL stop-loss price (risk anchor).

    Returns:
        The signed R-multiple (e.g. ``-1.0`` for a full stop-out, ``+2.0`` for a
        2R winner), or ``None`` when the inputs are insufficient/degenerate.
    """
    side = str(direction or "").strip().lower()
    entry = _f(entry_price)
    exit_ = _f(exit_price)
    sl = _f(stop_loss)

    if entry is None or exit_ is None or sl is None:
        return None
    if entry <= 0 or exit_ <= 0 or sl <= 0:
        return None

    if side in ("buy", "long"):
        risk = entry - sl
        if risk <= 0:
            return None
        return round((exit_ - entry) / risk, 4)
    if side in ("sell", "short"):
        risk = sl - entry
        if risk <= 0:
            return None
        return round((entry - exit_) / risk, 4)
    return None


def r_bucket_from_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise a list of ``{"r_multiple": float}`` dicts.

    Trades without a usable R are ignored. Returns count / wins / losses /
    win_rate / avg_r / total_r / profit_factor (all R-based).
    """
    rs = [t.get("r_multiple") for t in trades if isinstance(t, dict)]
    rs = [r for r in (_f(x) for x in rs) if r is not None]
    count = len(rs)
    if count == 0:
        return {
            "count": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "avg_r": 0.0,
            "total_r": 0.0,
            "profit_factor": 0.0,
        }
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = float("inf") if gross_profit > 0 else 0.0
    return {
        "count": count,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / count * 100.0, 2),
        "avg_r": round(sum(rs) / count, 4),
        "total_r": round(sum(rs), 4),
        "profit_factor": (
            round(profit_factor, 4) if profit_factor != float("inf") else profit_factor
        ),
    }


def _period_key(ts: datetime, period: str) -> str:
    """Return the bucket key for ``ts`` under ``period``.

    * ``day``   → ``YYYY-MM-DD``
    * ``week``  → ``YYYY-Www`` (ISO week, Monday-based)
    * ``month`` → ``YYYY-MM``
    """
    if period == "month":
        return ts.strftime("%Y-%m")
    if period == "week":
        iso = ts.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    return ts.strftime("%Y-%m-%d")


def aggregate_r_by_period(
    trades: list[dict[str, Any]],
    period: str = "day",
) -> list[dict[str, Any]]:
    """Group trades by period (day/week/month) and summarise R per bucket.

    Args:
        trades: Dicts with ``r_multiple`` (float|None) and ``closed_at``
            (datetime|ISO string|None). Trades missing a timestamp or a usable
            R are skipped for bucketing.
        period: ``"day"`` | ``"week"`` | ``"month"``.

    Returns:
        A list of buckets, newest first, each with ``key`` + :func:`r_bucket_from_trades`
        fields.
    """
    if period not in ("day", "week", "month"):
        period = "day"
    grouped: dict[str, list[dict[str, Any]]] = {}
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        r = _f(trade.get("r_multiple"))
        if r is None:
            continue
        raw_ts = trade.get("closed_at")
        ts: Optional[datetime] = None
        if isinstance(raw_ts, datetime):
            ts = raw_ts
        elif isinstance(raw_ts, str) and raw_ts:
            try:
                ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            except ValueError:
                ts = None
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        key = _period_key(ts, period)
        grouped.setdefault(key, []).append({"r_multiple": r})

    out: list[dict[str, Any]] = []
    for key in sorted(grouped.keys(), reverse=True):
        bucket = r_bucket_from_trades(grouped[key])
        bucket["key"] = key
        out.append(bucket)
    return out
