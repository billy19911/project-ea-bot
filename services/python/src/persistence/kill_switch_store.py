# -*- coding: utf-8 -*-
"""Kill switch state persistence — append-only JSONL store.

Mirrors JsonlLessonStore pattern: append-only JSONL + in-memory cache, fail-safe.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["KillSwitchStateStore"]

_DEFAULT_PATH = os.path.join("logs", "kill_switch.jsonl")


class KillSwitchStateStore:
    """Append-only JSONL kill switch store with in-memory cache.

    Args:
        path: File to persist to. Defaults to ``KILL_SWITCH_STATE_PATH`` env or
            ``logs/kill_switch.jsonl``.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = str(path or os.getenv("KILL_SWITCH_STATE_PATH") or _DEFAULT_PATH)
        self._state: Optional[dict[str, Any]] = None
        self._load()

    def _load(self) -> None:
        """Load last valid state; corrupt lines are skipped (fail-safe)."""
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("Skipping corrupt kill switch line in %s", self.path)
                        continue
                    if isinstance(entry, dict):
                        self._state = entry
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("Could not read kill switch store %s: %s", self.path, exc)

    def save_state(self, kill_switch: Any) -> None:
        """Persist full kill switch state snapshot."""
        from datetime import datetime, timezone

        if hasattr(kill_switch, "to_dict"):
            entry = kill_switch.to_dict()
        else:
            entry = dict(kill_switch)
        entry["timestamp"] = datetime.now(timezone.utc).isoformat()
        self._state = entry
        self._append_line(entry)

    def load_state(self) -> Optional[dict[str, Any]]:
        """Return last valid state from file."""
        return self._state

    def clear(self) -> None:
        """Drop state from cache and truncate the file."""
        self._state = None
        try:
            with open(self.path, "w", encoding="utf-8"):
                pass
        except OSError as exc:
            logger.warning("Could not truncate kill switch store %s: %s", self.path, exc)

    def _append_line(self, entry: dict[str, Any]) -> None:
        """Persist one entry; a write failure degrades to cache-only."""
        try:
            parent = os.path.dirname(self.path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except OSError as exc:
            logger.warning(
                "Could not persist kill switch state to %s (cache kept): %s", self.path, exc
            )
