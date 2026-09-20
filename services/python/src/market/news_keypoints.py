# -*- coding: utf-8 -*-
"""News key-points extraction — "why this matters" for a headline/event.

The news page shows a table; clicking a row should reveal the *important
points* — not raw chain-of-thought, but a short, deterministic breakdown:
impact read, affected instruments, direction, and the drivers in the text.

This is a deterministic NLP-lite extractor (no LLM): it uses the same keyword
vocabularies that score sentiment, plus a small instrument map, so the output
is explainable and reproducible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

__all__ = ["extract_key_points", "KeyPoints"]


# Instrument sensitivity map: a topic keyword → symbols typically affected and
# the direction of the *first-order* reaction.
_TOPIC_INSTRUMENTS: dict[str, dict[str, Any]] = {
    "inflation": {
        "symbols": ["XAUUSD", "DXY", "US10Y"],
        "note": "hot CPI lifts yields, pressures gold",
    },
    "cpi": {"symbols": ["XAUUSD", "DXY", "US10Y"], "note": "hot CPI lifts yields, pressures gold"},
    "rate": {
        "symbols": ["XAUUSD", "DXY", "UST"],
        "note": "higher rates strengthen USD, weigh on gold",
    },
    "fomc": {"symbols": ["XAUUSD", "DXY", "SPX"], "note": "hawkish tone strengthens USD"},
    "fed": {"symbols": ["XAUUSD", "DXY"], "note": "policy path drives USD and gold"},
    "powell": {"symbols": ["XAUUSD", "DXY", "SPX"], "note": "guidance moves rate expectations"},
    "jobs": {"symbols": ["DXY", "XAUUSD"], "note": "strong payrolls firm the USD"},
    "payroll": {"symbols": ["DXY", "XAUUSD"], "note": "strong payrolls firm the USD"},
    "nfp": {"symbols": ["DXY", "XAUUSD"], "note": "strong payrolls firm the USD"},
    "unemployment": {"symbols": ["DXY", "XAUUSD"], "note": "lower unemployment supports USD"},
    "gdp": {"symbols": ["DXY", "SPX"], "note": "growth surprise moves risk assets & USD"},
    "tariff": {"symbols": ["SPX", "CNH", "XAUUSD"], "note": "trade tension lifts safe havens"},
    "war": {
        "symbols": ["XAUUSD", "OIL", "CHF"],
        "note": "geopolitical risk lifts safe havens & oil",
    },
    "sanction": {"symbols": ["OIL", "XAUUSD"], "note": "supply risk lifts oil & havens"},
    "oil": {"symbols": ["USOIL", "CAD"], "note": "crude moves drive CAD and energy"},
    "gold": {"symbols": ["XAUUSD"], "note": "direct gold driver"},
}

_BULL_WORDS = ("rise", "rises", "gain", "gains", "up", "strong", "beat", "surge", "rally", "higher")
_BEAR_WORDS = ("fall", "falls", "drop", "drops", "down", "weak", "miss", "plunge", "slump", "lower")
_RISK_WORDS = ("war", "crisis", "default", "escalat", "sanction", "conflict")


@dataclass
class KeyPoints:
    """Structured key points for one news item / event."""

    summary: str
    impact: str
    direction: str  # BULLISH | BEARISH | NEUTRAL
    drivers: list[str] = field(default_factory=list)
    affected_instruments: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "impact": self.impact,
            "direction": self.direction,
            "drivers": list(self.drivers),
            "affected_instruments": list(self.affected_instruments),
            "notes": list(self.notes),
        }


def _first_sentence(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", text)
    return parts[0][:240]


def extract_key_points(
    headline: str,
    *,
    sentiment: float = 0.0,
    impact: str = "LOW",
    country: str = "",
    forecast: str = "",
    previous: str = "",
    actual: str = "",
) -> KeyPoints:
    """Extract deterministic key points from a headline or calendar event."""
    lower = (headline or "").lower()

    # Direction from sentiment sign (falls back to word scan).
    if sentiment > 0.15:
        direction = "BULLISH"
    elif sentiment < -0.15:
        direction = "BEARISH"
    else:
        pos = sum(1 for w in _BULL_WORDS if w in lower)
        neg = sum(1 for w in _BEAR_WORDS if w in lower)
        direction = "BULLISH" if pos > neg else "BEARISH" if neg > pos else "NEUTRAL"

    # Topic + instruments.
    instruments: list[str] = []
    notes: list[str] = []
    for topic, meta in _TOPIC_INSTRUMENTS.items():
        if topic in lower:
            for sym in meta["symbols"]:
                if sym not in instruments:
                    instruments.append(sym)
            notes.append(meta["note"])

    if any(w in lower for w in _RISK_WORDS):
        notes.append("Risk-off: safe-haven demand likely")

    # Data surprise (calendar events).
    drivers: list[str] = []
    if country:
        drivers.append(f"Region: {country.upper()}")
    if forecast or previous or actual:
        bits = []
        if actual:
            bits.append(f"actual {actual}")
        if forecast:
            bits.append(f"forecast {forecast}")
        if previous:
            bits.append(f"previous {previous}")
        if bits:
            drivers.append("Data: " + ", ".join(bits))

    summary = _first_sentence(headline)
    if not summary:
        summary = "—"

    return KeyPoints(
        summary=summary,
        impact=(impact or "LOW").upper(),
        direction=direction,
        drivers=drivers,
        affected_instruments=instruments,
        notes=notes,
    )
