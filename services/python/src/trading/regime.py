# -*- coding: utf-8 -*-
"""Market Regime Engine — deterministic classification of market conditions.

Classifies the current market into one of six regimes using ADX, Bollinger Bands,
and trend/volatility analysis.  All calculations are pure-Python and deterministic.

Price-series inputs are **oldest-first** (index 0 = oldest bar).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from .indicators import adx, bollinger_bands
from .trend import TrendDirection, detect_trend_adx, detect_trend_slope
from .volatility import atr_volatility, bollinger_band_width, classify_volatility

__all__ = [
    "MarketRegime",
    "RegimeResult",
    "detect_regime",
]


# ---------------------------------------------------------------------------
# Enums & dataclasses
# ---------------------------------------------------------------------------


class MarketRegime(str, Enum):
    """Six possible market regime classifications."""

    TRENDING = "trending"
    RANGING = "ranging"
    BREAKOUT = "breakout"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RegimeResult:
    """Result of a regime detection pass.

    Attributes:
        regime: The classified :class:`MarketRegime`.
        confidence: Confidence in [0.0, 1.0]; higher = more certain.
        metadata: Supporting diagnostic values (adx, bb_width, trend_direction, …).
    """

    regime: MarketRegime
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Bollinger Band width thresholds (bollinger_band_width returns percentage × 100,
# e.g. 5.0 means (upper-lower)/middle = 5 %)
_BB_SQUEEZE_THRESHOLD = 3.0  # < 3 % → LOW_VOLATILITY squeeze
_BB_EXPAND_THRESHOLD = 10.0  # > 10 % → HIGH_VOLATILITY expansion

# ADX thresholds
_ADX_TREND_MIN = 25.0  # ADX > 25 → trending
_ADX_RANGING_MAX = 20.0  # ADX < 20 → ranging


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_regime(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 20,
) -> RegimeResult:
    """Classify the current market regime from OHLC price data.

    Detection priority (first match wins):

    1. **LOW_VOLATILITY** — Bollinger Band width squeeze (< 3 %).
    2. **BREAKOUT** — Latest close breaks above upper BB or below lower BB.
    3. **HIGH_VOLATILITY** — Bollinger Band width expansion (> 10 %).
    4. **TRENDING** — ADX > 25 and clear directional trend.
    5. **RANGING** — ADX < 20 and no clear trend direction.
    6. **UNKNOWN** — Insufficient data or ambiguous signal.

    Args:
        highs:   High prices (oldest → newest).
        lows:    Low prices (oldest → newest).
        closes:  Close prices (oldest → newest).
        period:  Look-back period for all indicators (default 20).

    Returns:
        :class:`RegimeResult` with the detected regime, confidence, and metadata.
    """
    _unknown = RegimeResult(
        regime=MarketRegime.UNKNOWN,
        confidence=0.0,
        metadata={"reason": "insufficient_data"},
    )

    # Minimum bars required: period + 1 for ADX/ATR internals
    min_bars = period + 1
    if (
        len(highs) < min_bars
        or len(lows) < min_bars
        or len(closes) < min_bars
        or len(highs) != len(lows)
        or len(lows) != len(closes)
    ):
        return _unknown

    # --- Gather indicator values ---
    adx_value: Optional[float] = adx(highs, lows, closes, period)
    bb = bollinger_bands(closes, period)
    bb_width: Optional[float] = bollinger_band_width(closes, period)
    vol_pct: Optional[float] = atr_volatility(highs, lows, closes, period)
    vol_class: str = classify_volatility(vol_pct)

    trend_dir, trend_strength = detect_trend_adx(highs, lows, closes, period)
    slope_dir = detect_trend_slope(closes, period)

    latest_close = closes[-1]

    metadata: dict[str, Any] = {
        "adx": adx_value,
        "bb_width_pct": bb_width,
        "atr_volatility_pct": vol_pct,
        "volatility_class": vol_class,
        "trend_direction": trend_dir.value if trend_dir else None,
        "trend_strength": trend_strength.value if trend_strength else None,
        "slope_direction": slope_dir.value if slope_dir else None,
        "latest_close": latest_close,
        "bb_upper": bb.upper if bb else None,
        "bb_lower": bb.lower if bb else None,
    }

    # --- Rule 1: LOW_VOLATILITY (BB squeeze) ---
    if bb_width is not None and bb_width < _BB_SQUEEZE_THRESHOLD:
        # Confidence scales inversely with bb_width (tighter = more confident)
        confidence = min(1.0, (_BB_SQUEEZE_THRESHOLD - bb_width) / _BB_SQUEEZE_THRESHOLD)
        return RegimeResult(
            regime=MarketRegime.LOW_VOLATILITY,
            confidence=round(confidence, 4),
            metadata={**metadata, "trigger": "bb_squeeze"},
        )

    # --- Rule 2: BREAKOUT (price outside BB bands) ---
    if bb is not None:
        if latest_close > bb.upper:
            # Confidence proportional to how far above upper band
            overshoot = (latest_close - bb.upper) / (bb.upper - bb.lower + 1e-10)
            confidence = min(1.0, 0.6 + overshoot * 2.0)
            return RegimeResult(
                regime=MarketRegime.BREAKOUT,
                confidence=round(confidence, 4),
                metadata={**metadata, "trigger": "close_above_upper_bb", "direction": "up"},
            )
        if latest_close < bb.lower:
            overshoot = (bb.lower - latest_close) / (bb.upper - bb.lower + 1e-10)
            confidence = min(1.0, 0.6 + overshoot * 2.0)
            return RegimeResult(
                regime=MarketRegime.BREAKOUT,
                confidence=round(confidence, 4),
                metadata={**metadata, "trigger": "close_below_lower_bb", "direction": "down"},
            )

    # --- Rule 3: HIGH_VOLATILITY (BB wide expansion) ---
    if bb_width is not None and bb_width > _BB_EXPAND_THRESHOLD:
        confidence = min(1.0, (bb_width - _BB_EXPAND_THRESHOLD) / _BB_EXPAND_THRESHOLD)
        return RegimeResult(
            regime=MarketRegime.HIGH_VOLATILITY,
            confidence=round(confidence, 4),
            metadata={**metadata, "trigger": "bb_expansion"},
        )

    # --- Rule 4: TRENDING (ADX > 25 + directional slope) ---
    if adx_value is not None and adx_value > _ADX_TREND_MIN:
        is_directional = slope_dir in (TrendDirection.UPTREND, TrendDirection.DOWNTREND)
        if is_directional:
            # Confidence from ADX strength (25→0.5, 50→1.0)
            confidence = min(1.0, (adx_value - _ADX_TREND_MIN) / (_ADX_TREND_MIN * 2.0) + 0.5)
            return RegimeResult(
                regime=MarketRegime.TRENDING,
                confidence=round(confidence, 4),
                metadata={**metadata, "trigger": "adx_trend"},
            )

    # --- Rule 5: RANGING (ADX < 20 + no clear direction) ---
    if adx_value is not None and adx_value < _ADX_RANGING_MAX:
        is_ranging = slope_dir in (TrendDirection.RANGING, TrendDirection.UNKNOWN)
        if is_ranging:
            confidence = min(1.0, (_ADX_RANGING_MAX - adx_value) / _ADX_RANGING_MAX)
            return RegimeResult(
                regime=MarketRegime.RANGING,
                confidence=round(confidence, 4),
                metadata={**metadata, "trigger": "adx_ranging"},
            )

    # --- Rule 6: UNKNOWN (ambiguous / no rule matched) ---
    return RegimeResult(
        regime=MarketRegime.UNKNOWN,
        confidence=0.0,
        metadata={**metadata, "reason": "no_rule_matched"},
    )
