# -*- coding: utf-8 -*-
"""Persistent JSONL lesson store (Phase 7).

Append-only JSONL file with an in-memory cache, API-compatible with
``InMemoryLessonStore`` (``add_lesson`` / ``all_lessons`` / ``get_lessons`` /
``clear`` / ``__len__``). Lessons survive restarts.

Design rules:

* **Fail-safe** — a corrupt line is skipped on load; an unwritable file
  degrades to cache-only. Neither ever breaks the review path.
* **No new dependencies** — stdlib only.
* **Does not touch** ``memory/trade_memory.py`` (constraint from the plan).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["JsonlLessonStore"]

_DEFAULT_PATH = os.path.join("logs", "lessons.jsonl")


class JsonlLessonStore:
    """Append-only JSONL lesson store with an in-memory cache.

    Args:
        path: File to persist to. Defaults to ``LESSON_STORE_PATH`` env or
            ``logs/lessons.jsonl``.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = str(path or os.getenv("LESSON_STORE_PATH") or _DEFAULT_PATH)
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
                        logger.warning("Skipping corrupt lesson line in %s", self.path)
                        continue
                    if isinstance(lesson, dict):
                        self._lessons.append(lesson)
        except FileNotFoundError:
            pass
        except OSError as exc:  # unreadable path → start empty, never crash
            logger.warning("Could not read lesson store %s: %s", self.path, exc)

    # ------------------------------------------------------------------
    # Contract (InMemoryLessonStore-compatible)
    # ------------------------------------------------------------------
    def add_lesson(self, lesson: dict[str, Any]) -> None:
        """Append one lesson to the cache and the file (fail-safe write)."""
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
            logger.warning("Could not persist lesson to %s (cache kept): %s", self.path, exc)

    def all_lessons(self) -> list[dict[str, Any]]:
        """Return a shallow copy of every stored lesson."""
        return list(self._lessons)

    def get_lessons(self) -> list[dict[str, Any]]:
        """Alias for :meth:`all_lessons`."""
        return self.all_lessons()

    def clear(self) -> None:
        """Drop every lesson from cache and truncate the file."""
        self._lessons.clear()
        try:
            with open(self.path, "w", encoding="utf-8"):
                pass
        except OSError as exc:
            logger.warning("Could not truncate lesson store %s: %s", self.path, exc)

    def __len__(self) -> int:
        return len(self._lessons)
