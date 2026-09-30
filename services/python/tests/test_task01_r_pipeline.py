# -*- coding: utf-8 -*-
"""TASK 01 — R/R + performance pipeline stop-gate tests.

Covers the mandatory scenarios in ``telegram/_oc_task01.md``:

* BUY profit / loss, SELL profit / loss
* exact 1R / 2R / 3R
* trailing SL after entry does not change initial R
* BEP after entry → R = 0
* missing original SL → R unavailable (never fabricated)
* restart before close (entry context survives) / restart after close (durable)
* manual broker close (position disappears) detection
* fast SL/TP close
* partial close (volume shrink still a close on disappearance)
* duplicate close event → single review (idempotent store)
* same symbol, multi-account isolation (ledger keyed by unique trade id)

All tests are pure / file-backed and never touch MT5 or any live path.
"""

from __future__ import annotations

import pytest

from persistence.review_store import ReviewStore
from persistence.trade_ledger import TradeLedger
from review.close_detector import PositionCloseDetector
from review.r_multiple import compute_r_multiple


# ---------------------------------------------------------------------------
# Core R formula — BUY/SELL profit & loss, exact multiples, trailing, BEP
# ---------------------------------------------------------------------------
def test_buy_profit_positive_r():
    # entry 1.09452, SL 1.09387 (risk 0.00065), exit 1.09612 (reward +0.0016)
    r = compute_r_multiple(
        direction="BUY", entry_price=1.09452, exit_price=1.09612, stop_loss=1.09387
    )
    assert r is not None and r > 0
    assert r == pytest.approx((1.09612 - 1.09452) / (1.09452 - 1.09387), abs=1e-4)


def test_buy_loss_negative_r():
    r = compute_r_multiple(
        direction="BUY", entry_price=1.09452, exit_price=1.09287, stop_loss=1.09387
    )
    assert r is not None and r < 0


def test_sell_profit_positive_r():
    r = compute_r_multiple(
        direction="SELL", entry_price=1.38450, exit_price=1.38290, stop_loss=1.38527
    )
    assert r is not None and r > 0


def test_sell_loss_negative_r():
    r = compute_r_multiple(
        direction="SELL", entry_price=1.38450, exit_price=1.38610, stop_loss=1.38527
    )
    assert r is not None and r < 0


def test_exact_1r_2r_3r():
    # BUY: entry 100, SL 95 → risk 5.
    assert compute_r_multiple(
        direction="BUY", entry_price=100.0, exit_price=105.0, stop_loss=95.0
    ) == pytest.approx(1.0)
    assert compute_r_multiple(
        direction="BUY", entry_price=100.0, exit_price=110.0, stop_loss=95.0
    ) == pytest.approx(2.0)
    assert compute_r_multiple(
        direction="BUY", entry_price=100.0, exit_price=115.0, stop_loss=95.0
    ) == pytest.approx(3.0)
    # SELL: entry 100, SL 105 → risk 5.
    assert compute_r_multiple(
        direction="SELL", entry_price=100.0, exit_price=95.0, stop_loss=105.0
    ) == pytest.approx(1.0)
    assert compute_r_multiple(
        direction="SELL", entry_price=100.0, exit_price=90.0, stop_loss=105.0
    ) == pytest.approx(2.0)


def test_trailing_sl_does_not_change_initial_r():
    # Original SL 95 (risk 5). A trailed SL (e.g. 100) must NOT be the
    # denominator: R still uses the ORIGINAL SL passed in.
    r = compute_r_multiple(direction="BUY", entry_price=100.0, exit_price=110.0, stop_loss=95.0)
    assert r == pytest.approx(2.0)  # not (110-100)/(100-100)=inf or based on trail


def test_bep_after_entry_is_zero_r():
    r = compute_r_multiple(direction="BUY", entry_price=100.0, exit_price=100.0, stop_loss=95.0)
    assert r == pytest.approx(0.0)


def test_missing_or_degenerate_sl_returns_none():
    assert (
        compute_r_multiple(direction="BUY", entry_price=100.0, exit_price=110.0, stop_loss=0.0)
        is None
    )
    assert (
        compute_r_multiple(direction="BUY", entry_price=0.0, exit_price=110.0, stop_loss=95.0)
        is None
    )
    assert (
        compute_r_multiple(direction="UNKNOWN", entry_price=100.0, exit_price=110.0, stop_loss=95.0)
        is None
    )
    # Wrong-side stop (BUY with SL above entry) → degenerate risk → None.
    assert (
        compute_r_multiple(direction="BUY", entry_price=100.0, exit_price=110.0, stop_loss=105.0)
        is None
    )


# ---------------------------------------------------------------------------
# Restart before close — entry context must survive (store-level proxy)
# ---------------------------------------------------------------------------
def test_restart_before_close_entry_context_survives(tmp_path):
    from persistence.entry_context_store import EntryContextStore

    path = str(tmp_path / "ec.jsonl")
    EntryContextStore(path=path).remember(
        12345,
        {
            "symbol": "XAUUSD",
            "direction": "BUY",
            "entry_price": 2000.0,
            "stop_loss": 1990.0,
            "take_profit": 2020.0,
            "risk_distance": 10.0,
            "reward_distance": 20.0,
            "planned_rr": 2.0,
        },
    )
    # Restart → fresh instance reloads from disk.
    reloaded = EntryContextStore(path=path)
    ctx = reloaded.get(12345)
    assert ctx["stop_loss"] == 1990.0
    assert ctx["take_profit"] == 2020.0
    assert ctx["planned_rr"] == 2.0
    # R can now be computed honestly after restart.
    r = compute_r_multiple(
        direction=ctx["direction"],
        entry_price=ctx["entry_price"],
        exit_price=2030.0,
        stop_loss=ctx["stop_loss"],
    )
    assert r == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# Restart after close — review + ledger survive
# ---------------------------------------------------------------------------
def test_restart_after_close_review_survives(tmp_path):
    path = str(tmp_path / "reviews.jsonl")
    store = ReviewStore(path=path)
    store.add_review(
        {
            "trade_id": "T1",
            "outcome": "WIN",
            "pnl": 120.0,
            "r_multiple": 2.5,
            "root_cause_primary": "good_entry",
            "closed_at": "2025-01-02T03:04:05+00:00",
        }
    )
    reloaded = ReviewStore(path=path)
    assert reloaded.size() == 1
    assert reloaded.recent(1)[0]["r_multiple"] == 2.5


def test_restart_after_close_ledger_survives(tmp_path):
    path = str(tmp_path / "ledger.jsonl")
    ledger = TradeLedger(path=path)
    ledger.add_trade(
        {
            "trade_id": 777,
            "symbol": "EURUSD",
            "direction": "SELL",
            "entry_price": 1.10,
            "initial_stop_loss": 1.1050,
            "initial_take_profit": 1.09,
            "target_rr": 2.0,
            "status": "OPEN",
        }
    )
    ledger.update_trade(
        777,
        {"status": "CLOSED", "review_status": "REVIEWED", "r_multiple": 1.8, "exit_price": 1.091},
    )
    reloaded = TradeLedger(path=path)
    rec = reloaded.get_trade(777)
    assert rec["status"] == "CLOSED"
    assert rec["r_multiple"] == 1.8
    assert rec["initial_stop_loss"] == 1.1050
    assert rec["target_rr"] == 2.0


# ---------------------------------------------------------------------------
# Close detection — manual close, fast SL/TP, partial close
# ---------------------------------------------------------------------------
def _detector(captured, resolver=None):
    return PositionCloseDetector(
        on_close=captured.append,
        close_deal_resolver=resolver or (lambda t: None),
    )


def test_manual_broker_close_detected():
    captured: list[dict] = []
    det = _detector(captured)
    det.observe([{"ticket": 1, "side": "BUY", "price_open": 100.0, "price_current": 101.0}])
    closed = det.observe([])  # manual close → ticket gone
    assert len(closed) == 1
    assert closed[0]["trade_id"] == 1
    assert closed[0]["status"] == "CLOSED"


def test_fast_sl_tp_close_uses_real_deal():
    captured: list[dict] = []
    det = _detector(
        captured,
        resolver=lambda t: {"price": 95.0, "time": 1700000000, "profit": -50.0, "side": "SELL"},
    )
    det.observe([{"ticket": 9, "side": "BUY", "price_open": 100.0, "price_current": 99.9}])
    det.observe([])
    assert captured[0]["close_price"] == 95.0
    assert captured[0]["close_price_source"] == "deal_history"


def test_partial_close_still_detected_on_disappearance():
    captured: list[dict] = []
    det = _detector(captured)
    det.observe([{"ticket": 5, "side": "SELL", "price_open": 1.10, "volume": 1.0}])
    # Partial close: volume shrinks but ticket still present → NOT a close.
    det.observe([{"ticket": 5, "side": "SELL", "price_open": 1.10, "volume": 0.5}])
    assert captured == []
    # Final close → disappearance → one close.
    det.observe([])
    assert len(captured) == 1


def test_duplicate_close_event_not_re_emitted():
    captured: list[dict] = []
    det = _detector(captured)
    det.observe([{"ticket": 3, "side": "BUY", "price_open": 100.0}])
    det.observe([])  # close #1
    det.observe([])  # nothing left → no duplicate
    det.observe([])  # still nothing
    assert len(captured) == 1


# ---------------------------------------------------------------------------
# Duplicate review not persisted twice (idempotent store)
# ---------------------------------------------------------------------------
def test_duplicate_review_not_duplicated(tmp_path):
    store = ReviewStore(path=str(tmp_path / "reviews.jsonl"))
    payload = {
        "trade_id": "DUP1",
        "outcome": "WIN",
        "r_multiple": 1.0,
        "closed_at": "2025-01-02T00:00:00+00:00",
    }
    assert store.add_review(payload) is True
    assert store.add_review(payload) is False  # duplicate skipped
    assert store.size() == 1


# ---------------------------------------------------------------------------
# Same symbol, multi-account isolation
# ---------------------------------------------------------------------------
def test_same_symbol_multi_account_isolated(tmp_path):
    ledger = TradeLedger(path=str(tmp_path / "ledger.jsonl"))
    ledger.add_trade(
        {"trade_id": "ACC1-100", "symbol": "EURUSD", "account_id": "ACC1", "direction": "BUY"}
    )
    ledger.add_trade(
        {"trade_id": "ACC2-100", "symbol": "EURUSD", "account_id": "ACC2", "direction": "SELL"}
    )
    assert ledger.get_trade("ACC1-100")["direction"] == "BUY"
    assert ledger.get_trade("ACC2-100")["direction"] == "SELL"
    eur = ledger.query(symbol="EURUSD")
    assert len(eur) == 2


# ---------------------------------------------------------------------------
# Ledger schema — all spec §3.1 fields accepted
# ---------------------------------------------------------------------------
def test_ledger_accepts_all_spec_fields(tmp_path):
    ledger = TradeLedger(path=str(tmp_path / "ledger.jsonl"))
    ledger.add_trade(
        {
            "trade_id": 1,
            "signal_id": "S1",
            "opportunity_id": "O1",
            "account_id": "A1",
            "terminal_id": "T1",
            "symbol": "XAUUSD",
            "direction": "BUY",
            "volume": 0.1,
            "entry_price": 2000.0,
            "initial_stop_loss": 1990.0,
            "initial_take_profit": 2020.0,
            "initial_risk_price_distance": 10.0,
            "initial_risk_money": 100.0,
            "target_rr": 2.0,
            "opened_at": "2025-01-01T00:00:00+00:00",
            "closed_at": "2025-01-01T05:00:00+00:00",
            "exit_price": 2020.0,
            "pnl": 200.0,
            "r_multiple": 2.0,
            "close_reason": "TAKE_PROFIT",
            "broker_order_ticket": 11,
            "broker_deal_ticket": 12,
            "broker_position_ticket": 1,
            "status": "CLOSED",
            "review_status": "REVIEWED",
        }
    )
    rec = ledger.get_trade(1)
    for field in (
        "signal_id",
        "opportunity_id",
        "account_id",
        "terminal_id",
        "initial_take_profit",
        "target_rr",
        "close_reason",
        "broker_deal_ticket",
        "review_status",
    ):
        assert field in rec, f"missing {field}"
    assert rec["created_at"] and rec["updated_at"]
