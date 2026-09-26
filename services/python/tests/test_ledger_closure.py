# -*- coding: utf-8 -*-
"""LEDGER-SLTP T1 — ledger closure lifecycle tests.

The append-only order-state ledger never recorded a ``closed`` state, so every
historical ``position_confirmed`` record counted as an open internal position
forever. Reconciliation reported them as ``missing_in_broker`` (critical) and
the execution gate fail-closed, blocking all new orders.

These tests prove:

* a **verified** position disappearance appends a ``closed`` record (file +
  memory) and the reconciliation provider stops counting the ticket;
* a **failed** broker read (``ok=False``) writes nothing and emits no
  disappearance events (false-close guard);
* double-close is idempotent (exactly one ``closed`` record);
* transition validation rejects invalid sources and allows ``FILLED → CLOSED``;
* the monitor closure hook path uses ``get_positions_ex`` and skips on
  ``ok=False``.

All ledgers use ``tmp_path`` — the real ``logs/order_state.jsonl`` is never
touched.
"""

from __future__ import annotations

import json

from monitoring.position_monitor import EventType, PositionMonitor
from persistence import OrderStateStore

# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


class _VerifiedConnector:
    """Connector exposing the verified ``get_positions_ex()`` seam."""

    def __init__(self, positions=None, ok=True):
        self.positions = list(positions or [])
        self.ok = ok
        self.ex_calls = 0

    def get_positions_ex(self):
        self.ex_calls += 1
        return self.ok, list(self.positions)

    def get_positions(self):
        # Should NOT be used by the verified path.
        raise AssertionError(
            "get_positions() must not be called when get_positions_ex exists"
        )

    def get_tick(self, symbol):
        return None

    def get_ohlc(self, symbol, timeframe, count):
        return []


def _pos(ticket=1, symbol="EURUSD", sl=1.0, tp=2.0, volume=0.1):
    return {
        "ticket": ticket,
        "symbol": symbol,
        "side": "BUY",
        "volume": volume,
        "price_open": 1.5,
        "price_current": 1.5,
        "profit": 0.0,
        "sl": sl,
        "tp": tp,
    }


def _read_lines(path):
    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


# ---------------------------------------------------------------------------
# OrderStateStore.mark_closed
# ---------------------------------------------------------------------------


def test_mark_closed_appends_and_updates_memory(tmp_path):
    path = tmp_path / "order.jsonl"
    store = OrderStateStore(str(path))
    store.set_order("i1", "position_confirmed", {"ticket": 1001, "symbol": "EURUSD"})

    assert store.mark_closed(1001, reason="broker_position_disappeared") is True

    # File: a `closed` record was appended with the right shape.
    records = _read_lines(path)
    closed = [r for r in records if r.get("state") == "closed"]
    assert len(closed) == 1
    assert closed[0]["intent_id"] == "i1"  # latest record's intent_id
    assert closed[0]["ticket"] == 1001
    assert closed[0]["reason"] == "broker_position_disappeared"
    assert "timestamp" in closed[0]

    # Memory: the record for the intent is now `closed`.
    assert store.get_order("i1")["state"] == "closed"

    # Restart survives.
    assert OrderStateStore(str(path)).get_order("i1")["state"] == "closed"


def test_mark_closed_unknown_ticket_is_noop(tmp_path):
    path = tmp_path / "order.jsonl"
    store = OrderStateStore(str(path))
    store.set_order("i1", "position_confirmed", {"ticket": 1001})
    assert store.mark_closed(999999) is False
    assert len(_read_lines(path)) == 1  # only the confirm record


def test_mark_closed_double_close_idempotent(tmp_path):
    path = tmp_path / "order.jsonl"
    store = OrderStateStore(str(path))
    store.set_order("i1", "position_confirmed", {"ticket": 1001})

    assert store.mark_closed(1001) is True
    assert store.mark_closed(1001) is False  # already closed → no-op
    assert store.mark_closed(1001) is False

    records = _read_lines(path)
    assert len([r for r in records if r.get("state") == "closed"]) == 1


def test_mark_closed_allows_filled_source(tmp_path):
    path = tmp_path / "order.jsonl"
    store = OrderStateStore(str(path))
    store.set_order("i1", "filled", {"ticket": 1001})
    assert store.mark_closed(1001) is True
    assert store.get_order("i1")["state"] == "closed"


def test_mark_closed_rejects_invalid_source(tmp_path):
    path = tmp_path / "order.jsonl"
    store = OrderStateStore(str(path))
    # `risk_approved` cannot legally transition to `closed`.
    store.set_order("i1", "risk_approved", {"ticket": 1001})
    assert store.mark_closed(1001) is False
    assert store.get_order("i1")["state"] == "risk_approved"

    # Unknown source string is also rejected.
    store.set_order("i2", "not_a_state", {"ticket": 1002})
    assert store.mark_closed(1002) is False


def test_transition_table_allows_filled_to_closed():
    from execution.state_machine import OrderState, next_allowed

    assert OrderState.CLOSED in next_allowed(OrderState.FILLED)
    assert OrderState.CLOSED in next_allowed(OrderState.POSITION_CONFIRMED)
    # A terminal CLOSED has no further transitions.
    assert next_allowed(OrderState.CLOSED) == ()


# ---------------------------------------------------------------------------
# Reconciliation provider supersedes open states with `closed`
# ---------------------------------------------------------------------------


def test_provider_drops_closed_ticket(tmp_path):
    from execution.reconciliation_providers import internal_positions_from_store

    path = tmp_path / "order.jsonl"
    store = OrderStateStore(str(path))
    store.set_order(
        "i1", "position_confirmed", {"ticket": 1001, "symbol": "EURUSD", "volume": 0.1}
    )
    store.set_order(
        "i2", "position_confirmed", {"ticket": 1002, "symbol": "XAUUSD", "volume": 0.5}
    )

    # Before close: both counted.
    before = internal_positions_from_store(store.all_orders())
    assert {p["ticket"] for p in before} == {1001, 1002}

    store.mark_closed(1001)

    after = internal_positions_from_store(store.all_orders())
    assert {p["ticket"] for p in after} == {1002}


def test_provider_uses_latest_state_per_ticket():
    from execution.reconciliation_providers import internal_positions_from_store

    # Two intents mapping to the same ticket; the later `closed` must win.
    store = {
        "a": {"state": "position_confirmed", "ticket": 55, "symbol": "EURUSD"},
        "b": {"state": "closed", "ticket": 55, "symbol": "EURUSD"},
    }
    assert internal_positions_from_store(store) == []


# ---------------------------------------------------------------------------
# get_positions_ex connector seam
# ---------------------------------------------------------------------------


def test_connector_get_positions_ex_simulation_verified(monkeypatch):
    from mt5 import connector

    monkeypatch.setattr(connector, "_live_mode", False)
    ok, positions = connector.get_positions_ex()
    assert ok is True
    assert isinstance(positions, list)
    assert len(positions) >= 1  # simulated placeholders


def test_connector_get_positions_ex_live_read_failure(monkeypatch):
    """positions_get() returning None must signal unverified (False, [])."""
    import sys
    import types

    from mt5 import connector

    fake_mt5 = types.ModuleType("MetaTrader5")
    fake_mt5.positions_get = lambda: None  # read failure
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake_mt5)
    monkeypatch.setattr(connector, "_live_mode", True)

    ok, positions = connector.get_positions_ex()
    assert ok is False
    assert positions == []


# ---------------------------------------------------------------------------
# PositionMonitor closure hook + false-close guard
# ---------------------------------------------------------------------------


def test_monitor_verified_disappearance_closes_ledger(tmp_path):
    path = tmp_path / "order.jsonl"
    store = OrderStateStore(str(path))
    store.set_order("i1", "position_confirmed", {"ticket": 1, "symbol": "EURUSD"})

    conn = _VerifiedConnector(positions=[_pos(ticket=1)])
    monitor = PositionMonitor(mt5_connector=conn, order_state_store=store)

    # First cycle: position present, nothing disappears.
    assert monitor.detect_position_changes() == []
    assert store.get_order("i1")["state"] == "position_confirmed"

    # Second cycle: position genuinely gone (verified read of empty book).
    conn.positions = []
    events = monitor.detect_position_changes()
    assert any(e.event_type is EventType.POSITION_DISAPPEARED for e in events)
    assert conn.ex_calls == 2  # monitor used get_positions_ex, not get_positions

    # Ledger closed (file + memory) and provider stops counting it.
    assert store.get_order("i1")["state"] == "closed"
    closed = [r for r in _read_lines(path) if r.get("state") == "closed"]
    assert len(closed) == 1
    assert closed[0]["reason"] == "broker_position_disappeared"

    from execution.reconciliation_providers import internal_positions_from_store

    assert internal_positions_from_store(store.all_orders()) == []


def test_monitor_read_failure_skips_diff_and_closure(tmp_path):
    path = tmp_path / "order.jsonl"
    store = OrderStateStore(str(path))
    store.set_order("i1", "position_confirmed", {"ticket": 1, "symbol": "EURUSD"})

    conn = _VerifiedConnector(positions=[_pos(ticket=1)])
    monitor = PositionMonitor(mt5_connector=conn, order_state_store=store)
    monitor.detect_position_changes()  # establish tracked state (ticket 1 seen)

    # Now the read FAILS: ok=False, empty list — must NOT be treated as a close.
    conn.ok = False
    conn.positions = []
    events = monitor.detect_position_changes()

    assert events == []  # no disappearance events
    assert store.get_order("i1")["state"] == "position_confirmed"  # no ledger write
    assert store.mark_closed(1) is True  # ticket still open → close is still possible

    # Only the confirm record + the manual close above; the failed cycle wrote none.
    assert len([r for r in _read_lines(path) if r.get("state") == "closed"]) == 1


def test_monitor_disappearance_without_ledger_record_is_safe(tmp_path):
    """A disappeared ticket with no ledger record must not raise or write."""
    path = tmp_path / "order.jsonl"
    store = OrderStateStore(str(path))

    conn = _VerifiedConnector(positions=[_pos(ticket=42)])
    monitor = PositionMonitor(mt5_connector=conn, order_state_store=store)
    monitor.detect_position_changes()
    conn.positions = []
    events = monitor.detect_position_changes()

    assert any(e.event_type is EventType.POSITION_DISAPPEARED for e in events)
    # No record existed for ticket 42 → store unchanged (no file was written).
    assert not path.exists() or _read_lines(path) == []


def test_monitor_without_store_still_detects(tmp_path):
    """Backward compatibility: no order_state_store → detection unchanged."""
    conn = _VerifiedConnector(positions=[_pos(ticket=7)])
    monitor = PositionMonitor(mt5_connector=conn)
    monitor.detect_position_changes()
    conn.positions = []
    events = monitor.detect_position_changes()
    assert any(e.event_type is EventType.POSITION_DISAPPEARED for e in events)
