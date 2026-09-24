# -*- coding: utf-8 -*-
"""RED→GREEN tests for lead activity, LLM telemetry wiring, execution quality."""

from __future__ import annotations

import pytest

from src.agents.activity import get_activity_tracker
from src.agents.base import AgentPriority, BaseAgent
from src.agents.supervisor import SupervisorAgent


@pytest.fixture(autouse=True)
def _reset_activity() -> None:
    get_activity_tracker().reset()
    yield
    get_activity_tracker().reset()


class _Lead(BaseAgent):
    """Minimal department_lead handling only RISK_* style events."""

    def __init__(self, name: str, prefixes: tuple[str, ...]) -> None:
        super().__init__(name=name, agent_type="department_lead", priority=AgentPriority.HIGH)
        self._prefixes = prefixes

    def can_handle(self, event_type: str, context: dict) -> bool:  # noqa: ANN001
        return any(event_type.startswith(p) for p in self._prefixes)

    def analyze(self, context: dict) -> dict:  # noqa: ANN001
        return {"agent": self.name, "signal": "RISK_OFF", "confidence": 0.4}


class _Registry:
    def __init__(self, agents: list[BaseAgent]) -> None:
        self._agents = agents

    def get_by_type(self, agent_type: str) -> list[BaseAgent]:
        return [a for a in self._agents if a.agent_type == agent_type]

    def get(self, name: str):  # noqa: ANN201
        return next((a for a in self._agents if a.name == name), None)


def test_risk_event_increments_risk_lead_activity() -> None:
    risk_lead = _Lead("risk_lead", ("RISK_", "DRAWDOWN_", "MARGIN_"))
    review_lead = _Lead("review_lead", ("TRADE_CLOSE", "POST_TRADE_REVIEW"))
    registry = _Registry([risk_lead, review_lead])
    sup = SupervisorAgent(routing_policy="all_match")

    sup.analyze({"event_type": "RISK_BREACH", "registry": registry})

    snapshot = get_activity_tracker().snapshot()
    assert snapshot["risk_lead"]["invocations"] == 1
    assert snapshot["risk_lead"]["last_event_type"] == "RISK_BREACH"
    assert "review_lead" not in snapshot


def test_market_event_does_not_touch_risk_or_review_lead() -> None:
    risk_lead = _Lead("risk_lead", ("RISK_",))
    review_lead = _Lead("review_lead", ("TRADE_CLOSE",))
    market_lead = _Lead("market_lead", ("TREND_", "MARKET_"))
    registry = _Registry([risk_lead, review_lead, market_lead])
    sup = SupervisorAgent(routing_policy="all_match")

    sup.analyze({"event_type": "MARKET_TICK", "registry": registry})

    snapshot = get_activity_tracker().snapshot()
    assert "risk_lead" not in snapshot
    assert "review_lead" not in snapshot
    assert snapshot["market_lead"]["invocations"] == 1


# ---------------------------------------------------------------------------
# LLM telemetry wiring
# ---------------------------------------------------------------------------


def test_advisor_success_records_telemetry(monkeypatch) -> None:
    import src.system.settings_store as store_mod
    import src.system.v2_endpoints as v2
    from src.llm.advisor import LLMAdvisor

    v2._llm_store = None
    shared = v2.get_llm_store()

    class _Store:
        def snapshot(self):  # noqa: ANN201
            class Snap:
                values = {"llm_advisor_enabled": 1.0}

            return Snap()

    monkeypatch.setattr(store_mod, "get_settings_store", lambda: _Store())

    from tests.test_llm_advisor import FakeClient, FakeSupervisor

    advisor = LLMAdvisor(client=FakeClient(), supervisor=FakeSupervisor())
    advisor.advise("market", {"symbol": "XAUUSD", "bid": 1.0, "ask": 1.1})

    rows = shared.all()
    assert len(rows) == 1
    row = rows[0]
    assert row.model == "fake-model"
    assert row.agent == "llm_advisor:market"
    assert row.error == ""
    assert row.total_tokens == 60


def test_advisor_failure_records_telemetry_error(monkeypatch) -> None:
    import src.system.settings_store as store_mod
    import src.system.v2_endpoints as v2
    from src.llm.advisor import LLMAdvisor

    v2._llm_store = None
    shared = v2.get_llm_store()

    class _Store:
        def snapshot(self):  # noqa: ANN201
            class Snap:
                values = {"llm_advisor_enabled": 1.0}

            return Snap()

    monkeypatch.setattr(store_mod, "get_settings_store", lambda: _Store())

    from tests.test_llm_advisor import FakeClient, FakeSupervisor

    class Boom(FakeClient):
        def generate(self, *a, **k):  # noqa: ANN002, ANN003
            raise RuntimeError("gateway down")

    advisor = LLMAdvisor(client=Boom(), supervisor=FakeSupervisor())
    advisor.advise("market", {"symbol": "XAUUSD"})

    rows = shared.all()
    assert len(rows) == 1
    assert "gateway down" in rows[0].error


def test_model_governance_to_dict_non_empty() -> None:
    from src.observability.llm_telemetry import ModelGovernance

    gov = ModelGovernance()
    gov.set_state("m1", "ACTIVE")
    d = gov.to_dict()
    assert d["states"] == {"m1": "ACTIVE"}
    assert d["fallback_model"] == "deterministic"
    assert d["min_comparison_sample"] == 30
