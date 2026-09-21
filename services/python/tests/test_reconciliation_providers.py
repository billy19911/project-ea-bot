# -*- coding: utf-8 -*-
"""Tests for MT5-backed reconciliation providers (audit P0-3 follow-up)."""

from __future__ import annotations

from execution.reconciliation_providers import (
    MT5ReconciliationProviders,
    internal_positions_from_store,
)


class _FakeConnector:
    def __init__(self, positions=None, orders=None, explode=False):
        self._positions = positions or []
        self._orders = orders or []
        self._explode = explode

    def get_positions(self):
        if self._explode:
            raise RuntimeError("broker down")
        return self._positions

    def get_orders(self):
        if self._explode:
            raise RuntimeError("broker down")
        return self._orders


def test_internal_positions_from_store_only_confirmed_with_ticket() -> None:
    store = {
        "a": {"state": "position_confirmed", "ticket": 11, "symbol": "EURUSD", "volume": 0.1},
        "b": {"state": "filled", "ticket": 12, "symbol": "EURUSD", "volume": 0.2},
        "c": {"state": "submitting"},  # not confirmed
        "d": {"state": "position_confirmed"},  # no ticket
        "e": {"state": "closed", "ticket": 13},  # not a live position
    }
    positions = internal_positions_from_store(store)
    tickets = {p["ticket"] for p in positions}
    assert tickets == {11, 12}


def test_broker_side_reads_connector() -> None:
    conn = _FakeConnector(positions=[{"ticket": 1, "symbol": "EURUSD", "volume": 0.1}])
    providers = MT5ReconciliationProviders(connector=conn)
    assert providers.broker_positions() == [{"ticket": 1, "symbol": "EURUSD", "volume": 0.1}]


def test_broker_side_fail_safe_on_error() -> None:
    conn = _FakeConnector(explode=True)
    providers = MT5ReconciliationProviders(connector=conn)
    assert providers.broker_positions() == []
    assert providers.broker_orders() == []


def test_providers_report_no_internal_orders() -> None:
    providers = MT5ReconciliationProviders(connector=_FakeConnector())
    assert providers.internal_orders() == []


def test_mismatch_is_detected_via_real_runner() -> None:
    """A broker position with no internal counterpart → critical mismatch."""
    from execution.reconciliation_runner import ReconciliationGuard, ReconciliationRunner

    conn = _FakeConnector(positions=[{"ticket": 999, "symbol": "EURUSD", "volume": 0.1}])
    providers = MT5ReconciliationProviders(connector=conn, internal_store={})
    runner = ReconciliationRunner(interval=1, providers=providers)
    runner.run_once()

    report = runner.last_report()
    assert report is not None
    assert report.has_critical() is True
    assert ReconciliationGuard(runner).check_can_execute()[0] is False


def test_default_providers_noop_when_not_live() -> None:
    from execution.reconciliation_runner import ReconciliationProviders
    from orchestration.runtime import OrchestrationRuntime

    runtime = OrchestrationRuntime(reconciliation_interval=1)
    # Test env is not live → no-op providers → no false-positive mismatch.
    assert isinstance(runtime.reconciliation.providers, ReconciliationProviders)


if __name__ == "__main__":  # pragma: no cover
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
