# -*- coding: utf-8 -*-
"""Tests for the durable order state ledger store (B-5)."""

from __future__ import annotations

from persistence import OrderStateStore


def test_order_state_restart_survival(tmp_path):
    path = tmp_path / "order.jsonl"
    store = OrderStateStore(str(path))
    store.set_order("intent_1", "risk_approved", {"ts": "2026-09-24"})
    assert store.get_order("intent_1")["state"] == "risk_approved"

    # restart
    store2 = OrderStateStore(str(path))
    assert store2.get_order("intent_1")["state"] == "risk_approved"
    assert store2.get_order("intent_1")["ts"] == "2026-09-24"


def test_order_state_fail_safe_corrupt_line(tmp_path):
    path = tmp_path / "order.jsonl"
    path.write_text('{"intent_id":"i1","state":"ok"}\n{corrupt}\n{"intent_id":"i2","state":"ok"}\n')
    store = OrderStateStore(str(path))
    assert len(store.all_orders()) == 2  # corrupt line skipped


def test_order_state_unwritable_degrades_cache_only(tmp_path):
    # A path whose parent is a file cannot be created → write degrades to cache.
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    store = OrderStateStore(str(blocker / "sub" / "order.jsonl"))
    store.set_order("i1", "submitted")
    assert store.get_order("i1")["state"] == "submitted"


def test_order_state_backward_compat_no_store():
    from execution import state_machine

    state_machine.set_store(None)
    state_machine.reset_store()
    state_machine.set_order("test", "created")
    assert state_machine.get_order("test")["state"] == "created"
    # detach to avoid leaking into other tests
    state_machine.set_store(None)
    state_machine.reset_store()


def test_order_state_integration_populates_ledger(tmp_path):
    from execution import state_machine

    path = tmp_path / "order.jsonl"
    store = OrderStateStore(str(path))
    state_machine.reset_store()
    state_machine.set_store(store)
    state_machine.set_order("intent_x", state_machine.OrderState.RISK_APPROVED)

    # Simulate restart: fresh module state, re-attach same store.
    state_machine.reset_store()
    state_machine.set_store(OrderStateStore(str(path)))
    assert state_machine.get_order("intent_x")["state"] == "risk_approved"

    state_machine.set_store(None)
    state_machine.reset_store()
