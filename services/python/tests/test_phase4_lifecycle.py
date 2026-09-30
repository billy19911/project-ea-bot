# -*- coding: utf-8 -*-
"""Phase 4 — lifecycle tests (§26–§29, TEST 5–7/14–16): invalidation, expiry,
retest, touch states, duplicate/concurrent entry protection."""

from __future__ import annotations

import threading

import pytest

from src.trading.entry_lifecycle import EntryLifecycleManager
from src.trading.entry_zones import (
    MITIGATION_FULL,
    MITIGATION_TOUCHED,
    Zone,
    detect_zone_touch,
    evaluate_invalidation,
    is_zone_expired,
)


def _zone(**over) -> Zone:
    base = dict(
        zone_id="XAUUSD-M15-LONG-ORDER_BLOCK-abc12345",
        symbol="XAUUSD",
        direction="LONG",
        zone_type="ORDER_BLOCK",
        timeframe="M15",
        top=10.5,
        bottom=10.2,
        invalidation_price=10.2,
        invalidation_rule="close below OB low",
    )
    base.update(over)
    return Zone(**base)


# TEST 5 / INVARIANT C — invalidated setup never becomes ENTRY_READY.
def test_invalidation_transitions_to_invalid():
    mgr = EntryLifecycleManager()
    mgr.register("s1", "XAUUSD", "LONG", zone=_zone())
    status, reason = mgr.evaluate_lifecycle("s1", close_price=10.0)
    assert status == "INVALID"
    assert "invalid" in reason.lower()
    # Terminal: stays invalid, never resurrects as entry.
    status2, _ = mgr.evaluate_lifecycle("s1", close_price=10.4)
    assert status2 == "INVALID"


def test_wick_beyond_zone_is_not_invalidation():
    z = _zone()
    # Close still inside boundary → live, even if a wick dipped below.
    inv, _ = evaluate_invalidation(z, close_price=10.25)
    assert inv is False


# TEST 6 / INVARIANT B — expired setup never becomes ENTRY_READY.
def test_expired_setup_never_resurrects():
    mgr = EntryLifecycleManager()
    mgr.register("s2", "XAUUSD", "LONG", zone=_zone(), expires_ts=1000.0)
    status, _ = mgr.evaluate_lifecycle("s2", close_price=10.4, now_ts=2000.0)
    assert status == "EXPIRED"
    status2, _ = mgr.evaluate_lifecycle("s2", close_price=10.4, now_ts=1500.0)
    assert status2 == "EXPIRED"  # EXPIRED terminal — no resurrection


def test_zone_time_expiry():
    z = _zone(expires_at_ts=1000.0)
    assert is_zone_expired(z, now_ts=999.0) is False
    assert is_zone_expired(z, now_ts=1001.0) is True


# §28 mitigation lifecycle.
def test_mitigation_states_advance():
    z = _zone()
    assert z.mitigation == "FRESH"
    z.record_touch()
    assert z.mitigation == MITIGATION_TOUCHED
    z.record_touch()
    assert z.mitigation == "PARTIALLY_MITIGATED"
    z.mark_fully_mitigated()
    assert z.mitigation == MITIGATION_FULL
    assert z.is_live() is False


# §29 retest tracking.
def test_touch_tracking():
    z = _zone()
    assert z.touch_count == 0
    z.record_touch(ts=100.0)
    z.record_touch(ts=200.0)
    assert z.touch_count == 2
    assert z.first_touch_ts == 100.0
    assert z.last_touch_ts == 200.0


# TEST 1 / INVARIANT A — zone touch detection, bid semantics.
def test_zone_touch_uses_executable_bid_for_long():
    z = _zone()
    t = detect_zone_touch(z, bid=10.3)
    assert t.touched is True
    assert t.price_kind == "bid"
    # Ask above the zone does NOT count for a LONG.
    t2 = detect_zone_touch(z, ask=11.0)
    assert t2.touched is False


def test_zone_touch_short_uses_ask():
    z = _zone(direction="SHORT")
    t = detect_zone_touch(z, ask=10.3)
    assert t.touched is True
    assert t.price_kind == "ask"


def test_zone_touch_candle_range_counts():
    z = _zone()
    t = detect_zone_touch(z, candle_high=10.4, candle_low=10.1)
    assert t.touched is True
    assert t.price_kind == "candle_range"


def test_zone_touch_no_data_no_touch():
    z = _zone()
    assert detect_zone_touch(z).touched is False


# TEST 15/16 + INVARIANT G — idempotent + concurrency-safe entry claims.
def test_duplicate_event_claims_once():
    mgr = EntryLifecycleManager()
    mgr.register("s3", "XAUUSD", "LONG", zone=_zone())
    assert mgr.claim_entry("s3", trigger_id="micro_bos", candle_ts=1000.0) is True
    assert mgr.claim_entry("s3", trigger_id="micro_bos", candle_ts=1000.0) is False
    # Different candle → new claim allowed.
    assert mgr.claim_entry("s3", trigger_id="micro_bos", candle_ts=1001.0) is True


def test_concurrent_claims_fire_once():
    mgr = EntryLifecycleManager()
    mgr.register("s4", "XAUUSD", "LONG", zone=_zone())
    wins: list[bool] = []
    barrier = threading.Barrier(4)

    def worker():
        barrier.wait()
        wins.append(mgr.claim_entry("s4", trigger_id="t", candle_ts=500.0))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert wins.count(True) == 1
    assert wins.count(False) == 3


def test_setup_id_stable_across_register():
    mgr = EntryLifecycleManager()
    a = mgr.register("stable-1", "XAUUSD", "LONG", zone=_zone())
    b = mgr.register("stable-1", "XAUUSD", "LONG", zone=_zone())
    assert a is b  # same identity, not a new setup per tick


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
