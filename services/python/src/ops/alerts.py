# -*- coding: utf-8 -*-
"""Phase 7 alerts — structured operational alerts over runtime signals (§13).
Read-only evaluation; binds the existing AlertManager concept to live signals.
Normal WAIT/NO_TRADE is NOT an alert (§13 noise rule).
"""
from __future__ import annotations

from typing import Any

__all__ = ["evaluate_runtime_alerts", "ALERT_SEVERITIES"]
ALERT_SEVERITIES = ("INFO", "WARNING", "HIGH", "CRITICAL")


def _alert(category: str, severity: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"category": category, "severity": severity, "message": message, **extra}


def evaluate_runtime_alerts() -> dict[str, Any]:
    """Evaluate live signals into structured alerts (never raises)."""
    alerts: list[dict[str, Any]] = []
    # SYSTEM — research queue backlog/errors.
    try:
        from learning.review_store import ResearchQueue

        q = ResearchQueue()
        if q.errors > 0:
            alerts.append(
                _alert(
                    "RESEARCH",
                    "WARNING",
                    f"research queue has {q.errors} failed job(s)",
                    depth=q.depth(),
                    errors=q.errors,
                )
            )
        if q.depth() > 100:
            alerts.append(
                _alert("RESEARCH", "HIGH", f"research backlog depth {q.depth()}", depth=q.depth())
            )
    except Exception:  # noqa: BLE001
        pass
    # SYSTEM — reconciliation state.
    try:
        from orchestration.runtime import get_runtime

        rt = get_runtime()
        ok = rt.last_reconciliation_ok() if hasattr(rt, "last_reconciliation_ok") else None
        if ok is False:
            alerts.append(
                _alert(
                    "RECONCILIATION",
                    "CRITICAL",
                    "internal↔MT5 reconciliation critical mismatch — "
                    "new orders blocked (fail-closed)",
                )
            )
    except Exception:  # noqa: BLE001
        pass
    # MARKET DATA — staleness (UNKNOWN-safe).
    try:
        from .readmodels import market_snapshot

        m = market_snapshot()
        fresh = m.get("staleness", {}).get("fresh")
        if fresh is False:
            alerts.append(
                _alert("MARKET_DATA", "HIGH", "market data is stale", staleness=m.get("staleness"))
            )
    except Exception:  # noqa: BLE001
        pass
    # MODEL/BUDGET — provider errors.
    try:
        from .readmodels import budget_summary, model_summary

        ms = model_summary()
        if isinstance(ms.get("count"), int) and ms.get("count") == 0:
            alerts.append(_alert("MODEL", "INFO", "no model calls recorded yet"))
        _ = budget_summary()  # informational only
    except Exception:  # noqa: BLE001
        pass
    # STRATEGY — approval pending.
    try:
        from .readmodels import strategy_summary

        ss = strategy_summary()
        for v in ss.get("versions", []) or []:
            if v.get("status") == "CANDIDATE":
                alerts.append(
                    _alert(
                        "STRATEGY",
                        "WARNING",
                        f"strategy candidate {v.get('strategy_id')} " f"awaiting manual approval",
                    )
                )
                break
    except Exception:  # noqa: BLE001
        pass
    by_sev = {s: 0 for s in ALERT_SEVERITIES}
    for a in alerts:
        by_sev[a["severity"]] = by_sev.get(a["severity"], 0) + 1
    return {"alerts": alerts, "count": len(alerts), "by_severity": by_sev}
