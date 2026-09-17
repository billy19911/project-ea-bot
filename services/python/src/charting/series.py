# -*- coding: utf-8 -*-
"""Charting layer (Fase 1 "Pasar").

Turns real OHLC bars into a chart payload: candles plus indicator series.
All indicator maths come from :mod:`trading.indicators` (the same functions the
trading engine uses) — nothing is re-implemented here.

Honesty rules for the payload:

* A position where an indicator is not yet defined is ``None`` (serialised as
  JSON ``null``) — never a fabricated ``0.0``. The chart draws a gap.
* ``ema_series`` seeds with ``0.0`` placeholders; those are converted to
  ``None`` here so a chart never plunges to zero.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from ..trading.indicators import bollinger_series, ema_series, macd_series, rsi_series

__all__ = [
    "SUPPORTED_TIMEFRAMES",
    "build_chart_payload",
    "ema_chart_series",
]

#: Timeframes the MT5 terminal supports for candle retrieval.
SUPPORTED_TIMEFRAMES: tuple[str, ...] = (
    "M1",
    "M5",
    "M15",
    "M30",
    "H1",
    "H4",
    "D1",
    "W1",
    "MN1",
)

_DEFAULT_BB_PERIOD = 20
_DEFAULT_BB_STD = 2.0
_DEFAULT_RSI_PERIOD = 14
_MACD_FAST = 12
_MACD_SLOW = 26
_MACD_SIGNAL = 9


def ema_chart_series(prices: Sequence[float], period: int) -> list[Optional[float]]:
    """EMA series safe for charting.

    ``trading.indicators.ema_series`` returns ``0.0`` for the warm-up window;
    that is a placeholder for "not defined yet". For a chart, a zero would be
    a lie (the price axis would dive to zero), so the warm-up window is
    ``None`` here instead. Values from index ``period - 1`` on are the real
    EMA values.
    """
    raw = ema_series(list(prices), period)
    out: list[Optional[float]] = [None] * len(raw)
    if len(raw) < period:
        return out
    for i in range(period - 1, len(raw)):
        out[i] = raw[i]
    return out


def build_chart_payload(
    bars: Sequence[Any],
    *,
    ema_fast: int,
    ema_slow: int,
    include_bollinger: bool = True,
    include_rsi: bool = True,
    include_macd: bool = True,
) -> dict[str, Any]:
    """Build the chart payload from real OHLC bars (oldest → newest).

    Args:
        bars: OHLC bar objects (attributes ``time``, ``open``, ``high``,
            ``low``, ``close``, ``volume``).
        ema_fast: Fast EMA period for the overlay (must be < ``ema_slow``).
        ema_slow: Slow EMA period for the overlay.
        include_bollinger: Include Bollinger Bands overlay.
        include_rsi: Include the RSI sub-panel series.
        include_macd: Include the MACD sub-panel series.

    Returns:
        JSON-ready dict with ``bars``, ``overlays`` and ``panels``.

    Raises:
        ValueError: On invalid periods.
    """
    if ema_fast < 1:
        raise ValueError("ema_fast must be >= 1")
    if ema_slow <= ema_fast:
        raise ValueError("ema_slow must be > ema_fast")

    closes = [float(b.close) for b in bars]

    candles = [
        {
            "time": b.time.isoformat() if hasattr(b.time, "isoformat") else str(b.time),
            "open": float(b.open),
            "high": float(b.high),
            "low": float(b.low),
            "close": float(b.close),
            "volume": float(getattr(b, "volume", 0.0) or 0.0),
        }
        for b in bars
    ]

    overlays: dict[str, Any] = {
        "ema_fast": {"period": ema_fast, "values": ema_chart_series(closes, ema_fast)},
        "ema_slow": {"period": ema_slow, "values": ema_chart_series(closes, ema_slow)},
        "bollinger": None,
    }
    if include_bollinger:
        upper, middle, lower = bollinger_series(closes, _DEFAULT_BB_PERIOD, _DEFAULT_BB_STD)
        overlays["bollinger"] = {
            "period": _DEFAULT_BB_PERIOD,
            "std": _DEFAULT_BB_STD,
            "upper": upper,
            "middle": middle,
            "lower": lower,
        }

    panels: dict[str, Any] = {"rsi": None, "macd": None}
    if include_rsi:
        panels["rsi"] = {
            "period": _DEFAULT_RSI_PERIOD,
            "values": rsi_series(closes, _DEFAULT_RSI_PERIOD),
        }
    if include_macd:
        macd_line, signal_line, histogram = macd_series(
            closes, _MACD_FAST, _MACD_SLOW, _MACD_SIGNAL
        )
        panels["macd"] = {
            "fast": _MACD_FAST,
            "slow": _MACD_SLOW,
            "signal": _MACD_SIGNAL,
            "line": macd_line,
            "signal_line": signal_line,
            "histogram": histogram,
        }

    return {
        "bars": candles,
        "overlays": overlays,
        "panels": panels,
    }
