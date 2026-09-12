# -*- coding: utf-8 -*-
"""Trend detection algorithms — deterministic trend identification.

Analyzes price series to detect uptrends, downtrends, and ranging markets.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from .indicators import ema


class TrendDirection(str, Enum):
    """Trend direction classification."""

    UPTREND = "uptrend"
    DOWNTREND = "downtrend"
    RANGING = "ranging"
    UNKNOWN = "unknown"


class TrendStrength(str, Enum):
    """Trend strength classification."""

    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    NONE = "none"


def detect_trend_ema_cross(
    prices: list[float], short_period: int = 20, long_period: int = 50
) -> TrendDirection:
    """Detect trend using EMA crossover.

    Args:
        prices: Price series (oldest → newest).
        short_period: Short EMA period (default 20).
        long_period: Long EMA period (default 50).

    Returns:
        Trend direction based on EMA crossover.
    """
    if len(prices) < long_period:
        return TrendDirection.UNKNOWN

    short_ema = ema(prices, short_period)
    long_ema = ema(prices, long_period)

    if short_ema is None or long_ema is None:
        return TrendDirection.UNKNOWN

    diff_pct = ((short_ema - long_ema) / long_ema) * 100.0

    if diff_pct > 0.5:
        return TrendDirection.UPTREND
    elif diff_pct < -0.5:
        return TrendDirection.DOWNTREND
    return TrendDirection.RANGING


def detect_trend_slope(prices: list[float], period: int = 20) -> TrendDirection:
    """Detect trend using linear regression slope of recent prices.

    Args:
        prices: Price series (oldest → newest).
        period: Lookback window (default 20).

    Returns:
        Trend direction based on price slope.
    """
    if len(prices) < period or period <= 0:
        return TrendDirection.UNKNOWN

    recent = prices[-period:]
    n = len(recent)

    sum_x = sum(range(n))
    sum_y = sum(recent)
    sum_xy = sum(i * recent[i] for i in range(n))
    sum_x2 = sum(i * i for i in range(n))

    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0:
        return TrendDirection.UNKNOWN
    slope = (n * sum_xy - sum_x * sum_y) / denom

    avg_price = sum_y / n
    if avg_price == 0:
        return TrendDirection.UNKNOWN
    slope_pct = (slope / avg_price) * 100.0

    if slope_pct > 0.1:
        return TrendDirection.UPTREND
    elif slope_pct < -0.1:
        return TrendDirection.DOWNTREND
    return TrendDirection.RANGING


def detect_trend_adx(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
    threshold: float = 25.0,
) -> tuple[TrendDirection, TrendStrength]:
    """Detect trend using the ADX indicator.

    Args:
        highs: High prices (oldest → newest).
        lows: Low prices (oldest → newest).
        closes: Close prices (oldest → newest).
        period: ADX period (default 14).
        threshold: ADX threshold for trend identification (default 25).

    Returns:
        ``(trend_direction, trend_strength)``.
    """
    from .indicators import adx as calc_adx

    if len(highs) < period + 1:
        return (TrendDirection.UNKNOWN, TrendStrength.NONE)

    adx_value = calc_adx(highs, lows, closes, period)
    if adx_value is None:
        return (TrendDirection.UNKNOWN, TrendStrength.NONE)

    if adx_value < threshold:
        strength = TrendStrength.WEAK if adx_value > 20.0 else TrendStrength.NONE
        return (TrendDirection.RANGING, strength)

    direction = detect_trend_slope(closes, period)

    if adx_value > 40.0:
        strength = TrendStrength.STRONG
    elif adx_value > threshold:
        strength = TrendStrength.MODERATE
    else:
        strength = TrendStrength.WEAK

    return (direction, strength)


def identify_support_resistance(
    prices: list[float], window: int = 20
) -> tuple[Optional[float], Optional[float]]:
    """Identify support and resistance levels from local extrema.

    Args:
        prices: Price series (oldest → newest).
        window: Half-window for local extrema detection (default 20).

    Returns:
        ``(support, resistance)`` or ``(None, None)``.
    """
    if len(prices) < window * 2:
        return (None, None)

    lows: list[float] = []
    highs: list[float] = []

    for i in range(window, len(prices) - window):
        is_low = all(prices[i] <= prices[j] for j in range(i - window, i + window) if j != i)
        is_high = all(prices[i] >= prices[j] for j in range(i - window, i + window) if j != i)
        if is_low:
            lows.append(prices[i])
        if is_high:
            highs.append(prices[i])

    if not lows or not highs:
        return (None, None)

    return (min(lows), max(highs))


def calculate_trend_strength_percent(prices: list[float], period: int = 20) -> float:
    """Calculate trend strength as an R²-based percentage (0–100).

    Args:
        prices: Price series (oldest → newest).
        period: Lookback window (default 20).

    Returns:
        Strength percentage: 0 = no trend, 100 = perfect linear trend.
    """
    if len(prices) < period or period <= 0:
        return 0.0

    recent = prices[-period:]
    n = len(recent)

    sum_x = sum(range(n))
    sum_y = sum(recent)
    sum_xy = sum(i * recent[i] for i in range(n))
    sum_x2 = sum(i * i for i in range(n))

    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0:
        return 0.0
    slope = (n * sum_xy - sum_x * sum_y) / denom

    mean_y = sum_y / n
    ss_tot = sum((recent[i] - mean_y) ** 2 for i in range(n))
    if ss_tot == 0:
        return 100.0 if slope != 0 else 0.0

    ss_res = sum((recent[i] - (slope * i + (mean_y - slope * (sum_x / n)))) ** 2 for i in range(n))
    r_squared = 1.0 - (ss_res / ss_tot)
    return max(0.0, min(100.0, r_squared * 100.0))
