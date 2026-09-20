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
from typing import Dict, Tuple


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


def get_order(intent_id: str) -> Dict:
    """Retrieve order record by *intent_id*; raise KeyError if missing."""
    return _order_store[intent_id]


def set_order(intent_id: str, state: OrderState, extra: Dict | None = None) -> None:
    """Create or update an order record.

    ``extra`` can contain arbitrary metadata (e.g., timestamps, broker ticket).
    """
    record = _order_store.get(intent_id, {"intent_id": intent_id})
    record.update({"state": state.value})
    if extra:
        record.update(extra)
    _order_store[intent_id] = record


def reset_store() -> None:
    """Clear the in‑memory store – useful for test isolation."""
    _order_store.clear()
