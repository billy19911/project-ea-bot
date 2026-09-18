# -*- coding: utf-8 -*-
"""PostTradeReviewAgent — deterministic post-trade review specialist (Phase 4).

Reviews CLOSED trades, determines whether the execution followed the
committee plan, and extracts a single rule-based lesson per trade. Lessons
are persisted through an injectable ``lesson_store`` exposing an
``add_lesson`` interface (compatible with ``learning.LearningMemory``); the
default sink is an in-memory process-wide store.

Note on storage: the original plan suggested ``memory.trade_memory`` but its
``TradeMemoryStore`` exposes no lesson API (only trade/decision/risk/execution
records) and must not be modified. The ``add_lesson`` contract used here can
be backed by any sink, including a ``TradeMemoryStore`` adapter added later.

Safety: analysis-only. The agent has no permission to reach the Risk Gate,
the Execution Engine, or MT5, and it never raises on malformed input
(fail-closed UNSUPPORTED).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from agents.base import AgentPriority, BaseAgent

logger = logging.getLogger(__name__)

__all__ = ["PostTradeReviewAgent", "InMemoryLessonStore", "get_lesson_store", "set_lesson_store"]

_BULLISH_TOKENS = {"BUY", "LONG", "BULLISH", "BULL", "UP"}
_BEARISH_TOKENS = {"SELL", "SHORT", "BEARISH", "BEAR", "DOWN"}

#: Deterministic rule per (outcome, followed_plan). ``None`` adherence means
#: the trade record did not carry both the signal and the actual direction.
_RULES: dict[tuple[str, Optional[bool]], str] = {
    ("win", True): "Keep executing signal-consistent entries; the committee plan worked.",
    ("win", False): "Trade won despite deviating from the committee signal — do not repeat it.",
    ("win", None): "Log the committee signal and actual direction to measure plan adherence.",
    ("loss", True): "Plan-following loss: acceptable risk; keep the process, review sizing only.",
    (
        "loss",
        False,
    ): "Loss while deviating from the committee signal: enforce signal-consistent entries.",
    (
        "loss",
        None,
    ): "Log the committee signal and actual direction; adherence is currently unmeasured.",
    (
        "breakeven",
        True,
    ): "Breakeven while following the plan: process is sound, no change required.",
    (
        "breakeven",
        False,
    ): "Breakeven while deviating: review exit management against the committee plan.",
    (
        "breakeven",
        None,
    ): "Log the committee signal and actual direction for future adherence checks.",
    ("unknown", None): "Insufficient data for a specific rule; log the trade for trend analysis.",
}

_CONFIDENCE_BY_OUTCOME = {
    "win": 0.8,
    "loss": 0.75,
    "breakeven": 0.6,
    "unknown": 0.5,
}


def _normalize_direction(value: Any) -> Optional[str]:
    """Map buy/long/bullish-family and sell/short/bearish-family tokens."""
    if not isinstance(value, str):
        return None
    token = value.strip().upper()
    if token in _BULLISH_TOKENS:
        return "BULLISH"
    if token in _BEARISH_TOKENS:
        return "BEARISH"
    return None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class InMemoryLessonStore:
    """Process-wide fallback lesson sink (``add_lesson`` compatible)."""

    def __init__(self) -> None:
        self._lessons: list[dict[str, Any]] = []

    def add_lesson(self, lesson: dict[str, Any]) -> None:
        """Store one lesson (copied, so later mutations cannot alias it)."""
        self._lessons.append(dict(lesson))

    def all_lessons(self) -> list[dict[str, Any]]:
        """Return a shallow copy of every stored lesson."""
        return list(self._lessons)

    def get_lessons(self) -> list[dict[str, Any]]:
        """Alias for :meth:`all_lessons`."""
        return self.all_lessons()

    def clear(self) -> None:
        """Drop every stored lesson (mainly for tests)."""
        self._lessons.clear()

    def __len__(self) -> int:
        return len(self._lessons)


_default_lesson_store = InMemoryLessonStore()


def get_lesson_store() -> Any:
    """Return the process-wide default lesson store.

    The default is an in-memory store; production wiring may swap in a
    persistent store (e.g. ``learning.JsonlLessonStore``) via
    :func:`set_lesson_store` before agents are constructed.
    """
    return _default_lesson_store


def set_lesson_store(store: Any) -> None:
    """Override the process-wide default lesson store (tests / startup wiring).

    Agents already constructed keep their injected store; agents built after
    this call (or without an explicit store) use ``store``.
    """
    global _default_lesson_store
    _default_lesson_store = store if store is not None else InMemoryLessonStore()


class PostTradeReviewAgent(BaseAgent):
    """Reviews closed trades and extracts deterministic, rule-based lessons."""

    def __init__(self, lesson_store: Any = None) -> None:
        super().__init__(
            name="post_trade_review",
            agent_type="review",
            description="Reviews closed trades to extract lessons",
            priority=AgentPriority.LOW,  # post-trade, not time-critical
            permissions=["ANALYZE_TRADES"],
        )
        self._lesson_store = lesson_store if lesson_store is not None else _default_lesson_store

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def can_handle(self, event_type: str, context: dict[str, Any] | None = None) -> bool:
        """Accept trade-close review events only."""
        return event_type.startswith("TRADE_CLOSE") or event_type == "POST_TRADE_REVIEW"

    # ------------------------------------------------------------------
    # Input resolution (fail-closed)
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_pnl(trade: dict[str, Any]) -> Optional[float]:
        """Read P&L; derive it from entry/exit/side when absent."""
        pnl = trade.get("pnl")
        if _is_number(pnl):
            return float(pnl)
        entry = trade.get("entry_price")
        exit_price = trade.get("exit_price", trade.get("close_price"))
        side = _normalize_direction(trade.get("side", trade.get("direction")))
        if _is_number(entry) and _is_number(exit_price) and side is not None:
            diff = (exit_price - entry) if side == "BULLISH" else (entry - exit_price)
            return float(diff)
        return None

    @staticmethod
    def _resolve_outcome(trade: dict[str, Any], pnl: Optional[float]) -> str:
        """Normalize the outcome token, falling back to the P&L sign."""
        raw = trade.get("outcome")
        if isinstance(raw, str):
            token = raw.strip().lower()
            if token in ("win", "won", "profit", "tp"):
                return "win"
            if token in ("loss", "lost", "sl"):
                return "loss"
            if token in ("breakeven", "break-even", "be", "flat", "neutral"):
                return "breakeven"
        if pnl is None:
            return "unknown"
        if pnl > 0:
            return "win"
        if pnl < 0:
            return "loss"
        return "breakeven"

    @staticmethod
    def _resolve_followed_plan(trade: dict[str, Any]) -> Optional[bool]:
        """True/False when both signal and actual direction are present."""
        signal = _normalize_direction(trade.get("signal"))
        actual = _normalize_direction(trade.get("actual_direction"))
        if signal is None or actual is None:
            return None
        return signal == actual

    # ------------------------------------------------------------------
    # Enrichment via the existing review toolkit (best-effort, fail-safe)
    # ------------------------------------------------------------------

    def _enrich(self, trade: dict[str, Any], pnl: Optional[float]) -> dict[str, Any]:
        """Attach MAE/MFE + root cause when the review toolkit can compute them."""
        data: dict[str, Any] = {}
        try:
            from review.advanced_review import classify_root_cause
            from review.trade_review import TradeReviewer

            entry = trade.get("entry_price")
            exit_price = trade.get("exit_price", trade.get("close_price"))
            direction = _normalize_direction(trade.get("side", trade.get("direction")))
            if not (_is_number(entry) and _is_number(exit_price) and direction is not None):
                return data

            history = trade.get("price_history")
            prices = (
                [float(p) for p in history if _is_number(p)] if isinstance(history, list) else []
            )
            review = TradeReviewer().review_trade(
                {
                    "trade_id": str(trade.get("trade_id", "UNKNOWN")),
                    "entry_price": float(entry),
                    "exit_price": float(exit_price),
                    "direction": "BUY" if direction == "BULLISH" else "SELL",
                    "pnl": float(pnl or 0.0),
                    "agent_outputs": {"confidence": 0.5, "signal": "HOLD"},
                },
                prices,
            )
            data["mae"] = review.mae
            data["mfe"] = review.mfe
            root = classify_root_cause(
                {
                    "trade_id": str(trade.get("trade_id", "UNKNOWN")),
                    "outcome": review.outcome,
                    "decision_quality_score": review.decision_quality_score,
                    "execution_quality_score": review.execution_quality_score,
                    "timing_score": review.timing_score,
                    "mae": review.mae,
                    "mfe": review.mfe,
                }
            )
            data["root_cause"] = root.primary_cause
        except Exception as exc:  # enrichment is optional — never break review
            logger.debug("Review enrichment unavailable: %s", exc)
        return data

    # ------------------------------------------------------------------
    # Analyze
    # ------------------------------------------------------------------

    def _unsupported(self, reason: str) -> dict[str, Any]:
        """Explicit fail-closed result (no fabricated review, no lesson)."""
        return {
            "agent": self.name,
            "status": "UNSUPPORTED",
            "signal": "NEUTRAL",
            "confidence": 0.0,
            "reasons": [reason],
            "outcome": None,
            "followed_plan": None,
            "lessons_extracted": 0,
        }

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Review one closed trade; always returns a Supervisor-compatible dict."""
        if not isinstance(context, dict):
            return self._unsupported("No closed trade data available for review (fail-closed)")

        trade = context.get("closed_trade")
        if not isinstance(trade, dict) or not trade:
            return self._unsupported("No closed trade data available for review (fail-closed)")

        pnl = self._resolve_pnl(trade)
        outcome = self._resolve_outcome(trade, pnl)
        if outcome == "unknown" and pnl is None:
            return self._unsupported("Closed trade lacks both outcome and P&L data")
        if pnl is None:
            pnl = 0.0

        followed_plan = self._resolve_followed_plan(trade)
        if followed_plan is True:
            adherence = "followed"
        elif followed_plan is False:
            adherence = "deviated"
        else:
            adherence = "unknown"

        rule = (
            _RULES.get((outcome, followed_plan))
            or _RULES.get((outcome, None))
            or _RULES[("unknown", None)]
        )
        trade_id = str(trade.get("trade_id", "UNKNOWN"))
        symbol = str(trade.get("symbol", "UNKNOWN"))

        lesson: dict[str, Any] = {
            "trade_id": trade_id,
            "symbol": symbol,
            "outcome": outcome,
            "followed_plan": followed_plan,
            "category": f"{outcome}_{adherence}",
            "rule": rule,
            "lesson": f"{symbol} {outcome}: {rule}",
            "pnl": pnl,
            "source": self.name,
        }
        lesson.update(self._enrich(trade, pnl))

        try:
            self._lesson_store.add_lesson(lesson)
        except Exception as exc:  # fail-safe: persistence must never break review
            logger.warning("Lesson store failed for %s (review continues): %s", trade_id, exc)

        confidence = _CONFIDENCE_BY_OUTCOME.get(outcome, 0.5)
        reasons = [
            f"Reviewed closed trade {trade_id} ({symbol}): {outcome}",
            f"Plan adherence: {adherence}",
            f"Lesson: {rule}",
        ]
        if lesson.get("root_cause"):
            reasons.append(f"Root cause (review toolkit): {lesson['root_cause']}")

        return {
            "agent": self.name,
            "signal": "NEUTRAL",  # review never signals a direction
            "confidence": confidence,
            "reasons": reasons,
            "outcome": outcome,
            "followed_plan": followed_plan,
            "lessons_extracted": 1,
            "lesson": lesson,
        }
