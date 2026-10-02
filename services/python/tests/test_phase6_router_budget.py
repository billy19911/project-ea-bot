# -*- coding: utf-8 -*-
"""Phase 6 — Model Router & Budget acceptance tests.

* Model routing by complexity/risk/conflict/budget (cheap/medium/strong).
* Hierarchical token budget: Global -> Supervisor -> Department -> Task ->
  Agent -> Model, with concurrent execution unable to overspend.
* LLM committee is only convened on meaningful deterministic events
  (BOS/CHOCH/sweep/OB touch/FVG/volatility/news/spread/position change) —
  never on every candle.
"""

from __future__ import annotations

import threading

import pytest

from llm import budget as budget_mod
from llm import model_router as router_mod


# ── routing tiers ──────────────────────────────────────────────────────
def test_cheap_task_routes_to_cheap_tier() -> None:
    decision = router_mod.route_task(
        task_type="FAST_CLASSIFICATION",
        complexity="LOW",
        risk_tier="T0",
        conflict=False,
        budget_remaining=1000,
    )
    assert decision.tier in ("cheap", "medium")
    assert decision.tier == "cheap"


def test_conflict_escalates_to_strong_tier() -> None:
    decision = router_mod.route_task(
        task_type="CHALLENGE",
        complexity="HIGH",
        risk_tier="T3",
        conflict=True,
        budget_remaining=1000,
    )
    assert decision.tier == "strong"


def test_empty_budget_forces_cheapest_or_refusal() -> None:
    decision = router_mod.route_task(
        task_type="SUPERVISOR_SYNTHESIS",
        complexity="HIGH",
        risk_tier="T2",
        conflict=False,
        budget_remaining=0,
    )
    assert decision.tier in ("cheap", "refused")
    assert decision.allowed is False or decision.tier == "cheap"


# ── hierarchical budget ────────────────────────────────────────────────
def test_hierarchy_global_supervisor_department_task_agent_model() -> None:
    tree = budget_mod.BudgetTree(global_tokens=1000)
    supervisor = tree.child("supervisor", tokens=600)
    department = supervisor.child("market", tokens=400)
    task = department.child("task-1", tokens=200)
    agent = task.child("structure_analyst", tokens=100)
    model = agent.child("model-x", tokens=50)

    assert model.reserve(40) is True
    # The reservation propagates up: every ancestor accounts for it.
    assert tree.used_or_reserved() == 40
    assert supervisor.used_or_reserved() == 40
    # A sibling cannot exceed the remaining global budget.
    other = tree.child("other", tokens=1000)
    assert other.reserve(961) is False
    assert other.reserve(960) is True


def test_concurrent_reservations_cannot_overspend() -> None:
    tree = budget_mod.BudgetTree(global_tokens=100)
    results: list[bool] = []

    def worker() -> None:
        results.append(tree.reserve(30))

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(1 for ok in results if ok) == 3
    assert tree.used_or_reserved() <= 100


def test_provider_reported_usage_is_recorded() -> None:
    tree = budget_mod.BudgetTree(global_tokens=1000)
    node = tree.child("supervisor", tokens=500)
    assert node.reserve(100) is True
    node.commit(actual_tokens=80, actual_cost=0.02)
    snapshot = node.snapshot()
    assert snapshot["used_tokens"] == 80
    assert snapshot["used_cost"] == pytest.approx(0.02)


# ── event-gated LLM wake-ups ───────────────────────────────────────────
def test_meaningful_events_wake_committee() -> None:
    for event in (
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
    ):
        assert budget_mod.should_wake_committee(event) is True


def test_routine_candle_does_not_wake_committee() -> None:
    assert budget_mod.should_wake_committee("M1_CANDLE_CLOSE") is False
    assert budget_mod.should_wake_committee("") is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
