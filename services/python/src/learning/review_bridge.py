# -*- coding: utf-8 -*-
"""Live-review → canonical learning bridge (integration audit P1-1).
Best-effort, fail-closed, NEVER blocks trading: converts the live review
record (dict or object) into canonical DecisionReview / TradeReview entries,
persists them in the durable CanonicalStore, and enqueues a research job.
Any failure is swallowed — the trading loop is unaffected.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)
__all__ = ["bridge_review_record"]


def _as_dict(record: Any) -> dict[str, Any]:
    if isinstance(record, dict):
        return dict(record)
    to_dict = getattr(record, "to_dict", None)
    if callable(to_dict):
        try:
            out = to_dict()
            if isinstance(out, dict):
                return dict(out)
        except Exception:  # noqa: BLE001 - best-effort
            pass
    return {}


def bridge_review_record(record: Any) -> dict[str, Any]:
    """Bridge one live review record into canonical learning (never raises).
    Returns a small status dict for observability.
    """
    try:
        from .review_store import CanonicalStore, ResearchQueue, ReviewBuilder
    except Exception as exc:  # noqa: BLE001 - never break trading
        logger.debug("review bridge unavailable: %s", exc)
        return {"bridged": False, "reason": "imports unavailable"}
    try:
        data = _as_dict(record)
        builder = ReviewBuilder()
        store = CanonicalStore()
        queue = ResearchQueue()
        trade_id = data.get("trade_id") or data.get("ticket")
        if trade_id:
            review = builder.build_trade_review(
                review_id=f"rev-{trade_id}",
                trade_id=str(trade_id),
                setup_id=str(data.get("setup_id") or ""),
                trigger_id=str(data.get("trigger_id") or ""),
                strategy_version=str(data.get("strategy_version") or ""),
                entry_timestamp=str(data.get("entry_time") or data.get("opened_at") or ""),
                exit_timestamp=str(data.get("exit_time") or data.get("closed_at") or ""),
                entry_price=float(data.get("entry_price") or 0.0),
                exit_price=float(data.get("exit_price") or 0.0),
                stop_loss=float(data.get("stop_loss") or data.get("sl") or 0.0),
                direction=str(data.get("direction") or data.get("side") or ""),
                gross_pnl=float(data.get("gross_pnl") or data.get("pnl") or 0.0),
                net_pnl=float(data.get("net_pnl") or data.get("pnl") or 0.0),
                commission=float(data.get("commission") or 0.0),
                zone_type=str(data.get("zone_type") or ""),
                trigger_type=str(data.get("trigger_type") or ""),
                regime=str(data.get("regime") or ""),
                session=str(data.get("session") or ""),
                decision_quality=float(data.get("decision_quality", 0.5) or 0.5),
                reason_codes=[str(x) for x in (data.get("reason_codes") or [])],
                evidence_refs=[str(x) for x in (data.get("evidence_refs") or [])],
            )
            store.write("TradeReview", review.trade_id, review.to_dict())
            queue.submit(
                {"type": "trade_review", "trade_id": review.trade_id, "review_id": review.review_id}
            )
            return {"bridged": True, "kind": "TradeReview", "id": review.trade_id}
        event_id = data.get("event_id") or data.get("decision_id") or "unknown"
        decision = builder.build_decision_review(
            review_id=f"drev-{event_id}",
            event_id=str(event_id),
            decision_timestamp=str(data.get("timestamp") or data.get("closed_at") or ""),
            decision_state=str(data.get("decision_state") or data.get("status") or "UNKNOWN"),
            direction=str(data.get("direction") or ""),
            setup_id=str(data.get("setup_id") or ""),
            reason_codes=[str(x) for x in (data.get("reason_codes") or [])],
            strategy_version=str(data.get("strategy_version") or ""),
        )
        store.write("DecisionReview", decision.event_id, decision.to_dict())
        queue.submit(
            {
                "type": "decision_review",
                "event_id": decision.event_id,
                "review_id": decision.review_id,
            }
        )
        return {"bridged": True, "kind": "DecisionReview", "id": decision.event_id}
    except Exception as exc:  # noqa: BLE001 - bridge must never break trading
        logger.warning("review bridge failed (trading unaffected): %s", exc)
        return {"bridged": False, "reason": str(exc)[:120]}
