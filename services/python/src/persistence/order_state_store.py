# -*- coding: utf-8 -*-
"""Order state ledger persistence — append-only JSONL store.

Mirrors JsonlLessonStore pattern: append-only JSONL + in-memory cache, fail-safe.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["OrderStateStore"]

_DEFAULT_PATH = os.path.join("logs", "order_state.jsonl")


class OrderStateStore:
    """Append-only JSONL order state store with in-memory cache.

    Args:
        path: File to persist to. Defaults to ``ORDER_STATE_PATH`` env or
            ``logs/order_state.jsonl``.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = str(path or os.getenv("ORDER_STATE_PATH") or _DEFAULT_PATH)
        self._orders: dict[str, dict[str, Any]] = {}
        # Guards the read-modify-append sequence so a concurrent close/update
        # cannot interleave a stale record into the jsonl (LEDGER-SLTP T1).
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        """Load persisted orders; corrupt lines are skipped (fail-safe)."""
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning(
                            "Skipping corrupt order state line in %s", self.path
                        )
                        continue
                    if isinstance(entry, dict) and "intent_id" in entry:
                        self._orders[entry["intent_id"]] = entry
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("Could not read order state store %s: %s", self.path, exc)

    def set_order(
        self, intent_id: str, state: str, extra: Optional[dict[str, Any]] = None
    ) -> None:
        """Create or update an order record and persist it."""
        from datetime import datetime, timezone

        with self._lock:
            entry = self._orders.get(intent_id, {"intent_id": intent_id})
            entry.update(
                {
                    "state": state,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            if extra:
                entry.update(extra)
            self._orders[intent_id] = entry
            self._append_line(entry)

    def mark_closed(
        self,
        ticket: Any,
        reason: str = "broker_position_disappeared",
        at: Optional[str] = None,
    ) -> bool:
        """Append a ``closed`` state record for the latest open record of *ticket*.

        LEDGER-SLTP T1: the append-only ledger never recorded a ``closed`` state,
        so every historical ``position_confirmed``/``filled`` record counted as an
        open internal position forever and reconciliation reported it as
        ``missing_in_broker`` (critical) — permanently blocking new orders.

        The close is resolved against the *latest* record for a ticket (last
        record wins in the append-only log) so a later open state supersedes an
        earlier close.

        Args:
            ticket: Broker ticket to close. Matching is done on the record's
                ``ticket`` field (string/int compared as strings).
            reason: Human-readable close reason, persisted on the record.
            at: Optional ISO-8601 timestamp; defaults to now (UTC).

        Returns:
            ``True`` when a ``closed`` record was appended, ``False`` on a no-op
            (no matching record, already closed, or an invalid transition).
        """
        from datetime import datetime, timezone

        from execution.state_machine import OrderState, next_allowed

        if ticket is None:
            return False
        ticket_key = str(ticket)

        with self._lock:
            # Append-only log → the LAST record for a ticket is the current state.
            latest_intent: Optional[str] = None
            latest_record: Optional[dict[str, Any]] = None
            for intent_id, record in self._orders.items():
                if not isinstance(record, dict):
                    continue
                if str(record.get("ticket")) == ticket_key:
                    latest_intent = intent_id
                    latest_record = record

            if latest_intent is None or latest_record is None:
                logger.debug("mark_closed: no ledger record for ticket %s", ticket_key)
                return False

            current_state = str(latest_record.get("state", "")).lower()
            if current_state == OrderState.CLOSED.value:
                # Idempotent: already closed → no duplicate record.
                return False

            try:
                current = OrderState(current_state)
            except ValueError:
                logger.debug(
                    "mark_closed: unknown source state %r for ticket %s",
                    current_state,
                    ticket_key,
                )
                return False

            if OrderState.CLOSED not in next_allowed(current):
                logger.debug(
                    "mark_closed: transition %s → closed not allowed for ticket %s",
                    current.value,
                    ticket_key,
                )
                return False

            timestamp = at or datetime.now(timezone.utc).isoformat()
            entry = {
                "intent_id": latest_intent,
                "state": OrderState.CLOSED.value,
                "ticket": latest_record.get("ticket", ticket),
                "timestamp": timestamp,
                "reason": reason,
            }
            self._orders[latest_intent] = entry
            self._append_line(entry)
            return True

    def get_order(self, intent_id: str) -> Optional[dict[str, Any]]:
        """Retrieve order record by intent_id."""
        return self._orders.get(intent_id)

    def all_orders(self) -> dict[str, dict[str, Any]]:
        """Return a shallow copy of all orders."""
        return dict(self._orders)

    def clear(self) -> None:
        """Drop all orders from cache and truncate the file."""
        self._orders.clear()
        try:
            with open(self.path, "w", encoding="utf-8"):
                pass
        except OSError as exc:
            logger.warning(
                "Could not truncate order state store %s: %s", self.path, exc
            )

    def _append_line(self, entry: dict[str, Any]) -> None:
        """Persist one entry; a write failure degrades to cache-only."""
        with self._lock:
            try:
                parent = os.path.dirname(self.path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(entry, ensure_ascii=False, default=str) + "\n"
                    )
            except OSError as exc:
                logger.warning(
                    "Could not persist order state to %s (cache kept): %s",
                    self.path,
                    exc,
                )
