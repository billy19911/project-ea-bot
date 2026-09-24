# -*- coding: utf-8 -*-
"""Position reconciliation snapshot persistence — append-only JSONL store.

Mirrors JsonlLessonStore pattern: append-only JSONL + in-memory cache, fail-safe.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["PositionReconciliationStore"]

_DEFAULT_PATH = os.path.join("logs", "position_reconciliation.jsonl")


class PositionReconciliationStore:
    """Append-only JSONL position reconciliation store with in-memory cache.

    Args:
        path: File to persist to. Defaults to ``POSITION_RECONCILIATION_PATH`` env or
            ``logs/position_reconciliation.jsonl``.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = str(path or os.getenv("POSITION_RECONCILIATION_PATH") or _DEFAULT_PATH)
        self._snapshot: Optional[dict[str, Any]] = None
        self._load()

    def _load(self) -> None:
        """Load last valid snapshot; corrupt lines are skipped (fail-safe)."""
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
                            "Skipping corrupt position reconciliation line in %s", self.path
                        )
                        continue
                    if isinstance(entry, dict):
                        self._snapshot = entry
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("Could not read position reconciliation store %s: %s", self.path, exc)

    def save_snapshot(
        self, last_sl: dict[int, float], last_tp: dict[int, float], last_volume: dict[int, float]
    ) -> None:
        """Persist current reconciliation snapshot."""
        from datetime import datetime, timezone

        entry = {
            "last_sl": {str(k): v for k, v in last_sl.items()},
            "last_tp": {str(k): v for k, v in last_tp.items()},
            "last_volume": {str(k): v for k, v in last_volume.items()},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._snapshot = entry
        self._append_line(entry)

    def load_snapshot(
        self,
    ) -> Optional[tuple[dict[int, float], dict[int, float], dict[int, float]]]:
        """Return last snapshot as (last_sl, last_tp, last_volume) tuple."""
        if self._snapshot is None:
            return None
        last_sl = {int(k): v for k, v in self._snapshot.get("last_sl", {}).items()}
        last_tp = {int(k): v for k, v in self._snapshot.get("last_tp", {}).items()}
        last_volume = {int(k): v for k, v in self._snapshot.get("last_volume", {}).items()}
        return (last_sl, last_tp, last_volume)

    def clear(self) -> None:
        """Drop snapshot from cache and truncate the file."""
        self._snapshot = None
        try:
            with open(self.path, "w", encoding="utf-8"):
                pass
        except OSError as exc:
            logger.warning(
                "Could not truncate position reconciliation store %s: %s", self.path, exc
            )

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
                "Could not persist position reconciliation to %s (cache kept): %s",
                self.path,
                exc,
            )
