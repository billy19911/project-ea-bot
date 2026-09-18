# -*- coding: utf-8 -*-
"""Tests for Phase 4 — ReviewLead department wiring.

The ReviewLead is the third department lead (after MarketLead and RiskLead):

* identity — ``agent_type="department_lead"`` so the Supervisor delegates
  ``TRADE_CLOSE`` / ``POST_TRADE_REVIEW`` events to it;
* ``can_handle`` — accepts review events, rejects market/risk events;
* ``analyze`` — Supervisor-compatible dict wrapping the review specialist;
* supervisor integration — a ``TRADE_CLOSE`` event routed through the
  production Supervisor reaches ``review_lead`` and its specialist result;
* department isolation — market events still reach ``market_lead``.
"""

from __future__ import annotations

import pytest

from agents.base import AgentPriority, AgentRegistry
from agents.supervisor import SupervisorAgent
from review.intelligence import ReviewLead

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _RecordingLessonStore:
    def __init__(self) -> None:
        self.lessons: list[dict] = []

    def add_lesson(self, lesson: dict) -> None:
        self.lessons.append(dict(lesson))


def _closed_trade(**overrides):
    trade = {
        "trade_id": "T-400",
        "symbol": "EURUSD",
        "side": "buy",
        "entry_price": 1.1000,
        "exit_price": 1.1050,
        "pnl": 50.0,
        "outcome": "win",
        "signal": "BULLISH",
        "actual_direction": "BULLISH",
        "duration": 1800,
        "price_history": [1.1000, 1.1030, 1.1050],
    }
    trade.update(overrides)
    return trade


@pytest.fixture(autouse=True)
def _reset_registry():
    AgentRegistry.reset()
    yield
    AgentRegistry.reset()


@pytest.fixture()
def store():
    return _RecordingLessonStore()


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def test_review_lead_is_department_lead():
    lead = ReviewLead()
    assert lead.name == "review_lead"
    assert lead.agent_type == "department_lead"
    assert lead.role == "department_lead"


def test_review_lead_priority_is_normal():
    """Post-trade review is important but never time-critical."""
    assert ReviewLead().priority == AgentPriority.NORMAL


def test_review_lead_to_dict_has_department_metadata():
    data = ReviewLead().to_dict()
    assert data["role"] == "department_lead"
    assert data["department"] == "review"


# ---------------------------------------------------------------------------
# can_handle
# ---------------------------------------------------------------------------


def test_can_handle_review_events():
    lead = ReviewLead()
    assert lead.can_handle("TRADE_CLOSE", {}) is True
    assert lead.can_handle("TRADE_CLOSED", {}) is True
    assert lead.can_handle("POST_TRADE_REVIEW", {}) is True


def test_can_handle_rejects_other_departments():
    lead = ReviewLead()
    assert lead.can_handle("TREND_BULLISH", {}) is False
    assert lead.can_handle("MOMENTUM_BULLISH", {}) is False
    assert lead.can_handle("RISK_CHECK", {}) is False
    assert lead.can_handle("DRAWDOWN_WARNING", {}) is False


# ---------------------------------------------------------------------------
# analyze — Supervisor-compatible dict
# ---------------------------------------------------------------------------


def test_analyze_returns_supervisor_dict(store):
    lead = ReviewLead(lesson_store=store)
    result = lead.analyze({"closed_trade": _closed_trade()})

    assert result["agent"] == "review_lead"
    assert result["role"] == "department_lead"
    assert result["department"] == "review"
    assert result["signal"] == "NEUTRAL"
    assert isinstance(result["confidence"], float)
    assert isinstance(result["reasons"], list)
    assert "specialist_results" in result


def test_analyze_delegates_to_specialist(store):
    lead = ReviewLead(lesson_store=store)
    result = lead.analyze({"closed_trade": _closed_trade()})

    assert "post_trade_review" in result["specialist_results"]
    assert len(store.lessons) == 1


def test_analyze_without_data_fails_closed(store):
    lead = ReviewLead(lesson_store=store)
    result = lead.analyze({})
    assert result["signal"] == "NEUTRAL"
    assert result["confidence"] == 0.0
    assert store.lessons == []


# ---------------------------------------------------------------------------
# Supervisor integration
# ---------------------------------------------------------------------------


def test_supervisor_delegates_trade_close_to_review_lead(store):
    registry = AgentRegistry()
    lead = ReviewLead(lesson_store=store)
    registry.register(lead)

    sup = SupervisorAgent()
    sup._registry_cache = registry

    result = sup.analyze({"event_type": "TRADE_CLOSE", "closed_trade": _closed_trade()})

    assert "review_lead" in result["agent_results"], result["agent_results"]
    lead_result = result["agent_results"]["review_lead"]
    assert lead_result["department"] == "review"
    assert "post_trade_review" in lead_result["specialist_results"]
    assert len(store.lessons) == 1


def test_supervisor_does_not_send_market_events_to_review_lead():
    registry = AgentRegistry()
    registry.register(ReviewLead())

    sup = SupervisorAgent()
    sup._registry_cache = registry

    result = sup.analyze({"event_type": "TREND_BULLISH"})

    assert "review_lead" not in result["agent_results"]
    # Falls back to the legacy routing table (technical analyst).
    assert result["overall_signal"] in ("NEUTRAL", "BULLISH", "BEARISH")


def test_three_department_leads_coexist():
    """Market, risk and review leads can be registered side by side."""
    from market.intelligence import MarketLead
    from risk.intelligence import RiskLead

    registry = AgentRegistry()
    registry.register(MarketLead())
    registry.register(RiskLead())
    registry.register(ReviewLead())

    leads = registry.get_by_type("department_lead")
    names = {lead.name for lead in leads}
    assert names == {"market_lead", "risk_lead", "review_lead"}

    # Event isolation: each event type reaches exactly the right lead.
    assert MarketLead().can_handle("TREND_BULLISH", {}) is True
    assert RiskLead().can_handle("TREND_BULLISH", {}) is False
    assert ReviewLead().can_handle("TREND_BULLISH", {}) is False
