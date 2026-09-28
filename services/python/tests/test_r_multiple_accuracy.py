# -*- coding: utf-8 -*-
"""Tests for the R-multiple accuracy + persistence fixes.

Covers:
1. ``mt5.connector.get_position_close_deal`` — real close price from deal
   history (read-only; ``None`` in simulation).
2. ``review.close_detector`` — prefers the real closing deal over the last-seen
   snapshot, and flags the close-price provenance.
3. ``persistence.EntryContextStore`` — survives a restart (reload from disk),
   bounded cache, corrupt-line skip.
4. ``review.entry_context`` — reads back through the store after an in-memory
   miss (simulating a restart), while staying fail-safe.
5. ``review.auto_trigger._to_review_record`` — never fabricates a direction
   (unknown → no R), and carries the real ``closed_at``.
"""

from __future__ import annotations

import json

import pytest

from persistence.entry_context_store import EntryContextStore
from review import entry_context as ec
from review.auto_trigger import _to_review_record
from review.close_detector import PositionCloseDetector


# ---------------------------------------------------------------------------
# 1. Connector — get_position_close_deal (simulation → None)
# ---------------------------------------------------------------------------
def test_close_deal_none_in_simulation():
    from mt5 import connector

    # Simulation mode is the default in tests (no live MT5) → honest None.
    assert connector.get_position_close_deal(12345) is None
    assert connector.get_position_close_deal(None) is None


# ---------------------------------------------------------------------------
# 2. Close detector — prefers real deal, flags provenance
# ---------------------------------------------------------------------------
def test_close_detector_uses_real_deal_price_when_available():
    captured: list[dict] = []

    def resolver(ticket):
        return {"price": 2050.0, "time": 1700000000, "profit": 50.0, "side": "SELL"}

    det = PositionCloseDetector(on_close=captured.append, close_deal_resolver=resolver)
    det.observe(
        [
            {
                "ticket": 1,
                "symbol": "XAUUSD",
                "side": "BUY",
                "price_open": 2000.0,
                "price_current": 2010.0,  # stale snapshot — must NOT be used
                "profit": 10.0,
            }
        ]
    )
    det.observe([])  # ticket disappeared → close

    assert captured, "a close record must be emitted"
    rec = captured[0]
    assert rec["close_price"] == 2050.0
    assert rec["close_price_source"] == "deal_history"
    assert rec["pnl"] == 50.0
    # Real close time becomes an ISO string.
    assert isinstance(rec["closed_at"], str) and rec["closed_at"].startswith("2023-")


def test_close_detector_falls_back_to_last_seen_when_no_deal():
    captured: list[dict] = []

    def resolver(ticket):
        return None  # no deal available

    det = PositionCloseDetector(on_close=captured.append, close_deal_resolver=resolver)
    det.observe(
        [
            {
                "ticket": 7,
                "symbol": "EURUSD",
                "side": "SELL",
                "price_open": 1.1000,
                "price_current": 1.0950,
                "profit": 5.0,
            }
        ]
    )
    det.observe([])

    rec = captured[0]
    assert rec["close_price"] == 1.0950  # best-effort snapshot
    assert rec["close_price_source"] == "last_seen"


def test_close_detector_resolver_never_raises():
    captured: list[dict] = []

    def boom(ticket):
        raise RuntimeError("mt5 down")

    det = PositionCloseDetector(on_close=captured.append, close_deal_resolver=boom)
    det.observe([{"ticket": 3, "side": "BUY", "price_open": 100.0, "price_current": 101.0}])
    det.observe([])
    assert captured[0]["close_price_source"] == "last_seen"


# ---------------------------------------------------------------------------
# 3. EntryContextStore — persistence, bounded, corrupt-safe
# ---------------------------------------------------------------------------
def test_store_survives_reload(tmp_path):
    path = str(tmp_path / "ec.jsonl")
    store = EntryContextStore(path=path)
    store.remember(
        42,
        {
            "symbol": "XAUUSD",
            "direction": "BUY",
            "entry_price": 2000.0,
            "stop_loss": 1990.0,
            "agent_outputs": {"big": "x" * 5000},
        },
    )

    # A fresh instance simulates a service restart.
    reloaded = EntryContextStore(path=path)
    ctx = reloaded.get(42)
    assert ctx["symbol"] == "XAUUSD"
    assert ctx["stop_loss"] == 1990.0
    # Bulky fields are NOT persisted (small on-disk record).
    assert "agent_outputs" not in ctx


def test_store_is_bounded(tmp_path):
    store = EntryContextStore(path=str(tmp_path / "ec.jsonl"), max_entries=10)
    for i in range(50):
        store.remember(i, {"symbol": "S"})
    assert store.size() == 10
    assert store.get(0) == {}  # oldest evicted
    assert store.get(49)["symbol"] == "S"


def test_store_skips_corrupt_lines(tmp_path):
    path = tmp_path / "ec.jsonl"
    path.write_text(
        json.dumps({"ticket": "1", "symbol": "A"}) + "\n" + "not json\n" + "{\n",
        encoding="utf-8",
    )
    store = EntryContextStore(path=str(path))
    assert store.get(1)["symbol"] == "A"  # good line kept


def test_store_pop_removes_from_cache(tmp_path):
    store = EntryContextStore(path=str(tmp_path / "ec.jsonl"))
    store.remember(5, {"symbol": "Z"})
    assert store.pop(5)["symbol"] == "Z"
    assert store.get(5) == {}


# ---------------------------------------------------------------------------
# 4. Registry — reads through the store after an in-memory miss
# ---------------------------------------------------------------------------
@pytest.fixture
def _isolate_registry(tmp_path):
    store = EntryContextStore(path=str(tmp_path / "ec.jsonl"))
    ec.set_entry_context_store(store)
    ec.clear_entry_contexts()
    yield store
    ec.set_entry_context_store(None, disabled=True)
    ec.clear_entry_contexts()


def test_registry_reads_through_store_after_restart(_isolate_registry):
    ec.remember_entry_context(
        99, {"symbol": "XAUUSD", "direction": "BUY", "entry_price": 2000.0, "stop_loss": 1990.0}
    )
    # Simulate a restart: drop the in-memory cache but keep the store wired.
    with ec._lock:
        ec._store.clear()
    ctx = ec.get_entry_context(99)
    assert ctx["stop_loss"] == 1990.0  # recovered from persistence


def test_registry_missing_is_empty(_isolate_registry):
    assert ec.get_entry_context("nope") == {}


# ---------------------------------------------------------------------------
# 5. Review record — no fabricated direction, real closed_at
# ---------------------------------------------------------------------------
def test_direction_not_fabricated_when_unknown():
    rec = _to_review_record(
        {"ticket": 1, "entry_price": 100.0, "close_price": 110.0, "stop_loss": 95.0}
    )
    # No side / order_type → direction stays empty (never guessed "BUY").
    assert rec["direction"] == ""


def test_direction_from_side():
    assert _to_review_record({"side": "SELL", "close_price": 1})["direction"] == "SELL"
    assert (
        _to_review_record({"order_type": "ORDER_TYPE_SELL", "close_price": 1})["direction"]
        == "SELL"
    )


def test_closed_at_and_source_carried():
    rec = _to_review_record(
        {
            "ticket": 1,
            "side": "BUY",
            "close_price": 1.0,
            "closed_at": "2025-01-02T03:04:05+00:00",
            "close_price_source": "deal_history",
        }
    )
    assert rec["closed_at"] == "2025-01-02T03:04:05+00:00"
    assert rec["close_price_source"] == "deal_history"
