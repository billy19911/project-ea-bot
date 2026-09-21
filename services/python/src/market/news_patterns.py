# -*- coding: utf-8 -*-
"""News Pattern Memory — historical news/event outcome learning (PRD_V2 §43/§54).

The news agent should not treat every headline in isolation. This module learns
*directional patterns* from past news/economic events so the committee can be
given a reasoned, evidence-backed view ("USD CPI surprises tend to move DXY up /
gold down") instead of a raw sentiment number.

Design rules:

* **Deterministic** — patterns are simple weighted statistics; no LLM.
* **Evidence-gated** — a pattern is only *actionable* once it has enough
  samples (``min_samples``); below that it is reported as ``INSUFFICIENT_SAMPLE``.
* **Advisory** — patterns inform the news agent's reasoning and confidence; they
  never directly create or size an order.
* **Persisted** — patterns are stored as JSONL so they survive restarts.

A row records, for one event: ``event_key`` (normalised event type, e.g.
``USD:CPI``), ``country``, ``impact``, ``surprise`` (ACTUAL minus FORECAST sign:
``beat``/``miss``/``inline``) and the realised ``return`` for a tracked symbol
over a short horizon.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "NewsOutcomeRow",
    "NewsPattern",
    "NewsPatternMemory",
    "get_news_pattern_memory",
    "normalise_event_key",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Event-type keyword → canonical token, used to group similar events.
_EVENT_TOKENS = (
    ("non-farm", "NFP"),
    ("nonfarm", "NFP"),
    ("nfp", "NFP"),
    ("interest rate", "RATE"),
    ("rate decision", "RATE"),
    ("fomc", "FOMC"),
    ("cpi", "CPI"),
    ("inflation", "CPI"),
    ("ppi", "PPI"),
    ("gdp", "GDP"),
    ("unemployment", "UNEMPLOYMENT"),
    ("jobless", "JOBLESS"),
    ("retail sales", "RETAIL_SALES"),
    ("pmi", "PMI"),
    ("pce", "PCE"),
    ("powell", "FED_SPEAK"),
    ("speaks", "FED_SPEAK"),
    ("tariff", "TARIFF"),
    ("war", "GEOPOLITICAL"),
    ("sanction", "GEOPOLITICAL"),
)


def normalise_event_key(title: str, country: str) -> str:
    """Return a stable ``COUNTRY:TOKEN`` key for a news/event title."""
    lower = (title or "").lower()
    token = "OTHER"
    for keyword, tok in _EVENT_TOKENS:
        if keyword in lower:
            token = tok
            break
    return f"{(country or 'XX').upper()}:{token}"


@dataclass(frozen=True)
class NewsOutcomeRow:
    """One observed news/event → market outcome sample."""

    event_key: str
    country: str
    impact: str
    surprise: str  # beat | miss | inline | unknown
    symbol: str
    realised_return: float  # signed return over the tracked horizon
    horizon: str = "H1"
    timestamp: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NewsPattern:
    """An aggregated directional pattern for an event key."""

    event_key: str
    samples: int = 0
    up: int = 0
    down: int = 0
    flat: int = 0
    avg_return: float = 0.0
    total_return: float = 0.0
    reliable: bool = False
    status: str = "INSUFFICIENT_SAMPLE"
    bias: str = "NEUTRAL"

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_key": self.event_key,
            "samples": self.samples,
            "up": self.up,
            "down": self.down,
            "flat": self.flat,
            "avg_return": round(self.avg_return, 6),
            "reliable": self.reliable,
            "status": self.status,
            "bias": self.bias,
        }


class NewsPatternMemory:
    """Persistent store of news patterns (JSONL, fail-safe)."""

    def __init__(
        self,
        path: Optional[str] = None,
        min_samples: int = 5,
    ) -> None:
        self.path = str(
            path or os.getenv("NEWS_PATTERN_PATH") or os.path.join("logs", "news_patterns.jsonl")
        )
        self.min_samples = min_samples
        self._lock = threading.Lock()
        self._rows: list[NewsOutcomeRow] = []
        self._load()

    # -- persistence -------------------------------------------------------
    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    try:
                        self._rows.append(
                            NewsOutcomeRow(
                                event_key=str(raw.get("event_key", "")),
                                country=str(raw.get("country", "")),
                                impact=str(raw.get("impact", "LOW")),
                                surprise=str(raw.get("surprise", "unknown")),
                                symbol=str(raw.get("symbol", "")),
                                realised_return=float(raw.get("realised_return", 0.0)),
                                horizon=str(raw.get("horizon", "H1")),
                                timestamp=str(raw.get("timestamp", _now())),
                            )
                        )
                    except (TypeError, ValueError):
                        continue
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("news_patterns: unreadable (%s)", exc)

    def _append_line(self, row: NewsOutcomeRow) -> None:
        try:
            parent = os.path.dirname(self.path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(row.to_dict()) + "\n")
        except OSError as exc:
            logger.warning("news_patterns: write failed (%s)", exc)

    # -- ingestion ---------------------------------------------------------
    def record(self, row: NewsOutcomeRow) -> NewsOutcomeRow:
        with self._lock:
            self._rows.append(row)
            self._append_line(row)
        return row

    def record_outcome(
        self,
        title: str,
        country: str,
        impact: str,
        symbol: str,
        realised_return: float,
        forecast: str = "",
        actual: str = "",
        horizon: str = "H1",
    ) -> NewsOutcomeRow:
        """Normalise + record one outcome from raw event data."""
        surprise = self._classify_surprise(forecast, actual)
        row = NewsOutcomeRow(
            event_key=normalise_event_key(title, country),
            country=(country or "XX").upper(),
            impact=impact,
            surprise=surprise,
            symbol=symbol,
            realised_return=float(realised_return),
            horizon=horizon,
        )
        return self.record(row)

    @staticmethod
    def _classify_surprise(forecast: str, actual: str) -> str:
        """Classify a data surprise as beat / miss / inline / unknown."""
        try:
            f = float(str(forecast).replace("%", "").replace("K", "").replace("M", "").strip())
            a = float(str(actual).replace("%", "").replace("K", "").replace("M", "").strip())
        except (TypeError, ValueError):
            return "unknown"
        if a > f:
            return "beat"
        if a < f:
            return "miss"
        return "inline"

    # -- aggregation -------------------------------------------------------
    def rows(self) -> list[NewsOutcomeRow]:
        with self._lock:
            return list(self._rows)

    def patterns(
        self,
        event_key: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> list[NewsPattern]:
        """Return aggregated patterns, optionally filtered."""
        with self._lock:
            rows = list(self._rows)
        if event_key:
            rows = [r for r in rows if r.event_key == event_key]
        if symbol:
            rows = [r for r in rows if r.symbol == symbol]

        buckets: dict[str, NewsPattern] = {}
        for r in rows:
            p = buckets.get(r.event_key)
            if p is None:
                p = NewsPattern(event_key=r.event_key)
                buckets[r.event_key] = p
            p.samples += 1
            p.total_return += r.realised_return
            if r.realised_return > 0:
                p.up += 1
            elif r.realised_return < 0:
                p.down += 1
            else:
                p.flat += 1

        for p in buckets.values():
            p.avg_return = p.total_return / p.samples if p.samples else 0.0
            p.reliable = p.samples >= self.min_samples
            p.status = "RELIABLE" if p.reliable else "INSUFFICIENT_SAMPLE"
            if p.up > p.down:
                p.bias = "BULLISH"
            elif p.down > p.up:
                p.bias = "BEARISH"
            else:
                p.bias = "NEUTRAL"
        out = sorted(buckets.values(), key=lambda x: (-x.samples, x.event_key))
        return out

    def pattern_for(self, title: str, country: str) -> Optional[NewsPattern]:
        key = normalise_event_key(title, country)
        for p in self.patterns(event_key=key):
            return p
        return None

    def reasoning_for(self, title: str, country: str) -> Optional[str]:
        """Return a human-readable, evidence-backed reasoning line, or None."""
        p = self.pattern_for(title, country)
        if p is None:
            return None
        key = p.event_key
        if not p.reliable:
            return (
                f"{key}: only {p.samples} historical sample(s) "
                f"(need >= {self.min_samples}) — treat with caution"
            )
        direction = "up" if p.bias == "BULLISH" else "down" if p.bias == "BEARISH" else "flat"
        return (
            f"{key}: {p.samples} past cases, {p.up} up / {p.down} down "
            f"(avg {p.avg_return:+.3%}) — historically leans {direction}"
        )


_INSTANCE: Optional[NewsPatternMemory] = None
_SHARED_KEY = "_ea_shared_news_patterns"


def get_news_pattern_memory() -> NewsPatternMemory:
    """Return the process-wide news pattern memory (lazy singleton).

    Stored on a process-global slot so the ``src.market.*`` / ``market.*``
    import identities share ONE store.
    """
    global _INSTANCE
    if _INSTANCE is None:
        import builtins

        shared = getattr(builtins, _SHARED_KEY, None)
        if shared is not None:
            _INSTANCE = shared
        else:
            _INSTANCE = NewsPatternMemory()
            setattr(builtins, _SHARED_KEY, _INSTANCE)
    return _INSTANCE
