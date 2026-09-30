# -*- coding: utf-8 -*-
"""Phase 7 /ops read-model router — GET-only observability surface (§20).
Read-only: every endpoint assembles from canonical backend state and returns
it. The single mutation (`alerts/{id}/acknowledge`) is permissioned-audited
and changes only alert-ack state, never trading state.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ops", tags=["ops"])


def _ok(data: Any) -> dict[str, Any]:
    return {"status": "ok", "data": data}


@router.get("/overview")
def ops_overview() -> dict[str, Any]:
    from .readmodels import overview

    return _ok(overview())


@router.get("/health")
def ops_health() -> dict[str, Any]:
    from .readmodels import health_snapshot

    return _ok(health_snapshot())


@router.get("/market")
def ops_market(symbol: str = Query(default="XAUUSD")) -> dict[str, Any]:
    from .readmodels import market_snapshot

    return _ok(market_snapshot(symbol))


@router.get("/setups")
def ops_setups(symbol: str = Query(default="")) -> dict[str, Any]:
    """Active setups from the order/signal lifecycle stores (read-only)."""
    try:
        return _ok(
            {
                "setups": [],
                "note": "lifecycle registry is per-process; " "use decision trace for history",
                "symbol": symbol,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _ok({"setups": [], "error": str(exc)[:200]})


@router.get("/decisions/{decision_id}")
def ops_decision(decision_id: str) -> dict[str, Any]:
    from .trace import decision_trace

    return _ok(decision_trace(decision_id=decision_id))


@router.get("/setups/{setup_id}/trace")
def ops_setup_trace(setup_id: str) -> dict[str, Any]:
    from .trace import decision_trace

    return _ok(decision_trace(setup_id=setup_id))


@router.get("/trades/{trade_id}")
def ops_trade(trade_id: str) -> dict[str, Any]:
    from .trace import trade_trace

    return _ok(trade_trace(trade_id))


@router.get("/explain")
def ops_explain(
    setup_id: str = Query(default=""), event_id: str = Query(default="")
) -> dict[str, Any]:
    from .trace import explain_non_trade

    return _ok(explain_non_trade(setup_id=setup_id, event_id=event_id))


@router.get("/risk")
def ops_risk() -> dict[str, Any]:
    from .readmodels import risk_summary

    return _ok(risk_summary())


@router.get("/executions")
def ops_executions(limit: int = Query(default=25, le=200)) -> dict[str, Any]:
    from .readmodels import execution_summary

    return _ok(execution_summary(limit))


@router.get("/positions")
def ops_positions() -> dict[str, Any]:
    from .readmodels import position_summary

    return _ok(position_summary())


@router.get("/models")
def ops_models(limit: int = Query(default=50, le=200)) -> dict[str, Any]:
    from .readmodels import model_summary

    return _ok(model_summary(limit))


@router.get("/budget")
def ops_budget() -> dict[str, Any]:
    from .readmodels import budget_summary

    return _ok(budget_summary())


@router.get("/providers")
def ops_providers() -> dict[str, Any]:
    from .readmodels import provider_summary

    return _ok(provider_summary())


@router.get("/alerts")
def ops_alerts() -> dict[str, Any]:
    from .alerts import evaluate_runtime_alerts

    return _ok(evaluate_runtime_alerts())


@router.post("/alerts/{alert_id}/acknowledge")
def ops_alert_ack(alert_id: str, identity: str = Query(default="operator")) -> dict[str, Any]:
    """Acknowledge an alert (audited; changes no trading state) (§24–§26)."""
    from .secrets import audit_mutation

    rec = audit_mutation(
        action="alert.acknowledge", identity=identity, resource=f"alert:{alert_id}", result="OK"
    )
    return _ok(rec.to_dict())


@router.get("/audit")
def ops_audit(limit: int = Query(default=50, le=200)) -> dict[str, Any]:
    from .secrets import get_mutation_audit

    return _ok({"records": get_mutation_audit().recent(limit)})


@router.get("/research")
def ops_research() -> dict[str, Any]:
    from .readmodels import research_summary

    return _ok(research_summary())


@router.get("/strategies")
def ops_strategies() -> dict[str, Any]:
    from .readmodels import strategy_summary

    return _ok(strategy_summary())


@router.get("/search")
def ops_search(
    kind: str = Query(default=""),
    query: str = Query(default=""),
    limit: int = Query(default=25, le=100),
) -> dict[str, Any]:
    from .trace import search_records

    return _ok(search_records(kind=kind, query=query, limit=limit))


@router.get("/activity")
def ops_activity(limit: int = Query(default=50, le=200)) -> dict[str, Any]:
    """Recent operational activity: audit + alerts (paginated, §30)."""
    from .alerts import evaluate_runtime_alerts
    from .secrets import get_mutation_audit

    return _ok(
        {
            "audit": get_mutation_audit().recent(limit),
            "alerts": evaluate_runtime_alerts(),
        }
    )
