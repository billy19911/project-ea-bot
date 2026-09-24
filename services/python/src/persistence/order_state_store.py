# -*- coding: utf-8 -*-
"""Order state ledger persistence — append-only JSONL store.

Mirrors JsonlLessonStore pattern: append-only JSONL + in-memory cache, fail-safe.
"""

from __future__ import annotations

import json
import logging
import os
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
                        logger.warning("Skipping corrupt order state line in %s", self.path)
                        continue
                    if isinstance(entry, dict) and "intent_id" in entry:
                        self._orders[entry["intent_id"]] = entry
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("Could not read order state store %s: %s", self.path, exc)

    def set_order(self, intent_id: str, state: str, extra: Optional[dict[str, Any]] = None) -> None:
        """Create or update an order record and persist it."""
        from datetime import datetime, timezone

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
            logger.warning("Could not truncate order state store %s: %s", self.path, exc)

    def _append_line(self, entry: dict[str, Any]) -> None:
        """Persist one entry; a write failure degrades to cache-only."""
        try:
            parent = os.path.dirname(self.path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except OSError as exc:
            logger.warning("Could not persist order state to %s (cache kept): %s", self.path, exc)
