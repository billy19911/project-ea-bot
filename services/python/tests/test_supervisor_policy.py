# -*- coding: utf-8 -*-
"""Tests for the supervisor orchestration policy wiring (audit P2-3).

The production supervisor previously defaulted to ``first_match`` which collapsed
every cycle to a single agent — FIXED ORCHESTRATION. It now runs the
configurable policy (default ``all_match``) so matching departments collaborate.
"""

from __future__ import annotations

from agents.supervisor import SupervisorAgent
from orchestration.runtime import OrchestrationRuntime


def test_production_supervisor_uses_all_match_default() -> None:
    runtime = OrchestrationRuntime()
    assert runtime.pipeline.supervisor.routing_policy == "all_match"


def test_policy_reflects_config(monkeypatch) -> None:
    monkeypatch.setenv("SUPERVISOR_ROUTING_POLICY", "priority_based")
    supervisor = OrchestrationRuntime._build_pipeline()
    assert supervisor.supervisor.routing_policy == "priority_based"


def test_all_match_keeps_multiple_department_leads() -> None:
    from agents.base import BaseAgent
    from agents.registry import AgentRegistry
    from agents.supervisor import AgentPriority

    class _Lead(BaseAgent):
        def __init__(self, name):
            super().__init__(name=name, agent_type="department_lead", priority=AgentPriority.HIGH)

        def can_handle(self, event_type, context):
            return True

        def analyze(self, context):
            return {"agent": self.name, "signal": "NEUTRAL", "confidence": 0.0}

    registry = AgentRegistry()
    registry.register(_Lead("market_lead"))
    registry.register(_Lead("risk_lead"))

    supervisor = SupervisorAgent(routing_policy="all_match")
    supervisor._registry_cache = registry

    result = supervisor.analyze({"event_type": "BREAKOUT", "symbol": "EURUSD"})
    # Both department leads ran (dynamic multi-department orchestration).
    assert len(result.get("agent_results", {})) >= 2


if __name__ == "__main__":  # pragma: no cover
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
