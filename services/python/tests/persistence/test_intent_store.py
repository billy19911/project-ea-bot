# -*- coding: utf-8 -*-
"""Tests for the durable intent registry store (B-5)."""

from __future__ import annotations

from execution.intents import IntentRecord
from execution.state_machine import OrderState
from persistence import IntentStore


def _record(intent_id: str = "intent_1") -> IntentRecord:
    return IntentRecord(
        intent_id=intent_id,
        decision_id="dec_1",
        strategy_version="v1",
        symbol="EURUSD",
        direction="BUY",
    )


def test_intent_restart_survival(tmp_path):
    path = tmp_path / "intents.jsonl"
    store = IntentStore(str(path))
    store.add_intent(_record())
    assert store.get_intent("intent_1")["symbol"] == "EURUSD"

    # restart
    store2 = IntentStore(str(path))
    assert store2.get_intent("intent_1")["symbol"] == "EURUSD"
    assert store2.get_intent("intent_1")["event"] == "created"


def test_intent_fail_safe_corrupt_line(tmp_path):
    path = tmp_path / "intents.jsonl"
    path.write_text(
        '{"intent_id":"i1","event":"created","symbol":"EURUSD"}\n'
        "{not json}\n"
        '{"intent_id":"i2","event":"created","symbol":"GBPUSD"}\n'
    )
    store = IntentStore(str(path))
    assert len(store.all_intents()) == 2


def test_intent_update_state_persists(tmp_path):
    path = tmp_path / "intents.jsonl"
    store = IntentStore(str(path))
    store.add_intent(_record())
    store.update_intent_state("intent_1", "submitted", {"ticket": 123})

    store2 = IntentStore(str(path))
    assert store2.get_intent("intent_1")["state"] == "submitted"
    assert store2.get_intent("intent_1")["ticket"] == 123


def test_intent_backward_compat_no_store():
    from execution import intents

    intents.set_store(None)
    intents.reset_intents()
    intents.register_intent(_record("bc_1"))
    assert intents.get_intent("bc_1").symbol == "EURUSD"
    intents.set_store(None)
    intents.reset_intents()


def test_intent_integration_rebuilds_registry(tmp_path):
    from execution import intents

    path = tmp_path / "intents.jsonl"
    store = IntentStore(str(path))
    intents.reset_intents()
    intents.set_store(store)
    intents.register_intent(_record("intent_y"))
    intents.update_intent_state("intent_y", OrderState.RISK_APPROVED)

    # Simulate restart: fresh registry, re-attach store.
    intents.reset_intents()
    intents.set_store(IntentStore(str(path)))
    assert intents.get_intent("intent_y").state == OrderState.RISK_APPROVED

    intents.set_store(None)
    intents.reset_intents()
