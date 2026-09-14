# -*- coding: utf-8 -*-
"""Market Intelligence — EPIC 04 implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agents.base import AgentPriority, BaseAgent


@dataclass
class AnalystReport:
    """Result of specialist analysis."""

    analyst: str
    direction: str  # BULLISH, BEARISH, NEUTRAL
    confidence: float  # 0.0 to 1.0
    evidence: str
    reliability: float = 0.5


@dataclass
class CommitteeDecision:
    """Synthesized market decision."""

    department: str
    direction: str
    confidence: float
    reports: list[AnalystReport] = field(default_factory=list)
    agreements: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "department": self.department,
            "direction": self.direction,
            "confidence": self.confidence,
            "reports": [
                {
                    "analyst": r.analyst,
                    "direction": r.direction,
                    "confidence": r.confidence,
                    "evidence": r.evidence,
                }
                for r in self.reports
            ],
            "agreements": self.agreements,
            "conflicts": self.conflicts,
        }


class TechnicalAnalyst(BaseAgent):
    """Technical analysis specialist."""

    def __init__(self):
        super().__init__(
            name="Technical Analyst",
            agent_type="analyst",
            description="Analyzes price action, trends, and indicators",
            permissions=["ANALYZE_MARKET"],
        )

    def analyze(self, market_data: dict[str, Any]) -> AnalystReport:
        """Produce technical analysis report."""
        trend = market_data.get("trend", "NEUTRAL")
        rsi = market_data.get("rsi", 50.0)

        if trend == "UP" and rsi > 60:
            direction = "BULLISH"
            confidence = 0.7
        elif trend == "DOWN" and rsi < 40:
            direction = "BEARISH"
            confidence = 0.7
        else:
            direction = "NEUTRAL"
            confidence = 0.5

        return AnalystReport(
            analyst="TechnicalAnalyst",
            direction=direction,
            confidence=confidence,
            evidence=f"Trend: {trend}, RSI: {rsi}",
        )

    def execute(self, task):
        return {"status": "ok"}


class StructureAnalyst(BaseAgent):
    """Structure analysis specialist."""

    def __init__(self):
        super().__init__(
            name="Structure Analyst",
            agent_type="analyst",
            description="Analyzes support, resistance, and structure",
            permissions=["ANALYZE_MARKET"],
        )

    def analyze(self, market_data: dict[str, Any]) -> AnalystReport:
        """Produce structure analysis report."""
        current = market_data.get("current_price", 1.0)
        support = market_data.get("support", 0.95)
        resistance = market_data.get("resistance", 1.05)

        if current > (support + resistance) / 2:
            direction = "BULLISH"
            confidence = 0.6
        elif current < (support + resistance) / 2:
            direction = "BEARISH"
            confidence = 0.6
        else:
            direction = "NEUTRAL"
            confidence = 0.5

        return AnalystReport(
            analyst="StructureAnalyst",
            direction=direction,
            confidence=confidence,
            evidence=f"Price: {current}, S: {support}, R: {resistance}",
        )

    def execute(self, task):
        return {"status": "ok"}


class MomentumAnalyst(BaseAgent):
    """Momentum analysis specialist."""

    def __init__(self):
        super().__init__(
            name="Momentum Analyst",
            agent_type="analyst",
            description="Analyzes momentum indicators and trend strength",
            permissions=["ANALYZE_MARKET"],
        )

    def analyze(self, market_data: dict[str, Any]) -> AnalystReport:
        """Produce momentum analysis report."""
        rsi = market_data.get("rsi", 50.0)
        macd = market_data.get("macd", 0.0)

        if rsi > 70 and macd > 0.01:
            direction = "BULLISH"
            confidence = 0.6
        elif rsi < 30 and macd < -0.01:
            direction = "BEARISH"
            confidence = 0.6
        else:
            direction = "NEUTRAL"
            confidence = 0.5

        return AnalystReport(
            analyst="MomentumAnalyst",
            direction=direction,
            confidence=confidence,
            evidence=f"RSI: {rsi}, MACD: {macd}",
        )

    def execute(self, task):
        return {"status": "ok"}


class VolatilityAnalyst(BaseAgent):
    """Volatility analysis specialist."""

    def __init__(self):
        super().__init__(
            name="Volatility Analyst",
            agent_type="analyst",
            description="Analyzes volatility and risk",
            permissions=["ANALYZE_MARKET"],
        )

    def analyze(self, market_data: dict[str, Any]) -> AnalystReport:
        """Produce volatility analysis report."""
        iv = market_data.get("implied_volatility", 0.15)
        hv = market_data.get("historical_volatility", 0.12)

        if iv > hv * 1.2:
            direction = "NEUTRAL"
            confidence = 0.5
        else:
            direction = "NEUTRAL"
            confidence = 0.5

        return AnalystReport(
            analyst="VolatilityAnalyst",
            direction=direction,
            confidence=confidence,
            evidence=f"IV: {iv}, HV: {hv}",
        )

    def execute(self, task):
        return {"status": "ok"}


class NewsSentimentAnalyst(BaseAgent):
    """News and sentiment analysis specialist."""

    def __init__(self):
        super().__init__(
            name="News/Sentiment Analyst",
            agent_type="analyst",
            description="Analyzes news and sentiment",
            permissions=["ANALYZE_MARKET"],
        )

    def analyze(self, market_data: dict[str, Any]) -> AnalystReport:
        """Produce news/sentiment analysis report."""
        sentiment = market_data.get("sentiment_score", 0.5)

        if sentiment > 0.6:
            direction = "BULLISH"
            confidence = 0.55
        elif sentiment < 0.4:
            direction = "BEARISH"
            confidence = 0.55
        else:
            direction = "NEUTRAL"
            confidence = 0.5

        return AnalystReport(
            analyst="NewsSentimentAnalyst",
            direction=direction,
            confidence=confidence,
            evidence=f"Sentiment: {sentiment}",
        )

    def execute(self, task):
        return {"status": "ok"}


class MarketDepartment:
    """Market Intelligence Department."""

    def __init__(self, lead: MarketLead):
        self.lead = lead
        self.specialists = [
            TechnicalAnalyst(),
            StructureAnalyst(),
            MomentumAnalyst(),
            VolatilityAnalyst(),
            NewsSentimentAnalyst(),
        ]


class MarketLead(BaseAgent):
    """Market Intelligence Department Lead."""

    def __init__(self):
        super().__init__(
            name="Market Lead",
            agent_type="lead",
            description="Leads market intelligence analysis",
            permissions=["ANALYZE_MARKET"],
            priority=AgentPriority.HIGH,
        )
        self.department = None

    def create_department(self) -> MarketDepartment:
        """Create and manage market department."""
        self.department = MarketDepartment(self)
        return self.department

    def synthesize(self, market_data: dict[str, Any]) -> CommitteeDecision:
        """Synthesize consensus from specialists."""
        if not self.department:
            self.create_department()

        reports = []
        for specialist in self.department.specialists:
            report = specialist.analyze(market_data)
            reports.append(report)

        directions = [r.direction for r in reports]
        direction = max(set(directions), key=directions.count)
        confidence = sum(r.confidence for r in reports) / len(reports)

        return CommitteeDecision(
            department="market",
            direction=direction,
            confidence=confidence,
            reports=reports,
            agreements=["Analysis complete"],
            conflicts=[],
        )

    def can_handle(self, task_type: str) -> bool:
        return task_type == "market_analysis"

    def execute(self, task):
        return {"status": "ok"}

    def analyze(self, data: dict[str, Any]) -> AnalystReport:
        """BaseAgent abstract method implementation."""
        decision = self.synthesize(data)
        return AnalystReport(
            analyst="MarketLead",
            direction=decision.direction,
            confidence=decision.confidence,
            evidence=f"Consensus from {len(decision.reports)} specialists",
        )
