# -*- coding: utf-8 -*-
"""Working Memory (§17) — short-lived, in-process scratch store with TTL.

Working memory holds transient state relevant to the *current* reasoning cycle
(the active symbol, intermediate computations, the last event). Entries expire
automatically after a TTL and the store is size-bounded (oldest evicted first),
so it can never grow without bound. No external database is required.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Optional


class WorkingMemory:
    """Thread-safe, TTL- and size-bounded key/value scratch store."""

    def __init__(self, default_ttl: float = 300.0, max_size: int = 256) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        self.default_ttl = default_ttl
        self.max_size = max_size
        self._store: "OrderedDict[str, tuple[Any, float]]" = OrderedDict()
        self._lock = threading.Lock()

    def put(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Store ``value`` under ``key`` with an optional per-item TTL."""
        effective_ttl = self.default_ttl if ttl is None else ttl
        expires_at = time.monotonic() + effective_ttl if effective_ttl > 0 else float("inf")
        with self._lock:
            # Refresh recency ordering.
            self._store.pop(key, None)
            self._store[key] = (value, expires_at)
            self._evict_locked()

    def get(self, key: str) -> Any:
        """Return the value for ``key`` (None if missing or expired)."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            return value

    def delete(self, key: str) -> bool:
        """Remove ``key``; returns True when something was removed."""
        with self._lock:
            return self._store.pop(key, None) is not None

    def clear(self) -> None:
        """Remove all entries."""
        with self._lock:
            self._store.clear()

    def purge_expired(self) -> int:
        """Drop expired entries; returns the number purged."""
        now = time.monotonic()
        with self._lock:
            expired = [k for k, (_, exp) in self._store.items() if now > exp]
            for key in expired:
                del self._store[key]
            return len(expired)

    def keys(self) -> list[str]:
        """Return the current (unexpired) keys, most-recently-used last."""
        self.purge_expired()
        with self._lock:
            return list(self._store.keys())

    def __len__(self) -> int:
        self.purge_expired()
        with self._lock:
            return len(self._store)

    def _evict_locked(self) -> None:
        """Evict oldest entries until within ``max_size`` (lock held)."""
        while len(self._store) > self.max_size:
            self._store.popitem(last=False)
