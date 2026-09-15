# -*- coding: utf-8 -*-
"""Context Builder (§16) — filtered, bounded agent context snapshots.

The :class:`ContextBuilder` assembles the *minimal relevant* slice of system
state that an agent needs for one decision: a recent price window, the events
relevant to the current symbol, open positions, account state, relevant memory
hits, and strategy state.

Design guarantees:

* **Filtered** — only data relevant to the event's symbol passes through; the
  caller can supply per-section predicates via ``filters``.
* **Bounded** — every list is truncated to ``max_items`` / per-section caps so
  the builder never dumps the entire world into the context.
* **Provenanced** — each section carries ``source`` and ``count`` metadata and
  the snapshot carries a ``generated_at`` timestamp.
* **Deterministic & pure** — data providers are injected; identical inputs
  always produce identical output (a fixed clock can be injected for tests).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

__all__ = ["ContextBuilder"]

# Default per-section cap.
_DEFAULT_MAX_ITEMS = 20

FilterFn = Callable[[Any], bool]


class ContextBuilder:
    """Build filtered, size-bounded context snapshots for agents.

    Args:
        max_items: Global cap applied to every list section.
        max_price_items: Cap for the recent price window.
        clock: Callable returning an ISO timestamp (defaults to UTC now).
    """

    def __init__(
        self,
        max_items: int = _DEFAULT_MAX_ITEMS,
        max_price_items: Optional[int] = None,
        clock: Optional[Callable[[], str]] = None,
    ) -> None:
        if max_items <= 0:
            raise ValueError("max_items must be positive")
        if max_price_items is not None and max_price_items <= 0:
            raise ValueError("max_price_items must be positive")
        self.max_items = max_items
        self.max_price_items = max_price_items if max_price_items is not None else max_items
        self._clock = clock or (lambda: datetime.now(timezone.utc).isoformat())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(
        self,
        event: Optional[dict[str, Any]] = None,
        *,
        price_window: Optional[list[dict[str, Any]]] = None,
        events: Optional[list[dict[str, Any]]] = None,
        positions: Optional[list[dict[str, Any]]] = None,
        account_state: Optional[dict[str, Any]] = None,
        memory_hits: Optional[list[dict[str, Any]]] = None,
        strategy_state: Optional[dict[str, Any]] = None,
        max_items: Optional[int] = None,
        max_price_items: Optional[int] = None,
        filters: Optional[dict[str, FilterFn]] = None,
    ) -> dict[str, Any]:
        """Build a filtered, bounded context snapshot.

        All inputs are optional; empty inputs produce a minimal-but-valid
        context. ``filters`` maps a section name (``"events"``,
        ``"positions"``, ``"memory_hits"``, ``"price_window"``) to a predicate
        applied before truncation.
        """
        event = event or {}
        filters = filters or {}
        cap = max_items if max_items is not None else self.max_items
        price_cap = max_price_items if max_price_items is not None else self.max_price_items

        symbol = event.get("symbol")

        price = self._select(price_window or [], filters.get("price_window"))
        price = self._most_recent(price, price_cap)

        relevant_events = self._select(events or [], filters.get("events"))
        relevant_events = self._filter_by_symbol(relevant_events, symbol)
        relevant_events = relevant_events[:cap]

        open_positions = self._select(positions or [], filters.get("positions"))
        open_positions = self._filter_by_symbol(open_positions, symbol)
        open_positions = open_positions[:cap]

        hits = self._select(memory_hits or [], filters.get("memory_hits"))
        hits = self._filter_by_symbol(hits, symbol)
        hits = self._sort_by_score(hits)[:cap]

        account = dict(account_state) if account_state else {}
        strategy = dict(strategy_state) if strategy_state else {}

        provenance = {
            "generated_at": self._clock(),
            "symbol": symbol,
            "sections": {
                "price_window": {"source": "market_data", "count": len(price)},
                "relevant_events": {"source": "event_engine", "count": len(relevant_events)},
                "open_positions": {"source": "account", "count": len(open_positions)},
                "account_state": {"source": "account", "count": len(account)},
                "memory_hits": {"source": "memory", "count": len(hits)},
                "strategy_state": {"source": "strategy", "count": len(strategy)},
            },
        }

        return {
            "event": dict(event),
            "price_window": price,
            "relevant_events": relevant_events,
            "open_positions": open_positions,
            "account_state": account,
            "memory_hits": hits,
            "strategy_state": strategy,
            "provenance": provenance,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _select(items: list, predicate: Optional[FilterFn]) -> list:
        """Apply an optional caller-supplied predicate (deterministic order)."""
        if predicate is None:
            return list(items)
        return [item for item in items if predicate(item)]

    @staticmethod
    def _filter_by_symbol(
        items: list[dict[str, Any]], symbol: Optional[str]
    ) -> list[dict[str, Any]]:
        """Keep items whose ``symbol`` matches (or that carry no symbol)."""
        if not symbol:
            return list(items)
        kept = []
        for item in items:
            item_symbol = item.get("symbol") if isinstance(item, dict) else None
            if item_symbol is None or item_symbol == symbol:
                kept.append(item)
        return kept

    @staticmethod
    def _most_recent(items: list[dict[str, Any]], cap: int) -> list[dict[str, Any]]:
        """Keep the last ``cap`` items (most recent), preserving order."""
        if len(items) <= cap:
            return list(items)
        return list(items[-cap:])

    @staticmethod
    def _sort_by_score(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Sort by ``score`` descending; stable for equal/missing scores."""
        return sorted(
            items,
            key=lambda it: float(it.get("score", 0.0)) if isinstance(it, dict) else 0.0,
            reverse=True,
        )
