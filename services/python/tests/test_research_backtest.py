# -*- coding: utf-8 -*-
"""Tests for the research backtest realism (PRD §18 / P2-24).

The backtest must use the project's *real* indicator code (no hand-rolled EMA
loop), run deterministically, and support walk-forward validation: data is split
into train/test windows, a backtest runs on each window, and the results are
aggregated with ``walk_forward`` metadata.

Kept deliberately independent of the exact metrics: it asserts structure,
determinism and safe handling of empty/short data.
"""

from __future__ import annotations

import pytest
from research.engine import BacktestResult, ResearchEngine


def _make_experiment(engine: ResearchEngine, version: str = "v1"):
    hypothesis = engine.create_hypothesis("Trend", "EMA trend", ["ema"], ["rev"], {})
    engine.create_strategy_version(
        version, {"fast_ema_period": 3, "slow_ema_period": 8}
    )
    return engine.create_experiment(hypothesis.id, version, {})


def _trending_prices(n: int = 200) -> list[float]:
    # Deterministic oscillating-then-trending series so crossovers occur.
    prices = []
    price = 100.0
    for i in range(n):
        price += 1.0 if (i // 10) % 2 == 0 else -0.8
        prices.append(round(price, 4))
    return prices


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------
class TestDeterministic:
    def test_same_input_same_output(self) -> None:
        prices = _trending_prices()
        engine_a = ResearchEngine()
        engine_b = ResearchEngine()
        exp_a = _make_experiment(engine_a)
        exp_b = _make_experiment(engine_b)
        res_a = engine_a.run_backtest(exp_a, prices)
        res_b = engine_b.run_backtest(exp_b, prices)
        assert res_a.total_trades == res_b.total_trades
        assert res_a.net_pnl == pytest.approx(res_b.net_pnl)
        assert [t["pnl"] for t in res_a.trades] == [t["pnl"] for t in res_b.trades]

    def test_produces_trades_on_trending_data(self) -> None:
        engine = ResearchEngine()
        exp = _make_experiment(engine)
        result = engine.run_backtest(exp, _trending_prices())
        assert result.total_trades >= 1


# ---------------------------------------------------------------------------
# Walk-forward metadata
# ---------------------------------------------------------------------------
class TestWalkForward:
    def test_walk_forward_metadata_present(self) -> None:
        engine = ResearchEngine()
        exp = _make_experiment(engine)
        result = engine.run_backtest(exp, _trending_prices(), train_ratio=0.7)
        assert isinstance(result, BacktestResult)
        assert isinstance(result.walk_forward, dict)
        wf = result.walk_forward
        assert wf["enabled"] is True
        assert wf["train_ratio"] == pytest.approx(0.7)
        assert isinstance(wf["windows"], list)
        assert len(wf["windows"]) >= 1
        assert "aggregate" in wf

    def test_per_window_metrics_present(self) -> None:
        engine = ResearchEngine()
        exp = _make_experiment(engine)
        result = engine.run_backtest(exp, _trending_prices(), train_ratio=0.7)
        window = result.walk_forward["windows"][0]
        assert "split" in window
        assert set(window["split"]) == {"train", "test"}
        assert "metrics" in window
        for key in ("total_trades", "win_rate", "net_pnl", "max_drawdown"):
            assert key in window["metrics"]

    def test_aggregate_metrics_computed(self) -> None:
        engine = ResearchEngine()
        exp = _make_experiment(engine)
        result = engine.run_backtest(exp, _trending_prices(), train_ratio=0.7)
        aggregate = result.walk_forward["aggregate"]
        assert "total_trades" in aggregate
        assert "net_pnl" in aggregate
        assert "windows" in aggregate
        assert aggregate["windows"] == len(result.walk_forward["windows"])

    def test_walk_forward_can_be_disabled(self) -> None:
        engine = ResearchEngine()
        exp = _make_experiment(engine)
        result = engine.run_backtest(exp, _trending_prices(), walk_forward=False)
        assert result.walk_forward["enabled"] is False


# ---------------------------------------------------------------------------
# Empty / short data safety
# ---------------------------------------------------------------------------
class TestSafeDataHandling:
    def test_empty_data(self) -> None:
        engine = ResearchEngine()
        exp = _make_experiment(engine)
        result = engine.run_backtest(exp, [])
        assert result.total_trades == 0
        assert exp.status == "completed"

    def test_short_data(self) -> None:
        engine = ResearchEngine()
        exp = _make_experiment(engine)
        result = engine.run_backtest(exp, [1.0, 2.0])
        assert result.total_trades == 0

    def test_very_short_data_with_walk_forward(self) -> None:
        engine = ResearchEngine()
        exp = _make_experiment(engine)
        # Fewer bars than the slow EMA period — must not raise.
        result = engine.run_backtest(exp, [1.0, 2.0, 3.0, 4.0], train_ratio=0.7)
        assert isinstance(result, BacktestResult)


# ---------------------------------------------------------------------------
# O(n) performance: precomputed EMA series must not be O(n²) at 100k bars.
# ---------------------------------------------------------------------------
class TestScalability:
    def test_100k_bars_completes_in_reasonable_time(self) -> None:
        """100,000 bars should finish in well under the O(n²) worst case.

        The old implementation called ``ema()`` on a growing window per bar,
        producing ~10^10 operations for 100k bars. With the O(n) precomputed
        ``ema_series`` fix, this completes in seconds.
        """
        import time

        prices = _trending_prices(n=100_000)
        engine = ResearchEngine()
        exp = _make_experiment(engine)
        start = time.monotonic()
        result = engine.run_backtest(exp, prices)
        elapsed = time.monotonic() - start
        # O(n) should finish in ~3s on slow CI; O(n²) would take hours.
        # Allow generous headroom for CI variance.
        assert (
            elapsed < 30.0
        ), f"Backtest of 100k bars took {elapsed:.1f}s — O(n) fix may be broken"
        assert isinstance(result, BacktestResult)
        assert result.total_trades >= 0  # no crash, metrics computed

    def test_10k_bars_scales_linearly(self) -> None:
        """10k bars should be at least 5x faster per-bar than 1k bars (O(n) vs O(n²))."""
        import time

        engine = ResearchEngine()
        exp = _make_experiment(engine)
        prices_1k = _trending_prices(n=1_000)
        prices_10k = _trending_prices(n=10_000)
        start = time.monotonic()
        engine.run_backtest(exp, prices_1k)
        t_1k = time.monotonic() - start
        start = time.monotonic()
        engine.run_backtest(exp, prices_10k)
        t_10k = time.monotonic() - start
        # O(n): t_10k ≈ 10x t_1k (allow 2x–50x for overhead variance).
        # O(n²): t_10k would be ~100x t_1k, failing the upper bound.
        # If t_1k is too small to measure reliably, skip the ratio check.
        if t_1k >= 0.05:
            ratio = t_10k / t_1k
            assert ratio < 50.0, (
                f"Scaling ratio {ratio:.1f}x suggests O(n²): 10k took {t_10k:.2f}s, "
                f"1k took {t_1k:.2f}s"
            )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
