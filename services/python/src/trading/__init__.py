# -*- coding: utf-8 -*-
"""EA Bot Deterministic Trading Engine — packaged for integration with EA Bot.

This package provides:

- Technical indicators: SMA, EMA, RSI, MACD, ATR, ADX, Stochastic
- Trend detection: EMA crossover, slope analysis, ADX strength
- Volatility calculations: ATR, Bollinger Bands, historical volatility
- Position sizing: Fixed fractional, ATR-based, margin-based
- Risk metrics: Max drawdown, Sharpe ratio, Sortino ratio, profit factor

All calculations are pure-Python and deterministic — no LLM, no randomness.
"""

from __future__ import annotations

from .indicators import adx, atr, ema, macd, rsi, sma
from .position_sizing import atr_position_size
from .regime import MarketRegime, RegimeResult, detect_regime
from .risk import (
    exposure_percent,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    value_at_risk,
    win_rate,
)
from .trend import TrendDirection, calculate_trend_strength_percent
from .volatility import (
    atr_volatility,
    bollinger_band_width,
    classify_volatility,
    historical_volatility,
    price_range_volatility,
)

__all__ = [
    # Indicators
    "sma",
    "ema",
    "rsi",
    "macd",
    "atr",
    "adx",
    # Trend
    "TrendDirection",
    "calculate_trend_strength_percent",
    # Volatility
    "historical_volatility",
    "atr_volatility",
    "bollinger_band_width",
    "price_range_volatility",
    "classify_volatility",
    # Market Regime
    "MarketRegime",
    "RegimeResult",
    "detect_regime",
    # Position sizing
    "atr_position_size",
    # Risk metrics
    "max_drawdown",
    "sharpe_ratio",
    "sortino_ratio",
    "profit_factor",
    "win_rate",
    "value_at_risk",
    "exposure_percent",
]
