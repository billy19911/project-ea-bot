# -*- coding: utf-8 -*-
"""Full reconciliation engine — PRD_V2 §14 Reconciliation.

The :class:`Reconciler` compares internal state against the broker (MT5) state
and produces a structured, deterministic :class:`ReconciliationReport`.

Checks (PRD_V2 §14):

* positions — matched vs. missing on either side;
* orders — matched vs. orphan orders (held by the broker but unknown internally);
* lots / volume mismatches;
* SL / TP mismatches;
* symbol mismatches;
* magic-number mismatches.

On a critical mismatch the caller should BLOCK NEW ORDERS, reconcile, recover,
and only resume once consistency is restored. Criticality is exposed via
:meth:`ReconciliationReport.has_critical` — missing positions on either side and
orphan orders are always critical.

All list outputs are sorted by ticket so the report is deterministic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["FieldMismatch", "ReconciliationReport", "Reconciler"]

# Volume/lot tolerance for floating-point comparison.
_VOLUME_TOL = 1e-6
# Price tolerance for SL/TP comparison.
_PRICE_TOL = 1e-9


@dataclass
class FieldMismatch:
    """A single field-level mismatch for a ticket."""

    ticket: int
    field: str
    internal: Any
    broker: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket": self.ticket,
            "field": self.field,
            "internal": self.internal,
            "broker": self.broker,
        }


@dataclass
class ReconciliationReport:
    """Structured result of a reconciliation pass (PRD_V2 §14)."""

    matched: list[int] = field(default_factory=list)
    missing_in_broker: list[int] = field(default_factory=list)
    missing_internal: list[int] = field(default_factory=list)
    volume_mismatches: list[FieldMismatch] = field(default_factory=list)
    sltp_mismatches: list[FieldMismatch] = field(default_factory=list)
    symbol_mismatches: list[FieldMismatch] = field(default_factory=list)
    magic_mismatches: list[FieldMismatch] = field(default_factory=list)
    matched_orders: list[int] = field(default_factory=list)
    orphan_orders: list[int] = field(default_factory=list)

    def has_critical(self) -> bool:
        """True when the mismatch requires blocking new orders (§14).

        Missing positions on either side and orphan orders are critical. Volume,
        SL/TP, symbol and magic mismatches are also treated as critical because
        they can indicate an unintended or externally-modified position.
        """
        return bool(
            self.missing_in_broker
            or self.missing_internal
            or self.volume_mismatches
            or self.sltp_mismatches
            or self.symbol_mismatches
            or self.magic_mismatches
            or self.orphan_orders
        )

    def total_mismatches(self) -> int:
        """Total number of mismatches across all categories."""
        return (
            len(self.missing_in_broker)
            + len(self.missing_internal)
            + len(self.volume_mismatches)
            + len(self.sltp_mismatches)
            + len(self.symbol_mismatches)
            + len(self.magic_mismatches)
            + len(self.orphan_orders)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "matched": list(self.matched),
            "missing_in_broker": list(self.missing_in_broker),
            "missing_internal": list(self.missing_internal),
            "volume_mismatches": [m.to_dict() for m in self.volume_mismatches],
            "sltp_mismatches": [m.to_dict() for m in self.sltp_mismatches],
            "symbol_mismatches": [m.to_dict() for m in self.symbol_mismatches],
            "magic_mismatches": [m.to_dict() for m in self.magic_mismatches],
            "matched_orders": list(self.matched_orders),
            "orphan_orders": list(self.orphan_orders),
            "total_mismatches": self.total_mismatches(),
            "critical": self.has_critical(),
        }


def _field(item: Any, name: str, default: Any = None) -> Any:
    """Read a field from a dict or object."""
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _ticket(item: Any) -> int | None:
    """Extract an integer ticket from a dict/object (or None)."""
    value = _field(item, "ticket")
    if value is None:
        value = _field(item, "id")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _index_by_ticket(items: list[Any]) -> dict[int, Any]:
    """Index items by ticket, skipping entries without a usable ticket."""
    index: dict[int, Any] = {}
    for item in items:
        ticket = _ticket(item)
        if ticket is not None:
            index[ticket] = item
    return index


class Reconciler:
    """Compares internal state against broker state (PRD_V2 §14)."""

    def __init__(self, volume_tolerance: float = _VOLUME_TOL) -> None:
        self.volume_tolerance = volume_tolerance

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def compare(
        self,
        internal_positions: list[Any],
        broker_positions: list[Any],
        internal_orders: list[Any],
        broker_orders: list[Any],
    ) -> ReconciliationReport:
        """Compare internal vs. broker positions and orders.

        Args:
            internal_positions: Positions the system believes are open.
            broker_positions: Positions the broker reports as open.
            internal_orders: Orders the system believes are live.
            broker_orders: Orders the broker reports as live.

        Returns:
            A deterministic :class:`ReconciliationReport`.
        """
        report = ReconciliationReport()
        self._compare_positions(internal_positions, broker_positions, report)
        self._compare_orders(internal_orders, broker_orders, report)
        self._sort(report)
        return report

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _compare_positions(
        self,
        internal_positions: list[Any],
        broker_positions: list[Any],
        report: ReconciliationReport,
    ) -> None:
        internal = _index_by_ticket(internal_positions or [])
        broker = _index_by_ticket(broker_positions or [])

        for ticket in sorted(set(internal) & set(broker)):
            ipos = internal[ticket]
            bpos = broker[ticket]
            report.matched.append(ticket)
            self._compare_fields(ipos, bpos, ticket, report)

        report.missing_in_broker.extend(sorted(set(internal) - set(broker)))
        report.missing_internal.extend(sorted(set(broker) - set(internal)))

    def _compare_fields(
        self,
        ipos: Any,
        bpos: Any,
        ticket: int,
        report: ReconciliationReport,
    ) -> None:
        i_vol = _field(ipos, "volume", _field(ipos, "quantity", 0.0))
        b_vol = _field(bpos, "volume", _field(bpos, "quantity", 0.0))
        if abs(float(i_vol or 0.0) - float(b_vol or 0.0)) > self.volume_tolerance:
            report.volume_mismatches.append(FieldMismatch(ticket, "volume", i_vol, b_vol))

        i_sl, i_tp = _field(ipos, "sl", 0.0), _field(ipos, "tp", 0.0)
        b_sl, b_tp = _field(bpos, "sl", 0.0), _field(bpos, "tp", 0.0)
        if (
            abs(float(i_sl or 0.0) - float(b_sl or 0.0)) > _PRICE_TOL
            or abs(float(i_tp or 0.0) - float(b_tp or 0.0)) > _PRICE_TOL
        ):
            report.sltp_mismatches.append(
                FieldMismatch(ticket, "sl/tp", (i_sl, i_tp), (b_sl, b_tp))
            )

        i_sym = _field(ipos, "symbol", "")
        b_sym = _field(bpos, "symbol", "")
        if str(i_sym).upper() != str(b_sym).upper():
            report.symbol_mismatches.append(FieldMismatch(ticket, "symbol", i_sym, b_sym))

        i_magic = _field(ipos, "magic", 0)
        b_magic = _field(bpos, "magic", 0)
        if int(i_magic or 0) != int(b_magic or 0):
            report.magic_mismatches.append(FieldMismatch(ticket, "magic", i_magic, b_magic))

    def _compare_orders(
        self,
        internal_orders: list[Any],
        broker_orders: list[Any],
        report: ReconciliationReport,
    ) -> None:
        internal = _index_by_ticket(internal_orders or [])
        broker = _index_by_ticket(broker_orders or [])

        report.matched_orders.extend(sorted(set(internal) & set(broker)))
        # Orders the broker holds but the system does not know about are orphans.
        report.orphan_orders.extend(sorted(set(broker) - set(internal)))
        # Internal orders the broker has forgotten are also critical.
        report.missing_in_broker.extend(sorted(set(internal) - set(broker)))
        report.missing_in_broker = sorted(set(report.missing_in_broker))

    @staticmethod
    def _sort(report: ReconciliationReport) -> None:
        report.matched = sorted(set(report.matched))
        report.matched_orders = sorted(set(report.matched_orders))
        report.missing_in_broker = sorted(set(report.missing_in_broker))
        report.missing_internal = sorted(set(report.missing_internal))
        report.orphan_orders = sorted(set(report.orphan_orders))
        report.volume_mismatches.sort(key=lambda m: (m.ticket, m.field))
        report.sltp_mismatches.sort(key=lambda m: (m.ticket, m.field))
        report.symbol_mismatches.sort(key=lambda m: (m.ticket, m.field))
        report.magic_mismatches.sort(key=lambda m: (m.ticket, m.field))
