# -*- coding: utf-8 -*-
"""Durable execution state machine – Phase 34.

Defines the deterministic order lifecycle used by the ExecutionEngine.
The state progression is:
    INTENT_CREATED → RISK_APPROVED → SUBMITTING → SUBMITTED →
    ACKNOWLEDGED → PARTIALLY_FILLED → FILLED → POSITION_CONFIRMED → CLOSED

`OrderState` enum enumerates all states. Helper `next_allowed` returns the
set of permissible next states for a given current state. The module also
exposes a simple in‑memory `order_store` mapping intent IDs to their current
state and metadata. The ExecutionEngine will update this store after each
step.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional, Tuple


class OrderState(str, Enum):
    INTENT_CREATED = "intent_created"
    RISK_APPROVED = "risk_approved"
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    POSITION_CONFIRMED = "position_confirmed"
    CLOSED = "closed"
    UNKNOWN = "unknown"


# Mapping of allowed next states for each state.
_NEXT_ALLOWED: Dict[OrderState, Tuple[OrderState, ...]] = {
    OrderState.INTENT_CREATED: (OrderState.RISK_APPROVED,),
    OrderState.RISK_APPROVED: (OrderState.SUBMITTING,),
    OrderState.SUBMITTING: (OrderState.SUBMITTED, OrderState.UNKNOWN),
    OrderState.SUBMITTED: (OrderState.ACKNOWLEDGED, OrderState.UNKNOWN),
    OrderState.ACKNOWLEDGED: (OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.UNKNOWN),
    OrderState.PARTIALLY_FILLED: (OrderState.FILLED, OrderState.UNKNOWN),
    OrderState.FILLED: (OrderState.POSITION_CONFIRMED, OrderState.UNKNOWN),
    OrderState.POSITION_CONFIRMED: (OrderState.CLOSED, OrderState.UNKNOWN),
    OrderState.CLOSED: (),
    OrderState.UNKNOWN: (),
}


def next_allowed(state: OrderState) -> Tuple[OrderState, ...]:
    """Return a tuple of permissible next states for *state*.

    If the state is terminal (CLOSED/UNKNOWN) the tuple is empty.
    """
    return _NEXT_ALLOWED.get(state, ())


# Simple in‑memory store for order intent state tracking.
# In production this would be persisted; for tests a module‑level dict is enough.
_order_store: Dict[str, Dict] = {}

# Optional durable store (B-5). When set the ledger is persisted across restarts;
# when None the module degrades to in-memory only (backward compatible).
_store: Optional[Any] = None


def set_store(store: Optional[Any]) -> None:
    """Attach a durable :class:`OrderStateStore` (or ``None`` to detach).

    On attach, previously persisted orders are loaded into the in-memory
    ledger so state survives a restart.
    """
    global _store
    _store = store
    if store is not None:
        try:
            persisted = store.all_orders()
            for intent_id, record in persisted.items():
                _order_store[intent_id] = dict(record)
        except Exception:  # noqa: BLE001 - persistence must never break state machine
            pass


def get_store() -> Optional[Any]:
    """Return the currently attached durable store (or ``None``)."""
    return _store


def get_order(intent_id: str) -> Dict:
    """Retrieve order record by *intent_id*; raise KeyError if missing."""
    return _order_store[intent_id]


def set_order(intent_id: str, state: OrderState | str, extra: Dict | None = None) -> None:
    """Create or update an order record.

    ``extra`` can contain arbitrary metadata (e.g., timestamps, broker ticket).
    ``state`` accepts an :class:`OrderState` or a plain state string.
    """
    state_value = state.value if isinstance(state, OrderState) else str(state)
    record = _order_store.get(intent_id, {"intent_id": intent_id})
    record.update({"state": state_value})
    if extra:
        record.update(extra)
    _order_store[intent_id] = record
    if _store is not None:
        try:
            _store.set_order(intent_id, state_value, extra=extra)
        except Exception:  # noqa: BLE001 - persistence must never break state machine
            pass


def reset_store() -> None:
    """Clear the in‑memory store – useful for test isolation."""
    _order_store.clear()
