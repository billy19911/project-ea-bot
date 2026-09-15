# -*- coding: utf-8 -*-
"""Tests for PRD §18.1 review auto-trigger on position close."""

from __future__ import annotations

from typing import Any

from review.auto_trigger import (
    ReviewAutoTrigger,
    ReviewRecord,
    get_auto_trigger,
    on_position_closed,
    set_auto_trigger,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _closed_trade(trade_id: str = "T-1", pnl: float = 100.0) -> dict[str, Any]:
    return {
        "trade_id": trade_id,
        "symbol": "EURUSD",
        "direction": "BUY",
        "entry_price": 1.1000,
        "close_price": 1.1050,
        "pnl": pnl,
        "slippage": 0.0,
        "status": "CLOSED",
    }


# ---------------------------------------------------------------------------
# Core behaviour
# ---------------------------------------------------------------------------


def test_close_triggers_review_with_trade_ref():
    trigger = ReviewAutoTrigger()
    record = trigger.on_position_closed(_closed_trade("T-42"))

    assert isinstance(record, ReviewRecord)
    assert record.trade_id == "T-42"
    assert record.review.trade_id == "T-42"
    assert record.review.outcome == "WIN"
    assert record.root_cause.primary_cause  # non-empty classification
    assert trigger.stats()["reviewed"] == 1
    assert trigger.stats()["triggered"] == 1


def test_open_position_does_not_trigger():
    trigger = ReviewAutoTrigger()
    open_trade = {
        "trade_id": "T-OPEN",
        "symbol": "EURUSD",
        "direction": "BUY",
        "entry_price": 1.1000,
        "status": "OPEN",
    }
    assert trigger.on_position_closed(open_trade) is None
    assert trigger.stats()["reviewed"] == 0
    assert trigger.stats()["skipped"] == 1


def test_missing_close_price_is_skipped():
    trigger = ReviewAutoTrigger()
    # No close price and no explicit status → treated as open.
    assert trigger.on_position_closed({"trade_id": "X", "entry_price": 1.1}) is None
    assert trigger.stats()["skipped"] == 1


def test_none_trade_result_is_skipped():
    trigger = ReviewAutoTrigger()
    assert trigger.on_position_closed(None) is None


# ---------------------------------------------------------------------------
# Fail-safe behaviour
# ---------------------------------------------------------------------------


class _ExplodingReviewer:
    def review_trade(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("boom")


def test_reviewer_failure_does_not_propagate():
    trigger = ReviewAutoTrigger(reviewer=_ExplodingReviewer())  # type: ignore[arg-type]
    # Must not raise.
    result = trigger.on_position_closed(_closed_trade())
    assert result is None
    assert trigger.stats()["failed"] == 1
    assert trigger.stats()["reviewed"] == 0


def test_module_hook_failure_does_not_propagate():
    # A completely broken trigger object should be swallowed by the module hook.
    class _Broken:
        def on_position_closed(self, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("broken trigger")

    assert on_position_closed(_closed_trade(), trigger=_Broken()) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# History + callback
# ---------------------------------------------------------------------------


def test_review_history_is_bounded():
    trigger = ReviewAutoTrigger(max_history=3)
    for i in range(5):
        trigger.on_position_closed(_closed_trade(f"T-{i}"))
    recent = trigger.recent(limit=10)
    assert len(recent) == 3
    assert recent[0].trade_id == "T-4"  # newest first


def test_on_review_callback_invoked():
    seen: list[ReviewRecord] = []
    trigger = ReviewAutoTrigger(on_review=seen.append)
    trigger.on_position_closed(_closed_trade("T-CB"))
    assert len(seen) == 1
    assert seen[0].trade_id == "T-CB"


def test_on_review_callback_failure_is_swallowed():
    def _bad(_record: ReviewRecord) -> None:
        raise RuntimeError("callback boom")

    trigger = ReviewAutoTrigger(on_review=_bad)
    record = trigger.on_position_closed(_closed_trade("T-CB2"))
    assert record is not None  # review still produced


# ---------------------------------------------------------------------------
# Default trigger management
# ---------------------------------------------------------------------------


def test_default_trigger_singleton():
    set_auto_trigger(None)
    t1 = get_auto_trigger()
    t2 = get_auto_trigger()
    assert t1 is t2
    # Restore
    set_auto_trigger(None)
