# -*- coding: utf-8 -*-
"""Multi-timeframe analysis — higher-timeframe bias + lower-timeframe entry.

Deterministic helper the feed loop uses to attach two extra pieces of evidence
to every market snapshot:

* ``htf_bias`` — the higher-timeframe trend direction (BULLISH / BEARISH /
  NEUTRAL) and its strength, computed from a slower timeframe's EMA slope.
* ``timeframe_prices`` — ``{timeframe: closes}`` for the configured set so the
  momentum analyst can compute a true multi-timeframe consensus.

This is **read-only evidence gathering**: it never places orders and never
changes a signal by itself. The pipeline may use ``htf_bias`` as an entry
*filter* (an LTF entry that fights the HTF trend is down-graded), but the
decision to act always stays with the deterministic committee + Risk Gate.

Fail-safe: any read/compute error yields an empty/neutral result — a data
hiccup must never break the feed loop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from trading.indicators import ema_series

logger = logging.getLogger(__name__)

__all__ = [
    "HTFBias",
    "compute_htf_bias",
    "build_timeframe_prices",
    "DEFAULT_ANALYSIS_TIMEFRAMES",
]

# Timeframes pulled for the multi-TF consensus (LTF + MTF + HTF).
DEFAULT_ANALYSIS_TIMEFRAMES: tuple[str, ...] = ("M15", "H1", "H4")


@dataclass(frozen=True)
class HTFBias:
    """Higher-timeframe directional bias."""

    timeframe: str
    direction: str  # BULLISH | BEARISH | NEUTRAL
    strength: float  # 0.0..1.0 (normalised EMA separation)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "direction": self.direction,
            "strength": round(self.strength, 4),
            "reason": self.reason,
        }


def _closes_from_bars(bars: Any) -> list[float]:
    closes: list[float] = []
    for bar in bars or []:
        close = bar.get("close") if isinstance(bar, dict) else getattr(bar, "close", None)
        try:
            if close is not None:
                closes.append(float(close))
        except (TypeError, ValueError):
            continue
    return closes


def compute_htf_bias(
    closes: list[float],
    *,
    timeframe: str = "H4",
    fast_period: int = 20,
    slow_period: int = 50,
    min_strength: float = 0.0,
) -> HTFBias:
    """Compute the higher-timeframe bias from a close series.

    Bias = sign and magnitude of (fast EMA − slow EMA) normalised by the slow
    EMA. ``strength`` is clamped to ``[0, 1]`` against a 2% separation ceiling
    (a pragmatic "full conviction" threshold). Too-few bars → NEUTRAL.
    """
    closes = [float(c) for c in (closes or []) if c is not None]
    if len(closes) < max(fast_period, slow_period) + 1:
        return HTFBias(
            timeframe=timeframe,
            direction="NEUTRAL",
            strength=0.0,
            reason="insufficient bars for HTF bias",
        )

    fast = ema_series(closes, fast_period)
    slow = ema_series(closes, slow_period)
    f = fast[-1]
    s = slow[-1]
    if s <= 0:
        return HTFBias(
            timeframe=timeframe,
            direction="NEUTRAL",
            strength=0.0,
            reason="invalid slow EMA",
        )

    separation = (f - s) / s
    strength = min(abs(separation) / 0.02, 1.0)  # 2% separation == full strength

    if separation > 0 and strength > min_strength:
        direction = "BULLISH"
    elif separation < 0 and strength > min_strength:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    return HTFBias(
        timeframe=timeframe,
        direction=direction,
        strength=round(strength, 4),
        reason=f"EMA{fast_period} vs EMA{slow_period} separation {separation:+.4%}",
    )


def build_timeframe_prices(
    symbol: str,
    *,
    connector: Any,
    timeframes: tuple[str, ...] = DEFAULT_ANALYSIS_TIMEFRAMES,
    count: int = 120,
    emas: Optional[dict[str, tuple[int, int]]] = None,
) -> dict[str, Any]:
    """Fetch closes for each timeframe and compute the HTF bias.

    Returns a dict with:
      * ``timeframe_prices``: ``{tf: [closes]}`` (only non-empty series)
      * ``htf_bias``: dict form of the HTF :class:`HTFBias` (``None`` when the
        bias could not be computed)

    Fail-safe: a failed read for one timeframe is skipped; a total failure
    returns ``{"timeframe_prices": {}, "htf_bias": None}``.
    """
    result: dict[str, Any] = {"timeframe_prices": {}, "htf_bias": None}
    if connector is None:
        return result

    tf_prices: dict[str, list[float]] = {}
    for tf in timeframes:
        try:
            bars = connector.get_ohlc(symbol, tf, count)
            closes = _closes_from_bars(bars)
            if len(closes) >= 15:
                tf_prices[tf] = closes
        except Exception as exc:  # noqa: BLE001 - one TF never blocks the rest
            logger.debug("Multi-TF read failed for %s %s: %s", symbol, tf, exc)
            continue

    if not tf_prices:
        return result

    result["timeframe_prices"] = tf_prices

    # HTF bias from the SLOWEST available timeframe (max period = highest TF).
    htf_tf = max(tf_prices.keys(), key=_timeframe_rank)
    result["htf_bias"] = compute_htf_bias(tf_prices[htf_tf], timeframe=htf_tf).to_dict()
    return result


_TIMEFRAME_ORDER = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]


def _timeframe_rank(tf: str) -> int:
    """Return the ordinal rank of a timeframe string (higher = slower)."""
    try:
        return _TIMEFRAME_ORDER.index(str(tf).upper())
    except ValueError:
        return -1
