# -*- coding: utf-8 -*-
"""Semantic Memory (§17) — keyed facts/knowledge with tags and recency.

Semantic memory stores durable, reusable knowledge ("RSI divergence precedes
reversals", "breakouts fail in low volume"). Items are keyed, tagged, and
retrievable by tag with most-recent-first ordering. The store is size-bounded
(oldest evicted first). No external database is required.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SemanticItem:
    """A single keyed knowledge fact."""

    key: str
    content: str
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "content": self.content,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
        }


class SemanticMemory:
    """Thread-safe, size-bounded tag-indexed knowledge store."""

    def __init__(self, max_size: int = 1000) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        self.max_size = max_size
        self._items: dict[str, SemanticItem] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    def add(
        self,
        key: str,
        content: str,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> SemanticItem:
        """Store a fact under ``key`` (overwriting any existing entry)."""
        if not key or not str(key).strip():
            raise ValueError("SemanticMemory key must be non-empty")
        if not content or not str(content).strip():
            raise ValueError("SemanticMemory content must be non-empty")
        item = SemanticItem(
            key=key,
            content=content,
            tags=list(tags or []),
            metadata=dict(metadata or {}),
        )
        with self._lock:
            if key in self._items:
                self._order.remove(key)
            self._items[key] = item
            self._order.append(key)
            self._evict_locked()
        return item

    def get(self, key: str) -> Optional[SemanticItem]:
        """Return the item stored under ``key`` (None if absent)."""
        with self._lock:
            return self._items.get(key)

    def retrieve(
        self,
        tags: Optional[list[str]] = None,
        limit: int = 10,
    ) -> list[SemanticItem]:
        """Return items matching *any* of ``tags``, most recent first.

        With no tags supplied, returns all items most-recent-first.
        """
        wanted = set(tags or [])
        with self._lock:
            items = list(self._items.values())
        if wanted:
            items = [it for it in items if wanted.intersection(it.tags)]
        items.sort(key=lambda it: it.created_at, reverse=True)
        return items[:limit]

    def delete(self, key: str) -> bool:
        """Remove ``key``; returns True when something was removed."""
        with self._lock:
            if key in self._items:
                del self._items[key]
                self._order.remove(key)
                return True
            return False

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def _evict_locked(self) -> None:
        """Evict oldest entries until within ``max_size`` (lock held)."""
        while len(self._order) > self.max_size:
            oldest = self._order.pop(0)
            self._items.pop(oldest, None)
