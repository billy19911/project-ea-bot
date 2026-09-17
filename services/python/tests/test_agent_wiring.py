# -*- coding: utf-8 -*-
"""Wiring tests — startup agents must be reachable by the production Supervisor.

Regression tests for three real wiring bugs found in the production path:

1. Split-brain registry: ``src/main.py`` registered agents into the
   ``src.agents.registry`` module while ``src.orchestration.runtime`` injected
   ``agents.registry.agent_registry`` into the Supervisor — two distinct
   singletons, so every delegated analysis answered "not registered".
2. Registry clobber: ``SupervisorAgent.analyze`` overwrote its injected
   registry with ``None`` whenever the pipeline context omitted the
   "registry" key, discarding the production wiring on the first cycle.
3. Routing table sent momentum/oscillator, volatility and news events to the
   generic technical analyst or the UNSUPPORTED sentiment placeholder instead
   of the real specialist agents that exist for them.
"""

from __future__ import annotations

import agents.registry as agents_registry
from agents.base import AgentPriority, AgentRegistry, BaseAgent
from agents.supervisor import SupervisorAgent


class _EchoAgent(BaseAgent):
    """Minimal agent used to observe delegation."""

    def __init__(self) -> None:
        super().__init__(
            name="echo_agent",
            agent_type="echo",
            description="Echo agent for wiring tests",
            priority=AgentPriority.HIGH,
        )

    def can_handle(self, event_type: str, context: dict) -> bool:
        return True

    def analyze(self, context: dict) -> dict:
        return {
            "agent": self.name,
            "signal": "BULLISH",
            "confidence": 0.9,
            "reasons": ["echo"],
        }


def test_main_registry_is_the_registry_runtime_uses() -> None:
    """main.py must register into the exact singleton runtime injects."""
    import src.main as main_module

    assert main_module.agent_registry is agents_registry.agent_registry


def test_built_pipeline_uses_main_registry() -> None:
    """The production pipeline's supervisor gets main.py's registry object."""
    import src.main as main_module
    from src.orchestration.runtime import OrchestrationRuntime

    supervisor = OrchestrationRuntime._build_pipeline().supervisor

    assert supervisor._registry_cache is main_module.agent_registry


def test_supervisor_keeps_injected_registry_across_analyze() -> None:
    """A context without "registry" must not clear the injected registry."""
    import src.main as main_module
    from src.orchestration.runtime import OrchestrationRuntime

    supervisor = OrchestrationRuntime._build_pipeline().supervisor
    assert supervisor._registry_cache is main_module.agent_registry

    supervisor.analyze({"event_type": "TREND_BULLISH"})

    assert supervisor._registry_cache is main_module.agent_registry


def test_injected_registry_is_used_without_context_registry() -> None:
    """Delegation works from the injected registry alone (production path)."""
    registry = AgentRegistry()
    registry.register(_EchoAgent())
    try:
        sup = SupervisorAgent()
        sup._registry_cache = registry
        sup.add_route("ECHO_", ["echo_agent"])

        result = sup.analyze({"event_type": "ECHO_PING"})

        assert result["agent_results"]["echo_agent"]["signal"] == "BULLISH"
    finally:
        registry.unregister("echo_agent")


def test_default_routing_targets_real_specialists() -> None:
    """Momentum/volatility/news events route to the real specialist agents."""
    sup = SupervisorAgent()

    assert sup.match_routes("MOMENTUM_BULLISH")[0] == "momentum_analyst"
    assert sup.match_routes("RSI_OVERBOUGHT")[0] == "momentum_analyst"
    assert sup.match_routes("STOCH_OVERSOLD")[0] == "momentum_analyst"
    assert sup.match_routes("VOLATILITY_SPIKE")[0] == "volatility_analyst"
    assert sup.match_routes("NEWS_FLASH")[0] == "news_sentiment"
    assert sup.match_routes("SOCIAL_BUZZ")[0] == "news_sentiment"
    assert "technical_analyst" in sup.match_routes("TREND_BULLISH")


def test_register_default_agents_is_idempotent() -> None:
    """Startup registration must register all five agents and be re-runnable."""
    from src.main import agent_registry, register_default_agents

    expected = {
        "technical_analyst",
        "momentum_analyst",
        "structure_analyst",
        "volatility_analyst",
        "news_sentiment",
    }
    newly = register_default_agents()
    try:
        names = {agent.name for agent in agent_registry.list()}
        assert expected <= names
        # Second call must be a no-op, not a ValueError.
        assert register_default_agents() == []
    finally:
        for name in newly:
            agent_registry.unregister(name)


def test_registered_specialists_are_reachable_from_built_pipeline() -> None:
    """End-to-end: a momentum event reaches the registered momentum agent."""
    from src.main import agent_registry, register_default_agents
    from src.orchestration.runtime import OrchestrationRuntime

    newly = register_default_agents()
    try:
        supervisor = OrchestrationRuntime._build_pipeline().supervisor
        prices = [1.0 + 0.001 * i for i in range(40)]

        result = supervisor.analyze(
            {"event_type": "MOMENTUM_BULLISH", "prices": prices, "symbol": "EURUSD"}
        )

        momentum = result["agent_results"].get("momentum_analyst")
        assert momentum is not None, result["agent_results"]
        assert momentum["agent"] == "momentum_analyst"
        # The "not registered" stub uses a "reasons" list; real momentum
        # output uses "reasoning" plus metrics.
        assert "reasons" not in momentum
    finally:
        for name in newly:
            agent_registry.unregister(name)
