# -*- coding: utf-8 -*-
"""Persistent JSONL store for the Learning Engine 2.0 (PRD §43).

Mirrors :class:`learning.lesson_store.JsonlLessonStore` but stores
:class:`learning.engine_v2.Lesson` records so the evidence-gated learning
pipeline survives restarts.

Design rules:

* **Fail-safe** — a corrupt line is skipped on load; an unwritable file
  degrades to cache-only. Neither ever breaks the review path.
* **No new dependencies** — stdlib only.
* **Advisory only** — this store never mutates live strategy parameters; it
  only accumulates evidence-graded lessons/patterns for the research loop.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["JsonlEngineV2Store", "set_engine_v2_store", "get_engine_v2_store"]

_DEFAULT_PATH = os.path.join("logs", "learning_engine_v2.jsonl")

# Process-wide store (mirrors lesson_store's module-global pattern).
_STORE: Optional["JsonlEngineV2Store"] = None


class JsonlEngineV2Store:
    """Append-only JSONL store for Learning Engine 2.0 lessons.

    Args:
        path: File to persist to. Defaults to ``ENGINE_V2_STORE_PATH`` env or
            ``logs/learning_engine_v2.jsonl``.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = str(path or os.getenv("ENGINE_V2_STORE_PATH") or _DEFAULT_PATH)
        self._lessons: list[dict[str, Any]] = []
        self._load()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def _load(self) -> None:
        """Load persisted lessons; corrupt lines are skipped (fail-safe)."""
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        lesson = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("Skipping corrupt v2 lesson line in %s", self.path)
                        continue
                    if isinstance(lesson, dict):
                        self._lessons.append(lesson)
        except FileNotFoundError:
            pass
        except OSError as exc:  # unreadable path → start empty, never crash
            logger.warning("Could not read v2 lesson store %s: %s", self.path, exc)

    # ------------------------------------------------------------------
    # Contract
    # ------------------------------------------------------------------
    def add_lesson(self, lesson: dict[str, Any]) -> None:
        """Append one lesson dict to the cache and the file (fail-safe write)."""
        entry = dict(lesson)
        self._lessons.append(entry)
        self._append_line(entry)

    def _append_line(self, lesson: dict[str, Any]) -> None:
        """Persist one lesson; a write failure degrades to cache-only."""
        try:
            parent = os.path.dirname(self.path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(lesson, ensure_ascii=False, default=str) + "\n")
        except OSError as exc:
            logger.warning("Could not persist v2 lesson to %s (cache kept): %s", self.path, exc)

    def all_lessons(self) -> list[dict[str, Any]]:
        """Return a shallow copy of every stored lesson."""
        return list(self._lessons)

    def clear(self) -> None:
        """Drop every lesson from cache and truncate the file."""
        self._lessons.clear()
        try:
            with open(self.path, "w", encoding="utf-8"):
                pass
        except OSError as exc:
            logger.warning("Could not truncate v2 lesson store %s: %s", self.path, exc)

    def __len__(self) -> int:
        return len(self._lessons)


def set_engine_v2_store(store: Optional[JsonlEngineV2Store]) -> None:
    """Attach the process-wide v2 lesson store (None detaches)."""
    global _STORE
    _STORE = store


def get_engine_v2_store() -> Optional[JsonlEngineV2Store]:
    """Return the process-wide v2 lesson store (or None if not wired)."""
    return _STORE
