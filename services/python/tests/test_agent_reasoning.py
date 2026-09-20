# -*- coding: utf-8 -*-
"""Tests for the sharpened technical analyst + agent pattern memory (PRD §43)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.agents.agent_memory import AgentOutcome, AgentPatternMemory
from src.agents.base import TechnicalAnalystAgent

# --- Test doubles for detected events ---------------------------------------


@dataclass
class FakeEventType:
    value: str


@dataclass
class FakeEvent:
    event_type: FakeEventType


@dataclass
class FakeMarketState:
    trend_direction: str = ""
    adx_value: float = 0.0


def _ev(name: str) -> FakeEvent:
    return FakeEvent(FakeEventType(name))


def _events(*names: str) -> list[Any]:
    return [_ev(n) for n in names]


# --- Agent pattern memory ----------------------------------------------------


def test_memory_insufficient_sample() -> None:
    mem = AgentPatternMemory(min_samples=5)
    mem.record_outcome("technical_analyst", "BULLISH", True, regime="trend_up")
    skill = mem.skill_for("technical_analyst", "trend_up")
    assert skill is not None
    assert skill.reliable is False
    assert skill.status == "INSUFFICIENT_SAMPLE"


def test_memory_confidence_adjust_up() -> None:
    mem = AgentPatternMemory(min_samples=4)
    for _ in range(8):
        mem.record_outcome("technical_analyst", "BULLISH", True, regime="trend_up")
    adjusted, note = mem.adjust_confidence("technical_analyst", "trend_up", 0.6)
    assert adjusted > 0.6
    assert "correct in trend_up" in note


def test_memory_confidence_adjust_down() -> None:
    mem = AgentPatternMemory(min_samples=4)
    for i in range(8):
        mem.record_outcome("technical_analyst", "BULLISH", i % 4 == 0, regime="range")
    adjusted, _ = mem.adjust_confidence("technical_analyst", "range", 0.6)
    assert adjusted < 0.6


def test_memory_confidence_clamped() -> None:
    mem = AgentPatternMemory(min_samples=2)
    for _ in range(6):
        mem.record_outcome("a", "BULLISH", True, regime="r")
    adjusted, _ = mem.adjust_confidence("a", "r", 0.95)
    assert 0.0 <= adjusted <= 1.0


def test_memory_unknown_agent() -> None:
    mem = AgentPatternMemory(min_samples=2)
    adjusted, note = mem.adjust_confidence("nobody", "range", 0.5)
    assert adjusted == 0.5
    assert "no prior record" in note


def test_memory_bounded() -> None:
    mem = AgentPatternMemory(min_samples=1, max_records=3)
    for i in range(6):
        mem.record(AgentOutcome(agent="a", regime="r", direction="BULLISH", correct=True))
    assert len(mem.outcomes()) == 3


# --- Technical analyst sharpening -------------------------------------------


def test_analyst_no_events() -> None:
    agent = TechnicalAnalystAgent()
    out = agent.analyze({"detected_events": []})
    assert out["signal"] == "NEUTRAL"
    assert out["event_count"] == 0


def test_analyst_weighted_bullish() -> None:
    agent = TechnicalAnalystAgent()
    out = agent.analyze(
        {"detected_events": _events("TREND_BULLISH", "MOMENTUM_BULLISH", "BREAKOUT")}
    )
    assert out["signal"] == "BULLISH"
    assert out["evidence"]["net"] > 0
    assert out["confidence"] > 0.5


def test_analyst_weighted_bearish() -> None:
    agent = TechnicalAnalystAgent()
    out = agent.analyze(
        {"detected_events": _events("TREND_BEARISH", "MOMENTUM_BEARISH", "BREAKDOWN")}
    )
    assert out["signal"] == "BEARISH"
    assert out["evidence"]["net"] < 0


def test_analyst_conflict_reduces_confidence() -> None:
    agent = TechnicalAnalystAgent()
    out = agent.analyze({"detected_events": _events("TREND_BULLISH", "TREND_BEARISH")})
    assert out["conflict"] is True
    # Balanced evidence → low confidence.
    assert out["confidence"] < 0.5


def test_analyst_regime_discount() -> None:
    agent = TechnicalAnalystAgent()
    # Strong uptrend: bearing oscillator read discounted.
    out = agent.analyze(
        {
            "detected_events": _events("TREND_BULLISH", "RSI_OVERBOUGHT"),
            "market_state": FakeMarketState(trend_direction="up", adx_value=30.0),
        }
    )
    assert out["signal"] == "BULLISH"
    assert out["regime"] == "trend_up"


def test_analyst_uses_memory(monkeypatch) -> None:
    import src.agents.agent_memory as am

    mem = AgentPatternMemory(min_samples=2)
    for _ in range(6):
        mem.record_outcome("technical_analyst", "BULLISH", True, regime="trend_up")
    monkeypatch.setattr(am, "_INSTANCE", mem)

    agent = TechnicalAnalystAgent()
    out = agent.analyze(
        {
            "detected_events": _events("TREND_BULLISH"),
            "market_state": FakeMarketState(trend_direction="up", adx_value=30.0),
        }
    )
    joined = " ".join(out["reasons"])
    assert "correct in trend_up" in joined
