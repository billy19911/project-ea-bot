# -*- coding: utf-8 -*-
"""Tests for news key-points extraction."""

from __future__ import annotations

from src.market.news_keypoints import extract_key_points


def test_basic_bullish() -> None:
    kp = extract_key_points("Stocks rally as inflation cools", sentiment=0.6, impact="HIGH")
    assert kp.direction == "BULLISH"
    assert kp.impact == "HIGH"
    assert "XAUUSD" in kp.affected_instruments or "DXY" in kp.affected_instruments


def test_bearish_from_sentiment() -> None:
    kp = extract_key_points("Gold plunges on hawkish Fed", sentiment=-0.7)
    assert kp.direction == "BEARISH"


def test_direction_from_words_when_neutral() -> None:
    kp = extract_key_points("Oil prices surge on supply cuts", sentiment=0.0)
    assert kp.direction == "BULLISH"


def test_calendar_event_drivers() -> None:
    kp = extract_key_points(
        "US CPI m/m",
        impact="High",
        country="USD",
        forecast="3.0%",
        previous="2.9%",
        actual="3.2%",
    )
    joined = " ".join(kp.drivers)
    assert "Region: USD" in joined
    assert "actual 3.2%" in joined
    assert "forecast 3.0%" in joined


def test_geopolitical_note() -> None:
    kp = extract_key_points("War escalates in region", sentiment=-0.5)
    assert any("Risk-off" in n for n in kp.notes)


def test_summary_first_sentence() -> None:
    kp = extract_key_points("Fed holds rates. Markets react later.")
    assert kp.summary == "Fed holds rates."


def test_empty_headline_no_crash() -> None:
    kp = extract_key_points("")
    assert kp.summary == "—"
    assert kp.direction == "NEUTRAL"


def test_to_dict() -> None:
    d = extract_key_points("CPI rises", sentiment=0.3).to_dict()
    for key in ("summary", "impact", "direction", "drivers", "affected_instruments", "notes"):
        assert key in d
