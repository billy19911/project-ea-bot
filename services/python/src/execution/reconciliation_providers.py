# -*- coding: utf-8 -*-
"""MT5-backed reconciliation providers (audit P0-3 follow-up).

The reconciliation *gate* (audit P0-3) only blocks orders when it actually sees
a mismatch — but production wiring used no-op providers, so it always reconciled
"empty vs empty". These providers feed the reconciler with:

* **internal state** — the positions/orders the execution layer believes it
  placed, reconstructed from the durable order state machine store
  (``execution.state_machine``), and
* **broker state** — the live positions/orders read from the read-only MT5
  connector (``mt5.connector``).

Design guarantees:

* **Read-only** — reads MT5 only; never sends an order.
* **Fail-safe** — any read error returns an empty list for that side (the
  runner already treats provider errors as fail-safe). A degraded read must not
  crash the scheduler loop.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["MT5ReconciliationProviders", "internal_positions_from_store"]

# Order states that mean "the engine believes a position exists".
_POSITION_STATES = {"position_confirmed", "filled"}


def _to_dict(obj: Any) -> dict[str, Any]:
    """Best-effort dict conversion for pydantic models / objects."""
    if isinstance(obj, dict):
        return dict(obj)
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            return dict(dump())
        except Exception:  # noqa: BLE001 - malformed model
            return {}
    return {}


def _internal_order_store() -> dict:
    """Return the execution state-machine order store, trying both import paths.

    The FastAPI app imports ``src.execution.*`` while tests import
    ``execution.*``; these are distinct module instances, so both paths must be
    tried (same pattern as ``execution.engine._send_to_mt5``).
    """
    for mod_name in ("execution.state_machine", "src.execution.state_machine"):
        try:
            import importlib

            return importlib.import_module(mod_name)._order_store
        except (ImportError, AttributeError):
            continue
    return {}


def internal_positions_from_store(store: Optional[dict] = None) -> list[dict[str, Any]]:
    """Reconstruct the internal position ledger from the order state machine.

    Reads ``execution.state_machine._order_store`` (or the injected ``store``)
    and emits one entry per order whose state indicates a confirmed position
    and that carries a broker ``ticket``.

    LEDGER-SLTP T1: state is resolved per **ticket** using the latest record so
    a ``closed`` state supersedes an earlier ``position_confirmed``/``filled``
    record for the same ticket (the append-only ledger keeps one row per intent,
    but a ticket that was later closed must never be reported as an open
    internal position — otherwise reconciliation would flag a phantom
    ``missing_in_broker`` and block all new orders).
    """
    if store is None:
        store = _internal_order_store()

    # Resolve the latest state per ticket (last writer wins, insertion-ordered).
    latest_state_by_ticket: dict[str, str] = {}
    record_by_ticket: dict[str, dict[str, Any]] = {}
    for record in list((store or {}).values()):
        if not isinstance(record, dict):
            continue
        ticket = record.get("ticket")
        if ticket is None:
            continue
        key = str(ticket)
        latest_state_by_ticket[key] = str(record.get("state", "")).lower()
        record_by_ticket[key] = record

    positions: list[dict[str, Any]] = []
    for key, state in latest_state_by_ticket.items():
        if state not in _POSITION_STATES:
            continue
        record = record_by_ticket[key]
        positions.append(
            {
                "ticket": record.get("ticket"),
                "symbol": record.get("symbol", ""),
                "volume": record.get("volume"),
            }
        )
    return positions


class MT5ReconciliationProviders:
    """Reconciliation providers backed by the internal store + live MT5.

    Args:
        connector: Object exposing ``get_positions()`` / ``get_orders()``.
            Defaults to the production read-only ``mt5.connector`` module.
        internal_store: Optional mapping of intent id → order record. Defaults
            to the execution state machine's in-memory store.
    """

    def __init__(
        self,
        connector: Any = None,
        internal_store: Optional[dict] = None,
    ) -> None:
        self._connector = connector
        self._internal_store = internal_store

    def _connector_or_default(self) -> Any:
        if self._connector is not None:
            return self._connector
        # Try both import paths (``src.mt5`` for the app, ``mt5`` for tests).
        for mod_name in ("mt5.connector", "src.mt5.connector"):
            try:
                import importlib

                return importlib.import_module(mod_name)
            except ImportError:
                continue
        raise ImportError("mt5.connector is not importable")

    # ------------------------------------------------------------------
    # Internal side
    # ------------------------------------------------------------------
    def internal_positions(self) -> list[Any]:
        return internal_positions_from_store(self._internal_store)

    def internal_orders(self) -> list[Any]:
        # The internal ledger currently tracks positions (via the order store).
        # Order-level tracking is not persisted yet, so report none rather than
        # fabricating.
        return []

    # ------------------------------------------------------------------
    # Broker side
    # ------------------------------------------------------------------
    def broker_positions(self) -> list[Any]:
        try:
            raw = self._connector_or_default().get_positions() or []
            return [_to_dict(p) for p in raw if _to_dict(p)]
        except Exception as exc:  # noqa: BLE001 - fail-safe
            logger.debug("Broker positions read failed: %s", exc)
            return []

    def broker_orders(self) -> list[Any]:
        try:
            raw = self._connector_or_default().get_orders() or []
            return [_to_dict(o) for o in raw if _to_dict(o)]
        except Exception as exc:  # noqa: BLE001 - fail-safe
            logger.debug("Broker orders read failed: %s", exc)
            return []
