# -*- coding: utf-8 -*-
"""Review auto-trigger — fires post-trade review when a position closes (PRD §18.1).

Wires the :class:`~review.trade_review.TradeReviewer` and
:func:`~review.advanced_review.classify_root_cause` into the position-close
path so every closed trade is reviewed automatically.

The hook is deliberately **fail-safe**: any error raised while reviewing is
logged and swallowed so the close path is never broken. Only closed trades are
reviewed; still-open positions pass through untouched.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .advanced_review import RootCauseClassification, classify_root_cause
from .trade_review import TradeReviewer, TradeReviewResult

logger = logging.getLogger(__name__)

__all__ = [
    "ReviewAutoTrigger",
    "ReviewRecord",
    "on_position_closed",
    "get_auto_trigger",
    "set_auto_trigger",
]

# Keys that indicate a position is still open (no review should fire).
_OPEN_STATUSES = {"OPEN", "PENDING", "NEW", "ACTIVE", "RUNNING"}
# Keys that indicate a position has closed.
_CLOSED_STATUSES = {"CLOSED", "CLOSE", "FILLED", "DONE", "EXIT"}


def _get(source: Any, name: str, default: Any = None) -> Any:
    """Read a field from a dict or object."""
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _is_closed(trade_result: Any) -> bool:
    """Return True if ``trade_result`` represents a closed position.

    A record is treated as closed when an explicit status says so, or when an
    exit/close price is present. Records that explicitly say "open" are
    rejected even if they carry a price.
    """
    status = str(_get(trade_result, "status", "") or "").upper()
    if status in _OPEN_STATUSES:
        return False
    if status in _CLOSED_STATUSES:
        return True

    # Implicit: only closed when a close/exit price is present.
    close_price = _get(trade_result, "close_price", None)
    if close_price is None:
        close_price = _get(trade_result, "exit_price", None)
    return close_price is not None


def _to_review_record(trade_result: Any) -> dict[str, Any]:
    """Normalize an arbitrary trade/close record into a review record dict."""
    close_price = _get(trade_result, "close_price", None)
    if close_price is None:
        close_price = _get(trade_result, "exit_price", None)
    entry_price = _get(trade_result, "entry_price", _get(trade_result, "open_price", 0.0))

    direction = _get(trade_result, "direction", None)
    if direction is None:
        # For a close, the closing order side is opposite the position side.
        side = str(_get(trade_result, "side", "") or "").upper()
        if side in ("BUY", "SELL"):
            direction = side
        else:
            order_type = str(_get(trade_result, "order_type", "") or "").upper()
            direction = "SELL" if "SELL" in order_type else "BUY"

    trade_id = _get(trade_result, "trade_id", None) or _get(trade_result, "ticket", None)
    return {
        "trade_id": str(trade_id) if trade_id is not None else "UNKNOWN",
        "entry_price": float(entry_price or 0.0),
        "exit_price": float(close_price or 0.0),
        "direction": str(direction or "BUY"),
        "pnl": float(_get(trade_result, "pnl", 0.0) or 0.0),
        "agent_outputs": _get(trade_result, "agent_outputs", {}) or {},
        "retries": int(_get(trade_result, "retries", 0) or 0),
        "slippage": float(
            _get(trade_result, "slippage", _get(trade_result, "slippage_applied", 0.0)) or 0.0
        ),
        "price_history": list(_get(trade_result, "price_history", []) or []),
        "regime_at_entry": _get(trade_result, "regime_at_entry", None),
        "regime_at_exit": _get(trade_result, "regime_at_exit", None),
        "news_events": _get(trade_result, "news_events", None),
    }


@dataclass
class ReviewRecord:
    """A completed automatic review of a closed trade."""

    trade_id: str
    review: TradeReviewResult
    root_cause: RootCauseClassification

    def to_dict(self) -> dict[str, Any]:
        """Serialize the record to a plain dict."""
        return {
            "trade_id": self.trade_id,
            "outcome": self.review.outcome,
            "pnl": self.review.pnl,
            "timing_score": self.review.timing_score,
            "decision_quality_score": self.review.decision_quality_score,
            "execution_quality_score": self.review.execution_quality_score,
            "root_cause": self.root_cause.primary_cause,
            "root_cause_confidence": self.root_cause.confidence,
            "root_cause_secondary": list(self.root_cause.secondary_causes),
            "summary": self.review.summary,
        }


class ReviewAutoTrigger:
    """Trigger post-trade review + root-cause analysis on position close.

    Args:
        reviewer: Optional :class:`TradeReviewer` (defaults to a new instance).
        on_review: Optional callback invoked with the :class:`ReviewRecord`
            after a successful review (useful for persistence/journaling).
        max_history: Maximum number of reviews retained (bounded history).
    """

    def __init__(
        self,
        reviewer: Optional[TradeReviewer] = None,
        on_review: Optional[Callable[[ReviewRecord], None]] = None,
        max_history: int = 500,
    ) -> None:
        self._reviewer = reviewer or TradeReviewer()
        self._on_review = on_review
        self._max_history = max(1, int(max_history))
        self._history: deque[ReviewRecord] = deque(maxlen=self._max_history)
        self._lock = threading.Lock()
        self._stats: dict[str, int] = {"triggered": 0, "reviewed": 0, "failed": 0, "skipped": 0}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def on_position_closed(self, trade_result: Any) -> Optional[ReviewRecord]:
        """Review a closed position. Never raises.

        Args:
            trade_result: A dict or object describing the ``trade_result``.
                Open positions (no close price / explicit open status) are
                ignored.

        Returns:
            The :class:`ReviewRecord` if a review was produced, else ``None``.
        """
        if trade_result is None or not _is_closed(trade_result):
            with self._lock:
                self._stats["skipped"] += 1
            return None

        with self._lock:
            self._stats["triggered"] += 1

        record = _to_review_record(trade_result)
        try:
            review = self._reviewer.review_trade(
                record,
                record["price_history"],
            )
            root_cause = classify_root_cause(
                {
                    "trade_id": record["trade_id"],
                    "outcome": review.outcome,
                    "decision_quality_score": review.decision_quality_score,
                    "execution_quality_score": review.execution_quality_score,
                    "timing_score": review.timing_score,
                    "mae": review.mae,
                    "mfe": review.mfe,
                },
                regime_at_entry=record["regime_at_entry"],
                regime_at_exit=record["regime_at_exit"],
                news_events=record["news_events"],
            )
        except Exception as exc:  # fail-safe: never break the close path
            with self._lock:
                self._stats["failed"] += 1
            logger.exception("Auto-review failed for %s: %s", record["trade_id"], exc)
            return None

        review_record = ReviewRecord(
            trade_id=record["trade_id"], review=review, root_cause=root_cause
        )
        with self._lock:
            self._stats["reviewed"] += 1
            self._history.append(review_record)

        if self._on_review is not None:
            try:
                self._on_review(review_record)
            except Exception as exc:  # fail-safe
                logger.warning("on_review callback failed for %s: %s", record["trade_id"], exc)

        logger.info(
            "Auto-review complete for trade %s: %s (%s)",
            record["trade_id"],
            review.outcome,
            root_cause.primary_cause,
        )
        return review_record

    def recent(self, limit: int = 50) -> list[ReviewRecord]:
        """Return the most recent review records (newest first)."""
        with self._lock:
            items = list(self._history)
        items.reverse()
        return items[: max(0, int(limit))]

    def stats(self) -> dict[str, int]:
        """Return a snapshot of trigger statistics."""
        with self._lock:
            return dict(self._stats)


# ---------------------------------------------------------------------------
# Module-level default trigger
# ---------------------------------------------------------------------------

_default_trigger: Optional[ReviewAutoTrigger] = None
_default_lock = threading.Lock()


def get_auto_trigger() -> ReviewAutoTrigger:
    """Return the process-wide default :class:`ReviewAutoTrigger`."""
    global _default_trigger
    with _default_lock:
        if _default_trigger is None:
            _default_trigger = ReviewAutoTrigger()
        return _default_trigger


def set_auto_trigger(trigger: Optional[ReviewAutoTrigger]) -> None:
    """Override the process-wide default trigger (mainly for tests)."""
    global _default_trigger
    with _default_lock:
        _default_trigger = trigger


def on_position_closed(
    trade_result: Any,
    trigger: Optional[ReviewAutoTrigger] = None,
) -> Optional[ReviewRecord]:
    """Review a closed position via the default (or supplied) trigger.

    This is the hook wired into the position-close path. It is fail-safe and
    returns ``None`` for open positions or on any review error.
    """
    try:
        active = trigger if trigger is not None else get_auto_trigger()
        return active.on_position_closed(trade_result)
    except Exception as exc:  # last-resort guard: never break the close path
        logger.exception("on_position_closed hook failed: %s", exc)
        return None
