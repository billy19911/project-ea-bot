# -*- coding: utf-8 -*-
"""Intent registry persistence — append-only JSONL store.

Mirrors JsonlLessonStore pattern: append-only JSONL + in-memory cache, fail-safe.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["IntentStore"]

_DEFAULT_PATH = os.path.join("logs", "intents.jsonl")


class IntentStore:
    """Append-only JSONL intent store with in-memory cache.

    Args:
        path: File to persist to. Defaults to ``INTENT_STORE_PATH`` env or
            ``logs/intents.jsonl``.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = str(path or os.getenv("INTENT_STORE_PATH") or _DEFAULT_PATH)
        self._intents: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        """Load persisted intents; corrupt lines are skipped (fail-safe)."""
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("Skipping corrupt intent line in %s", self.path)
                        continue
                    if isinstance(entry, dict) and "intent_id" in entry:
                        intent_id = entry["intent_id"]
                        if entry.get("event") == "created":
                            self._intents[intent_id] = entry
                        elif entry.get("event") == "updated":
                            if intent_id in self._intents:
                                self._intents[intent_id].update(entry)
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("Could not read intent store %s: %s", self.path, exc)

    def add_intent(self, record: Any) -> None:
        """Add a new intent record (expects IntentRecord with to_dict())."""
        from datetime import datetime, timezone

        if hasattr(record, "to_dict"):
            entry = record.to_dict()
        else:
            entry = dict(record)
        entry["event"] = "created"
        entry["timestamp"] = datetime.now(timezone.utc).isoformat()
        intent_id = entry.get("intent_id")
        if intent_id:
            self._intents[intent_id] = entry
        self._append_line(entry)

    def update_intent_state(
        self, intent_id: str, new_state: str, extra: Optional[dict[str, Any]] = None
    ) -> None:
        """Update intent state and persist the change."""
        from datetime import datetime, timezone

        entry = {
            "intent_id": intent_id,
            "state": new_state,
            "event": "updated",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if extra:
            entry.update(extra)
        if intent_id in self._intents:
            self._intents[intent_id].update(entry)
        self._append_line(entry)

    def get_intent(self, intent_id: str) -> Optional[dict[str, Any]]:
        """Retrieve intent record by intent_id."""
        return self._intents.get(intent_id)

    def all_intents(self) -> dict[str, dict[str, Any]]:
        """Return a shallow copy of all intents."""
        return dict(self._intents)

    def clear(self) -> None:
        """Drop all intents from cache and truncate the file."""
        self._intents.clear()
        try:
            with open(self.path, "w", encoding="utf-8"):
                pass
        except OSError as exc:
            logger.warning("Could not truncate intent store %s: %s", self.path, exc)

    def _append_line(self, entry: dict[str, Any]) -> None:
        """Persist one entry; a write failure degrades to cache-only."""
        try:
            parent = os.path.dirname(self.path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except OSError as exc:
            logger.warning("Could not persist intent to %s (cache kept): %s", self.path, exc)
