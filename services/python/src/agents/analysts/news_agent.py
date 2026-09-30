# -*- coding: utf-8 -*-
"""Deterministic news/sentiment analysis agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..base import AgentCapability, AgentPriority, BaseAgent


class SentimentDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class ImpactLevel(int, Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class NewsItem:
    """Single news/calandar item."""

    headline: str = ""
    sentiment: float = 0.0
    impact: str = "LOW"
    category: str = "GENERAL"
    time_utc: str = ""


@dataclass
class NewsSentimentInput:
    """Unified input schema for news sentiment analysis."""

    news_items: list[NewsItem] = field(default_factory=list)
    economic_events: list[dict[str, Any]] = field(default_factory=list)
    sentiment_override: float = 0.0


@dataclass
class NewsSentimentOutput:
    """Stable news sentiment agent output schema."""

    signal: str
    confidence: float
    reasoning: list[str]
    metrics: dict[str, float]


IMPACT_SCORE = {"LOW": 1.0, "MEDIUM": 2.0, "HIGH": 3.5, "CRITICAL": 5.0}
SENTIMENT_THRESH_HIGH = 0.4
SENTIMENT_THRESH_LOW = -0.4
CRITICAL_IMPACT_COUNT = 1


class NewsSentimentAgent(BaseAgent):
    """Evaluate news headlines and economic calendar for sentiment impact."""

    SYSTEM_PROMPT = (
        "Evaluate news sentiment through deterministic rules. Use headline "
        "sentiment scores and economic impact levels. Filter high-impact events."
    )

    def __init__(self) -> None:
        super().__init__(
            name="news_sentiment",
            agent_type="news",
            description="Deterministic news sentiment and high-impact news filter",
            priority=AgentPriority.HIGH,
            display_name="NEWS-WIRE",
        )
        self.capabilities = [
            AgentCapability("news_analysis", "Analyzes news headlines for sentiment"),
            AgentCapability("event_filtering", "Filters high-impact economic events"),
            AgentCapability("impact_assessment", "Scores combined market impact"),
        ]

    def can_handle(self, event_type: str, context: dict[str, Any]) -> bool:
        if event_type.startswith("NEWS_") or event_type.startswith("SOCIAL_"):
            return True
        return bool(context.get("sentiment") or context.get("news_items"))

    @staticmethod
    def _parse_news_items(source: Any) -> list[NewsItem]:
        if not source or not isinstance(source, list):
            return []
        items = []
        for item in source:
            if isinstance(item, dict):
                items.append(
                    NewsItem(
                        headline=str(item.get("headline", "")),
                        sentiment=float(item.get("sentiment", 0)),
                        impact=str(item.get("impact", "LOW")),
                        category=str(item.get("category", "GENERAL")),
                    )
                )
            elif isinstance(item, NewsItem):
                items.append(item)
        return items

    @staticmethod
    def _input(context: dict[str, Any]) -> NewsSentimentInput:
        source = context.get("sentiment", context)
        if isinstance(source, NewsSentimentInput):
            return source
        if source is None:
            return NewsSentimentInput()
        news = NewsSentimentAgent._parse_news_items(source.get("news_items", []))
        econ = source.get("economic_events", source.get("calendar", []))
        return NewsSentimentInput(
            news_items=news,
            economic_events=list(econ) if isinstance(econ, list) else [],
            sentiment_override=float(source.get("sentiment_override", 0)),
        )

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Return deterministic sentiment assessment."""
        try:
            data = self._input(context)
            total_sentiment = 0.0
            weighted_impact = 0.0
            high_impact_events: list[dict[str, Any]] = []
            for item in data.news_items:
                s = max(-1.0, min(1.0, item.sentiment))
                total_sentiment += s
                level = IMPACT_SCORE.get(item.impact.upper(), IMPACT_SCORE["LOW"])
                weighted_impact += s * level
            for ev in data.economic_events:
                impact_val = ev.get("impact", "LOW")
                level = IMPACT_SCORE.get(str(impact_val).upper(), IMPACT_SCORE["LOW"])
                if level >= IMPACT_SCORE["HIGH"]:
                    high_impact_events.append(ev)
                sentiment = float(ev.get("sentiment", 0))
                weighted_impact += sentiment * level
            avg_sentiment = total_sentiment / len(data.news_items) if data.news_items else 0.0
            high_impact_count = len(high_impact_events)
            has_critical = any(
                IMPACT_SCORE.get(str(e.get("impact", "LOW")).upper(), 1) >= IMPACT_SCORE["CRITICAL"]
                for e in high_impact_events
            )
            # Directional signal from the WEIGHTED news sentiment. A high-impact
            # event only matters when it also carries directional sentiment; an
            # event with no realised deviation (sentiment 0) must NOT force a
            # BEARISH call. This keeps the committee honest and related to the
            # actual data instead of defaulting to BEARISH on any high-impact day.
            if avg_sentiment >= SENTIMENT_THRESH_HIGH:
                signal, confidence = "BULLISH", min(0.85, 0.6 + avg_sentiment)
            elif avg_sentiment <= SENTIMENT_THRESH_LOW:
                signal, confidence = "BEARISH", min(0.85, 0.6 + abs(avg_sentiment))
            elif weighted_impact <= -IMPACT_SCORE["HIGH"]:
                # Strongly negative net impact (weighted) → mild bearish tilt.
                signal, confidence = "BEARISH", 0.62
            elif weighted_impact >= IMPACT_SCORE["HIGH"]:
                signal, confidence = "BULLISH", 0.62
            else:
                signal, confidence = "NEUTRAL", 0.55

            reasoning = [
                f"Sentimen berita bersih: {avg_sentiment:+.3f} "
                f"(dari {len(data.news_items)} berita)",
            ]
            if high_impact_events:
                titles = [
                    str(e.get("title") or e.get("headline") or "").strip()
                    for e in high_impact_events
                ]
                titles = [t for t in titles if t]
                shown = ", ".join(titles[:3])
                extra = f" (+{len(titles) - 3})" if len(titles) > 3 else ""
                reasoning.append(f"{high_impact_count} event berdampak tinggi: {shown}{extra}")
            if has_critical:
                reasoning.append("Ada event berdampak KRITIS di kalender")
            if not data.news_items and not data.economic_events:
                reasoning.append("Tidak ada berita/event untuk dianalisis")

            # Historical pattern memory (PRD §43/§54): add evidence-backed
            # reasoning from similar past events. Advisory only.
            pattern_notes = self._pattern_reasoning(data, context)
            reasoning.extend(pattern_notes)

            metrics = {
                "news_count": len(data.news_items),
                "events_count": len(data.economic_events),
                "high_impact_count": high_impact_count,
                "avg_sentiment": round(avg_sentiment, 6),
                "weighted_impact": round(weighted_impact, 6),
                "has_critical": 1.0 if has_critical else 0.0,
                "pattern_notes": float(len(pattern_notes)),
            }
            return {
                "agent": self.name,
                "signal": signal,
                "confidence": confidence,
                "reasoning": reasoning,
                "metrics": metrics,
            }
        except (TypeError, ValueError, KeyError) as exc:
            return {
                "agent": self.name,
                "signal": "UNKNOWN",
                "confidence": 0.0,
                "reasoning": [f"Invalid sentiment input: {exc}"],
                "metrics": {},
            }

    @staticmethod
    def _pattern_reasoning(data: "NewsSentimentInput", context: dict[str, Any]) -> list[str]:
        """Return evidence-backed reasoning lines from pattern memory.

        Fail-safe: a memory problem never breaks analysis. Returns [] when no
        pattern memory is available or there are no matching events.
        """
        notes: list[str] = []
        try:
            from ...market.news_patterns import get_news_pattern_memory

            memory = get_news_pattern_memory()
            seen: set[str] = set()
            for ev in data.economic_events:
                title = str(ev.get("title", ev.get("headline", "")))
                country = str(ev.get("country", ""))
                if not title:
                    continue
                line = memory.reasoning_for(title, country)
                if line and line not in seen:
                    seen.add(line)
                    notes.append(line)
            for item in data.news_items:
                line = memory.reasoning_for(item.headline, "XX")
                if line and line not in seen:
                    seen.add(line)
                    notes.append(line)
        except Exception:  # noqa: BLE001 - memory must never break analysis
            return notes
        return notes


NewsSentiment = NewsSentimentAgent
