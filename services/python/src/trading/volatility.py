# -*- coding: utf-8 -*-
"""Volatility calculations for deterministic market analysis."""

from __future__ import annotations

import math
from typing import Optional

from .indicators import atr, bollinger_bands


def historical_volatility(
    prices: list[float], period: int = 20, annualization: int = 252
) -> Optional[float]:
    if len(prices) < period + 1 or period <= 0:
        return None
    returns = []
    recent = prices[-(period + 1) :]
    for i in range(1, len(recent)):
        if recent[i - 1] == 0:
            return None
        returns.append(math.log(recent[i] / recent[i - 1]))
    mean_return = sum(returns) / len(returns)
    variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
    return math.sqrt(variance) * math.sqrt(annualization) * 100.0


def atr_volatility(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14
) -> Optional[float]:
    value = atr(highs, lows, closes, period)
    if value is None or not closes or closes[-1] == 0:
        return None
    return (value / closes[-1]) * 100.0


def bollinger_band_width(
    prices: list[float], period: int = 20, std_dev: float = 2.0
) -> Optional[float]:
    bands = bollinger_bands(prices, period, std_dev)
    if bands is None:
        return None
    upper, middle, lower = bands.upper, bands.middle, bands.lower
    if middle == 0:
        return None
    return ((upper - lower) / middle) * 100.0


def price_range_volatility(
    highs: list[float], lows: list[float], period: int = 20
) -> Optional[float]:
    if len(highs) < period or len(lows) < period or period <= 0:
        return None
    recent_high = max(highs[-period:])
    recent_low = min(lows[-period:])
    midpoint = (recent_high + recent_low) / 2.0
    if midpoint == 0:
        return None
    return ((recent_high - recent_low) / midpoint) * 100.0


def classify_volatility(volatility_pct: Optional[float]) -> str:
    if volatility_pct is None:
        return "unknown"
    if volatility_pct < 0.5:
        return "very_low"
    if volatility_pct < 1.5:
        return "low"
    if volatility_pct < 3.0:
        return "normal"
    if volatility_pct < 6.0:
        return "high"
    return "extreme"
