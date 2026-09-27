# -*- coding: utf-8 -*-
"""Entry-context registry — bridges entry-time decision context to the close path.

The learning loops need the agent outputs / news events that framed the ENTRY
decision, but the close path (broker position disappearance) only sees the
position snapshot. This module keeps a small, bounded, thread-safe in-memory
map ticket -> entry context written when an entry is executed, and read when
the position closes.

Fail-safe by design: every function swallows errors; a missing entry simply
returns {}.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any

__all__ = [
    "remember_entry_context",
    "get_entry_context",
    "pop_entry_context",
    "clear_entry_contexts",
    "entry_context_size",
]

_MAX_ENTRIES = 500

_lock = threading.Lock()
_store: "OrderedDict[str, dict[str, Any]]" = OrderedDict()


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


def get_entry_context(ticket: Any) -> dict[str, Any]:
    """Look up entry context by ticket. Returns a shallow copy."""
    ticket_str = _key(ticket)
    with _lock:
        raw = _store.get(ticket_str)
        return dict(raw) if raw else {}


def pop_entry_context(ticket: Any) -> dict[str, Any]:
    """Look up and consume entry context by ticket. Returns a shallow copy."""
    ticket_str = _key(ticket)
    with _lock:
        raw = _store.pop(ticket_str, None)
        return dict(raw) if raw else {}


def clear_entry_contexts() -> None:
    """Clear all stored contexts (for testing / reset)."""
    with _lock:
        _store.clear()


def entry_context_size() -> int:
    """Return the number of stored contexts."""
    with _lock:
        return len(_store)
