# -*- coding: utf-8 -*-
"""Restart recovery + durable reconciliation readiness gate — TASK 08.

Broker state and internal state must converge *safely* across a process restart.
The dangerous default is to treat ``internal == empty`` as ``broker == empty``:
after a crash the in-memory ledger is empty while the broker may still hold one
of our positions, so a naive "no internal state → allow new orders" decision can
double-enter.

This module implements the ordered restart sequence required by the master plan
(section 10) and a fail-closed readiness gate:

    load durable intents
      → connect MT5
      → read open positions
      → read recent orders / deals
      → reconcile
      → rebuild internal state
      → ONLY THEN permit new execution

Design guarantees (all proven by tests):

* **Fail-closed.** Until the sequence completes CLEANLY the gate blocks new
  orders. An uncertain read (MT5 unreadable, no connection, reconcile error) is
  *uncertain*, never "empty".
* **Never internal-empty == broker-empty.** A broker read failure is reported as
  unverified, distinct from "the broker genuinely holds nothing".
* **Idempotent duplicate recovery.** Recovery ADOPTS an already-landed order,
  it never re-sends. The durable ``intent_id`` (idempotency key) is the
  reconciliation key, so a re-dispatch of a recovered intent is refused by the
  existing duplicate detector.
* **Deterministic.** Same inputs → same report; no clock/network dependence in
  the decision path beyond the injected callables.

Everything external (MT5 connect, position/order/deal reads, clock) is injected
so the coordinator is fully testable without a live terminal.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "RecoveryState",
    "RestartRecoveryReport",
    "RestartRecoveryCoordinator",
    "ReconciliationReadinessGate",
]


class RecoveryState(str, Enum):
    """Outcome of the restart recovery sequence."""

    #: Sequence has not run yet → NOT permitted (fail-closed).
    PENDING = "pending"
    #: Sequence completed and internal↔broker state converged → permitted.
    RECONCILED = "reconciled"
    #: Sequence ran and found an unrecoverable/uncertain state → BLOCK.
    BLOCKED = "blocked"


@dataclass
class RestartRecoveryReport:
    """Structured result of one restart recovery attempt."""

    state: RecoveryState = RecoveryState.PENDING
    steps: list[str] = field(default_factory=list)
    mt5_connected: bool = False
    #: True only when the broker position/order reads were *verified*.
    broker_read_verified: bool = False
    open_positions: int = 0
    open_orders: int = 0
    recovered_intents: int = 0
    adopted_intents: list[str] = field(default_factory=list)
    reconciliation_ok: bool = False
    critical_mismatches: int = 0
    reason: str = ""

    @property
    def permits_execution(self) -> bool:
        """True only when recovery completed cleanly (RECONCILED)."""
        return self.state is RecoveryState.RECONCILED

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "steps": list(self.steps),
            "mt5_connected": self.mt5_connected,
            "broker_read_verified": self.broker_read_verified,
            "open_positions": self.open_positions,
            "open_orders": self.open_orders,
            "recovered_intents": self.recovered_intents,
            "adopted_intents": list(self.adopted_intents),
            "reconciliation_ok": self.reconciliation_ok,
            "critical_mismatches": self.critical_mismatches,
            "reason": self.reason,
            "permits_execution": self.permits_execution,
        }


class RestartRecoveryCoordinator:
    """Run the ordered restart sequence and expose a fail-closed readiness gate.

    Args:
        load_intents: Zero-arg callable returning the durable intent records
            (list of dicts, each carrying at least ``intent_id`` and ``state``).
        connect_mt5: Zero-arg callable returning True when MT5 is connected.
        read_positions: Zero-arg callable returning the broker positions
            (list of dicts). May return ``(ok, positions)`` to disambiguate a
            genuine empty book (``ok=True``) from a failed read (``ok=False``).
        read_orders: Zero-arg callable returning the broker orders (list).
        read_deals: Zero-arg callable returning recent deals (list). Optional.
        reconcile: Callable ``(intents) -> report`` where ``report`` exposes a
            ``has_critical()`` (bool) and ``to_dict()`` (or is a dict with
            ``critical``). Optional; when absent reconciliation is skipped and
            the broker-read verification alone decides.
        rebuild_state: Optional callable ``(intents, broker_positions) -> None``
            invoked to rebuild the internal ledger from the recovered truth.
    """

    def __init__(
        self,
        *,
        load_intents: Callable[[], list[Any]],
        connect_mt5: Callable[[], bool],
        read_positions: Callable[[], Any],
        read_orders: Callable[[], Any],
        read_deals: Optional[Callable[[], Any]] = None,
        reconcile: Optional[Callable[[list[Any]], Any]] = None,
        rebuild_state: Optional[Callable[[list[Any], list[Any]], None]] = None,
    ) -> None:
        self._load_intents = load_intents
        self._connect_mt5 = connect_mt5
        self._read_positions = read_positions
        self._read_orders = read_orders
        self._read_deals = read_deals
        self._reconcile = reconcile
        self._rebuild_state = rebuild_state
        self._report = RestartRecoveryReport()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def report(self) -> RestartRecoveryReport:
        return self._report

    @property
    def permits_execution(self) -> bool:
        """True only after a CLEAN recovery run (fail-closed otherwise)."""
        return self._report.permits_execution

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------
    def run(self) -> RestartRecoveryReport:
        """Execute the full ordered restart sequence (fail-closed).

        Never raises — any error leaves the coordinator in ``BLOCKED`` with the
        failure reason recorded, so a broken recovery can never accidentally
        permit execution.
        """
        report = RestartRecoveryReport(state=RecoveryState.BLOCKED)
        report.steps.append("start")

        # 1. LOAD DURABLE INTENTS ---------------------------------------
        try:
            intents = list(self._load_intents() or [])
        except Exception as exc:  # noqa: BLE001 - uncertain → block
            report.reason = f"failed to load durable intents: {exc}"
            self._report = report
            logger.warning("Restart recovery: %s", report.reason)
            return report
        report.steps.append("load_durable_intents")
        open_intents = [i for i in intents if _intent_is_open(i)]
        report.recovered_intents = len(open_intents)

        # 2. CONNECT MT5 ------------------------------------------------
        try:
            connected = bool(self._connect_mt5())
        except Exception as exc:  # noqa: BLE001
            connected = False
            logger.warning("Restart recovery: MT5 connect raised (%s)", exc)
        report.mt5_connected = connected
        report.steps.append("connect_mt5")
        if not connected:
            report.reason = "MT5 not connected — broker state unverified (fail-closed)"
            self._report = report
            return report

        # 3. READ OPEN POSITIONS ---------------------------------------
        # A read failure must be reported as UNVERIFIED, never as "empty".
        positions, positions_ok = _read_with_verification(self._read_positions)
        report.steps.append("read_open_positions")
        if not positions_ok:
            report.reason = (
                "broker positions read failed — cannot prove broker=empty "
                "(fail-closed, internal-empty != broker-empty)"
            )
            self._report = report
            return report
        report.broker_read_verified = True
        report.open_positions = len(positions)

        # 4. READ RECENT ORDERS / DEALS --------------------------------
        orders, orders_ok = _read_with_verification(self._read_orders)
        report.steps.append("read_orders_deals")
        if not orders_ok:
            report.reason = "broker orders read failed — state uncertain (fail-closed)"
            self._report = report
            return report
        report.open_orders = len(orders)
        if self._read_deals is not None:
            try:
                deals = self._read_deals() or []
                # Track which recovered intents were already fulfilled at the
                # broker so duplicate recovery adopts instead of re-sending.
                report.adopted_intents = _match_intents_to_broker(
                    open_intents, positions, orders, deals
                )
            except Exception as exc:  # noqa: BLE001 - deals are best-effort
                logger.debug("Restart recovery: deal read skipped (%s)", exc)

        # 5. RECONCILE --------------------------------------------------
        report.steps.append("reconcile")
        if self._reconcile is not None:
            try:
                rec = self._reconcile(intents)
                report.reconciliation_ok = not _is_critical(rec)
                report.critical_mismatches = _mismatch_count(rec)
            except Exception as exc:  # noqa: BLE001 - uncertain → block
                report.reason = f"reconciliation failed: {exc} (fail-closed)"
                self._report = report
                logger.warning("Restart recovery: %s", report.reason)
                return report
            if not report.reconciliation_ok:
                report.reason = (
                    f"reconciliation found {report.critical_mismatches} critical "
                    "mismatch(es) — new orders blocked until state converges"
                )
                self._report = report
                return report
        else:
            # No reconciler → we can only trust the verified broker read.
            report.reconciliation_ok = True

        # 6. REBUILD INTERNAL STATE ------------------------------------
        if self._rebuild_state is not None:
            try:
                self._rebuild_state(intents, positions)
            except Exception as exc:  # noqa: BLE001 - rebuild failure → block
                report.reason = f"state rebuild failed: {exc} (fail-closed)"
                self._report = report
                return report
        report.steps.append("rebuild_internal_state")

        # 7. ONLY NOW PERMIT EXECUTION ---------------------------------
        report.state = RecoveryState.RECONCILED
        report.reason = "restart recovery complete — broker and internal state converged"
        report.steps.append("reconciled")
        self._report = report
        logger.info(
            "Restart recovery reconciled: positions=%d intents=%d",
            report.open_positions,
            report.recovered_intents,
        )
        return report


class ReconciliationReadinessGate:
    """Fail-closed execution gate keyed on restart-recovery readiness.

    Exposes ``check_can_execute() -> (allowed, reason)`` — the same shape the
    :class:`~orchestration.pipeline.TradingPipeline` dependency/reconciliation
    guards use — so the pipeline can refuse new orders until recovery has run
    and converged.

    Fail-closed: until the recovery report is ``RECONCILED`` the gate blocks. A
    coordinator that has not run yet (``PENDING``) also blocks, because on a
    fresh restart nothing has proven the broker state yet. Callers that want the
    historical "allow before first run" behaviour simply do not wire this gate.
    """

    def __init__(self, coordinator: RestartRecoveryCoordinator) -> None:
        self._coordinator = coordinator

    def check_can_execute(self) -> tuple[bool, str]:
        report = self._coordinator.report
        if report.permits_execution:
            return True, ""
        if report.state is RecoveryState.BLOCKED:
            return False, report.reason or "restart recovery blocked new orders"
        return False, "restart recovery pending — broker state not yet reconciled"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_OPEN_STATES = {
    "position_confirmed",
    "filled",
    "submitted",
    "acknowledged",
    "unknown",
    "submitting",
}


def _intent_is_open(record: Any) -> bool:
    """True when a durable intent record represents a not-yet-closed order."""
    state = str(_field(record, "state", "")).lower()
    return state in _OPEN_STATES


def _field(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _read_with_verification(reader: Callable[[], Any]) -> tuple[list[Any], bool]:
    """Read broker state, distinguishing "verified empty" from "failed read".

    A reader returning ``(ok, items)`` is honoured exactly. A reader returning a
    bare list is treated as verified (the caller opted into that contract). Any
    exception is an UNVERIFIED read → ``( , False)``.
    """
    try:
        result = reader()
    except Exception as exc:  # noqa: BLE001 - uncertain read → unverified
        logger.debug("Broker read raised (unverified): %s", exc)
        return [], False
    if isinstance(result, tuple) and len(result) == 2:
        ok, items = result
        return list(items or []), bool(ok)
    return list(result or []), True


def _is_critical(rec: Any) -> bool:
    """True when a reconciliation report carries a critical mismatch."""
    if rec is None:
        return True
    has_critical = getattr(rec, "has_critical", None)
    if callable(has_critical):
        try:
            return bool(has_critical())
        except Exception:  # noqa: BLE001
            return True
    if isinstance(rec, dict):
        if "critical" in rec:
            return bool(rec.get("critical"))
        return bool(rec.get("total_mismatches", 0))
    return False


def _mismatch_count(rec: Any) -> int:
    if rec is None:
        return 0
    total = getattr(rec, "total_mismatches", None)
    if callable(total):
        try:
            return int(total())
        except Exception:  # noqa: BLE001
            return 0
    if isinstance(rec, dict):
        return int(rec.get("total_mismatches", 0) or 0)
    return 0


def _match_intents_to_broker(
    intents: list[Any],
    positions: list[Any],
    orders: list[Any],
    deals: list[Any],
) -> list[str]:
    """Return intent ids that already have a broker counterpart (adopt, no re-send).

    Matching is by any persisted broker ticket (order/deal/position) present on
    the intent record, compared against the broker ranks. Only intents that
    already carry a ticket are considered (an intent that never reached the
    broker has nothing to adopt).
    """
    broker_tickets: set[str] = set()
    for collection in (positions, orders, deals):
        for item in collection or []:
            for key in ("ticket", "order", "deal", "position_id", "position"):
                value = _field(item, key, None)
                if value not in (None, ""):
                    broker_tickets.add(str(value))
    adopted: list[str] = []
    for intent in intents or []:
        ticket = None
        for key in (
            "broker_position_ticket",
            "broker_order_ticket",
            "broker_deal_ticket",
            "ticket",
        ):
            value = _field(intent, key, None)
            if value not in (None, ""):
                ticket = str(value)
                break
        if ticket and ticket in broker_tickets:
            adopted.append(str(_field(intent, "intent_id", "") or ""))
    return adopted
