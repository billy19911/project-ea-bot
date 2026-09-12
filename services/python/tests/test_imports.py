# -*- coding: utf-8 -*-
"""Test static imports for trading package."""

from trading import (
    TrendDirection,
    adx,
    atr,
    atr_position_size,
    atr_volatility,
    bollinger_band_width,
    calculate_trend_strength_percent,
    classify_volatility,
    ema,
    exposure_percent,
    historical_volatility,
    macd,
    max_drawdown,
    price_range_volatility,
    profit_factor,
    rsi,
    sharpe_ratio,
    sma,
    sortino_ratio,
    value_at_risk,
    win_rate,
)


def test_all_imports_available():
    """Verify all exported functions are importable."""
    assert callable(sma)
    assert callable(ema)
    assert callable(rsi)
    assert callable(macd)
    assert callable(atr)
    assert callable(adx)
    assert isinstance(TrendDirection, type)
    assert callable(calculate_trend_strength_percent)
    assert callable(historical_volatility)
    assert callable(atr_volatility)
    assert callable(bollinger_band_width)
    assert callable(price_range_volatility)
    assert callable(classify_volatility)
    assert callable(atr_position_size)
    assert callable(max_drawdown)
    assert callable(sharpe_ratio)
    assert callable(sortino_ratio)
    assert callable(profit_factor)
    assert callable(win_rate)
    assert callable(value_at_risk)
    assert callable(exposure_percent)
