# -*- coding: utf-8 -*-
"""Tests for the durable kill switch state store (B-5)."""

from __future__ import annotations

from persistence import KillSwitchStateStore
from risk.kill_switch import KillSwitch, KillSwitchState


def test_kill_switch_restart_survival(tmp_path):
    path = tmp_path / "ks.jsonl"
    store = KillSwitchStateStore(str(path))
    ks = KillSwitch()
    ks.trigger("test", "op")
    ks.lock()
    store.save_state(ks)

    # restart
    store2 = KillSwitchStateStore(str(path))
    loaded = store2.load_state()
    assert loaded["state"] == "locked"
    assert loaded["locked"] is True


def test_kill_switch_fail_safe_corrupt_line(tmp_path):
    path = tmp_path / "ks.jsonl"
    path.write_text(
        '{"state":"triggered","locked":false}\n' "{bad json\n" '{"state":"locked","locked":true}\n'
    )
    store = KillSwitchStateStore(str(path))
    assert store.load_state()["state"] == "locked"


def test_kill_switch_auto_persist_via_methods(tmp_path):
    from risk import kill_switch as ks_module

    path = tmp_path / "ks.jsonl"
    store = KillSwitchStateStore(str(path))
    ks_module.set_kill_switch_store(store)
    ks = KillSwitch()
    ks.trigger("auto", "system")
    ks.lock()
    assert store.load_state()["state"] == "locked"

    ks_module.set_kill_switch_store(None)


def test_kill_switch_load_factory_reconstructs(tmp_path):
    from risk import kill_switch as ks_module

    path = tmp_path / "ks.jsonl"
    store = KillSwitchStateStore(str(path))
    ks = KillSwitch()
    ks.trigger("factory", "system")
    ks.lock()
    store.save_state(ks)

    ks_module.set_kill_switch_store(KillSwitchStateStore(str(path)))
    restored = ks_module.load_kill_switch()
    assert restored.state == KillSwitchState.LOCKED
    assert restored.locked is True
    ks_module.set_kill_switch_store(None)


def test_kill_switch_backward_compat_no_store():
    # With no store attached, behaviour is unchanged and never crashes.
    from risk import kill_switch as ks_module

    ks_module.set_kill_switch_store(None)
    ks = KillSwitch()
    ks.trigger("no-store", "system")
    assert ks.state == KillSwitchState.TRIGGERED
    ks.lock()
    assert ks.locked is True
    restored = ks_module.load_kill_switch()
    assert restored.state == KillSwitchState.ACTIVE
