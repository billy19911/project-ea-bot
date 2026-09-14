# -*- coding: utf-8 -*-
"""Tests for EPIC 01 Department model — DepartmentLead abstraction.

Department Lead sits between Supervisor and Specialists (PRD V2 §5.2).
A lead decides which specialists are required, dispatches to them,
and returns a department-level assessment.
"""

from __future__ import annotations

from typing import Any

import pytest

from agents.base import AgentPriority, AgentRegistry, BaseAgent
from agents.departments import Department, DepartmentLead
from agents.supervisor import SupervisorAgent


class StubSpecialist(BaseAgent):
    """Simple specialist that returns a fixed signal."""

    def __init__(
        self, name: str, signal: str = "NEUTRAL", priority: AgentPriority = AgentPriority.NORMAL
    ):
        super().__init__(
            name=name,
            agent_type="specialist",
            description=f"Stub specialist {name}",
            priority=priority,
        )
        self.signal = signal
        self.call_count = 0

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        self.call_count += 1
        return {
            "agent": self.name,
            "signal": self.signal,
            "confidence": 0.8,
            "reasons": [f"{self.name} analysed"],
        }


@pytest.fixture(autouse=True)
def _reset_registry():
    AgentRegistry.reset()
    yield
    AgentRegistry.reset()


# ---------------------------------------------------------------------------
# Department creation
# ---------------------------------------------------------------------------


def test_department_creation():
    dept = Department(
        name="market", display_name="Market Intelligence", description="Market analysis department"
    )
    assert dept.name == "market"
    assert dept.display_name == "Market Intelligence"
    assert dept.specialists == []


def test_department_add_remove_specialist():
    dept = Department(name="market", display_name="Market Intelligence", description="")
    spec = StubSpecialist("technical")
    dept.add_specialist(spec)
    assert dept.specialists == [spec]

    dept.remove_specialist("technical")
    assert dept.specialists == []


def test_department_duplicate_specialist_raises():
    dept = Department(name="market", display_name="Market Intelligence", description="")
    spec = StubSpecialist("technical")
    dept.add_specialist(spec)
    with pytest.raises(ValueError):
        dept.add_specialist(spec)


# ---------------------------------------------------------------------------
# DepartmentLead behavior
# ---------------------------------------------------------------------------


def test_lead_routes_to_selected_specialists_only():
    """Lead must decide which specialists are required — no fixed fan-out."""
    dept = Department(name="market", display_name="Market Intelligence", description="")
    technical = StubSpecialist("technical", signal="BULLISH")
    momentum = StubSpecialist("momentum", signal="BEARISH")
    dept.add_specialist(technical)
    dept.add_specialist(momentum)

    lead = DepartmentLead(department=dept, name="market_lead")

    # Only technical is selected for this event
    result = lead.analyze({"event_type": "TREND_BULLISH", "required_specialists": ["technical"]})

    assert result["department"] == "market"
    assert technical.call_count == 1
    assert momentum.call_count == 0  # Not a fixed fan-out


def test_lead_returns_department_consensus():
    dept = Department(name="market", display_name="Market Intelligence", description="")
    technical = StubSpecialist("technical", signal="BULLISH")
    momentum = StubSpecialist("momentum", signal="BULLISH")
    dept.add_specialist(technical)
    dept.add_specialist(momentum)

    lead = DepartmentLead(department=dept, name="market_lead")
    result = lead.analyze(
        {"event_type": "TREND_BULLISH", "required_specialists": ["technical", "momentum"]}
    )

    assert result["department"] == "market"
    assert result["consensus_signal"] == "BULLISH"
    assert "technical" in result["specialist_results"]
    assert "momentum" in result["specialist_results"]


def test_lead_handles_specialist_failure():
    dept = Department(name="market", display_name="Market Intelligence", description="")

    class FailingSpecialist(StubSpecialist):
        def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("boom")

    technical = StubSpecialist("technical", signal="BULLISH")
    failing = FailingSpecialist("failing", signal="BULLISH")
    dept.add_specialist(technical)
    dept.add_specialist(failing)

    lead = DepartmentLead(department=dept, name="market_lead")
    result = lead.analyze(
        {"event_type": "TREND_BULLISH", "required_specialists": ["technical", "failing"]}
    )

    assert result["department"] == "market"
    # Failed specialist should not crash the lead
    assert "failing" in result["specialist_results"]
    assert result["specialist_results"]["failing"]["status"] == "ERROR"


def test_lead_with_routing_function():
    """Lead can use a custom routing function to pick specialists."""
    dept = Department(name="risk", display_name="Risk Intelligence", description="")
    account = StubSpecialist("account_risk", signal="CAUTION")
    position = StubSpecialist("position_risk", signal="OK")
    dept.add_specialist(account)
    dept.add_specialist(position)

    def route(context):
        return ["account_risk"] if context.get("risk_level") == "high" else ["position_risk"]

    lead = DepartmentLead(department=dept, name="risk_lead", routing_fn=route)

    lead.analyze({"event_type": "RISK_CHECK", "risk_level": "high"})
    assert account.call_count == 1
    assert position.call_count == 0

    lead.analyze({"event_type": "RISK_CHECK", "risk_level": "low"})
    assert position.call_count == 1


# ---------------------------------------------------------------------------
# Supervisor uses Department Leads (not direct specialists)
# ---------------------------------------------------------------------------


def test_supervisor_can_delegate_to_department():
    dept = Department(name="market", display_name="Market Intelligence", description="")
    technical = StubSpecialist("technical", signal="BULLISH")
    dept.add_specialist(technical)
    lead = DepartmentLead(department=dept, name="market_lead")

    reg = AgentRegistry()
    reg.register(lead)
    reg.register(technical)

    sup = SupervisorAgent(routing_policy="all_match")
    sup._registry_cache = reg

    # Supervisor routes to the LEAD as a regular agent — no special casing needed
    result = sup.analyze({"event_type": "TREND_BULLISH", "agents": [lead]})
    assert "market_lead" in result["agent_results"]


def test_lead_to_dict_includes_department_metadata():
    dept = Department(name="market", display_name="Market Intelligence", description="")
    lead = DepartmentLead(department=dept, name="market_lead")
    d = lead.to_dict()
    assert d["department"] == "market"
    assert d["role"] == "department_lead"
