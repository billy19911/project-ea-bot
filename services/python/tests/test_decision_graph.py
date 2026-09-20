# -*- coding: utf-8 -*-
"""Tests for Decision Replay & Audit Graph (Phase 45)."""

from src.review.decision_graph import STAGE_ORDER, DecisionGraphStore, GraphStage


def _store_with_graph() -> DecisionGraphStore:
    store = DecisionGraphStore()
    g = store.start("D182", event_id="E1", strategy_version="v12")
    g.add_node(GraphStage.EVENT, {"type": "tick"})
    g.add_node(GraphStage.MARKET_SNAPSHOT, {"bid": 1.085, "ask": 1.0852})
    g.add_node(GraphStage.AGENTS_ACTIVATED, {"agents": ["trend", "sentiment"]})
    g.add_node(GraphStage.AGENT_OUTPUTS, {"trend": "long"})
    g.add_node(GraphStage.CONFLICTS, {"resolved": False})
    g.add_node(GraphStage.SUPERVISOR_SUMMARY, {"summary": "go long"})
    g.add_node(GraphStage.TRADE_PROPOSAL, {"side": "buy", "lot": 0.1})
    g.add_node(GraphStage.RISK_CHECKS, {"passed": True})
    g.add_node(GraphStage.EXECUTION, {"order_id": 555}, execution_id="X1")
    g.add_node(GraphStage.BROKER_RESULT, {"retcode": 0})
    g.add_node(GraphStage.POSITION, {"ticket": 555}, trade_id="TR1")
    g.add_node(GraphStage.RESULT, {"pnl": 12.5})
    g.add_node(GraphStage.REVIEW, {"grade": "B"})
    return store


def test_replay_returns_all_stages_in_order() -> None:
    store = _store_with_graph()
    replay = store.replay("D182")
    assert replay is not None
    stages = [s["stage"] for s in replay["steps"]]
    assert stages == list(STAGE_ORDER)


def test_correlation_ids_propagate() -> None:
    store = _store_with_graph()
    replay = store.replay("D182")
    assert replay["decision_id"] == "D182"
    assert replay["event_id"] == "E1"
    # execution_id and trade_id promoted from later nodes.
    assert replay["execution_id"] == "X1"
    assert replay["trade_id"] == "TR1"
    assert replay["strategy_version"] == "v12"


def test_replay_uses_stored_snapshot_not_live_market() -> None:
    store = _store_with_graph()
    replay = store.replay("D182")
    snapshot = next(s for s in replay["steps"] if s["stage"] == GraphStage.MARKET_SNAPSHOT)
    # The stored snapshot values are returned verbatim.
    assert snapshot["payload"] == {"bid": 1.085, "ask": 1.0852}


def test_out_of_order_insertion_is_sorted() -> None:
    store = DecisionGraphStore()
    g = store.start("D1")
    # Insert RESULT first, then EVENT — replay must reorder canonically.
    g.add_node(GraphStage.RESULT, {"pnl": 1})
    g.add_node(GraphStage.EVENT, {"type": "tick"})
    g.add_node(GraphStage.MARKET_SNAPSHOT, {"bid": 1})
    replay = store.replay("D1")
    stages = [s["stage"] for s in replay["steps"]]
    assert stages == [GraphStage.EVENT, GraphStage.MARKET_SNAPSHOT, GraphStage.RESULT]


def test_replay_unknown_decision_returns_none() -> None:
    store = DecisionGraphStore()
    assert store.replay("NOPE") is None


def test_bounded_store_evicts_oldest() -> None:
    store = DecisionGraphStore(max_graphs=2)
    for did in ("D1", "D2", "D3"):
        store.start(did)
    assert store.list_ids() == ["D2", "D3"]
    assert store.get("D1") is None
