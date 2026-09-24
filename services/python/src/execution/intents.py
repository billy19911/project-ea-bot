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

# Optional durable store (B-5). When set intents are persisted across restarts;
# when None the module degrades to in-memory only (backward compatible).
_store: Optional[Any] = None


def set_store(store: Optional[Any]) -> None:
    """Attach a durable :class:`IntentStore` (or ``None`` to detach).

    On attach, previously persisted intents are rebuilt into the in-memory
    registry so intent metadata survives a restart.
    """
    global _store
    _store = store
    if store is not None:
        try:
            for intent_id, entry in store.all_intents().items():
                if intent_id in _intent_store:
                    continue
                created_at_raw = entry.get("created_at")
                try:
                    created_at = datetime.fromisoformat(str(created_at_raw))
                except (TypeError, ValueError):
                    created_at = datetime.now(timezone.utc)
                state_raw = entry.get("state", OrderState.INTENT_CREATED.value)
                try:
                    state = OrderState(state_raw)
                except ValueError:
                    state = OrderState.UNKNOWN
                _intent_store[intent_id] = IntentRecord(
                    intent_id=intent_id,
                    decision_id=str(entry.get("decision_id", "")),
                    strategy_version=str(entry.get("strategy_version", "")),
                    symbol=str(entry.get("symbol", "")),
                    direction=str(entry.get("direction", "")),
                    created_at=created_at,
                    state=state,
                    extra=dict(entry.get("extra") or {}),
                )
        except Exception:  # noqa: BLE001 - persistence must never break intents
            pass


def get_store() -> Optional[Any]:
    """Return the currently attached durable store (or ``None``)."""
    return _store


def register_intent(record: IntentRecord) -> None:
    """Add a new intent; raise if duplicate intent_id."""
    if record.intent_id in _intent_store:
        raise ValueError(f"Duplicate intent_id {record.intent_id}")
    _intent_store[record.intent_id] = record
    if _store is not None:
        try:
            _store.add_intent(record)
        except Exception:  # noqa: BLE001 - persistence must never break registration
            pass
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
    if _store is not None:
        try:
            _store.update_intent_state(intent_id, new_state.value, extra=extra)
        except Exception:  # noqa: BLE001 - persistence must never break updates
            pass
    set_order(intent_id, new_state, extra=rec.extra)


def reset_intents() -> None:
    _intent_store.clear()
    reset_store()
