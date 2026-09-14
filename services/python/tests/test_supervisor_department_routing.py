# -*- coding: utf-8 -*-
"""Tests for EPIC 01.03 — Supervisor routing to DepartmentLead.

Supervisor should recognize DepartmentLead agents via ``agent_type == 'department_lead'``
and delegate events to them, not directly to specialists.
"""

from __future__ import annotations

import pytest

from agents.base import AgentPriority, AgentRegistry, BaseAgent
from agents.departments import Department, DepartmentLead
from agents.supervisor import SupervisorAgent


class SimpleSpecialist(BaseAgent):
    def __init__(self, name: str, signal: str = "NEUTRAL"):
        super().__init__(name=name, agent_type="specialist", priority=AgentPriority.NORMAL)
        self.signal = signal

    def analyze(self, context: dict) -> dict:
        return {"agent": self.name, "signal": self.signal}


@pytest.fixture(autouse=True)
def _reset_registry():
    AgentRegistry.reset()
    yield
    AgentRegistry.reset()


# ---------------------------------------------------------------------------
# Supervisor delegates to department lead (no direct specialist)
# ---------------------------------------------------------------------------


def test_supervisor_routes_to_department_lead():
    dept = Department(name="market", display_name="Market", description="")
    tech = SimpleSpecialist("technical", signal="BULLISH")
    dept.add_specialist(tech)
    lead = DepartmentLead(department=dept, name="market_lead")

    reg = AgentRegistry()
    reg.register(lead)
    reg.register(tech)  # specialist still registered, but supervisor shouldn't call it directly

    sup = SupervisorAgent(routing_policy="all_match")

    # Registry is read from context by analyze(); pass it there (matches legacy API).
    result = sup.analyze(
        {"event_type": "TREND_BULLISH", "required_specialists": ["technical"], "registry": reg}
    )
    # Supervisor should have called the lead, not the specialist directly
    assert "market_lead" in result["agent_results"]
    assert "technical" not in result["agent_results"]

    # Lead should have delegated to the specialist internally
    lead_result = result["agent_results"]["market_lead"]
    assert lead_result["specialist_results"]["technical"]["signal"] == "BULLISH"


def test_supervisor_all_match_includes_multiple_department_leads():
    # Market department
    market = Department(name="market", display_name="Market", description="")
    tech = SimpleSpecialist("technical", signal="BULLISH")
    market.add_specialist(tech)
    market_lead = DepartmentLead(department=market, name="market_lead")

    # Risk department
    risk = Department(name="risk", display_name="Risk", description="")
    acc = SimpleSpecialist("account_risk", signal="CAUTION")
    risk.add_specialist(acc)
    risk_lead = DepartmentLead(department=risk, name="risk_lead")

    reg = AgentRegistry()
    for a in [market_lead, tech, risk_lead, acc]:
        reg.register(a)

    sup = SupervisorAgent(routing_policy="all_match")

    result = sup.analyze(
        {
            "event_type": "RISK_CHECK",
            "required_specialists": ["technical", "account_risk"],
            "registry": reg,
        }
    )
    # Both leads must be invoked
    assert "market_lead" in result["agent_results"]
    assert "risk_lead" in result["agent_results"]
    # Specialists should be nested under their respective leads
    assert (
        result["agent_results"]["market_lead"]["specialist_results"]["technical"]["signal"]
        == "BULLISH"
    )
    assert (
        result["agent_results"]["risk_lead"]["specialist_results"]["account_risk"]["signal"]
        == "CAUTION"
    )


# ---------------------------------------------------------------------------
# DepartmentLead metadata inclusion
# ---------------------------------------------------------------------------


def test_department_lead_to_dict_has_role_and_department():
    dept = Department(name="research", display_name="Research", description="")
    lead = DepartmentLead(department=dept, name="research_lead")
    d = lead.to_dict()
    assert d["role"] == "department_lead"
    assert d["department"] == "research"
