# -*- coding: utf-8 -*-
"""Tests for SupervisorAgent Phase 7 enhancements.

Covers: priority sorting, context filtering, concurrency limits,
token-budget tracking, routing policies, and backward compatibility.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from agents.base import AgentPriority, AgentRegistry, BaseAgent
from agents.supervisor import SupervisorAgent

# ---------------------------------------------------------------------------
# Helper agents with controllable priority / can_handle
# ---------------------------------------------------------------------------


class StubAgent(BaseAgent):
    """Agent that records calls; allows injecting priority and filter logic."""

    def __init__(
        self,
        name: str,
        priority: AgentPriority = AgentPriority.NORMAL,
        *,
        allowed_events: list[str] | None = None,
        delay: float = 0.0,
    ) -> None:
        super().__init__(
            name=name,
            agent_type="stub",
            description=f"Stub agent {name}",
            priority=priority,
        )
        self.allowed_events = allowed_events
        self.delay = delay
        self.call_count = 0
        self._lock = threading.Lock()

    def can_handle(self, event_type: str, context: dict[str, Any]) -> bool:
        if self.allowed_events is not None:
            return event_type in self.allowed_events
        return True

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.call_count += 1
        if self.delay > 0:
            time.sleep(self.delay)
        return {
            "agent": self.name,
            "signal": "BULLISH",
            "confidence": 0.8,
            "reasons": [f"{self.name} analysed"],
        }


@pytest.fixture(autouse=True)
def _reset_registry():
    """Ensure registry is clean before/after each test."""
    AgentRegistry.reset()
    yield
    AgentRegistry.reset()


def _make_registry(*agents: BaseAgent) -> AgentRegistry:
    """Build and populate a fresh AgentRegistry."""
    reg = AgentRegistry()
    for agent in agents:
        reg.register(agent)
    return reg


# ===================================================================
# 1. Priority sorting
# ===================================================================


class TestPrioritySorting:
    def test_sort_critical_first(self):
        low = StubAgent("low", AgentPriority.LOW)
        high = StubAgent("high", AgentPriority.HIGH)
        crit = StubAgent("crit", AgentPriority.CRITICAL)
        norm = StubAgent("norm", AgentPriority.NORMAL)
        reg = _make_registry(low, high, crit, norm)

        sup = SupervisorAgent(routing_policy="all_match")
        sup._registry_cache = reg

        sorted_names = sup.sort_agents_by_priority(["low", "norm", "high", "crit"])
        assert sorted_names == ["crit", "high", "norm", "low"]

    def test_sort_stable_for_equal(self):
        a = StubAgent("a", AgentPriority.NORMAL)
        b = StubAgent("b", AgentPriority.NORMAL)
        reg = _make_registry(a, b)

        sup = SupervisorAgent()
        sup._registry_cache = reg

        sorted_names = sup.sort_agents_by_priority(["a", "b"])
        # Same priority → original order preserved (stable sort).
        assert sorted_names == ["a", "b"]

    def test_sort_unknown_agent_defaults_normal(self):
        high = StubAgent("high", AgentPriority.HIGH)
        reg = _make_registry(high)

        sup = SupervisorAgent()
        sup._registry_cache = reg

        sorted_names = sup.sort_agents_by_priority(["unknown", "high"])
        # "unknown" gets NORMAL=50, "high" gets 75 → high first.
        assert sorted_names == ["high", "unknown"]


# ===================================================================
# 2. Context filtering
# ===================================================================


class TestContextFiltering:
    def test_filter_by_event_type(self):
        trend_only = StubAgent(
            "trend_only",
            allowed_events=["TREND_BULLISH"],
        )
        all_events = StubAgent("all_events")
        reg = _make_registry(trend_only, all_events)

        sup = SupervisorAgent()
        sup._registry_cache = reg

        kept = sup.filter_agents(
            ["trend_only", "all_events"],
            {"event_type": "RSI_OVERBOUGHT"},
        )
        assert "trend_only" not in kept
        assert "all_events" in kept

    def test_filter_keeps_unregistered_agents(self):
        sup = SupervisorAgent()
        sup._registry_cache = _make_registry()

        kept = sup.filter_agents(
            ["ghost_agent"],
            {"event_type": "TREND_BULLISH"},
        )
        # Unknown agents pass through (the analyze method reports them).
        assert kept == ["ghost_agent"]


# ===================================================================
# 3. Concurrency limits
# ===================================================================


class TestConcurrency:
    def test_max_concurrency_respected(self):
        """Verify that at most max_concurrency agents run in parallel."""
        peak_lock = threading.Lock()
        peak = [0]
        current = [0]

        class TrackedAgent(BaseAgent):
            def __init__(self, name: str) -> None:
                super().__init__(
                    name=name,
                    agent_type="tracked",
                    priority=AgentPriority.NORMAL,
                )

            def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
                with peak_lock:
                    current[0] += 1
                    if current[0] > peak[0]:
                        peak[0] = current[0]
                time.sleep(0.05)
                with peak_lock:
                    current[0] -= 1
                return {
                    "agent": self.name,
                    "signal": "NEUTRAL",
                    "confidence": 0.0,
                    "reasons": [],
                }

        agents = [TrackedAgent(f"t{i}") for i in range(6)]
        reg = _make_registry(*agents)

        sup = SupervisorAgent(
            max_concurrency=2,
            token_budget=50000,
            routing_policy="all_match",
        )

        ctx = {
            "event_type": "TREND_BULLISH",
            "registry": reg,
            "agents": agents,
        }
        result = sup.analyze(ctx)
        # All 6 agents should have been invoked.
        assert len(result["agent_results"]) == 6
        # Peak concurrency should not exceed max_concurrency.
        assert peak[0] <= 2


# ===================================================================
# 4. Token budget
# ===================================================================


class TestTokenBudget:
    def test_budget_depleted_skips_agents(self):
        a1 = StubAgent("a1", AgentPriority.HIGH)
        a2 = StubAgent("a2", AgentPriority.NORMAL)
        a3 = StubAgent("a3", AgentPriority.LOW)
        reg = _make_registry(a1, a2, a3)

        sup = SupervisorAgent(
            token_budget=350,
            routing_policy="all_match",
            max_concurrency=1,
        )

        ctx = {
            "event_type": "TREND_BULLISH",
            "registry": reg,
            "agents": [a1, a2, a3],
            "token_estimates": {"a1": 200, "a2": 200, "a3": 200},
        }
        result = sup.analyze(ctx)
        # Only a1 fits (200 ≤ 350); a2 would push to 400 → skipped.
        assert "a1" in result["agent_results"]
        assert "a2" not in result["agent_results"]
        assert "a3" not in result["agent_results"]
        assert "a2" in result["skipped_agents"]
        assert result["token_used"] == 200

    def test_check_token_budget_basic(self):
        sup = SupervisorAgent(token_budget=500)
        assert sup.check_token_budget("x", 300) is True
        assert sup.token_used == 300
        assert sup.check_token_budget("y", 300) is False
        assert sup.token_used == 300  # not consumed

    def test_reset_token_budget(self):
        sup = SupervisorAgent(token_budget=500)
        sup.token_used = 400
        sup.reset_token_budget()
        assert sup.token_used == 0


# ===================================================================
# 5. Routing policies
# ===================================================================


class TestRoutingPolicies:
    def test_first_match_returns_one(self):
        a = StubAgent("a", AgentPriority.NORMAL)
        b = StubAgent("b", AgentPriority.HIGH)
        reg = _make_registry(a, b)

        sup = SupervisorAgent(
            routing_policy="first_match",
            max_concurrency=1,
        )

        ctx = {
            "event_type": "TREND_BULLISH",
            "registry": reg,
            "agents": [a, b],
        }
        result = sup.analyze(ctx)
        # After priority sort b comes first; first_match → only b.
        assert len(result["agent_results"]) == 1
        assert "b" in result["agent_results"]

    def test_all_match_returns_all(self):
        a = StubAgent("a", AgentPriority.NORMAL)
        b = StubAgent("b", AgentPriority.HIGH)
        reg = _make_registry(a, b)

        sup = SupervisorAgent(
            routing_policy="all_match",
            max_concurrency=1,
        )

        ctx = {
            "event_type": "TREND_BULLISH",
            "registry": reg,
            "agents": [a, b],
        }
        result = sup.analyze(ctx)
        assert len(result["agent_results"]) == 2

    def test_priority_based_sorts_then_runs_all(self):
        low = StubAgent("low", AgentPriority.LOW)
        crit = StubAgent("crit", AgentPriority.CRITICAL)
        reg = _make_registry(low, crit)

        sup = SupervisorAgent(
            routing_policy="priority_based",
            max_concurrency=1,
        )

        ctx = {
            "event_type": "TREND_BULLISH",
            "registry": reg,
            "agents": [low, crit],
        }
        result = sup.analyze(ctx)
        assert len(result["agent_results"]) == 2
        # Summary order should reflect priority (crit first).
        assert result["summary"].startswith("crit:")


# ===================================================================
# 6. Backward compatibility
# ===================================================================


class TestBackwardCompatibility:
    def test_default_params(self):
        sup = SupervisorAgent()
        assert sup.max_concurrency == 3
        assert sup.token_budget == 8000
        assert sup.routing_policy == "first_match"
        assert sup.token_used == 0

    def test_match_routes_unchanged(self):
        sup = SupervisorAgent()
        names = sup.match_routes("TREND_BULLISH")
        assert "technical_analyst" in names

    def test_analyze_without_agents_or_registry(self):
        sup = SupervisorAgent(routing_policy="first_match")
        result = sup.analyze({"event_type": "TREND_BULLISH"})
        assert result["event_type"] == "TREND_BULLISH"
        assert "agent_results" in result
        assert "skipped_agents" in result

    def test_analyze_with_registry(self):
        """Original use-case: pass registry in context."""
        from agents.base import TechnicalAnalystAgent

        ta = TechnicalAnalystAgent()
        reg = _make_registry(ta)
        sup = SupervisorAgent(routing_policy="first_match")

        result = sup.analyze(
            {
                "event_type": "TREND_BULLISH",
                "registry": reg,
                "detected_events": [],
            }
        )
        assert result["event_type"] == "TREND_BULLISH"
        assert "technical_analyst" in result["agent_results"]

    def test_add_remove_route_still_works(self):
        sup = SupervisorAgent()
        sup.add_route("CUSTOM_", ["my_agent"])
        assert "my_agent" in sup.match_routes("CUSTOM_EVENT")
        assert sup.remove_route("CUSTOM_") is True
        assert sup.remove_route("NONEXISTENT") is False


# ===================================================================
# Synthesis wiring — the Supervisor must emit a pipeline-ready proposal
# so the Risk Gate is actually reached (regression for the bug where every
# cycle was NO_TRADE because no proposal was ever produced).
# ===================================================================


class _SignalAgent(BaseAgent):
    """Agent that always returns a fixed signal/confidence."""

    def __init__(self, name: str, signal: str, confidence: float) -> None:
        super().__init__(
            name=name,
            agent_type="analyst",
            description=f"signal agent {name}",
            priority=AgentPriority.NORMAL,
        )
        self._signal = signal
        self._confidence = confidence

    def can_handle(self, event_type: str, context: dict[str, Any]) -> bool:
        return True

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "agent": self.name,
            "signal": self._signal,
            "confidence": self._confidence,
            "reasons": ["stub"],
        }


class TestSupervisorSynthesisWiring:
    def _context(self, *agents: BaseAgent) -> dict[str, Any]:
        return {
            "event_type": "BREAKOUT",
            "symbol": "EURUSD",
            "agents": list(agents),
            "event": {"event_id": "e1", "event_type": "BREAKOUT", "symbol": "EURUSD"},
            "close": 1.1000,
            "atr": 0.0020,
        }

    def test_bullish_consensus_emits_proposal(self):
        sup = SupervisorAgent()
        ctx = self._context(
            _SignalAgent("structure_analyst", "BULLISH", 0.8),
            _SignalAgent("momentum_analyst", "BUY", 0.7),
        )
        result = sup.analyze(ctx)

        assert result["overall_signal"] in ("BULLISH", "BUY")
        proposal = result["proposal"]
        assert proposal is not None
        assert proposal["direction"] == "BUY"
        # Pipeline/risk-gate expected keys.
        assert proposal["entry_price"] == 1.1
        assert proposal["stop_loss"] is not None
        assert proposal["take_profit"] is not None
        assert result["synthesis"] is not None
        assert result["synthesis"]["proposal"]["direction"] == "BUY"

    def test_bearish_consensus_emits_sell_proposal(self):
        sup = SupervisorAgent()
        ctx = self._context(
            _SignalAgent("structure_analyst", "BEARISH", 0.85),
            _SignalAgent("momentum_analyst", "SELL", 0.75),
        )
        proposal = sup.analyze(ctx)["proposal"]
        assert proposal is not None
        assert proposal["direction"] == "SELL"

    def test_neutral_consensus_emits_no_proposal(self):
        """No actionable signal must NOT fabricate a trade (fail-closed)."""
        sup = SupervisorAgent()
        ctx = self._context(
            _SignalAgent("structure_analyst", "NEUTRAL", 0.2),
            _SignalAgent("momentum_analyst", "NEUTRAL", 0.3),
        )
        result = sup.analyze(ctx)
        assert result["proposal"] is None

    def test_synthesis_failure_is_fail_closed(self):
        """A broken synthesizer yields no proposal, never an exception."""
        sup = SupervisorAgent()

        class _Boom:
            def generate_proposal(self, *a, **k):
                raise RuntimeError("boom")

        sup.synthesizer = _Boom()  # type: ignore[assignment]
        ctx = self._context(_SignalAgent("structure_analyst", "BULLISH", 0.9))
        result = sup.analyze(ctx)
        assert result["proposal"] is None
