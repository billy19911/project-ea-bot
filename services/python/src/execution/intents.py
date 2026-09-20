# -*- coding: utf-8 -*-
"""Intent tracking – Phase 34 durable execution.

Provides a simple in‑memory store for order intent metadata and state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .state_machine import OrderState, reset_store, set_order


@dataclass
class IntentRecord:
    intent_id: str
    decision_id: str
    strategy_version: str
    symbol: str
    direction: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    state: OrderState = OrderState.INTENT_CREATED
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "decision_id": self.decision_id,
            "strategy_version": self.strategy_version,
            "symbol": self.symbol,
            "direction": self.direction,
            "created_at": self.created_at.isoformat(),
            "state": self.state.value,
            "extra": self.extra,
        }


# In‑memory global store – cleared on test reset.
_intent_store: Dict[str, IntentRecord] = {}


def register_intent(record: IntentRecord) -> None:
    """Add a new intent; raise if duplicate intent_id."""
    if record.intent_id in _intent_store:
        raise ValueError(f"Duplicate intent_id {record.intent_id}")
    _intent_store[record.intent_id] = record
    # Mirror in state_machine for compatibility.
    set_order(record.intent_id, record.state)


def get_intent(intent_id: str) -> IntentRecord:
    return _intent_store[intent_id]


def update_intent_state(
    intent_id: str, new_state: OrderState, extra: Optional[Dict[str, Any]] = None
) -> None:
    rec = _intent_store[intent_id]
    rec.state = new_state
    if extra:
        rec.extra.update(extra)
    set_order(intent_id, new_state, extra=rec.extra)


def reset_intents() -> None:
    _intent_store.clear()
    reset_store()
