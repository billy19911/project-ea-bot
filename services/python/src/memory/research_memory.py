# -*- coding: utf-8 -*-
"""Research Memory (§17) — research findings and their outcomes.

Research memory stores :class:`ResearchNote` findings together with the
outcome recorded for them later (e.g. ``confirmed`` / ``invalidated`` / a
custom label), so the platform can look findings up by outcome or topic. The
store is size-bounded. No external database is required.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ResearchNote:
    """A single research finding with a (later-recorded) outcome."""

    id: str
    topic: str
    finding: str
    outcome: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "topic": self.topic,
            "finding": self.finding,
            "outcome": self.outcome,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
        }


class ResearchMemory:
    """Thread-safe, size-bounded store of research findings and outcomes."""

    def __init__(self, max_size: int = 1000) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        self.max_size = max_size
        self._notes: dict[str, ResearchNote] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    def add(self, note: ResearchNote, outcome: Optional[str] = None) -> ResearchNote:
        """Store ``note``; ``outcome`` optionally sets/overrides its outcome."""
        if not note.id or not str(note.id).strip():
            raise ValueError("ResearchNote id must be non-empty")
        if outcome is not None:
            note.outcome = outcome
        with self._lock:
            if note.id in self._notes:
                self._order.remove(note.id)
            self._notes[note.id] = note
            self._order.append(note.id)
            self._evict_locked()
        return note

    def get(self, note_id: str) -> Optional[ResearchNote]:
        """Return the note with ``note_id`` (None if absent)."""
        with self._lock:
            return self._notes.get(note_id)

    def by_outcome(self, outcome: str) -> list[ResearchNote]:
        """Return notes whose recorded outcome equals ``outcome``."""
        with self._lock:
            notes = list(self._notes.values())
        return [n for n in notes if n.outcome == outcome]

    def by_topic(self, topic: str) -> list[ResearchNote]:
        """Return notes whose topic equals ``topic``."""
        with self._lock:
            notes = list(self._notes.values())
        return [n for n in notes if n.topic == topic]

    def record_outcome(self, note_id: str, outcome: str) -> bool:
        """Record an outcome for an existing note; True if the note existed."""
        with self._lock:
            note = self._notes.get(note_id)
            if note is None:
                return False
            note.outcome = outcome
            return True

    def __len__(self) -> int:
        with self._lock:
            return len(self._notes)

    def _evict_locked(self) -> None:
        """Evict oldest notes until within ``max_size``."""
        while len(self._order) > self.max_size:
            oldest = self._order.pop(0)
            self._notes.pop(oldest, None)
