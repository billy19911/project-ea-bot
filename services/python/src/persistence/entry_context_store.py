# -*- coding: utf-8 -*-
"""Entry-context persistence — append-only JSONL store.

The entry-context registry (``review.entry_context``) bridges the entry-time
decision context (original stop-loss, direction, entry price, regime) to the
close path so the trade's R-multiple can be computed honestly. It used to live
purely in memory, so a service restart lost the context of every still-open
position — those trades then closed with ``R = None`` (the "table empty / win
has no R" symptom on the Performance page).

This store persists the registry to disk using the SAME pattern as the other
B-5 stores (append-only JSONL + in-memory cache, fail-safe), so the context
survives a restart.

Memory discipline: the cache is a bounded ``OrderedDict`` trimmed to
``max_entries`` (oldest evicted), and each record holds only the small scalar
fields the close path needs — never the bulky agent outputs / news events.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections import OrderedDict
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["EntryContextStore"]

_DEFAULT_PATH = os.path.join("logs", "entry_context.jsonl")

# Only these small scalar fields are persisted (keeps the JSONL tiny and the
# cache bounded). Bulky fields are intentionally dropped.
_PERSISTED_FIELDS = (
    "symbol",
    "direction",
    "entry_price",
    "stop_loss",
    # take_profit + explicit RR snapshot (spec §3.2) — persisted so the close
    # path / performance view can report planned RR without re-deriving it.
    "take_profit",
    "risk_distance",
    "reward_distance",
    "planned_rr",
    "regime",
    "ts",
)


def _slim(context: dict[str, Any]) -> dict[str, Any]:
    """Return only the small persisted fields from a full context dict."""
    out: dict[str, Any] = {}
    for key in _PERSISTED_FIELDS:
        if key in context:
            out[key] = context[key]
    return out


class EntryContextStore:
    """Append-only JSONL entry-context store with a bounded in-memory cache.

    Args:
        path: File to persist to. Defaults to ``ENTRY_CONTEXT_PATH`` env or
            ``logs/entry_context.jsonl``.
        max_entries: Maximum number of tickets kept in the cache (oldest
            evicted first). Keeps memory bounded regardless of trade volume.
    """

    def __init__(self, path: Optional[str] = None, max_entries: int = 1000) -> None:
        self.path = str(path or os.getenv("ENTRY_CONTEXT_PATH") or _DEFAULT_PATH)
        self._max_entries = max(1, int(max_entries))
        self._entries: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        """Load persisted contexts; corrupt lines are skipped (fail-safe)."""
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("Skipping corrupt entry-context line in %s", self.path)
                        continue
                    if not isinstance(entry, dict):
                        continue
                    ticket = entry.get("ticket")
                    if ticket is None:
                        continue
                    key = str(ticket)
                    # Later lines win (append-only, last record is newest).
                    self._entries.pop(key, None)
                    self._entries[key] = entry
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("Could not read entry-context store %s: %s", self.path, exc)
        self._trim()

    def _trim(self) -> None:
        """Evict oldest entries beyond the cap (bounded memory)."""
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def remember(self, ticket: Any, context: dict[str, Any]) -> None:
        """Store (or update) the entry context for *ticket* and persist it."""
        if ticket is None:
            return
        key = str(ticket)
        if not key:
            return
        record = {"ticket": key}
        record.update(_slim(context))
        with self._lock:
            self._entries.pop(key, None)
            self._entries[key] = record
            self._trim()
            self._append_line(record)

    def get(self, ticket: Any) -> dict[str, Any]:
        """Return the stored context for *ticket* (shallow copy), or ``{}``."""
        if ticket is None:
            return {}
        key = str(ticket)
        with self._lock:
            raw = self._entries.get(key)
            if raw is None:
                return {}
            return {k: v for k, v in raw.items() if k != "ticket"}

    def pop(self, ticket: Any) -> dict[str, Any]:
        """Return and remove the stored context for *ticket* (shallow copy).

        Pop only affects the in-memory cache; the append-only file is left
        untouched (a later restart would reload it, which is harmless — a
        closed ticket simply never looks up its context again).
        """
        if ticket is None:
            return {}
        key = str(ticket)
        with self._lock:
            raw = self._entries.pop(key, None)
        if raw is None:
            return {}
        return {k: v for k, v in raw.items() if k != "ticket"}

    def clear(self) -> None:
        """Drop all cached contexts and truncate the file."""
        with self._lock:
            self._entries.clear()
            try:
                with open(self.path, "w", encoding="utf-8"):
                    pass
            except OSError as exc:
                logger.warning("Could not truncate entry-context store %s: %s", self.path, exc)

    def size(self) -> int:
        """Return the number of cached entries."""
        with self._lock:
            return len(self._entries)

    def _append_line(self, record: dict[str, Any]) -> None:
        """Persist one record; a write failure degrades to cache-only."""
        with self._lock:
            try:
                parent = os.path.dirname(self.path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            except OSError as exc:
                logger.warning(
                    "Could not persist entry context to %s (cache kept): %s",
                    self.path,
                    exc,
                )
