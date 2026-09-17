# -*- coding: utf-8 -*-
"""Tests for the *series* indicator variants used by the chart layer.

The series variants must agree with the existing latest-value functions used
by the trading engine (``rsi``, ``macd``, ``bollinger_bands``) — otherwise the
chart would draw a different indicator than the one the engine trades on.
Alignment and ``None`` handling are locked in here too: a ``None`` means "not
enough data yet", never a fabricated 0.0.
"""

from __future__ import annotations

import pytest

from src.trading.indicators import (
    bollinger_bands,
    bollinger_series,
    macd,
    macd_series,
    rsi,
    rsi_series,
)


def _trend(n: int = 60) -> list[float]:
    """Deterministic, wiggly price series (oldest → newest)."""
    out = []
    price = 100.0
    for i in range(n):
        price += ((i % 7) - 3) * 0.5 + 0.1
        out.append(round(price, 4))
    return out


class TestRsiSeries:
    def test_last_value_matches_rsi(self) -> None:
        prices = _trend(80)
        series = rsi_series(prices, 14)
        assert series[-1] == pytest.approx(rsi(prices, 14))

    def test_alignment(self) -> None:
        prices = _trend(50)
        series = rsi_series(prices, 14)
        assert len(series) == len(prices)
        # Before period+1 bars there is no RSI — None, not 0.0.
        assert all(v is None for v in series[:14])
        assert series[14] is not None

    def test_insufficient_data_all_none(self) -> None:
        series = rsi_series([100.0, 101.0], 14)
        assert series == [None, None]

    def test_rising_series_hits_100(self) -> None:
        prices = [100.0 + i for i in range(40)]
        series = rsi_series(prices, 14)
        assert series[-1] == pytest.approx(100.0)

    def test_period_validation(self) -> None:
        with pytest.raises(ValueError):
            rsi_series([1.0, 2.0], 0)


class TestMacdSeries:
    def test_last_values_match_macd(self) -> None:
        prices = _trend(120)
        macd_line, signal_line, hist = macd_series(prices, 12, 26, 9)
        ref = macd(prices, 12, 26, 9)
        assert ref is not None
        assert macd_line[-1] == pytest.approx(ref.macd_line)
        assert signal_line[-1] == pytest.approx(ref.signal_line)
        assert hist[-1] == pytest.approx(ref.histogram)

    def test_alignment_and_none_leading(self) -> None:
        prices = _trend(120)
        macd_line, signal_line, hist = macd_series(prices, 12, 26, 9)
        for arr in (macd_line, signal_line, hist):
            assert len(arr) == len(prices)
        # MACD line starts at slow_period-1.
        assert all(v is None for v in macd_line[:25])
        assert macd_line[25] is not None
        # Signal line starts later (slow-1 + signal-1).
        assert all(v is None for v in signal_line[:33])
        assert signal_line[33] is not None

    def test_insufficient_data(self) -> None:
        macd_line, signal_line, hist = macd_series([100.0] * 10, 12, 26, 9)
        assert all(v is None for v in macd_line)
        assert all(v is None for v in signal_line)
        assert all(v is None for v in hist)

    def test_period_validation(self) -> None:
        with pytest.raises(ValueError):
            macd_series([1.0] * 50, 26, 12, 9)


class TestBollingerSeries:
    def test_last_values_match_bollinger_bands(self) -> None:
        prices = _trend(60)
        upper, middle, lower = bollinger_series(prices, 20, 2.0)
        ref = bollinger_bands(prices, 20, 2.0)
        assert ref is not None
        assert upper[-1] == pytest.approx(ref.upper)
        assert middle[-1] == pytest.approx(ref.middle)
        assert lower[-1] == pytest.approx(ref.lower)

    def test_alignment_and_none_leading(self) -> None:
        prices = _trend(60)
        upper, middle, lower = bollinger_series(prices, 20, 2.0)
        for arr in (upper, middle, lower):
            assert len(arr) == len(prices)
            assert all(v is None for v in arr[:19])
            assert arr[19] is not None

    def test_insufficient_data(self) -> None:
        upper, middle, lower = bollinger_series([100.0] * 5, 20, 2.0)
        assert all(v is None for v in upper)
        assert all(v is None for v in middle)
        assert all(v is None for v in lower)

    def test_bands_ordering(self) -> None:
        prices = _trend(60)
        upper, middle, lower = bollinger_series(prices, 20, 2.0)
        for u, m, l in zip(upper[19:], middle[19:], lower[19:]):
            assert u is not None and m is not None and l is not None
            assert l <= m <= u

    def test_period_validation(self) -> None:
        with pytest.raises(ValueError):
            bollinger_series([1.0] * 30, 0)
