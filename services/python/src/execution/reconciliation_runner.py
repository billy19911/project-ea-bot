# -*- coding: utf-8 -*-
"""Periodic reconciliation runner — PRD_V2 §14 Reconciliation wiring.

The :class:`~execution.reconciliation.Reconciler` produces
:class:`~execution.reconciliation.ReconciliationReport`s, but it is only useful
if it actually *runs* during autonomous operation. This module wraps it in a
small, deterministic, fail-safe :class:`ReconciliationRunner` that:

* runs every ``interval`` cycles (tick-based, configurable),
* pulls internal/broker position & order state from injected providers
  (default: no-op providers so tests and dry-runs never require MT5),
* keeps a *bounded* history of reports, and
* never raises — provider/reconciler errors are logged, counted and recorded so
  the scheduler loop is never crashed.

The runner is deliberately MT5-agnostic: production callers inject providers
backed by the live connector; everything else gets safe empty state.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any, Optional

from .reconciliation import Reconciler, ReconciliationReport

logger = logging.getLogger(__name__)

__all__ = ["ReconciliationProviders", "ReconciliationRunner", "ReconciliationGuard"]

# Default reconciliation cadence (in pipeline cycles).
DEFAULT_RECONCILIATION_INTERVAL = 30
# Default bound on retained reconciliation reports.
DEFAULT_RECONCILIATION_HISTORY = 50


class ReconciliationProviders:
    """Default no-op providers (safe empty state, no MT5 dependency).

    Override any of the four methods (or pass any object exposing them) to feed
    real position/order data into the reconciler.
    """

    def internal_positions(self) -> list[Any]:
        return []

    def broker_positions(self) -> list[Any]:
        return []

    def internal_orders(self) -> list[Any]:
        return []

    def broker_orders(self) -> list[Any]:
        return []


class ReconciliationRunner:
    """Runs the reconciler every ``interval`` cycles, fail-safe and bounded.

    Args:
        interval: Number of :meth:`tick` calls between reconciliation runs.
            Values < 1 are clamped to 1 (reconcile every cycle).
        providers: Object exposing ``internal_positions``, ``broker_positions``,
            ``internal_orders`` and ``broker_orders``. Defaults to a
            :class:`ReconciliationProviders` no-op instance.
        history_limit: Maximum number of reports retained (bounded).
        reconciler: Optional pre-built :class:`Reconciler` (for tolerance tuning).
    """

    def __init__(
        self,
        interval: int = DEFAULT_RECONCILIATION_INTERVAL,
        providers: Optional[Any] = None,
        history_limit: int = DEFAULT_RECONCILIATION_HISTORY,
        reconciler: Optional[Reconciler] = None,
    ) -> None:
        self.interval = max(1, int(interval))
        self.providers = providers if providers is not None else ReconciliationProviders()
        self.reconciler = reconciler if reconciler is not None else Reconciler()
        self._history: deque[ReconciliationReport] = deque(maxlen=max(1, int(history_limit)))
        self._cycles = 0
        self._runs = 0
        self._errors = 0
        self._last_ok = True

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def cycles(self) -> int:
        """Number of cycles ticked (attempted reconciliation cycles)."""
        return self._cycles

    @property
    def runs(self) -> int:
        """Number of reconciliation runs actually performed."""
        return self._runs

    @property
    def errors(self) -> int:
        """Number of reconciliation runs that failed (fail-safe)."""
        return self._errors

    @property
    def last_ok(self) -> bool:
        """Whether the most recent reconciliation completed cleanly.

        Meaningful only once at least one run has happened; defaults to True so
        the scheduler summary reads sensibly before the first run.
        """
        return self._last_ok

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------
    def tick(self) -> Optional[ReconciliationReport]:
        """Advance one cycle; run reconciliation when the interval is reached.

        Returns:
            The :class:`ReconciliationReport` when a run happened, else ``None``.
            Never raises — reconciliation failures are logged and recorded.
        """
        self._cycles += 1
        if self._cycles % self.interval != 0:
            return None
        return self.run_once()

    def run_once(self) -> Optional[ReconciliationReport]:
        """Force a reconciliation run now (fail-safe). Returns ``None`` on error."""
        self._runs += 1
        try:
            internal_positions = list(self.providers.internal_positions())
            broker_positions = list(self.providers.broker_positions())
            internal_orders = list(self.providers.internal_orders())
            broker_orders = list(self.providers.broker_orders())
            report = self.reconciler.compare(
                internal_positions,
                broker_positions,
                internal_orders,
                broker_orders,
            )
        except Exception as exc:  # fail-safe: never crash the caller's loop
            self._errors += 1
            self._last_ok = False
            logger.warning("Reconciliation run failed: %s", exc)
            return None

        self._last_ok = not report.has_critical()
        # Record audit entry for this reconciliation run (best-effort).
        try:
            try:
                from ..audit import get_shared_audit_log
            except ImportError:  # imported as top-level ``execution.*``
                from audit import get_shared_audit_log

            get_shared_audit_log().append(
                actor="reconciliation",
                action="run",
                target="reconciliation",
                details=report.to_dict() if report else {},
            )
        except Exception as exc:  # audit must never break the loop
            logger.debug("Reconciliation audit entry skipped: %s", exc)
        self._history.append(report)
        return report

    # ------------------------------------------------------------------
    # History / summary
    # ------------------------------------------------------------------
    def last_report(self) -> Optional[ReconciliationReport]:
        """Return the most recent report, or ``None`` if none yet."""
        return self._history[-1] if self._history else None

    def history(self) -> list[ReconciliationReport]:
        """Return retained reports (oldest first)."""
        return list(self._history)

    def summary(self) -> dict[str, Any]:
        """Return scheduler-friendly reconciliation summary counters."""
        return {
            "reconciliations_run": self._runs,
            "last_reconciliation_ok": self._last_ok,
            "reconciliation_errors": self._errors,
        }


class ReconciliationGuard:
    """Execution gate over a :class:`ReconciliationRunner` (audit P0-3).

    Exposes ``check_can_execute() -> (allowed, reason)`` — the same shape the
    :class:`~orchestration.pipeline.TradingPipeline` ``dependency_guard`` uses —
    so a **critical** reconciliation mismatch (missing/orphan position, volume
    drift, …) blocks NEW orders instead of being a read-only observation.

    Fail-closed policy: once a critical mismatch is observed, execution stays
    blocked until a later reconciliation run comes back clean. Before the first
    run the guard allows execution (there is no evidence of mismatch yet), so
    wiring it does not freeze a freshly started system.
    """

    def __init__(self, runner: ReconciliationRunner) -> None:
        self._runner = runner

    def check_can_execute(self) -> tuple[bool, str]:
        """Return ``(allowed, reason)``; blocked while last reconciliation is bad."""
        if self._runner.last_ok:
            return True, ""
        return (
            False,
            "execution blocked — reconciliation mismatch (internal state != MT5)",
        )
