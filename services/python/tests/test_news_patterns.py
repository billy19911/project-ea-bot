# -*- coding: utf-8 -*-
"""Tests for news pattern memory + news agent pattern reasoning (PRD §43/§54)."""

from __future__ import annotations

import os
import tempfile

import pytest

from src.market.news_patterns import NewsOutcomeRow, NewsPatternMemory, normalise_event_key


@pytest.fixture
def temp_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    yield path
    try:
        os.remove(path)
    except OSError:
        pass


def test_normalise_event_key() -> None:
    assert normalise_event_key("US CPI m/m", "USD") == "USD:CPI"
    assert normalise_event_key("Non-Farm Payrolls", "USD") == "USD:NFP"
    assert normalise_event_key("FOMC Statement", "USD") == "USD:FOMC"
    assert normalise_event_key("Random thing", "USD") == "USD:OTHER"


def test_classify_surprise() -> None:
    assert NewsPatternMemory._classify_surprise("3.0%", "3.2%") == "beat"
    assert NewsPatternMemory._classify_surprise("3.2%", "3.0%") == "miss"
    assert NewsPatternMemory._classify_surprise("3.0%", "3.0%") == "inline"
    assert NewsPatternMemory._classify_surprise("abc", "def") == "unknown"


def test_record_and_patterns(temp_path: str) -> None:
    mem = NewsPatternMemory(path=temp_path, min_samples=3)
    for i in range(4):
        mem.record(
            NewsOutcomeRow(
                event_key="USD:CPI",
                country="USD",
                impact="HIGH",
                surprise="beat",
                symbol="XAUUSD",
                realised_return=-0.002 if i < 3 else 0.001,
            )
        )
    patterns = mem.patterns(event_key="USD:CPI")
    assert len(patterns) == 1
    p = patterns[0]
    assert p.samples == 4
    assert p.reliable is True
    assert p.status == "RELIABLE"
    assert p.bias == "BEARISH"  # 3 down, 1 up


def test_insufficient_sample(temp_path: str) -> None:
    mem = NewsPatternMemory(path=temp_path, min_samples=5)
    mem.record_outcome("US CPI m/m", "USD", "HIGH", "XAUUSD", -0.003, "3.0%", "3.2%")
    p = mem.patterns(event_key="USD:CPI")[0]
    assert p.reliable is False
    assert p.status == "INSUFFICIENT_SAMPLE"


def test_reasoning_reliable(temp_path: str) -> None:
    mem = NewsPatternMemory(path=temp_path, min_samples=3)
    for _ in range(4):
        mem.record_outcome("US CPI m/m", "USD", "HIGH", "XAUUSD", -0.002, "3.0%", "3.2%")
    line = mem.reasoning_for("US CPI m/m", "USD")
    assert line is not None
    assert "USD:CPI" in line
    assert "leans down" in line


def test_reasoning_insufficient(temp_path: str) -> None:
    mem = NewsPatternMemory(path=temp_path, min_samples=5)
    mem.record_outcome("US CPI m/m", "USD", "HIGH", "XAUUSD", -0.002, "3.0%", "3.2%")
    line = mem.reasoning_for("US CPI m/m", "USD")
    assert line is not None
    assert "caution" in line


def test_reasoning_unknown_event(temp_path: str) -> None:
    mem = NewsPatternMemory(path=temp_path, min_samples=1)
    assert mem.reasoning_for("Never seen event", "ZZZ") is None


def test_persistence_roundtrip(temp_path: str) -> None:
    mem = NewsPatternMemory(path=temp_path, min_samples=1)
    mem.record_outcome("US NFP", "USD", "HIGH", "EURUSD", 0.004, "150K", "200K")
    # Fresh instance reads the persisted line.
    mem2 = NewsPatternMemory(path=temp_path, min_samples=1)
    patterns = mem2.patterns(event_key="USD:NFP")
    assert len(patterns) == 1
    assert patterns[0].samples == 1


def test_news_agent_uses_pattern_reasoning(temp_path: str, monkeypatch) -> None:
    from src.agents.analysts import news_agent as na
    from src.market import news_patterns as np_mod

    mem = NewsPatternMemory(path=temp_path, min_samples=2)
    for _ in range(3):
        mem.record_outcome("US CPI m/m", "USD", "HIGH", "XAUUSD", -0.002, "3.0%", "3.2%")
    monkeypatch.setattr(np_mod, "_INSTANCE", mem)

    agent = na.NewsSentimentAgent()
    result = agent.analyze(
        {
            "sentiment": {
                "news_items": [],
                "economic_events": [{"title": "US CPI m/m", "country": "USD", "impact": "High"}],
            }
        }
    )
    joined = " ".join(result["reasoning"])
    assert "USD:CPI" in joined
    assert result["metrics"]["pattern_notes"] >= 1.0


def test_news_agent_fails_safe_without_memory(monkeypatch) -> None:
    from src.agents.analysts import news_agent as na

    def boom():
        raise RuntimeError("no memory")

    monkeypatch.setattr("src.market.news_patterns.get_news_pattern_memory", boom, raising=False)
    agent = na.NewsSentimentAgent()
    # Must not raise; reasoning just lacks pattern notes.
    result = agent.analyze(
        {"sentiment": {"news_items": [{"headline": "Gold up", "sentiment": 0.5}]}}
    )
    assert result["signal"] in {"BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN"}
