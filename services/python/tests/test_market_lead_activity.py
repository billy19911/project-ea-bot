# -*- coding: utf-8 -*-
"""Regression tests — MarketLead must record specialist activity.

The production path runs specialists through ``MarketLead.analyze`` (it does
not use ``DepartmentLead``), so it must record their runs itself. Before this
fix, the AI Control page showed every specialist as ``idle`` with zero
invocations even though they run on every market cycle.
"""

from __future__ import annotations

import pytest

from agents.activity import get_activity_tracker
from agents.base import AgentPriority, BaseAgent
from market.intelligence import MarketLead


class _StubSpecialist(BaseAgent):
    """Deterministic specialist that always succeeds."""

    def __init__(self, name: str, signal: str = "NEUTRAL", confidence: float = 0.5) -> None:
        super().__init__(name=name, agent_type="specialist", priority=AgentPriority.NORMAL)
        self.signal = signal
        self.confidence = confidence

    def analyze(self, context: dict) -> dict:
        return {
            "agent": self.name,
            "signal": self.signal,
            "confidence": self.confidence,
        }


class _BoomSpecialist(BaseAgent):
    """Specialist that always raises — the defensive boundary must hold."""

    def __init__(self, name: str) -> None:
        super().__init__(name=name, agent_type="specialist", priority=AgentPriority.NORMAL)

    def analyze(self, context: dict) -> dict:
        raise RuntimeError("boom")


@pytest.fixture(autouse=True)
def _fresh_tracker():
    tracker = get_activity_tracker()
    tracker.reset()
    yield tracker
    tracker.reset()


def test_market_lead_records_specialist_runs(_fresh_tracker):
    lead = MarketLead(
        specialists={"technical_analyst": _StubSpecialist("technical_analyst", "BULLISH", 0.8)}
    )
    lead.analyze({})

    entry = _fresh_tracker.get("technical_analyst")
    assert entry is not None
    assert entry["invocations"] == 1
    assert entry["status"] == "active"
    assert entry["signal_counts"] == {"BULLISH": 1}
    assert entry["last_active"] is not None


def test_market_lead_records_specialist_errors(_fresh_tracker):
    lead = MarketLead(specialists={"technical_analyst": _BoomSpecialist("technical_analyst")})
    lead.analyze({})

    entry = _fresh_tracker.get("technical_analyst")
    assert entry is not None
    assert entry["invocations"] == 1
    assert entry["errors"] == 1
    assert entry["status"] == "active"


def test_activity_recording_never_breaks_analysis(_fresh_tracker):
    """A specialist with a non-float confidence must not break the cycle."""
    stub = _StubSpecialist("technical_analyst", "BEARISH", "bad")  # type: ignore[arg-type]
    lead = MarketLead(specialists={"technical_analyst": stub})
    result = lead.analyze({})
    assert result["specialist_results"]["technical_analyst"]["signal"] == "BEARISH"
    entry = _fresh_tracker.get("technical_analyst")
    assert entry is not None
    assert entry["invocations"] == 1
