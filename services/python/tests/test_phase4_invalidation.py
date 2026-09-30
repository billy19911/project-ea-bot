# -*- coding: utf-8 -*-
"""Phase 4 — invalidation & expiry edge tests (§27–§29, TEST 5–7/14/17)."""

from __future__ import annotations

import pytest

from src.trading.entry_lifecycle import EntryLifecycleManager
from src.trading.entry_zones import MITIGATION_INVALIDATED, Zone, evaluate_invalidation


def _z(direction="LONG", inv=None) -> Zone:
    inv_price = inv if inv is not None else (10.2 if direction == "LONG" else 10.5)
    return Zone(
        zone_id="z1",
        symbol="XAUUSD",
        direction=direction,
        zone_type="ORDER_BLOCK",
        timeframe="M15",
        top=10.5,
        bottom=10.2,
        invalidation_price=inv_price,
        invalidation_rule="close beyond boundary",
    )


def test_long_invalidation_close_below():
    z = _z("LONG")
    inv, reason = evaluate_invalidation(z, close_price=10.19)
    assert inv is True and z.direction == "LONG"


def test_short_invalidation_close_above():
    z = _z("SHORT")
    inv, reason = evaluate_invalidation(z, close_price=10.51)
    assert inv is True


def test_no_close_price_is_not_invalidated():
    z = _z("LONG")
    inv, reason = evaluate_invalidation(z, close_price=0.0)
    assert inv is False
    assert "no close" in reason


def test_mark_invalidated_records_reason():
    z = _z("LONG")
    z.mark_invalidated("structure broke")
    assert z.mitigation == MITIGATION_INVALIDATED
    assert z.metadata.get("invalidation_reason") == "structure broke"
    assert z.is_live() is False


# TEST 7 — stale trigger window.
def test_stale_trigger_not_fresh():
    from src.trading.trigger_engine import evaluate_triggers

    r = evaluate_triggers(
        direction="LONG",
        zone_top=10.3,
        zone_bottom=10.2,
        opens=[10.4, 10.45, 10.5],
        highs=[10.5, 10.55, 10.7],
        lows=[10.3, 10.35, 10.15],
        closes=[10.42, 10.5, 10.6],
        atr=0.2,
        is_closed=True,
        candle_ts=1000.0,
        now_ts=1000.0,
    )
    assert r.is_fresh(60.0, now_ts=1061.0) is False


# TEST 17 / INVARIANT E — unknown data → not ready.
def test_unknown_data_not_entry_ready():
    from src.agents.roles import EntryRole

    out = EntryRole().analyze({"setup": {"direction": "BUY", "missing_conditions": []}})
    # No trigger_result and no trigger_confirmed → WAIT, never ENTRY_READY.
    assert out.signal == "WAIT_TRIGGER"


def test_lifecycle_unknown_setup():
    mgr = EntryLifecycleManager()
    status, reason = mgr.evaluate_lifecycle("does-not-exist")
    assert status == "UNKNOWN"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
