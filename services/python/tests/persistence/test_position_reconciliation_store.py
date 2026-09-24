# -*- coding: utf-8 -*-
"""Tests for the durable position reconciliation store (B-5)."""

from __future__ import annotations

from persistence import PositionReconciliationStore


def test_position_reconciliation_restart(tmp_path):
    path = tmp_path / "pos.jsonl"
    store = PositionReconciliationStore(str(path))
    store.save_snapshot(
        last_sl={123: 1.1000},
        last_tp={123: 1.1050},
        last_volume={123: 0.1},
    )

    # restart
    store2 = PositionReconciliationStore(str(path))
    sl, tp, vol = store2.load_snapshot()
    assert sl[123] == 1.1000
    assert tp[123] == 1.1050
    assert vol[123] == 0.1


def test_position_reconciliation_fail_safe_corrupt_line(tmp_path):
    path = tmp_path / "pos.jsonl"
    path.write_text(
        '{"last_sl":{"1":1.1},"last_tp":{},"last_volume":{}}\n'
        "{oops\n"
        '{"last_sl":{"2":2.2},"last_tp":{},"last_volume":{}}\n'
    )
    store = PositionReconciliationStore(str(path))
    sl, _, _ = store.load_snapshot()
    assert sl == {2: 2.2}  # last valid line wins, corrupt skipped


def test_position_reconciliation_no_snapshot(tmp_path):
    store = PositionReconciliationStore(str(tmp_path / "empty.jsonl"))
    assert store.load_snapshot() is None


def test_position_reconciliation_backward_compat_monitor():
    # A PositionMonitor without a store keeps working (no breaking change).
    from monitoring.position_monitor import PositionMonitor

    monitor = PositionMonitor()
    assert monitor.reconciliation_store is None
    assert monitor.detect_position_changes() == []


def test_position_reconciliation_monitor_restores(tmp_path):
    from monitoring.position_monitor import PositionMonitor

    path = tmp_path / "pos.jsonl"
    seed = PositionReconciliationStore(str(path))
    seed.save_snapshot(last_sl={7: 1.2345}, last_tp={7: 1.2450}, last_volume={7: 0.5})

    monitor = PositionMonitor(reconciliation_store=PositionReconciliationStore(str(path)))
    assert monitor._last_sl == {7: 1.2345}
    assert monitor._last_tp == {7: 1.2450}
    assert monitor._last_volume == {7: 0.5}
