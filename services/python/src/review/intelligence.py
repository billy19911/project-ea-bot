# -*- coding: utf-8 -*-
"""ReviewLead — Review Department lead (Phase 4).

Third department lead (after ``MarketLead`` and ``RiskLead``). The Supervisor
detects it via ``agent_type="department_lead"`` and delegates
``TRADE_CLOSE*`` / ``POST_TRADE_REVIEW`` events here; the lead runs the
``PostTradeReviewAgent`` specialist and returns a Supervisor-compatible dict.

The lead is analysis-only: it holds no permission to reach the Risk Gate,
the Execution Engine, or MT5, and it never raises on malformed input.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.analysts.review_agent import PostTradeReviewAgent
from agents.base import AgentPriority, BaseAgent

logger = logging.getLogger(__name__)

__all__ = ["ReviewLead"]


class ReviewLead(BaseAgent):
    """Leads the review department (post-trade analysis)."""

    #: Event families routed to the review department.
    REVIEW_EVENT_PREFIXES = ("TRADE_CLOSE", "POST_TRADE_REVIEW")

    def __init__(self, lesson_store: Any = None) -> None:
        super().__init__(
            name="review_lead",
            agent_type="department_lead",
            description="Leads Review Department (post-trade analysis)",
            role="department_lead",
            permissions=["ANALYZE_TRADES"],
            priority=AgentPriority.NORMAL,
        )
        self._specialist = PostTradeReviewAgent(lesson_store=lesson_store)

    def can_handle(self, event_type: str, context: dict[str, Any] | None = None) -> bool:
        """Accept trade-close review events only."""
        return any(event_type.startswith(prefix) for prefix in self.REVIEW_EVENT_PREFIXES)

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Run the review specialist and wrap its result for the Supervisor."""
        if not isinstance(context, dict):
            context = {}
        result = self._specialist.analyze(context)
        specialist_key = result.get("agent", "post_trade_review")
        return {
            "agent": self.name,
            "role": "department_lead",
            "department": "review",
            "signal": result.get("signal", "NEUTRAL"),
            "confidence": result.get("confidence", 0.0),
            "reasons": result.get("reasons", []),
            "specialist_results": {specialist_key: result},
        }

    def execute(self, task):
        return {"status": "ok"}

    def to_dict(self) -> dict[str, Any]:
        """Include department identity in standard agent metadata."""
        result = super().to_dict()
        result.update({"department": "review", "role": "department_lead"})
        return result
