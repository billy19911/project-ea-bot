# -*- coding: utf-8 -*-
"""Learning feedback loop (Phase 7).

Closes the loop: lessons persisted by reviews are summarised for the next
analysis cycle and surfaced (advisory only) by the department leads.

* :class:`LessonFeedbackProvider` — read-only summary of lessons per symbol.
* :func:`record_review_lesson` — bridge for ``ReviewAutoTrigger.on_review``
  so the legacy paper-close review path writes to the same store as
  ``ReviewLead`` events.

Design rules:

* Fail-safe: a broken store never breaks the pipeline or the close path.
* Advisory only: the leads add a *reason*; signal and confidence are never
  changed here (deterministic behaviour stays intact).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["LessonFeedbackProvider", "format_lessons_reason", "record_review_lesson"]

# Outcome values counted as wins/losses in the summary.
_WIN_OUTCOMES = {"win", "won", "profit"}
_LOSS_OUTCOMES = {"loss", "lost", "lose"}


class LessonFeedbackProvider:
    """Summarise stored lessons for the analysis context (fail-safe, read-only).

    Args:
        store: Any object exposing ``all_lessons()`` (e.g. ``JsonlLessonStore``
            or ``InMemoryLessonStore``).
    """

    def __init__(self, store: Any) -> None:
        self._store = store

    def summarize_for_symbol(self, symbol: str, max_lessons: int = 5) -> dict[str, Any]:
        """Return compact lesson stats for ``symbol`` (``"*"`` = all symbols).

        Never raises: a broken store degrades to an empty summary.
        """
        try:
            lessons = self._store.all_lessons() or []
        except Exception as exc:  # noqa: BLE001 - feedback must never break a cycle
            logger.warning("Lesson store unavailable for feedback: %s", exc)
            return {"count": 0, "wins": 0, "losses": 0, "recent": []}

        target = str(symbol or "*").upper()
        if target != "*":
            lessons = [
                lesson
                for lesson in lessons
                if str(lesson.get("symbol") or "").upper() in (target, "")
            ]

        wins = sum(1 for lesson in lessons if self._outcome_of(lesson) in _WIN_OUTCOMES)
        losses = sum(1 for lesson in lessons if self._outcome_of(lesson) in _LOSS_OUTCOMES)

        recent = []
        for lesson in reversed(lessons[-max(0, int(max_lessons)) :]):
            recent.append(
                {
                    "category": str(lesson.get("category") or ""),
                    "lesson": str(lesson.get("lesson") or lesson.get("rule") or ""),
                    "outcome": str(lesson.get("outcome") or ""),
                }
            )

        return {"count": len(lessons), "wins": wins, "losses": losses, "recent": recent}

    @staticmethod
    def _outcome_of(lesson: dict[str, Any]) -> str:
        """Normalise a lesson's outcome to lowercase."""
        return str(lesson.get("outcome") or "").strip().lower()


def format_lessons_reason(lessons: Any) -> Optional[str]:
    """Format a compact advisory reason from a lesson summary, or ``None``.

    Returns e.g. ``"Historical lessons: 3 (W 2/L 1) — last: EURUSD win: keep it"``.
    Only reads the summary dict produced by
    :meth:`LessonFeedbackProvider.summarize_for_symbol`; malformed input
    yields ``None`` so callers can simply skip the reason.
    """
    if not isinstance(lessons, dict):
        return None
    try:
        count = int(lessons.get("count") or 0)
        wins = int(lessons.get("wins") or 0)
        losses = int(lessons.get("losses") or 0)
    except (TypeError, ValueError):
        return None
    if count <= 0:
        return None

    reason = f"Historical lessons: {count} (W {wins}/L {losses})"
    recent = lessons.get("recent") or []
    if recent and isinstance(recent[0], dict):
        last = str(recent[0].get("lesson") or recent[0].get("category") or "").strip()
        if last:
            reason += f" — last: {last}"
    return reason


def record_review_lesson(store: Any, record: Any) -> None:
    """Persist a compact lesson from a ``ReviewRecord`` (fail-safe).

    Wired as ``ReviewAutoTrigger(on_review=...)`` so both review paths
    (ReviewLead events and the paper-close hook) write to one store.
    """
    try:
        trade_id = str(getattr(record, "trade_id", "") or "")
        review = getattr(record, "review", None)
        root_cause = getattr(record, "root_cause", None)
        outcome = str(getattr(review, "outcome", "") or "")
        lesson: dict[str, Any] = {
            "trade_id": trade_id,
            "symbol": str(getattr(review, "symbol", "") or ""),
            "outcome": outcome.lower() if outcome else "",
            "root_cause": str(getattr(root_cause, "primary_cause", "") or ""),
            "lesson": str(getattr(review, "summary", "") or ""),
            "source": "review_auto_trigger",
        }
        store.add_lesson(lesson)
    except Exception as exc:  # noqa: BLE001 - the close path must never break
        logger.warning("Failed to record review lesson (close path continues): %s", exc)
