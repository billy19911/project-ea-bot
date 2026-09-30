# -*- coding: utf-8 -*-
"""Phase 7 trace assemblers — decision/trade trace + non-trade explanation.
Assembles from EXISTING stores only (decision graph store, order ledger,
review stores, canonical learning store). Read-only; never mutates state.
"""
from __future__ import annotations

from typing import Any

from .secrets import UNKNOWN, mask_secrets

__all__ = [
    "decision_trace",
    "trade_trace",
    "explain_non_trade",
    "search_records",
]


def _graph_store() -> Any:
    try:
        from review.decision_graph import DecisionGraphStore

        return DecisionGraphStore()
    except Exception:  # noqa: BLE001
        return None


def _order_store() -> Any:
    try:
        from execution.state_machine import get_store

        return get_store()
    except Exception:  # noqa: BLE001
        return None


def decision_trace(
    decision_id: str = "", *, setup_id: str = "", event_id: str = ""
) -> dict[str, Any]:
    """Assemble a full lifecycle trace for a decision/setup/event (§5).
    Nodes: EVENT → EVIDENCE → SETUP → DEBATE → TRIGGER → ENTRY_ASSESSMENT →
    DECISION → RISK → EXECUTION → POSITION → RECONCILIATION → REVIEW →
    RESEARCH. Missing nodes are UNKNOWN (never fabricated).
    """
    nodes: list[dict[str, Any]] = []
    key = decision_id or setup_id or event_id
    graph = _graph_store()
    if graph is not None and key:
        try:
            g = graph.get(key) if hasattr(graph, "get") else None
            if g is not None:
                nodes.append(
                    {
                        "node": "DECISION_GRAPH",
                        "payload": (g.to_dict() if hasattr(g, "to_dict") else dict(g)),
                    }
                )
        except Exception:  # noqa: BLE001
            pass
    store = _order_store()
    if store is not None and key:
        try:
            rec = store.get_order(key)
            if rec:
                nodes.append({"node": "EXECUTION", "payload": dict(rec)})
        except Exception:  # noqa: BLE001
            pass
    try:
        from learning.review_store import CanonicalStore

        canon = CanonicalStore()
        for kind in ("DecisionReview", "TradeReview", "CounterfactualReview"):
            for row in canon.query(kind):
                ids = {
                    str(row.get("review_id", "")),
                    str(row.get("event_id", "")),
                    str(row.get("trade_id", "")),
                    str(row.get("setup_id", "")),
                }
                if key and key in ids:
                    nodes.append({"node": kind.upper(), "payload": dict(row)})
    except Exception:  # noqa: BLE001
        pass
    return mask_secrets(
        {
            "key": key or UNKNOWN,
            "nodes": nodes,
            "complete": len(nodes) > 0,
        }
    )


def trade_trace(trade_id: str = "") -> dict[str, Any]:
    """Trade-centric trace: execution → position → review → research (§5)."""
    base = decision_trace(decision_id=trade_id)
    base["trade_id"] = trade_id or UNKNOWN
    return base


def explain_non_trade(*, setup_id: str = "", event_id: str = "") -> dict[str, Any]:
    """Explain WAIT/REJECT/EXPIRED/INVALIDATED with blocking/missing (§6)."""
    key = setup_id or event_id
    explanation: dict[str, Any] = {
        "key": key or UNKNOWN,
        "state": UNKNOWN,
        "blocking_conditions": [],
        "missing_conditions": [],
        "reason_codes": [],
        "evidence": [],
        "risk_result": UNKNOWN,
        "expiry": UNKNOWN,
        "invalidation": UNKNOWN,
    }
    try:
        from learning.review_store import CanonicalStore

        canon = CanonicalStore()
        for row in canon.query("DecisionReview"):
            ids = {
                str(row.get("review_id", "")),
                str(row.get("event_id", "")),
                str(row.get("setup_id", "")),
            }
            if key and key in ids:
                explanation.update(
                    {
                        "state": row.get("decision_state", UNKNOWN),
                        "blocking_conditions": row.get("blocking_conditions", []),
                        "missing_conditions": row.get("missing_conditions", []),
                        "reason_codes": row.get("reason_codes", []),
                        "evidence": row.get("evidence_refs", []),
                        "risk_result": row.get("risk_decision", UNKNOWN),
                    }
                )
                break
    except Exception:  # noqa: BLE001
        pass
    return mask_secrets(explanation)


def search_records(*, kind: str = "", query: str = "", limit: int = 25) -> dict[str, Any]:
    """Deterministic search over canonical records (§17). No LLM involved."""
    q = str(query or "").lower()
    out: list[dict[str, Any]] = []
    try:
        from learning.review_store import CanonicalStore

        canon = CanonicalStore()
        rows = canon.query(kind or None)
        for row in rows:
            blob = str(row).lower()
            if not q or q in blob:
                out.append(row)
            if len(out) >= max(1, int(limit)):
                break
    except Exception:  # noqa: BLE001
        pass
    return mask_secrets({"results": out, "count": len(out), "query": query})
