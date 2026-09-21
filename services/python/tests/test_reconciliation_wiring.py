# -*- coding: utf-8 -*-
"""Tests for periodic reconciliation wiring (PRD_V2 §14).

The :class:`~execution.reconciliation.Reconciler` must actually RUN periodically
during autonomous operation — not just exist. These tests drive the
:class:`~orchestration.runtime.OrchestrationRuntime` across pipeline cycles and
assert that:

* reconciliation runs every N cycles (configurable interval),
* the :class:`ReconciliationReport` is stored in a bounded history,
* ``last_reconciliation()`` and scheduler stats expose the real outcome, and
* a reconciliation error never crashes the cycle (fail-safe).

No MT5 connection is required: position/order providers default to no-ops.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from execution.reconciliation import ReconciliationReport
from src.orchestration.runtime import OrchestrationRuntime, set_runtime


class _CountingProviders:
    """Position/order providers that return canned (deterministic) state."""

    def __init__(
        self, internal_positions, broker_positions, internal_orders=None, broker_orders=None
    ):
        self._internal_positions = internal_positions
        self._broker_positions = broker_positions
        self._internal_orders = internal_orders or []
        self._broker_orders = broker_orders or []
        self.calls = 0

    def internal_positions(self):
        self.calls += 1
        return list(self._internal_positions)

    def broker_positions(self):
        return list(self._broker_positions)

    def internal_orders(self):
        return list(self._internal_orders)

    def broker_orders(self):
        return list(self._broker_orders)


# ---------------------------------------------------------------------------
# Runs every N cycles + bounded history
# ---------------------------------------------------------------------------
class TestPeriodicReconciliation:
    def test_runs_only_after_interval_cycles(self) -> None:
        providers = _CountingProviders([], [])
        runtime = OrchestrationRuntime(
            reconciliation_interval=3, reconciliation_providers=providers
        )
        for _ in range(2):
            runtime.run_cycle({"event_type": "BREAKOUT"})
        assert runtime.last_reconciliation() is None  # not yet
        runtime.run_cycle({"event_type": "BREAKOUT"})
        report = runtime.last_reconciliation()
        assert isinstance(report, ReconciliationReport)
        assert runtime.reconciliations_run() == 1

    def test_runs_each_interval_boundary(self) -> None:
        providers = _CountingProviders([], [])
        runtime = OrchestrationRuntime(
            reconciliation_interval=2, reconciliation_providers=providers
        )
        for _ in range(6):
            runtime.run_cycle({"event_type": "BREAKOUT"})
        assert runtime.reconciliations_run() == 3  # cycles 2, 4, 6

    def test_history_is_bounded(self) -> None:
        providers = _CountingProviders([], [])
        runtime = OrchestrationRuntime(
            reconciliation_interval=1,
            reconciliation_providers=providers,
            reconciliation_history_limit=3,
        )
        for _ in range(6):
            runtime.run_cycle({"event_type": "BREAKOUT"})
        assert len(runtime.reconciliation_history()) == 3

    def test_report_reflects_mismatches(self) -> None:
        internal = [
            {"ticket": 1, "symbol": "EURUSD", "volume": 0.1, "sl": 1.0, "tp": 2.0, "magic": 1}
        ]
        broker = [
            {"ticket": 1, "symbol": "EURUSD", "volume": 0.2, "sl": 1.0, "tp": 2.0, "magic": 1}
        ]
        providers = _CountingProviders(internal, broker)
        runtime = OrchestrationRuntime(
            reconciliation_interval=1, reconciliation_providers=providers
        )
        runtime.run_cycle({"event_type": "BREAKOUT"})
        report = runtime.last_reconciliation()
        assert report is not None
        assert report.has_critical() is True
        assert runtime.last_reconciliation_ok() is False

    def test_clean_reconciliation_is_ok(self) -> None:
        internal = [
            {"ticket": 5, "symbol": "EURUSD", "volume": 0.1, "sl": 1.0, "tp": 2.0, "magic": 1}
        ]
        providers = _CountingProviders(internal, internal)
        runtime = OrchestrationRuntime(
            reconciliation_interval=1, reconciliation_providers=providers
        )
        runtime.run_cycle({"event_type": "BREAKOUT"})
        assert runtime.last_reconciliation_ok() is True


# ---------------------------------------------------------------------------
# Fail-safe: errors never crash the cycle
# ---------------------------------------------------------------------------
class TestFailSafe:
    def test_provider_error_is_recorded_not_raised(self) -> None:
        class _Boom:
            def internal_positions(self):
                raise RuntimeError("broker down")

            def broker_positions(self):
                return []

            def internal_orders(self):
                return []

            def broker_orders(self):
                return []

        runtime = OrchestrationRuntime(reconciliation_interval=1, reconciliation_providers=_Boom())
        record = runtime.run_cycle({"event_type": "BREAKOUT"})
        # The cycle still returns a result — reconciliation never crashes it.
        assert isinstance(record, dict)
        assert runtime.reconciliations_run() == 1
        assert runtime.last_reconciliation() is None
        assert runtime.last_reconciliation_ok() is False
        assert runtime.reconciliation_errors() >= 1

    def test_default_providers_are_safe_noops(self) -> None:
        # With no providers injected the runtime must not require MT5.
        runtime = OrchestrationRuntime(reconciliation_interval=1)
        runtime.run_cycle({"event_type": "BREAKOUT"})
        report = runtime.last_reconciliation()
        assert isinstance(report, ReconciliationReport)
        assert report.has_critical() is False


# ---------------------------------------------------------------------------
# Scheduler stats
# ---------------------------------------------------------------------------
class TestSchedulerStats:
    def test_stats_include_reconciliation_fields(self) -> None:
        runtime = OrchestrationRuntime(reconciliation_interval=1)
        runtime.run_cycle({"event_type": "BREAKOUT"})
        stats = runtime.scheduler.stats()
        assert stats["reconciliations_run"] == 1
        assert "last_reconciliation_ok" in stats
        assert stats["last_reconciliation_ok"] is True


# ---------------------------------------------------------------------------
# GET /reconciliation/status endpoint
# ---------------------------------------------------------------------------
class TestReconciliationStatusEndpoint:
    def test_status_returns_real_data(self) -> None:
        from src.main import app

        client = TestClient(app)
        runtime = OrchestrationRuntime(reconciliation_interval=1)
        set_runtime(runtime)
        try:
            runtime.run_cycle({"event_type": "BREAKOUT"})

            resp = client.get("/reconciliation/status")
            assert resp.status_code == 200
            body = resp.json()
            assert body["source"] == "live"
            assert body["history_count"] >= 1
            assert body["last_report"] is not None
            assert "critical" in body["last_report"]
        finally:
            # Restore a clean runtime so this test cannot leak decisions or
            # reports into tests that assert an empty control plane.
            set_runtime(None)


# ---------------------------------------------------------------------------
# Audit P0-3 — ReconciliationGuard blocks new orders on a critical mismatch
# ---------------------------------------------------------------------------
class TestReconciliationGuard:
    def _runner_with(self, internal, broker):
        from execution.reconciliation_runner import ReconciliationRunner

        providers = _CountingProviders(internal, broker)
        return ReconciliationRunner(interval=1, providers=providers)

    def test_guard_allows_before_any_run(self) -> None:
        from execution.reconciliation_runner import ReconciliationGuard

        guard = ReconciliationGuard(self._runner_with([], []))
        allowed, reason = guard.check_can_execute()
        assert allowed is True
        assert reason == ""

    def test_guard_blocks_after_critical_mismatch(self) -> None:
        from execution.reconciliation_runner import ReconciliationGuard

        internal = [
            {"ticket": 1, "symbol": "EURUSD", "volume": 0.1, "sl": 1.0, "tp": 2.0, "magic": 1}
        ]
        broker = []  # position missing on the broker → critical
        runner = self._runner_with(internal, broker)
        runner.run_once()

        guard = ReconciliationGuard(runner)
        allowed, reason = guard.check_can_execute()
        assert allowed is False
        assert "reconciliation" in reason

    def test_guard_unblocks_after_clean_run(self) -> None:
        from execution.reconciliation_runner import ReconciliationGuard

        internal = [
            {"ticket": 1, "symbol": "EURUSD", "volume": 0.1, "sl": 1.0, "tp": 2.0, "magic": 1}
        ]
        providers = _CountingProviders(internal, [])

        from execution.reconciliation_runner import ReconciliationRunner

        runner = ReconciliationRunner(interval=1, providers=providers)
        runner.run_once()  # critical (broker empty)
        guard = ReconciliationGuard(runner)
        assert guard.check_can_execute()[0] is False

        # Now the broker matches → clean run clears the block.
        providers._broker_positions = list(internal)
        runner.run_once()
        assert guard.check_can_execute()[0] is True

    def test_runtime_pipeline_has_reconciliation_guard(self) -> None:
        runtime = OrchestrationRuntime(reconciliation_interval=1)
        assert runtime.pipeline.reconciliation_guard is not None
        assert runtime.pipeline.reconciliation_guard.check_can_execute()[0] is True


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
