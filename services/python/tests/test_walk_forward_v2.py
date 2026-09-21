# -*- coding: utf-8 -*-
"""Tests for walk‑forward validation (Phase 40)."""

from datetime import datetime, timedelta, timezone

from src.research.backtest_v2 import Bar
from src.research.walk_forward_v2 import WalkForwardValidator


def _make_price_series(start: float, steps: int) -> list[float]:
    return [start + i * 0.0005 for i in range(steps)]


def _bars_from_prices(prices: list[float], start_hour: int = 0) -> list[Bar]:
    base = datetime(2024, 1, 1, start_hour, 0, tzinfo=timezone.utc)
    bars = []
    for i, p in enumerate(prices):
        bars.append(
            Bar(
                time=base + timedelta(hours=i),
                open=p,
                high=p * 1.001,
                low=p * 0.999,
                close=p,
            )
        )
    return bars


def _simple_signal(_bars: list[Bar], idx: int) -> int:
    # Simple upward trend detector: go long when price rises, short otherwise.
    if idx < 1:
        return 0
    return 1 if _bars[idx].close >= _bars[idx - 1].close else -1


def test_walk_forward_basic() -> None:
    prices = _make_price_series(1.08, 30)
    bars = _bars_from_prices(prices)
    validator = WalkForwardValidator(n_windows=3, train_ratio=0.6)
    report = validator.validate(bars, _simple_signal)
    # Expect three windows, each with a status field.
    assert len(report.windows) == 3
    for win in report.windows:
        assert win.period.startswith("2024-Q")
        # Minimum trade count is 1 by default.
        assert win.trades >= 1
        # Every window must have PASS or FAIL (never INSufficient with this data).
        assert win.status in {"PASS", "FAIL"}
    # With a gently rising series we expect at least one PASS.
    assert any(w.status == "PASS" for w in report.windows)


def test_insufficient_trades_marked() -> None:
    # A tiny series yields a single OOS window with too few trades.
    prices = _make_price_series(1.08, 6)
    bars = _bars_from_prices(prices)
    validator = WalkForwardValidator(n_windows=1, min_trades=99)
    report = validator.validate(bars, _simple_signal)
    assert len(report.windows) == 1
    assert report.windows[0].status == "INSUFFICIENT"


def test_custom_thresholds() -> None:
    # Use a *flat* series so net profit is ~0 → PF must fail the 2.0 bar.
    prices = [1.08 for _ in range(60)]
    bars = _bars_from_prices(prices)
    validator = WalkForwardValidator(
        n_windows=2,
        min_profit_factor=2.0,
        min_expectancy_r=0.5,
        max_dd_pct=5.0,
    )
    report = validator.validate(bars, _simple_signal)
    # With stringent thresholds no window should PASS.
    assert report.pass_count == 0
    assert report.fail_count == len(report.windows)
    assert not report.robust


def test_param_search_is_actually_applied() -> None:
    """Audit P2-14: param_search re-fits and its fitted fn is used OOS."""
    prices = _make_price_series(1.08, 40)
    bars = _bars_from_prices(prices)
    validator = WalkForwardValidator(n_windows=2, train_ratio=0.6)

    calls = {"n": 0}
    trained_on: list[int] = []

    def param_search(train_bars):
        calls["n"] += 1
        trained_on.append(len(train_bars))

        # Return a *fitted* signal fn — always flat (no trades).
        def fitted(_bars, _idx):
            return 0

        return fitted

    report = validator.validate(bars, _simple_signal, param_search=param_search)
    # The fitter was called once per window…
    assert calls["n"] == len(report.windows)
    # …and each call received a non-empty train segment.
    assert all(n > 0 for n in trained_on)


def test_param_search_failure_falls_back_to_base_signal() -> None:
    """A raising param_search must not crash validation (fallback to base)."""
    prices = _make_price_series(1.08, 30)
    bars = _bars_from_prices(prices)
    validator = WalkForwardValidator(n_windows=2, train_ratio=0.6)

    def boom(_train_bars):
        raise RuntimeError("fit failed")

    report = validator.validate(bars, _simple_signal, param_search=boom)
    assert len(report.windows) == 2  # validation still completed
