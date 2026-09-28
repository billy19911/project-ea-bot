# -*- coding: utf-8 -*-
"""Entry-context registry — bridges entry-time decision context to the close path.

The learning loops need the agent outputs / news events that framed the ENTRY
decision, but the close path (broker position disappearance) only sees the
position snapshot. This module keeps a small, bounded, thread-safe map
ticket -> entry context written when an entry is executed, and read when the
position closes.

Persistence (R-multiple fix): the registry is backed by
:class:`persistence.entry_context_store.EntryContextStore` (append-only JSONL +
bounded cache) so the context — most importantly the ORIGINAL stop-loss needed
to compute the trade's R-multiple — survives a service restart. When the store
is unavailable, an in-memory fallback keeps the old behaviour.

Memory discipline: only the small scalar fields the close path needs are
persisted (symbol / direction / entry_price / stop_loss / regime / ts); the
bulky agent outputs / news events stay in memory only (best-effort) so the
on-disk record stays tiny.

Fail-safe by design: every function swallows errors; a missing entry simply
returns {}.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Optional

__all__ = [
    "remember_entry_context",
    "get_entry_context",
    "pop_entry_context",
    "clear_entry_contexts",
    "entry_context_size",
    "set_entry_context_store",
]

_MAX_ENTRIES = 500

_lock = threading.Lock()
# In-memory full context (including bulky agent outputs / news events), used as
# the primary read path within a process and as the fallback when no store.
_store: "OrderedDict[str, dict[str, Any]]" = OrderedDict()

# Backing store (append-only JSONL). Wired at startup; optional so the module
# keeps working in isolation (tests, scripts) with the in-memory cache only.
_STORE: Optional[Any] = None
_STORE_LOCK = threading.Lock()
# When True, no default store is auto-created (persistence explicitly off —
# used by tests to keep the registry in-memory only).
_PERSISTENCE_DISABLED = False


def set_entry_context_store(store: Optional[Any], *, disabled: bool = False) -> None:
    """Wire (or clear) the persistent backing store.

    The store must expose ``remember(ticket, context)`` / ``get(ticket)`` /
    ``pop(ticket)``.

    Args:
        store: The store instance, or ``None``.
        disabled: When True, persistence is turned OFF entirely — no default
            store is auto-created either (the registry becomes in-memory only).
            Passing ``None`` with ``disabled=False`` re-enables lazy default
            creation.
    """
    global _STORE, _PERSISTENCE_DISABLED
    with _STORE_LOCK:
        _STORE = store
        _PERSISTENCE_DISABLED = bool(disabled)


def _get_store() -> Optional[Any]:
    """Return the wired store, or the process-wide default (lazy)."""
    global _STORE
    if _STORE is not None:
        return _STORE
    with _STORE_LOCK:
        if _PERSISTENCE_DISABLED:
            return None
        if _STORE is None:
            try:
                from persistence.entry_context_store import EntryContextStore

                _STORE = EntryContextStore()
            except Exception:  # noqa: BLE001 - store is optional
                _STORE = None
        return _STORE


def _key(ticket: Any) -> str:
    return str(ticket) if ticket is not None else ""


def remember_entry_context(ticket: Any, context: dict[str, Any]) -> None:
    """Register the context for an entry by its broker ticket.

    Args:
        ticket: Broker position ticket number (str, int, or None).
        context: Entry-time decision context containing:
            - symbol (str): trading symbol.
            - direction (str): BUY/SELL/WAIT.
            - agent_outputs (dict): per-agent outputs with confidence scores.
            - news_events (list): news events framing the trade.
            - regime (str): market regime at entry.
            - entry_price (float): entry price level.
            - stop_loss (float): the ORIGINAL stop-loss price of this order,
              used by the close path to compute the trade's R-multiple.
            - ts (float): Unix timestamp of entry.

    Fail-safe: errors are swallowed silently.
    """
    ticket_str = _key(ticket)
    if not ticket_str:
        return
    with _lock:
        _store[ticket_str] = dict(context)
        # Trim oldest entries beyond capacity
        while len(_store) > _MAX_ENTRIES:
            _store.popitem(last=False)
    # Persist the small scalar subset so the context (esp. the original SL)
    # survives a restart. Fail-safe: a store error never breaks the entry.
    try:
        store = _get_store()
        if store is not None:
            store.remember(ticket, context)
    except Exception:  # noqa: BLE001 - persistence is best-effort
        pass


def get_entry_context(ticket: Any) -> dict[str, Any]:
    """Look up entry context by ticket. Returns a shallow copy."""
    ticket_str = _key(ticket)
    with _lock:
        raw = _store.get(ticket_str)
        if raw is not None:
            return dict(raw)
    # In-memory miss (e.g. after a restart) — fall back to the persisted store.
    try:
        store = _get_store()
        if store is not None:
            return store.get(ticket)
    except Exception:  # noqa: BLE001 - store is best-effort
        pass
    return {}


def pop_entry_context(ticket: Any) -> dict[str, Any]:
    """Look up and consume entry context by ticket. Returns a shallow copy."""
    ticket_str = _key(ticket)
    with _lock:
        raw = _store.pop(ticket_str, None)
    if raw is not None:
        out = dict(raw)
        try:
            store = _get_store()
            if store is not None:
                store.pop(ticket)
        except Exception:  # noqa: BLE001
            pass
        return out
    try:
        store = _get_store()
        if store is not None:
            return store.pop(ticket)
    except Exception:  # noqa: BLE001
        pass
    return {}


def clear_entry_contexts() -> None:
    """Clear all stored contexts (for testing / reset)."""
    with _lock:
        _store.clear()
    try:
        store = _get_store()
        if store is not None:
            store.clear()
    except Exception:  # noqa: BLE001
        pass


def entry_context_size() -> int:
    """Return the number of stored contexts."""
    with _lock:
        return len(_store)
