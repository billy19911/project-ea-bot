# -*- coding: utf-8 -*-
"""Decision Replay & Audit Graph — PRD_V2 §45.

Every trade decision is recorded as a *graph* of ordered stages so it can be
explained operationally **without persisting raw chain-of-thought**. Replay uses
the *stored snapshots*, never the current market conditions (PRD §45 acceptance
criteria).

Decision graph stages (PRD §45)::

    EVENT → MARKET_SNAPSHOT → AGENTS_ACTIVATED → AGENT_OUTPUTS → CONFLICTS
          → SUPERVISOR_SUMMARY → TRADE_PROPOSAL → RISK_CHECKS → EXECUTION
          → BROKER_RESULT → POSITION → RESULT → REVIEW

Every node carries the shared correlation ids: ``decision_id``, ``event_id``,
``trade_id``, ``execution_id``, ``strategy_version``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

__all__ = [
    "GraphStage",
    "DecisionNode",
    "DecisionGraph",
    "DecisionGraphStore",
    "STAGE_ORDER",
]

# Canonical stage order (PRD §45).
STAGE_ORDER: tuple[str, ...] = (
    "EVENT",
    "MARKET_SNAPSHOT",
    "AGENTS_ACTIVATED",
    "AGENT_OUTPUTS",
    "CONFLICTS",
    "SUPERVISOR_SUMMARY",
    "TRADE_PROPOSAL",
    "RISK_CHECKS",
    "EXECUTION",
    "BROKER_RESULT",
    "POSITION",
    "RESULT",
    "REVIEW",
)


class GraphStage:
    """Namespace of the canonical stage names (avoids magic strings)."""

    EVENT = "EVENT"
    MARKET_SNAPSHOT = "MARKET_SNAPSHOT"
    AGENTS_ACTIVATED = "AGENTS_ACTIVATED"
    AGENT_OUTPUTS = "AGENT_OUTPUTS"
    CONFLICTS = "CONFLICTS"
    SUPERVISOR_SUMMARY = "SUPERVISOR_SUMMARY"
    TRADE_PROPOSAL = "TRADE_PROPOSAL"
    RISK_CHECKS = "RISK_CHECKS"
    EXECUTION = "EXECUTION"
    BROKER_RESULT = "BROKER_RESULT"
    POSITION = "POSITION"
    RESULT = "RESULT"
    REVIEW = "REVIEW"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class DecisionNode:
    """A single stage snapshot in a decision graph (PRD §45)."""

    stage: str
    payload: dict[str, Any]
    timestamp: str = field(default_factory=_now)
    decision_id: str = ""
    event_id: str = ""
    trade_id: str = ""
    execution_id: str = ""
    strategy_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "payload": dict(self.payload),
            "timestamp": self.timestamp,
            "decision_id": self.decision_id,
            "event_id": self.event_id,
            "trade_id": self.trade_id,
            "execution_id": self.execution_id,
            "strategy_version": self.strategy_version,
        }


@dataclass
class DecisionGraph:
    """Ordered set of nodes for one decision, replayable from snapshots."""

    decision_id: str
    event_id: str = ""
    trade_id: str = ""
    execution_id: str = ""
    strategy_version: str = ""
    nodes: list[DecisionNode] = field(default_factory=list)
    created_at: str = field(default_factory=_now)

    def add_node(
        self,
        stage: str,
        payload: dict[str, Any],
        event_id: Optional[str] = None,
        trade_id: Optional[str] = None,
        execution_id: Optional[str] = None,
        strategy_version: Optional[str] = None,
    ) -> DecisionNode:
        """Append a stage snapshot node, inheriting correlation ids."""
        node = DecisionNode(
            stage=stage,
            payload=dict(payload),
            decision_id=self.decision_id,
            event_id=event_id or self.event_id,
            trade_id=trade_id or self.trade_id,
            execution_id=execution_id or self.execution_id,
            strategy_version=strategy_version or self.strategy_version,
        )
        self.nodes.append(node)
        # Promote ids onto the graph for later nodes.
        if node.event_id and not self.event_id:
            self.event_id = node.event_id
        if node.trade_id and not self.trade_id:
            self.trade_id = node.trade_id
        if node.execution_id and not self.execution_id:
            self.execution_id = node.execution_id
        if node.strategy_version and not self.strategy_version:
            self.strategy_version = node.strategy_version
        return node

    def ordered_nodes(self) -> list[DecisionNode]:
        """Return nodes in canonical stage order (stable within a stage)."""
        index = {stage: i for i, stage in enumerate(STAGE_ORDER)}
        return sorted(
            self.nodes,
            key=lambda n: (index.get(n.stage, len(STAGE_ORDER)), self.nodes.index(n)),
        )

    def replay(self) -> dict[str, Any]:
        """Return the full ordered replay of the decision from stored snapshots."""
        return {
            "decision_id": self.decision_id,
            "event_id": self.event_id,
            "trade_id": self.trade_id,
            "execution_id": self.execution_id,
            "strategy_version": self.strategy_version,
            "created_at": self.created_at,
            "steps": [node.to_dict() for node in self.ordered_nodes()],
        }

    def to_dict(self) -> dict[str, Any]:
        return self.replay()


class DecisionGraphStore:
    """In-memory bounded store of decision graphs (PRD §45)."""

    def __init__(self, max_graphs: int = 1000) -> None:
        self.max_graphs = max_graphs
        self._graphs: dict[str, DecisionGraph] = {}
        self._order: list[str] = []

    def start(
        self,
        decision_id: str,
        event_id: str = "",
        strategy_version: str = "",
    ) -> DecisionGraph:
        """Create (or replace) a decision graph for *decision_id*."""
        graph = DecisionGraph(
            decision_id=decision_id,
            event_id=event_id,
            strategy_version=strategy_version,
        )
        if decision_id not in self._graphs:
            self._order.append(decision_id)
        self._graphs[decision_id] = graph
        self._trim()
        return graph

    def get(self, decision_id: str) -> Optional[DecisionGraph]:
        return self._graphs.get(decision_id)

    def replay(self, decision_id: str) -> Optional[dict[str, Any]]:
        """Replay a stored decision using its snapshots (never live market)."""
        graph = self._graphs.get(decision_id)
        return graph.replay() if graph else None

    def list_ids(self) -> list[str]:
        return list(self._order)

    def _trim(self) -> None:
        while len(self._order) > self.max_graphs:
            oldest = self._order.pop(0)
            self._graphs.pop(oldest, None)
