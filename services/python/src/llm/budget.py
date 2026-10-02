# -*- coding: utf-8 -*-
"""Phase 6 — hierarchical token budget + event-gated committee wake-ups.

* ``BudgetTree``: Global -> Supervisor -> Department -> Task -> Agent -> Model.
  Every reservation propagates to ALL ancestors under one lock, so concurrent
  execution can never overspend the shared budget. Provider-reported actual
  usage is recorded via ``commit()`` (refunding the unused remainder).
* ``should_wake_committee``: the committee (LLM work) is convened ONLY on
  meaningful deterministic events — never on every candle.

Fail-safe: budget exhaustion refuses (never overspends); unknown events do
not wake the committee.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Optional

__all__ = [
    "BudgetTree",
    "BudgetNode",
    "should_wake_committee",
    "COMMITTEE_WAKE_EVENTS",
]

#: Deterministic events that may convene the committee (Phase 6 §"wake LLMs").
COMMITTEE_WAKE_EVENTS = frozenset(
    {
        "BOS",
        "CHOCH",
        "LIQUIDITY_SWEEP",
        "OB_TOUCH",
        "FVG_INTERACTION",
        "VOLATILITY_CHANGE",
        "NEWS_PROXIMITY",
        "SPREAD_ANOMALY",
        "INVALIDATION",
        "POSITION_STATE_CHANGE",
    }
)


def should_wake_committee(event_type: str) -> bool:
    """True only for meaningful deterministic events (never routine candles)."""
    return str(event_type or "").strip().upper() in COMMITTEE_WAKE_EVENTS


@dataclass
class BudgetNode:
    """One node in the hierarchical budget tree."""

    name: str
    max_tokens: Optional[int]
    _tree: "BudgetTree" = field(repr=False)
    _parent: Optional["BudgetNode"] = field(default=None, repr=False)
    _children: list["BudgetNode"] = field(default_factory=list, repr=False)
    used_tokens: int = 0
    used_cost: float = 0.0

    def child(self, name: str, tokens: Optional[int] = None) -> "BudgetNode":
        """Create a child scope under this node (shares the tree lock)."""
        node = BudgetNode(name=name, max_tokens=tokens, _tree=self._tree, _parent=self)
        with self._tree._lock:
            self._children.append(node)
        return node

    def _chain(self) -> list["BudgetNode"]:
        node: Optional[BudgetNode] = self
        chain: list[BudgetNode] = []
        while node is not None:
            chain.append(node)
            node = node._parent
        return chain

    def reserve(self, tokens: int) -> bool:
        """Reserve tokens against this node AND every ancestor (atomic)."""
        tokens = int(tokens)
        if tokens <= 0:
            return True
        with self._tree._lock:
            for node in self._chain():
                if node.max_tokens is not None and node._reserved + tokens > node.max_tokens:
                    return False
            for node in self._chain():
                node._reserved += tokens
            return True

    def commit(self, actual_tokens: int, actual_cost: float = 0.0) -> None:
        """Record provider-reported actual usage; refund the unused remainder."""
        actual_tokens = max(0, int(actual_tokens))
        with self._tree._lock:
            for node in self._chain():
                node._reserved = max(0, node._reserved - actual_tokens)
                node.used_tokens += actual_tokens
                node.used_cost += float(actual_cost or 0.0)

    def used_or_reserved(self) -> int:
        with self._tree._lock:
            return self.used_tokens + self._reserved

    def snapshot(self) -> dict[str, Any]:
        with self._tree._lock:
            return {
                "name": self.name,
                "max_tokens": self.max_tokens,
                "reserved_tokens": self._reserved,
                "used_tokens": self.used_tokens,
                "used_cost": round(self.used_cost, 6),
            }

    _reserved: int = 0


class BudgetTree:
    """Root of the hierarchical budget (the Global scope)."""

    def __init__(self, global_tokens: Optional[int] = None) -> None:
        self._lock = threading.RLock()
        self.root = BudgetNode(name="global", max_tokens=global_tokens, _tree=self)

    def child(self, name: str, tokens: Optional[int] = None) -> BudgetNode:
        return self.root.child(name, tokens)

    def reserve(self, tokens: int) -> bool:
        return self.root.reserve(tokens)

    def used_or_reserved(self) -> int:
        return self.root.used_or_reserved()

    def snapshot(self) -> dict[str, Any]:
        return self.root.snapshot()
