# -*- coding: utf-8 -*-
"""Technical indicators for the deterministic trading engine.

All calculations are pure-Python (no numpy / ta-lib dependency) and
deterministic — given the same input sequence the output is always
identical.

All price-series inputs are **oldest-first** (index 0 = oldest bar).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

__all__ = [
    "BollingerResult",
    "MACDResult",
    "StochasticResult",
    "atr",
    "adx",
    "ema",
    "ema_series",
    "macd",
    "rsi",
    "sma",
    "stochastic",
    "true_range",
    "wma",
]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MACDResult:
    """MACD calculation result — latest values."""

    macd_line: float
    signal_line: float
    histogram: float


@dataclass(frozen=True)
class BollingerResult:
    """Bollinger Bands — latest values."""

    upper: float
    middle: float
    lower: float


@dataclass(frozen=True)
class StochasticResult:
    """Stochastic Oscillator — latest %K and %D."""

    k: float
    d: float


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_divide(numerator: float, denominator: float) -> float:
    """Divide safely, returning ``0.0`` when *denominator* is zero."""
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _wilder_smooth(data: list[float], period: int) -> list[float | None]:
    """Apply Wilder's smoothing (EMA equivalent with ``alpha = 1/period``).

    First output is the simple average of the first *period* values.
    Subsequent values use: ``smoothed[i] = (smoothed[i-1] * (period-1) + value[i]) / period``
    """
    n = len(data)
    result: list[float | None] = [None] * n
    if n < period:
        return result
    result[period - 1] = sum(data[:period]) / period
    for i in range(period, n):
        result[i] = (result[i - 1] * (period - 1) + data[i]) / period
    return result


def _last_non_none(values: list[float | None]) -> Optional[float]:
    """Return the last non-None value, or ``None``."""
    for v in reversed(values):
        if v is not None:
            return v
    return None


# ---------------------------------------------------------------------------
# SMA — Simple Moving Average
# ---------------------------------------------------------------------------


def sma(prices: list[float], period: int) -> Optional[float]:
    """Simple Moving Average of the latest *period* prices.

    Args:
        prices: Price series (oldest → newest).
        period: Window size (≥ 1).

    Returns:
        SMA of the last *period* prices, or ``None`` if insufficient data.
    """
    if period < 1:
        raise ValueError("period must be >= 1")
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period


# ---------------------------------------------------------------------------
# WMA — Weighted Moving Average (linear weights)
# ---------------------------------------------------------------------------


def wma(prices: list[float], period: int) -> Optional[float]:
    """Weighted Moving Average (linear weights, newest gets highest).

    Args:
        prices: Price series (oldest → newest).
        period: Window size (≥ 1).

    Returns:
        WMA of the last *period* prices, or ``None``.
    """
    if period < 1:
        raise ValueError("period must be >= 1")
    if len(prices) < period:
        return None
    window = prices[-period:]
    weight_sum = period * (period + 1) / 2.0
    weighted = sum(window[j] * (j + 1) for j in range(period))
    return weighted / weight_sum


# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------


def ema(prices: list[float], period: int) -> Optional[float]:
    """Exponential Moving Average — latest value only.

    Uses ``alpha = 2 / (period + 1)`` and seeds with the SMA of the first
    *period* prices, then iterates to the latest bar.

    Args:
        prices: Price series (oldest → newest).
        period: EMA period (≥ 1).

    Returns:
        Latest EMA value, or ``None`` if insufficient data.
    """
    if period < 1:
        raise ValueError("period must be >= 1")
    if len(prices) < period:
        return None

    alpha = 2.0 / (period + 1.0)
    result = sum(prices[:period]) / period  # seed with SMA
    for i in range(period, len(prices)):
        result = alpha * prices[i] + (1.0 - alpha) * result
    return result


def ema_series(prices: list[float], period: int) -> list[float]:
    """Full EMA series (oldest → newest).

    Early entries (before ``period - 1``) are ``0.0`` as placeholders.
    """
    if period < 1:
        raise ValueError("period must be >= 1")
    n = len(prices)
    result: list[float] = [0.0] * n
    if n < period:
        return result
    alpha = 2.0 / (period + 1.0)
    result[period - 1] = sum(prices[:period]) / period
    for i in range(period, n):
        result[i] = alpha * prices[i] + (1.0 - alpha) * result[i - 1]
    return result


# ---------------------------------------------------------------------------
# RSI — Relative Strength Index (Wilder's smoothing)
# ---------------------------------------------------------------------------


def rsi(prices: list[float], period: int = 14) -> Optional[float]:
    """Latest RSI value using Wilder's smoothing.

    Args:
        prices: Close prices (oldest → newest).
        period: Look-back period (default 14).

    Returns:
        RSI value in [0, 100] or ``None`` if insufficient data.
    """
    if period < 1:
        raise ValueError("period must be >= 1")
    if len(prices) < period + 1:
        return None

    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # Wilder's recursive smoothing for all remaining deltas
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------


def macd(
    prices: list[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> Optional[MACDResult]:
    """MACD — latest values.

    Args:
        prices: Price series (oldest → newest).
        fast_period: Fast EMA period (default 12).
        slow_period: Slow EMA period (default 26).
        signal_period: Signal-line EMA period (default 9).

    Returns:
        :class:`MACDResult` or ``None`` if insufficient data.
    """
    if fast_period < 1 or slow_period < 1 or signal_period < 1:
        raise ValueError("periods must be >= 1")
    if fast_period >= slow_period:
        raise ValueError("fast_period must be < slow_period")
    if len(prices) < slow_period + signal_period:
        return None

    fast_ema_vals = ema_series(prices, fast_period)
    slow_ema_vals = ema_series(prices, slow_period)

    # MACD line — valid from index (slow_period - 1) onwards
    macd_valid: list[float] = [
        fast_ema_vals[i] - slow_ema_vals[i] for i in range(slow_period - 1, len(prices))
    ]
    if len(macd_valid) < signal_period:
        return None

    signal_ema = ema_series(macd_valid, signal_period)

    macd_line = macd_valid[-1]
    signal_line = signal_ema[-1]
    histogram = macd_line - signal_line

    return MACDResult(macd_line=macd_line, signal_line=signal_line, histogram=histogram)


# ---------------------------------------------------------------------------
# True Range & ATR
# ---------------------------------------------------------------------------


def true_range(highs: list[float], lows: list[float], closes: list[float]) -> list[float]:
    """True Range for each bar (starting from index 1).

    ``TR = max(high - low, |high - prev_close|, |low - prev_close|)``
    """
    n = len(highs)
    if n == 0:
        return []
    tr: list[float] = [0.0]
    for i in range(1, n):
        tr.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        )
    return tr


def atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> Optional[float]:
    """Average True Range with Wilder's smoothing.

    Args:
        highs: High prices (oldest → newest).
        lows: Low prices (oldest → newest).
        closes: Close prices (oldest → newest).
        period: ATR period (default 14).

    Returns:
        Latest ATR value or ``None`` if insufficient data.
    """
    if period < 1:
        raise ValueError("period must be >= 1")
    if len(highs) < period + 1 or len(lows) < period + 1 or len(closes) < period + 1:
        return None
    if len(highs) != len(lows) or len(lows) != len(closes):
        return None

    tr = true_range(highs, lows, closes)
    smoothed = _wilder_smooth(tr, period)
    return _last_non_none(smoothed)


# ---------------------------------------------------------------------------
# ADX — Average Directional Index
# ---------------------------------------------------------------------------


def _calculate_dm(highs: list[float], lows: list[float], n: int) -> tuple[list[float], list[float]]:
    """Calculate daily +DM and -DM (length ``n - 1``)."""
    pdm: list[float] = []
    mdm: list[float] = []
    for i in range(1, n):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        if up_move > down_move and up_move > 0:
            pdm.append(up_move)
        else:
            pdm.append(0.0)
        if down_move > up_move and down_move > 0:
            mdm.append(down_move)
        else:
            mdm.append(0.0)
    return pdm, mdm


def adx(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> Optional[float]:
    """Average Directional Index (full Wilder's pipeline).

    Measures trend strength on a 0–100 scale.  Values > 25 → strong trend.

    Args:
        highs: High prices (oldest → newest).
        lows: Low prices (oldest → newest).
        closes: Close prices (oldest → newest).
        period: Smoothing period (default 14).

    Returns:
        Latest ADX value or ``None`` if insufficient data.
    """
    if period < 2:
        raise ValueError("period must be >= 2")
    if len(highs) < period + 1 or len(lows) < period + 1 or len(closes) < period + 1:
        return None
    if len(highs) != len(lows) or len(lows) != len(closes):
        return None

    tr = true_range(highs, lows, closes)
    pdm, mdm = _calculate_dm(highs, lows, len(highs))

    # _calculate_dm returns n-1 elements; pad to match tr length
    pdm = [0.0] + pdm
    mdm = [0.0] + mdm

    tr_smooth = _wilder_smooth(tr, period)
    pdm_smooth = _wilder_smooth(pdm, period)
    mdm_smooth = _wilder_smooth(mdm, period)

    # +DI and -DI
    di_plus: list[float | None] = [None] * len(tr)
    di_minus: list[float | None] = [None] * len(tr)
    for i in range(len(tr)):
        if tr_smooth[i] is not None and tr_smooth[i] > 0:
            if pdm_smooth[i] is not None:
                di_plus[i] = 100.0 * pdm_smooth[i] / tr_smooth[i]
            if mdm_smooth[i] is not None:
                di_minus[i] = 100.0 * mdm_smooth[i] / tr_smooth[i]

    # DX
    dx_values: list[float | None] = [None] * len(tr)
    for i in range(len(tr)):
        if di_plus[i] is not None and di_minus[i] is not None:
            diff = abs(di_plus[i] - di_minus[i])
            total = di_plus[i] + di_minus[i]
            dx_values[i] = _safe_divide(diff * 100.0, total)

    # ADX = Wilder-smooth of DX
    adx_smoothed = _wilder_smooth([v for v in dx_values if v is not None], period)
    return _last_non_none(adx_smoothed)


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------


def bollinger_bands(
    prices: list[float], period: int = 20, num_std: float = 2.0
) -> Optional[BollingerResult]:
    """Latest Bollinger Bands.

    Args:
        prices: Price series (oldest → newest).
        period: SMA window (default 20).
        num_std: Standard deviations for bands (default 2.0).

    Returns:
        :class:`BollingerResult` or ``None``.
    """
    if period < 1:
        raise ValueError("period must be >= 1")
    if len(prices) < period:
        return None

    window = prices[-period:]
    middle = sum(window) / period
    variance = sum((p - middle) ** 2 for p in window) / period
    std = math.sqrt(variance)

    upper = middle + num_std * std
    lower = middle - num_std * std
    return BollingerResult(upper=upper, middle=middle, lower=lower)


def stochastic(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
    smooth: int = 3,
) -> Optional[StochasticResult]:
    """Latest Stochastic Oscillator (%K, %D).

    Args:
        highs: High prices (oldest → newest).
        lows: Low prices (oldest → newest).
        closes: Close prices (oldest → newest).
        period: Lookback for HH/LL (default 14).
        smooth: SMA window for %D (default 3).

    Returns:
        :class:`StochasticResult` or ``None``.
    """
    if period < 1 or smooth < 1:
        raise ValueError("period and smooth must be >= 1")
    if len(highs) < period or len(lows) < period or len(closes) < period:
        return None
    if len(highs) != len(lows) or len(lows) != len(closes):
        return None

    k_values: list[float] = []
    for i in range(len(closes) - period, len(closes)):
        window_h = highs[i : i + period]
        window_l = lows[i : i + period]
        hh = max(window_h)
        ll = min(window_l)
        if hh == ll:
            k_values.append(50.0)
        else:
            k = ((closes[i + period - 1] - ll) / (hh - ll)) * 100.0
            k_values.append(k)

    if len(k_values) == 0:
        return None

    k = k_values[-1]
    d_window = k_values[-smooth:]
    d = sum(d_window) / len(d_window)
    return StochasticResult(k=k, d=d)
