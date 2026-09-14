# -*- coding: utf-8 -*-
"""Tests for EPIC 01.02 — AgentRegistry metadata extension.

Registry must track: type, role, permissions, dependencies, model_policy, timeout.
"""

from __future__ import annotations

import pytest

from agents.base import AgentPriority, AgentRegistry, BaseAgent


class StubAgent(BaseAgent):
    def __init__(
        self,
        name: str,
        agent_type: str = "stub",
        role: str = "specialist",
        permissions: list[str] | None = None,
        dependencies: list[str] | None = None,
        model_policy: dict[str, str] | None = None,
        timeout_seconds: int = 30,
    ):
        super().__init__(name=name, agent_type=agent_type, priority=AgentPriority.NORMAL)
        self.role = role
        self.permissions = permissions or []
        self.dependencies = dependencies or []
        self.model_policy = model_policy or {}
        self.timeout_seconds = timeout_seconds

    def analyze(self, context: dict) -> dict:
        return {"agent": self.name, "signal": "NEUTRAL"}


@pytest.fixture(autouse=True)
def _reset_registry():
    AgentRegistry.reset()
    yield
    AgentRegistry.reset()


# ---------------------------------------------------------------------------
# Agent metadata serialization
# ---------------------------------------------------------------------------


def test_agent_to_dict_includes_metadata():
    """Agent.to_dict() must include role, permissions, dependencies, model_policy, timeout."""
    agent = StubAgent(
        name="technical",
        role="market_specialist",
        permissions=["READ_MARKET_DATA"],
        dependencies=["market_connector"],
        model_policy={"provider": "openai", "model": "gpt-4"},
        timeout_seconds=60,
    )

    d = agent.to_dict()
    assert d["name"] == "technical"
    assert d["role"] == "market_specialist"
    assert d["permissions"] == ["READ_MARKET_DATA"]
    assert d["dependencies"] == ["market_connector"]
    assert d["model_policy"] == {"provider": "openai", "model": "gpt-4"}
    assert d["timeout_seconds"] == 60


def test_agent_to_dict_defaults():
    """Agent without explicit metadata must return empty lists/dicts."""
    agent = StubAgent(name="simple", agent_type="test")
    d = agent.to_dict()
    assert d["permissions"] == []
    assert d["dependencies"] == []
    assert d["model_policy"] == {}
    assert d["timeout_seconds"] == 30


# ---------------------------------------------------------------------------
# Registry query by role
# ---------------------------------------------------------------------------


def test_registry_get_by_role():
    """Registry.get_by_role() must return agents matching a role."""
    reg = AgentRegistry()
    specialist = StubAgent(name="tech", role="market_specialist")
    lead = StubAgent(name="market_lead", role="department_lead")
    reg.register(specialist)
    reg.register(lead)

    specialists = reg.get_by_role("market_specialist")
    assert len(specialists) == 1
    assert specialists[0].name == "tech"

    leads = reg.get_by_role("department_lead")
    assert len(leads) == 1
    assert leads[0].name == "market_lead"


def test_registry_get_by_role_empty():
    """Registry.get_by_role() must return empty list when no match."""
    reg = AgentRegistry()
    assert reg.get_by_role("nonexistent_role") == []


# ---------------------------------------------------------------------------
# Registry query by permission
# ---------------------------------------------------------------------------


def test_registry_get_by_permission():
    """Registry.get_by_permission() must return agents with that permission."""
    reg = AgentRegistry()
    exec_agent = StubAgent(name="executor", permissions=["EXECUTE_TRADE", "READ_MARKET_DATA"])
    reader = StubAgent(name="reader", permissions=["READ_MARKET_DATA"])
    reg.register(exec_agent)
    reg.register(reader)

    traders = reg.get_by_permission("EXECUTE_TRADE")
    assert len(traders) == 1
    assert traders[0].name == "executor"

    readers = reg.get_by_permission("READ_MARKET_DATA")
    assert len(readers) == 2


def test_registry_get_by_permission_empty():
    """Registry.get_by_permission() must return empty when no agent has it."""
    reg = AgentRegistry()
    reg.register(StubAgent(name="reader", permissions=["READ_MARKET_DATA"]))
    assert reg.get_by_permission("WRITE_CONFIG") == []


# ---------------------------------------------------------------------------
# Registry metadata export
# ---------------------------------------------------------------------------


def test_registry_export_metadata():
    """Registry.export_metadata() must return full metadata for all agents."""
    reg = AgentRegistry()
    agent1 = StubAgent(
        name="a1",
        role="specialist",
        permissions=["READ_MARKET_DATA"],
        dependencies=["connector"],
        model_policy={"provider": "openai"},
        timeout_seconds=45,
    )
    agent2 = StubAgent(name="a2", role="lead")
    reg.register(agent1)
    reg.register(agent2)

    metadata = reg.export_metadata()
    assert len(metadata) == 2
    assert metadata["a1"]["role"] == "specialist"
    assert metadata["a1"]["permissions"] == ["READ_MARKET_DATA"]
    assert metadata["a2"]["role"] == "lead"


# ---------------------------------------------------------------------------
# Permission validation
# ---------------------------------------------------------------------------


def test_registry_validate_permissions():
    """Registry.validate_permissions() must check if agent has all required permissions."""
    reg = AgentRegistry()
    agent = StubAgent(name="exec", permissions=["EXECUTE_TRADE", "READ_MARKET_DATA"])
    reg.register(agent)

    assert reg.validate_permissions("exec", ["EXECUTE_TRADE"]) is True
    assert reg.validate_permissions("exec", ["READ_MARKET_DATA"]) is True
    assert reg.validate_permissions("exec", ["EXECUTE_TRADE", "READ_MARKET_DATA"]) is True
    assert reg.validate_permissions("exec", ["WRITE_CONFIG"]) is False
    assert reg.validate_permissions("exec", ["EXECUTE_TRADE", "WRITE_CONFIG"]) is False


def test_registry_validate_permissions_unknown_agent():
    """Registry.validate_permissions() must return False for unknown agent."""
    reg = AgentRegistry()
    assert reg.validate_permissions("ghost", ["ANY"]) is False
