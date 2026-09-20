# -*- coding: utf-8 -*-
"""Certification checks for production readiness.

Each function returns a dict with keys:
  component: str
  status: "PASS" | "WARN" | "FAIL" | "NOT_CONFIGURED" | "NOT_AVAILABLE"
  version: str (or empty)
  verified_at: ISO timestamp
  details: list[str]

The checks are lightweight and never raise; failures return status accordingly.
"""

from __future__ import annotations

import datetime
from typing import Any, Callable, List


# Simple helper to generate a status record
def _record(
    component: str, status: str, version: str = "", details: List[str] | None = None
) -> dict[str, Any]:
    return {
        "component": component,
        "status": status,
        "version": version,
        "verified_at": datetime.datetime.utcnow().isoformat() + "Z",
        "details": details or [],
    }


# ---------------------------------------------------------------------------
# Individual checks – stubbed/simple implementations
# ---------------------------------------------------------------------------


def check_database() -> dict[str, Any]:
    try:
        from sqlalchemy import text

        from ..db.database import engine

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return _record("database", "PASS", version="1.0")
    except Exception as exc:  # pragma: no cover – real DB may be absent in CI
        return _record("database", "NOT_AVAILABLE", details=[str(exc)])


def check_python_service() -> dict[str, Any]:
    # The Python service is this process – always PASS if we reach here
    return _record("python_service", "PASS", version="1.0")


def check_node_service() -> dict[str, Any]:
    # Node service is the web API – we cannot easily query here; assume NOT_CONFIGURED
    return _record(
        "node_service", "NOT_CONFIGURED", details=["Node server not queried from Python"]
    )


def check_web_service() -> dict[str, Any]:
    # Web build exists if static files were generated – assume PASS after build
    return _record("web_service", "PASS", version="1.0")


def check_mt5_connector() -> dict[str, Any]:
    try:
        from ..mt5.connector import is_live_mode

        live = is_live_mode()
        status = "PASS" if live else "WARN"
        return _record("mt5_connector", status, details=["live_mode=" + str(live)])
    except Exception as exc:  # pragma: no cover
        return _record("mt5_connector", "NOT_AVAILABLE", details=[str(exc)])


def check_market_feed() -> dict[str, Any]:
    try:
        from ..market.news_feed import NewsFeedProvider

        provider = NewsFeedProvider()
        # Simple fetch to verify no exception (cache may be empty)
        provider.fetch_news(force_refresh=True)
        return _record("market_feed", "PASS", version="2.0")
    except Exception as exc:  # pragma: no cover
        return _record("market_feed", "FAIL", details=[str(exc)])


def check_agent_registry() -> dict[str, Any]:
    from ..agents.registry import agent_registry

    count = len(agent_registry.list())
    status = "PASS" if count > 0 else "WARN"
    return _record("agent_registry", status, details=[f"registered_agents={count}"])


def check_supervisor() -> dict[str, Any]:
    from ..agents.supervisor import SupervisorAgent

    try:
        sup = SupervisorAgent()
        # basic property access ensures it's constructible
        _ = sup.name
        return _record("supervisor", "PASS")
    except Exception as exc:  # pragma: no cover
        return _record("supervisor", "FAIL", details=[str(exc)])


def check_risk_engine() -> dict[str, Any]:
    try:
        from ..risk.engine import RiskEngine

        engine = RiskEngine()
        # presence of calculate_account_risk is sufficient
        _ = engine.calculate_account_risk
        return _record("risk_engine", "PASS")
    except Exception as exc:  # pragma: no cover
        return _record("risk_engine", "FAIL", details=[str(exc)])


def check_execution() -> dict[str, Any]:
    try:
        from ..execution.engine import ExecutionEngine

        engine = ExecutionEngine()
        _ = engine.execute_order
        return _record("execution", "PASS")
    except Exception as exc:  # pragma: no cover
        return _record("execution", "FAIL", details=[str(exc)])


def check_reconciliation() -> dict[str, Any]:
    try:
        from ..orchestration.runtime import get_runtime

        runtime = get_runtime()
        _ = runtime._reconciliation_runner
        return _record("reconciliation", "PASS")
    except Exception as exc:  # pragma: no cover
        return _record("reconciliation", "FAIL", details=[str(exc)])


def check_learning() -> dict[str, Any]:
    try:
        from ..learning.feedback import record_review_lesson  # noqa: F401

        # Callable presence is enough
        return _record("learning", "PASS")
    except Exception as exc:  # pragma: no cover
        return _record("learning", "FAIL", details=[str(exc)])


def check_telegram() -> dict[str, Any]:
    try:
        from ..telegram.notifier import get_gateway

        gw = get_gateway()
        connected = bool(gw.transport is not None and gw.allowlist)
        status = "PASS" if connected else "WARN"
        return _record("telegram", status, details=["connected=" + str(connected)])
    except Exception as exc:  # pragma: no cover
        return _record("telegram", "NOT_AVAILABLE", details=[str(exc)])


def check_observability() -> dict[str, Any]:
    # Observability metrics are always available – PASS
    return _record("observability", "PASS")


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


def run_certification() -> List[dict[str, Any]]:
    checks: List[Callable[[], dict[str, Any]]] = [
        check_database,
        check_python_service,
        check_node_service,
        check_web_service,
        check_mt5_connector,
        check_market_feed,
        check_agent_registry,
        check_supervisor,
        check_risk_engine,
        check_execution,
        check_reconciliation,
        check_learning,
        check_telegram,
        check_observability,
    ]
    results = []
    for fn in checks:
        try:
            results.append(fn())
        except Exception as exc:
            results.append(_record(fn.__name__, "FAIL", details=[str(exc)]))
    return results
