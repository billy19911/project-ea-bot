# -*- coding: utf-8 -*-
"""Deterministic fundamental analysis agent.

Consumes economic calendar data (injected by NewsFeedProvider via the
autonomous scheduler's context_provider) and produces a directional signal
for XAUUSD based on:

1. Interest Rate Differential — hawkish (Fed hike expectations) = USD bullish
   = XAUUSD bearish; dovish (Fed cut) = USD bearish = XAUUSD bullish.
2. High-Impact Deviations — CPI / NFP / GDP actual vs forecast: a positive
   surprise (actual > forecast) is USD bullish = XAUUSD bearish.
3. Risk Sentiment — geopolitical tension / crisis triggers safe-haven flows
   into gold = XAUUSD bullish.

The agent is fully deterministic (no LLM) and fail-closed: when no economic
event data is available it returns NEUTRAL with confidence 0.55.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..base import AgentCapability, AgentPriority, BaseAgent


class FundamentalSignal(str, Enum):
    """Fundamental signal directions."""

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


@dataclass
class EconomicEvent:
    """Parsed economic calendar event."""

    title: str = ""
    currency: str = ""
    impact: str = "LOW"  # LOW / MEDIUM / HIGH / CRITICAL
    actual: str = ""
    forecast: str = ""
    previous: str = ""
    sentiment: float = 0.0  # -1.0 .. 1.0 (hawkish positive, dovish negative)
    category: str = "GENERAL"

    @property
    def is_high_impact(self) -> bool:
        return self.impact.upper() in ("HIGH", "CRITICAL")

    @property
    def has_deviation(self) -> bool:
        """Whether we can compute actual vs forecast deviation."""
        return bool(self.actual and self.forecast)


@dataclass
class FundamentalInput:
    """Input schema assembled from scheduler context."""

    events: list[EconomicEvent] = field(default_factory=list)
    symbol: str = "XAUUSD"
    risk_sentiment: float = 0.0  # -1.0 .. 1.0 (positive = risk-on)


@dataclass
class FundamentalOutput:
    """Stable output schema for the fundamental agent."""

    signal: str
    confidence: float
    reasoning: list[str]
    metrics: dict[str, float]


# ---------------------------------------------------------------------------
# Lexicon — hawkish / dovish keyword dictionaries
# ---------------------------------------------------------------------------

# Terms that indicate rate hike / tightening (USD bullish, gold bearish)
HAWKISH_KEYWORDS = frozenset(
    {
        "rate hike",
        "rate increase",
        "hike rates",
        "raise rates",
        "tightening",
        "hawkish",
        "fed hikes",
        "rate decision: hike",
        "interest rate increase",
        "monetary tightening",
        "higher rates",
        "quantitative tightening",
        "qt",
        "taper",
        "tapering",
        "strong dollar",
        "aggressive",
        "inflation fighting",
        "combat inflation",
    }
)

# Terms that indicate rate cut / easing (USD bearish, gold bullish)
DOVISH_KEYWORDS = frozenset(
    {
        "rate cut",
        "rate decrease",
        "cut rates",
        "lower rates",
        "dovish",
        "fed cuts",
        "rate decision: cut",
        "interest rate cut",
        "monetary easing",
        "quantitative easing",
        "qe",
        "stimulus",
        "accommodative",
        "weak dollar",
        "patient",
        "pause",
        "hold rates",
        "rate hold",
    }
)

# Safe-haven / risk-off keywords (gold bullish)
SAFE_HAVEN_KEYWORDS = frozenset(
    {
        "war",
        "conflict",
        "geopolitical",
        "crisis",
        "escalation",
        "invasion",
        "sanctions",
        "terror",
        "tension",
        "uncertainty",
        "recession",
        "bank failure",
        "bank collapse",
        "default",
        "safe haven",
        "flight to safety",
        "risk off",
        "fear",
        "panic",
    }
)

# High-impact event title keywords (for deviation analysis)
HIGH_IMPACT_EVENTS = frozenset(
    {
        "interest rate",
        "fomc",
        "fed rate",
        "cpi",
        "nfp",
        "nonfarm",
        "non-farm",
        "gdp",
        "retail sales",
        "pmi",
        "unemployment",
        "jobless",
    }
)

# Impact multiplier by impact level
IMPACT_WEIGHT = {
    "LOW": 0.3,
    "MEDIUM": 0.6,
    "HIGH": 1.0,
    "CRITICAL": 1.5,
}

# Confidence thresholds
CONF_BULLISH = 0.68
CONF_BEARISH = 0.68
CONF_NEUTRAL = 0.55

# Scoring thresholds for aggregate fundamental score
SCORE_BULLISH = 0.15
SCORE_BEARISH = -0.15


class FundamentalAnalystAgent(BaseAgent):
    """Deterministic fundamental analyst using economic calendar data.

    Reads economic_events from the scheduler context (injected by
    NewsFeedProvider) and produces a directional signal for XAUUSD.
    """

    SYSTEM_PROMPT = (
        "Evaluate fundamental drivers through deterministic rules: interest "
        "rate differential, high-impact deviations (CPI/NFP/GDP actual vs "
        "forecast), and risk sentiment (safe-haven flows)."
    )

    def __init__(self) -> None:
        super().__init__(
            name="fundamental_analyst",
            agent_type="fundamental",
            description=(
                "Deterministic fundamental analysis from economic calendar "
                "(interest rates, CPI, NFP, GDP, risk sentiment)"
            ),
            priority=AgentPriority.HIGH,
        )
        self.capabilities = [
            AgentCapability("economic_calendar", "Monitors economic events"),
            AgentCapability(
                "interest_rate_differential",
                "Hawkish/dovish rate analysis",
            ),
            AgentCapability(
                "high_impact_deviations",
                "CPI/NFP/GDP actual vs forecast",
            ),
            AgentCapability(
                "risk_sentiment",
                "Safe-haven flow detection",
            ),
        ]

    def can_handle(self, event_type: str, context: dict[str, Any]) -> bool:
        """Handle fundamental / economic / earnings event types."""
        prefixes = ("ECONOMIC_", "EARNINGS_", "INTEREST_RATE_", "FOMC_", "FED_")
        if any(event_type.startswith(p) for p in prefixes):
            return True
        # Also handle when economic_events are present in context
        econ = context.get("economic_events") or context.get("calendar")
        if isinstance(econ, list) and len(econ) > 0:
            return True
        return False

    # -- parsing -----------------------------------------------------------

    @staticmethod
    def _parse_events(source: Any) -> list[EconomicEvent]:
        """Parse economic events from context (list of dicts)."""
        if not source or not isinstance(source, list):
            return []
        events: list[EconomicEvent] = []
        for item in source:
            if not isinstance(item, dict):
                continue
            events.append(
                EconomicEvent(
                    title=str(item.get("title", item.get("event", ""))),
                    currency=str(item.get("currency", "")),
                    impact=str(item.get("impact", "LOW")).upper(),
                    actual=str(item.get("actual", "")),
                    forecast=str(item.get("forecast", "")),
                    previous=str(item.get("previous", "")),
                    sentiment=float(item.get("sentiment", 0)),
                    category=str(item.get("category", "GENERAL")),
                )
            )
        return events

    @staticmethod
    def _input(context: dict[str, Any]) -> FundamentalInput:
        """Assemble FundamentalInput from scheduler context."""
        source = context.get("sentiment", context)
        if isinstance(source, FundamentalInput):
            return source
        if source is None:
            source = {}
        if not isinstance(source, dict):
            source = {}
        econ_raw = (
            source.get("economic_events")
            or context.get("economic_events")
            or source.get("calendar")
            or context.get("calendar")
            or []
        )
        events = FundamentalAnalystAgent._parse_events(econ_raw)
        symbol = str(source.get("symbol", context.get("symbol", "XAUUSD")))
        risk_sentiment = float(source.get("risk_sentiment", 0.0))
        return FundamentalInput(
            events=events,
            symbol=symbol,
            risk_sentiment=risk_sentiment,
        )

    # -- scoring helpers ---------------------------------------------------

    @staticmethod
    def _text_sentiment(text: str) -> float:
        """Score text from -1.0 (dovish) to +1.0 (hawkish)."""
        if not text:
            return 0.0
        lower = text.lower()
        score = 0.0
        for kw in HAWKISH_KEYWORDS:
            if kw in lower:
                score += 0.5
        for kw in DOVISH_KEYWORDS:
            if kw in lower:
                score -= 0.5
        for kw in SAFE_HAVEN_KEYWORDS:
            if kw in lower:
                # Safe haven → gold bullish → treat as dovish for USD
                score -= 0.4
        return max(-1.0, min(1.0, score))

    @staticmethod
    def _parse_numeric(value: str) -> float | None:
        """Parse a numeric value from string (strip %, strip non-numeric)."""
        if not value or not isinstance(value, str):
            return None
        cleaned = value.strip().rstrip("%").strip()
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            # Try extracting first number from string
            import re

            match = re.search(r"-?\d+\.?\d*", cleaned)
            if match:
                try:
                    return float(match.group())
                except ValueError:
                    return None
            return None

    def _deviation_score(self, event: EconomicEvent) -> tuple[float, str]:
        """Compute deviation score from actual vs forecast.

        Returns (score, reason). Positive = USD bullish (gold bearish).
        """
        if not event.has_deviation:
            # Use sentiment field if available
            return event.sentiment, ""
        actual = self._parse_numeric(event.actual)
        forecast = self._parse_numeric(event.forecast)
        if actual is None or forecast is None:
            return event.sentiment, ""
        diff = actual - forecast
        # Normalize: small diffs (< 0.1) → small impact, large diffs → large
        # Use a simple scaling factor based on impact level
        weight = IMPACT_WEIGHT.get(event.impact, 0.3)
        # Cap the normalized deviation at ±1.0
        normalized = max(-1.0, min(1.0, diff * weight * 10))
        reason = (
            f"{event.title}: actual {event.actual} vs forecast "
            f"{event.forecast} (deviation {diff:+.2f})"
        )
        return normalized, reason

    # -- main analysis -----------------------------------------------------

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Run deterministic fundamental analysis and return result dict."""
        try:
            data = self._input(context)
            if not data.events:
                return {
                    "agent": self.name,
                    "signal": "NEUTRAL",
                    "confidence": CONF_NEUTRAL,
                    "reasons": ["No economic events available for analysis"],
                    "metrics": {
                        "event_count": 0,
                        "hawkish_score": 0.0,
                        "dovish_score": 0.0,
                        "safe_haven_score": 0.0,
                        "net_fundamental_score": 0.0,
                    },
                }

            hawkish_score = 0.0
            dovish_score = 0.0
            safe_haven_score = 0.0
            deviation_reasons: list[str] = []
            event_count = len(data.events)
            high_impact_count = 0

            for event in data.events:
                # Text sentiment from title
                text_score = self._text_sentiment(event.title)
                # Deviation score
                dev_score, dev_reason = self._deviation_score(event)
                # Combine: use deviation if available, else use text + sentiment
                combined = (
                    dev_score
                    if event.has_deviation
                    else (
                        (text_score + event.sentiment) / 2
                        if (text_score or event.sentiment)
                        else 0.0
                    )
                )
                combined = max(-1.0, min(1.0, combined))

                weight = IMPACT_WEIGHT.get(event.impact, 0.3)

                if combined > 0:
                    hawkish_score += combined * weight
                elif combined < 0:
                    dovish_score += abs(combined) * weight

                # Check for safe-haven keywords
                lower_title = event.title.lower()
                if any(kw in lower_title for kw in SAFE_HAVEN_KEYWORDS):
                    safe_haven_score += 0.3 * weight

                if event.is_high_impact:
                    high_impact_count += 1

                if dev_reason:
                    deviation_reasons.append(dev_reason)

            # Add risk sentiment from context
            if data.risk_sentiment < 0:
                # Risk-off → safe haven demand → gold bullish
                safe_haven_score += abs(data.risk_sentiment)

            # Net fundamental score: positive = USD bullish (gold bearish)
            # negative = USD bearish (gold bullish)
            net_score = hawkish_score - dovish_score - safe_haven_score

            # For XAUUSD: invert USD direction
            # hawkish USD → XAUUSD bearish
            # dovish USD / safe haven → XAUUSD bullish
            if SCORE_BEARISH <= net_score <= SCORE_BULLISH:
                # Neutral zone
                signal = "NEUTRAL"
                confidence = CONF_NEUTRAL
            elif net_score > 0:
                # USD bullish → XAUUSD bearish
                signal = "BEARISH"
                confidence = min(0.85, CONF_BEARISH + abs(net_score) * 0.1)
            else:
                # USD bearish / safe haven → XAUUSD bullish
                signal = "BULLISH"
                confidence = min(0.85, CONF_BULLISH + abs(net_score) * 0.1)

            reasoning: list[str] = [
                f"Analyzed {event_count} economic events " f"({high_impact_count} high-impact)",
                f"Hawkish score: {hawkish_score:.3f}",
                f"Dovish score: {dovish_score:.3f}",
                f"Safe-haven score: {safe_haven_score:.3f}",
                f"Net fundamental score: {net_score:.3f}",
            ]
            reasoning.extend(deviation_reasons[:5])  # top 5 deviations

            metrics = {
                "event_count": float(event_count),
                "high_impact_count": float(high_impact_count),
                "hawkish_score": round(hawkish_score, 6),
                "dovish_score": round(dovish_score, 6),
                "safe_haven_score": round(safe_haven_score, 6),
                "net_fundamental_score": round(net_score, 6),
            }

            return {
                "agent": self.name,
                "signal": signal,
                "confidence": round(confidence, 4),
                "reasons": reasoning,
                "metrics": metrics,
            }
        except (TypeError, ValueError, KeyError) as exc:
            return {
                "agent": self.name,
                "signal": "NEUTRAL",
                "confidence": CONF_NEUTRAL,
                "reasons": [f"Fundamental analysis error: {exc}"],
                "metrics": {},
            }


FundamentalAnalyst = FundamentalAnalystAgent
