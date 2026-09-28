# -*- coding: utf-8 -*-
"""Tests for R-multiple computation + per-period aggregation.

R expresses a trade's result in units of initial risk (1R = |entry - initial
SL|). These tests pin the sign/direction conventions and the honest fallbacks
(``None`` instead of a fabricated 0).
"""

from __future__ import annotations

from datetime import datetime, timezone

from review.r_multiple import aggregate_r_by_period, compute_r_multiple, r_bucket_from_trades

# ---------------------------------------------------------------------------
# compute_r_multiple
# ---------------------------------------------------------------------------


def test_buy_winner_positive_r():
    # entry 2000, SL 1990 (10 risk), exit 2020 → +2R
    r = compute_r_multiple(direction="buy", entry_price=2000, exit_price=2020, stop_loss=1990)
    assert r == 2.0


def test_buy_full_stop_minus_one_r():
    r = compute_r_multiple(direction="buy", entry_price=2000, exit_price=1990, stop_loss=1990)
    assert r == -1.0


def test_sell_winner_positive_r():
    # entry 2000, SL 2010 (10 risk), exit 1980 → +2R
    r = compute_r_multiple(direction="sell", entry_price=2000, exit_price=1980, stop_loss=2010)
    assert r == 2.0


def test_sell_full_stop_minus_one_r():
    r = compute_r_multiple(direction="sell", entry_price=2000, exit_price=2010, stop_loss=2010)
    assert r == -1.0


def test_breakeven_is_zero_r():
    r = compute_r_multiple(direction="buy", entry_price=2000, exit_price=2000, stop_loss=1990)
    assert r == 0.0


def test_case_insensitive_and_long_short_aliases():
    assert (
        compute_r_multiple(direction="LONG", entry_price=100, exit_price=110, stop_loss=95) == 2.0
    )
    assert (
        compute_r_multiple(direction="Short", entry_price=100, exit_price=90, stop_loss=105) == 2.0
    )


def test_trailing_stop_does_not_shrink_denominator():
    # We always pass the ORIGINAL SL, so R is unaffected by later trailing.
    r = compute_r_multiple(direction="buy", entry_price=2000, exit_price=2020, stop_loss=1990)
    assert r == 2.0
    # If a (wrongly) tighter-but-valid original SL were used, risk shrinks and
    # R inflates — this documents WHY we must keep the original SL.
    r_tight = compute_r_multiple(direction="buy", entry_price=2000, exit_price=2020, stop_loss=1996)
    assert r_tight == 5.0  # 20 / 4


def test_missing_or_degenerate_inputs_return_none():
    assert (
        compute_r_multiple(direction="buy", entry_price=2000, exit_price=2020, stop_loss=0) is None
    )
    assert (
        compute_r_multiple(direction="buy", entry_price=0, exit_price=2020, stop_loss=1990) is None
    )
    assert (
        compute_r_multiple(direction="buy", entry_price=2000, exit_price=0, stop_loss=1990) is None
    )
    assert (
        compute_r_multiple(direction="hold", entry_price=2000, exit_price=2020, stop_loss=1990)
        is None
    )


def test_wrong_side_stop_returns_none():
    # A BUY with SL above entry is invalid (risk <= 0) → None, not a fake number.
    assert (
        compute_r_multiple(direction="buy", entry_price=2000, exit_price=2020, stop_loss=2010)
        is None
    )


# ---------------------------------------------------------------------------
# r_bucket_from_trades
# ---------------------------------------------------------------------------


def test_bucket_summary_averages_r():
    trades = [{"r_multiple": -1.0}, {"r_multiple": 2.0}]
    bucket = r_bucket_from_trades(trades)
    assert bucket["count"] == 2
    assert bucket["wins"] == 1
    assert bucket["losses"] == 1
    assert bucket["win_rate"] == 50.0
    assert bucket["avg_r"] == 0.5  # (-1 + 2) / 2
    assert bucket["total_r"] == 1.0
    assert bucket["profit_factor"] == 2.0  # 2 / 1


def test_bucket_ignores_missing_r():
    trades = [{"r_multiple": 1.0}, {"r_multiple": None}, {}]
    bucket = r_bucket_from_trades(trades)
    assert bucket["count"] == 1
    assert bucket["avg_r"] == 1.0


def test_bucket_empty_is_zeroed():
    bucket = r_bucket_from_trades([])
    assert bucket["count"] == 0
    assert bucket["avg_r"] == 0.0


# ---------------------------------------------------------------------------
# aggregate_r_by_period
# ---------------------------------------------------------------------------


def _trade(r: float, ts: datetime) -> dict:
    return {"r_multiple": r, "closed_at": ts}


def test_aggregate_by_day():
    d1 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    d1b = datetime(2025, 1, 1, 15, 0, tzinfo=timezone.utc)
    d2 = datetime(2025, 1, 2, 9, 0, tzinfo=timezone.utc)
    buckets = aggregate_r_by_period(
        [_trade(-1.0, d1), _trade(2.0, d1b), _trade(1.0, d2)],
        period="day",
    )
    # Newest first.
    assert buckets[0]["key"] == "2025-01-02"
    assert buckets[0]["avg_r"] == 1.0
    assert buckets[1]["key"] == "2025-01-01"
    assert buckets[1]["count"] == 2
    assert buckets[1]["avg_r"] == 0.5


def test_aggregate_by_month():
    buckets = aggregate_r_by_period(
        [
            _trade(1.0, datetime(2025, 1, 15, tzinfo=timezone.utc)),
            _trade(3.0, datetime(2025, 1, 20, tzinfo=timezone.utc)),
            _trade(-1.0, datetime(2025, 2, 3, tzinfo=timezone.utc)),
        ],
        period="month",
    )
    assert buckets[0]["key"] == "2025-02"
    assert buckets[0]["avg_r"] == -1.0
    assert buckets[1]["key"] == "2025-01"
    assert buckets[1]["avg_r"] == 2.0


def test_aggregate_by_week_is_iso():
    # 2025-01-06 is a Monday → ISO week 02.
    buckets = aggregate_r_by_period(
        [_trade(2.0, datetime(2025, 1, 6, tzinfo=timezone.utc))],
        period="week",
    )
    assert buckets[0]["key"] == "2025-W02"


def test_aggregate_skips_bad_timestamp_and_r():
    buckets = aggregate_r_by_period(
        [
            {"r_multiple": 1.0, "closed_at": None},
            {"r_multiple": None, "closed_at": datetime(2025, 1, 1, tzinfo=timezone.utc)},
        ],
        period="day",
    )
    assert buckets == []


def test_aggregate_accepts_iso_string_timestamp():
    buckets = aggregate_r_by_period(
        [{"r_multiple": 1.5, "closed_at": "2025-03-01T12:00:00+00:00"}],
        period="day",
    )
    assert buckets[0]["key"] == "2025-03-01"
    assert buckets[0]["avg_r"] == 1.5
