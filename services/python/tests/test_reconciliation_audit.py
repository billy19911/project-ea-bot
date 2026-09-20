# -*- coding: utf-8 -*-
"""Tests for Phase 35 — reconciliation 2.0 runner + audit."""

from src.audit import get_shared_audit_log
from src.execution.reconciliation_runner import ReconciliationRunner


class _Providers:
    """Internal believes one position is open; broker reports none."""

    def internal_positions(self):
        return [{"ticket": 1, "symbol": "XAUUSD", "volume": 0.1}]

    def broker_positions(self):
        return []

    def internal_orders(self):
        return []

    def broker_orders(self):
        return []


def test_reconciliation_records_audit_on_run() -> None:
    audit = get_shared_audit_log()
    before = len(audit)
    runner = ReconciliationRunner(interval=1, providers=_Providers())
    report = runner.run_once()
    assert report is not None
    # missing_in_broker → critical
    assert report.has_critical()
    assert len(audit) > before
    last = audit.entries()[-1]
    assert last["actor"] == "reconciliation"
    assert last["action"] == "run"


def test_reconciliation_tick_interval() -> None:
    runner = ReconciliationRunner(interval=3, providers=_Providers())
    assert runner.tick() is None
    assert runner.tick() is None
    rep = runner.tick()
    assert rep is not None
