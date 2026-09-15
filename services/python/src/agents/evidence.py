# -*- coding: utf-8 -*-
"""Evidence Model (§8) — typed evidence facts with provenance & quality.

Agents never emit raw prose as their only output; they attach
:class:`EvidenceItem` records (FACT / INTERPRETATION / RECOMMENDATION) to an
:class:`EvidenceBundle`. Each item carries provenance (source, timestamp,
timeframe), a freshness marker, and a quality score in ``[0, 1]`` so
downstream consumers (consensus, decision state) can weight evidence
deterministically without majority voting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class EvidenceKind(str, Enum):
    """Classification of an evidence item."""

    FACT = "FACT"
    INTERPRETATION = "INTERPRETATION"
    RECOMMENDATION = "RECOMMENDATION"


class Freshness(str, Enum):
    """Coarse freshness buckets derived from age."""

    FRESH = "fresh"
    STALE = "stale"

    @classmethod
    def from_age(cls, age_seconds: Optional[float], fresh_threshold: float = 300.0) -> "Freshness":
        if age_seconds is None:
            return cls.FRESH
        return cls.FRESH if age_seconds <= fresh_threshold else cls.STALE


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class EvidenceItem:
    """A single validated piece of evidence.

    Validation occurs in :meth:`__post_init__`:

    * ``content`` must be non-empty.
    * ``kind`` must be a valid :class:`EvidenceKind` (strings are coerced).
    * ``quality`` must lie within ``[0, 1]``.
    """

    kind: EvidenceKind
    content: str
    source: str
    timestamp: str = field(default_factory=_now_iso)
    timeframe: str = ""
    quality: float = 0.5
    freshness: Freshness = Freshness.FRESH
    age_seconds: Optional[float] = None
    metric_name: Optional[str] = None
    metric_value: Optional[float] = None

    def __post_init__(self) -> None:
        # Coerce string kind to enum, rejecting unknown values.
        if not isinstance(self.kind, EvidenceKind):
            try:
                self.kind = EvidenceKind(str(self.kind).upper())
            except ValueError as exc:
                raise ValueError(f"Invalid evidence kind: {self.kind!r}") from exc

        if not self.content or not str(self.content).strip():
            raise ValueError("EvidenceItem content must be non-empty")

        if not (0.0 <= float(self.quality) <= 1.0):
            raise ValueError(f"EvidenceItem quality must be in [0, 1], got {self.quality}")
        self.quality = float(self.quality)

        # Derive freshness from age when provided.
        if self.age_seconds is not None:
            self.freshness = Freshness.from_age(self.age_seconds)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the item."""
        return {
            "kind": self.kind.value,
            "content": self.content,
            "source": self.source,
            "timestamp": self.timestamp,
            "timeframe": self.timeframe,
            "quality": self.quality,
            "freshness": self.freshness.value,
            "age_seconds": self.age_seconds,
            "metric": (
                {"name": self.metric_name, "value": self.metric_value}
                if self.metric_name is not None
                else None
            ),
        }


@dataclass
class EvidenceBundle:
    """An ordered collection of :class:`EvidenceItem` records."""

    _items: list[EvidenceItem] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add(self, item: EvidenceItem) -> "EvidenceBundle":
        """Append an evidence item (returns self for chaining)."""
        if not isinstance(item, EvidenceItem):
            raise TypeError("EvidenceBundle.add expects an EvidenceItem")
        self._items.append(item)
        return self

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    def items(self) -> list[EvidenceItem]:
        """All items, in insertion order."""
        return list(self._items)

    def filter(self, kind: EvidenceKind) -> list[EvidenceItem]:
        """Return only items of the given ``kind``."""
        if not isinstance(kind, EvidenceKind):
            kind = EvidenceKind(str(kind).upper())
        return [item for item in self._items if item.kind == kind]

    def facts(self) -> list[EvidenceItem]:
        """Convenience accessor for FACT items."""
        return self.filter(EvidenceKind.FACT)

    def interpretations(self) -> list[EvidenceItem]:
        """Convenience accessor for INTERPRETATION items."""
        return self.filter(EvidenceKind.INTERPRETATION)

    def recommendations(self) -> list[EvidenceItem]:
        """Convenience accessor for RECOMMENDATION items."""
        return self.filter(EvidenceKind.RECOMMENDATION)

    def is_empty(self) -> bool:
        """True when the bundle holds no evidence."""
        return len(self._items) == 0

    def __len__(self) -> int:
        return len(self._items)

    # ------------------------------------------------------------------
    # Freshness
    # ------------------------------------------------------------------

    def is_stale(self, max_age: float) -> bool:
        """Return True when any item is older than ``max_age`` seconds.

        An empty bundle is never considered stale.
        """
        for item in self._items:
            if item.age_seconds is None:
                continue
            if item.age_seconds > max_age:
                return True
        return False

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize the bundle and its items."""
        return {
            "count": len(self._items),
            "items": [item.to_dict() for item in self._items],
        }
