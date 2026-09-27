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

__all__ = [
    "LessonFeedbackProvider",
    "format_lessons_reason",
    "record_review_lesson",
    "record_review_lesson_v2",
]

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


def _review_field(record: Any, name: str, default: Any = "") -> Any:
    """Read ``name`` from a review record (dict or object), fail-safe."""
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)


def record_review_lesson_v2(engine: Any, store: Any, record: Any) -> Any:
    """Feed a review record into the Learning Engine 2.0 (PRD §43).

    Converts the review into an evidence-graded :class:`Lesson` (always an
    OBSERVATION on ingestion — one trade never promotes a pattern), records it
    in ``engine``, and (when a persistent ``store`` is provided) appends the
    lesson dict to the store so it survives restarts.

    Fail-safe: any error is swallowed — the review/close path must never break.
    Returns the recorded lesson (or ``None`` on failure).
    """
    try:
        from .engine_v2 import Lesson

        trade_result = _review_field(record, "trade_result", {}) or {}
        if not isinstance(trade_result, dict):
            trade_result = {}
        review = _review_field(record, "review", None)
        root_cause = _review_field(record, "root_cause", None)

        trade_id = str(_review_field(record, "trade_id", "") or "")
        symbol = str(trade_result.get("symbol") or _review_field(review, "symbol", "") or "")
        outcome = str(
            trade_result.get("outcome") or _review_field(review, "outcome", "") or ""
        ).lower()
        regime = str(trade_result.get("regime", "unknown"))
        direction = str(trade_result.get("direction", "NEUTRAL")).upper()
        root_cause_name = str(_review_field(root_cause, "primary_cause", "") or "")

        lesson = Lesson(
            lesson_id=f"v2:{trade_id}" if trade_id else f"v2:{symbol}:{outcome}",
            trade_id=trade_id,
            symbol=symbol,
            strategy_version=str(trade_result.get("strategy_version", "") or "live"),
            category=_category_for(root_cause_name, direction),
            outcome=outcome,
            context={
                "regime": regime,
                "direction": direction,
                "root_cause": root_cause_name,
            },
            lesson=str(_review_field(review, "summary", "") or ""),
        )
        recorded = engine.record_lesson(lesson)
        if store is not None:
            store.add_lesson(recorded.to_dict())
        return recorded
    except Exception as exc:  # noqa: BLE001 - learning must never break review
        logger.warning("Learning Engine v2 recording failed (review continues): %s", exc)
        return None


def _category_for(root_cause: str, direction: str) -> str:
    """Map a free-text root cause to a LessonCategory value (best-effort)."""
    text = (root_cause or "").lower()
    if "timing" in text or "entry" in text:
        return "ENTRY_TIMING"
    if "exit" in text or "close" in text:
        return "EXIT_TIMING"
    if "size" in text or "sizing" in text:
        return "POSITION_SIZING"
    if "risk" in text or "stop" in text:
        return "RISK_MANAGEMENT"
    if "regime" in text or "trend" in text or "range" in text:
        return "REGIME_FIT"
    if "slip" in text or "execution" in text or "spread" in text:
        return "EXECUTION_QUALITY"
    return "OTHER"
