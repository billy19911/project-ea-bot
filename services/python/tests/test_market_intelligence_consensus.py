# -*- coding: utf-8 -*-
"""Tests for PRD_V2 §10 — deterministic, evidence-weighted consensus.

Verifies that :meth:`MarketLead.synthesize` resolves conflicting analysts by
evidence quality/weight (reliability + confidence), never by headcount, and
that the outcome is explainable through a rationale and a dissent record.
"""

from __future__ import annotations

from market.intelligence import AnalystReport, MarketLead


def _make_lead_with_reports(reports):
    """Build a MarketLead whose specialists echo the supplied reports."""
    lead = MarketLead()
    lead.create_department()

    class _EchoSpecialist:
        def __init__(self, report):
            self._report = report

        def analyze(self, market_data):
            return self._report

    lead.department.specialists = [_EchoSpecialist(r) for r in reports]
    return lead


class TestEvidenceWeightedConsensus:
    def test_weight_beats_headcount(self):
        """Two weak bearish reports must NOT outvote one strong bullish report."""
        reports = [
            AnalystReport(
                analyst="a1",
                direction="BEARISH",
                confidence=0.2,
                evidence="weak",
                reliability=0.1,
            ),
            AnalystReport(
                analyst="a2",
                direction="BEARISH",
                confidence=0.2,
                evidence="weak",
                reliability=0.1,
            ),
            AnalystReport(
                analyst="a3",
                direction="BULLISH",
                confidence=0.9,
                evidence="strong",
                reliability=0.95,
            ),
        ]
        lead = _make_lead_with_reports(reports)
        decision = lead.synthesize({})
        # Evidence weight, not headcount (2 vs 1), decides.
        assert decision.direction == "BULLISH"

    def test_deterministic_tie_break(self):
        """Equal weight across directions resolves deterministically (no vote)."""
        reports = [
            AnalystReport("a1", "BULLISH", 0.5, "x", reliability=0.5),
            AnalystReport("a2", "BEARISH", 0.5, "y", reliability=0.5),
        ]
        lead1 = _make_lead_with_reports(reports)
        lead2 = _make_lead_with_reports(list(reports))
        assert lead1.synthesize({}).direction == lead2.synthesize({}).direction

    def test_unanimous_direction(self):
        reports = [
            AnalystReport("a1", "BULLISH", 0.7, "x", reliability=0.7),
            AnalystReport("a2", "BULLISH", 0.6, "y", reliability=0.6),
        ]
        lead = _make_lead_with_reports(reports)
        decision = lead.synthesize({})
        assert decision.direction == "BULLISH"

    def test_all_neutral(self):
        reports = [
            AnalystReport("a1", "NEUTRAL", 0.5, "x"),
            AnalystReport("a2", "NEUTRAL", 0.5, "y"),
        ]
        lead = _make_lead_with_reports(reports)
        decision = lead.synthesize({})
        assert decision.direction == "NEUTRAL"


class TestExplainability:
    def test_rationale_present(self):
        reports = [
            AnalystReport("a1", "BULLISH", 0.9, "x", reliability=0.9),
            AnalystReport("a2", "BEARISH", 0.3, "y", reliability=0.2),
        ]
        lead = _make_lead_with_reports(reports)
        decision = lead.synthesize({})
        assert decision.rationale
        assert "BU" in decision.rationale.upper() or "bea" in decision.rationale.lower()

    def test_dissent_recorded(self):
        reports = [
            AnalystReport("a1", "BULLISH", 0.9, "x", reliability=0.9),
            AnalystReport("a2", "BEARISH", 0.3, "y", reliability=0.2),
        ]
        lead = _make_lead_with_reports(reports)
        decision = lead.synthesize({})
        assert decision.dissent
        # The dissenting analyst is recorded by name.
        assert any("a2" in d for d in decision.dissent)

    def test_no_dissent_when_unanimous(self):
        reports = [
            AnalystReport("a1", "BULLISH", 0.9, "x", reliability=0.9),
            AnalystReport("a2", "BULLISH", 0.8, "y", reliability=0.8),
        ]
        lead = _make_lead_with_reports(reports)
        decision = lead.synthesize({})
        assert decision.dissent == []

    def test_to_dict_serializes_explanation(self):
        reports = [
            AnalystReport("a1", "BULLISH", 0.9, "x", reliability=0.9),
            AnalystReport("a2", "BEARISH", 0.3, "y", reliability=0.2),
        ]
        lead = _make_lead_with_reports(reports)
        data = lead.synthesize({}).to_dict()
        assert "rationale" in data
        assert "dissent" in data
        assert data["dissent"]


class TestPublicApiStable:
    def test_full_department_still_synthesizes(self):
        """The default 5-specialist department still returns a CommitteeDecision."""
        lead = MarketLead()
        decision = lead.synthesize(
            {
                "symbol": "EURUSD",
                "trend": "UP",
                "rsi": 65.0,
                "macd": 0.002,
                "support": 1.0750,
                "resistance": 1.0950,
                "current_price": 1.0850,
                "sentiment_score": 0.65,
                "historical_volatility": 0.12,
                "implied_volatility": 0.15,
            }
        )
        assert decision.department == "market"
        assert len(decision.reports) == 5
        assert decision.direction in ("BULLISH", "BEARISH", "NEUTRAL")
