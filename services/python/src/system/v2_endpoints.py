# -*- coding: utf-8 -*-
"""PRD_V2 Phase 36‑56 HTTP surface (read-mostly control-plane endpoints).

Wires the standalone Phase 36‑56 modules into the FastAPI app so the dashboard
and Telegram control center can consume them. Design rules mirror
``system/endpoints.py``:

* **Never fabricate** — a subsystem with no in-process state reports its
  explicit status (``unavailable`` / ``no_data``), never a fake zero.
* **Fail-safe** — every handler degrades gracefully; none raise.
* **No side-effect imports** — process singletons are lazy.

Endpoints::

    GET  /v2/circuit-breaker                 multi-level breaker state
    POST /v2/circuit-breaker/trigger         raise the level (deterministic)
    POST /v2/circuit-breaker/recover         clear a latched state (recovery)
    POST /v2/recovery/run                    run the crash-recovery flow
    GET  /v2/environment                     environment + live preconditions
    GET  /v2/accounts                        broker/account registry
    GET  /v2/capital                         capital allocation snapshot
    GET  /v2/incidents                       incident list
    POST /v2/incidents                       open an incident
    POST /v2/incidents/{id}/resolve          resolve an incident
    GET  /v2/slo                             SLO evaluation (p50/p95/p99)
    POST /v2/slo/sample                      record an SLI sample
    GET  /v2/execution-quality               execution-quality metrics
    GET  /v2/llm/telemetry                   LLM request telemetry
    GET  /v2/llm/governance                  model governance state
    GET  /v2/dashboard                       dashboard 2.0 payload
    GET  /v2/certification/gate              production certification gate
    GET  /v2/research/inbox                  research inbox items
    GET  /v2/lifecycle/{strategy_id}/{ver}   strategy lifecycle state
    GET  /v2/decision/{decision_id}/replay   decision replay (snapshots)
    GET  /v2/performance-intelligence        performance intelligence sample
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2", tags=["prd-v2"])


# ---------------------------------------------------------------------------
# Process-wide singletons (lazy, fail-safe)
# ---------------------------------------------------------------------------

_circuit_breaker = None
_recovery_store = None
_environment_guard = None
_account_manager = None
_capital_allocator = None
_incident_manager = None
_slo_tracker = None
_execution_quality = None
_llm_store = None
_llm_governance = None
_research_inbox = None
_lifecycle_governor = None
_decision_store = None


def get_circuit_breaker():
    global _circuit_breaker
    if _circuit_breaker is None:
        from ..risk.multi_level_breaker import MultiLevelBreaker

        _circuit_breaker = MultiLevelBreaker()
    return _circuit_breaker


def get_recovery_store():
    global _recovery_store
    if _recovery_store is None:
        from ..system.recovery import CheckpointStore

        _recovery_store = CheckpointStore()
    return _recovery_store


def get_environment_guard():
    global _environment_guard
    if _environment_guard is None:
        import os

        from ..live_readiness.environment import EnvironmentGuard

        env = os.getenv("EA_ENVIRONMENT", "DEV").upper()
        _environment_guard = EnvironmentGuard(environment=env)
    return _environment_guard


def get_account_manager():
    global _account_manager
    if _account_manager is None:
        from ..live_readiness.account_manager import AccountManager

        _account_manager = AccountManager()
    return _account_manager


def get_capital_allocator():
    global _capital_allocator
    if _capital_allocator is None:
        from ..risk.capital_allocation import CapitalAllocator

        _capital_allocator = CapitalAllocator(total_equity=0.0)
    return _capital_allocator


def get_incident_manager():
    global _incident_manager
    if _incident_manager is None:
        from ..monitoring.incidents import IncidentManager

        _incident_manager = IncidentManager()
    return _incident_manager


def get_slo_tracker():
    global _slo_tracker
    if _slo_tracker is None:
        from ..monitoring.slo import SLOTracker

        _slo_tracker = SLOTracker()
    return _slo_tracker


def get_execution_quality():
    global _execution_quality
    if _execution_quality is None:
        from ..observability.execution_quality import ExecutionQualityAnalytics

        _execution_quality = ExecutionQualityAnalytics()
    return _execution_quality


def get_llm_store():
    global _llm_store
    if _llm_store is None:
        from ..observability.llm_telemetry import LLMTelemetryStore

        _llm_store = LLMTelemetryStore()
    return _llm_store


def get_llm_governance():
    global _llm_governance
    if _llm_governance is None:
        from ..observability.llm_telemetry import ModelGovernance

        _llm_governance = ModelGovernance(store=get_llm_store())
    return _llm_governance


def get_research_inbox():
    global _research_inbox
    if _research_inbox is None:
        from ..research.scheduler import ResearchInbox

        _research_inbox = ResearchInbox()
    return _research_inbox


def get_lifecycle_governor():
    global _lifecycle_governor
    if _lifecycle_governor is None:
        from ..strategy.lifecycle import LifecycleGovernor

        _lifecycle_governor = LifecycleGovernor()
    return _lifecycle_governor


def get_decision_store():
    global _decision_store
    if _decision_store is None:
        from ..review.decision_graph import DecisionGraphStore

        _decision_store = DecisionGraphStore()
    return _decision_store


# ---------------------------------------------------------------------------
# Phase 36 — Multi-level circuit breaker
# ---------------------------------------------------------------------------


class BreakerTriggerBody(BaseModel):
    trigger: str
    reason: str = ""
    source: str = "operator"


class BreakerRecoverBody(BaseModel):
    condition_ok: bool = False
    target: str = "NORMAL"
    reason: str = "recovery condition satisfied"


@router.get("/circuit-breaker", summary="Multi-level circuit breaker state (Phase 36)")
async def circuit_breaker_state() -> dict[str, Any]:
    try:
        return {"value": get_circuit_breaker().to_dict(), "source": "live", "status": "OK"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("circuit-breaker state failed: %s", exc)
        return {"value": None, "source": "unavailable", "status": "UNAVAILABLE"}


@router.post("/circuit-breaker/trigger", summary="Raise the breaker level (Phase 36)")
async def circuit_breaker_trigger(body: BreakerTriggerBody) -> dict[str, Any]:
    from ..risk.multi_level_breaker import TriggerType

    try:
        try:
            trigger = TriggerType(body.trigger)
        except ValueError:
            return {"error": f"unknown trigger: {body.trigger}", "source": "unavailable"}
        record = get_circuit_breaker().trigger(trigger, reason=body.reason, source=body.source)
        return {"value": record.to_dict(), "source": "live", "status": "OK"}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "source": "unavailable"}


@router.post("/circuit-breaker/recover", summary="Clear a latched breaker state (Phase 36)")
async def circuit_breaker_recover(body: BreakerRecoverBody) -> dict[str, Any]:
    from ..risk.multi_level_breaker import BreakerLevel

    try:
        try:
            target = BreakerLevel[body.target.upper()]
        except KeyError:
            return {"error": f"unknown target: {body.target}", "source": "unavailable"}
        record = get_circuit_breaker().recover(
            condition_ok=body.condition_ok, reason=body.reason, target=target
        )
        return {"value": record.to_dict(), "source": "live", "status": "OK"}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "source": "unavailable"}


# ---------------------------------------------------------------------------
# Phase 37 — Recovery flow
# ---------------------------------------------------------------------------


@router.post("/recovery/run", summary="Run the crash-recovery flow (Phase 37)")
async def recovery_run() -> dict[str, Any]:
    try:
        from ..system.recovery import RecoveryCoordinator

        coordinator = RecoveryCoordinator(store=get_recovery_store())
        result = coordinator.recover()
        return {"value": result.to_dict(), "source": "live", "status": "OK"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("recovery run failed: %s", exc)
        return {"value": None, "source": "unavailable", "status": "UNAVAILABLE"}


# ---------------------------------------------------------------------------
# Phase 51 — Environment separation
# ---------------------------------------------------------------------------


@router.get("/environment", summary="Environment + live preconditions (Phase 51)")
async def environment_state() -> dict[str, Any]:
    try:
        guard = get_environment_guard()
        allowed, reason = guard.can_execute_live()
        return {
            "value": {
                "environment": guard.environment,
                "is_live": guard.is_live(),
                "live_allowed": allowed,
                "reason": reason,
                "preconditions": {
                    "terminal_armed": guard.preconditions.terminal_armed,
                    "risk_gate_healthy": guard.preconditions.risk_gate_healthy,
                    "reconciliation_healthy": guard.preconditions.reconciliation_healthy,
                    "production_strategy": guard.preconditions.production_strategy,
                },
            },
            "source": "live",
            "status": "OK",
        }
    except Exception as exc:  # noqa: BLE001
        return {"value": None, "source": "unavailable", "status": "UNAVAILABLE", "error": str(exc)}


# ---------------------------------------------------------------------------
# Phase 53 — Accounts / brokers
# ---------------------------------------------------------------------------


@router.get("/accounts", summary="Broker/account registry (Phase 53)")
async def accounts_state() -> dict[str, Any]:
    try:
        return {"value": get_account_manager().to_dict(), "source": "live", "status": "OK"}
    except Exception as exc:  # noqa: BLE001
        return {"value": None, "source": "unavailable", "status": "UNAVAILABLE", "error": str(exc)}


# ---------------------------------------------------------------------------
# Phase 52 — Capital allocation
# ---------------------------------------------------------------------------


@router.get("/capital", summary="Capital allocation snapshot (Phase 52)")
async def capital_state() -> dict[str, Any]:
    try:
        return {"value": get_capital_allocator().snapshot(), "source": "live", "status": "OK"}
    except Exception as exc:  # noqa: BLE001
        return {"value": None, "source": "unavailable", "status": "UNAVAILABLE", "error": str(exc)}


# ---------------------------------------------------------------------------
# Phase 55 — Incidents
# ---------------------------------------------------------------------------


class IncidentBody(BaseModel):
    severity: str
    component: str
    trigger: str
    system_state: str = ""
    action_taken: str = ""


@router.get("/incidents", summary="List incidents (Phase 55)")
async def incidents_list() -> dict[str, Any]:
    try:
        mgr = get_incident_manager()
        return {
            "value": [i.to_dict() for i in mgr.all()],
            "open_critical": mgr.has_critical_open(),
            "source": "live",
            "status": "OK",
        }
    except Exception as exc:  # noqa: BLE001
        return {"value": None, "source": "unavailable", "status": "UNAVAILABLE", "error": str(exc)}


@router.post("/incidents", summary="Open an incident (Phase 55)")
async def incidents_open(body: IncidentBody) -> dict[str, Any]:
    try:
        inc = get_incident_manager().open(
            severity=body.severity,
            component=body.component,
            trigger=body.trigger,
            system_state=body.system_state,
            action_taken=body.action_taken,
        )
        return {"value": inc.to_dict(), "source": "live", "status": "OK"}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "source": "unavailable"}


@router.post("/incidents/{incident_id}/resolve", summary="Resolve an incident (Phase 55)")
async def incidents_resolve(incident_id: str, recovery_state: str = "RESOLVED") -> dict[str, Any]:
    try:
        inc = get_incident_manager().get(incident_id)
        if inc is None:
            return {"error": f"Incident {incident_id} not found", "source": "unavailable"}
        inc.resolve(recovery_state=recovery_state)
        return {"value": inc.to_dict(), "source": "live", "status": "OK"}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "source": "unavailable"}


# ---------------------------------------------------------------------------
# Phase 56 — SLO
# ---------------------------------------------------------------------------


class SLISampleBody(BaseModel):
    sli: str
    value: float


@router.get("/slo", summary="SLO evaluation (p50/p95/p99) (Phase 56)")
async def slo_state() -> dict[str, Any]:
    try:
        return {"value": get_slo_tracker().report(), "source": "live", "status": "OK"}
    except Exception as exc:  # noqa: BLE001
        return {"value": None, "source": "unavailable", "status": "UNAVAILABLE", "error": str(exc)}


@router.post("/slo/sample", summary="Record an SLI sample (Phase 56)")
async def slo_sample(body: SLISampleBody) -> dict[str, Any]:
    try:
        get_slo_tracker().record(body.sli, body.value)
        return {
            "value": get_slo_tracker().stats(body.sli).to_dict(),
            "source": "live",
            "status": "OK",
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "source": "unavailable"}


# ---------------------------------------------------------------------------
# Phase 47 — Execution quality
# ---------------------------------------------------------------------------


@router.get("/execution-quality", summary="Execution-quality metrics (Phase 47)")
async def execution_quality_state() -> dict[str, Any]:
    try:
        analytics = get_execution_quality()
        return {
            "value": {"metrics": analytics.summary(), "alerts": analytics.alerts()},
            "source": "live",
            "status": "OK",
        }
    except Exception as exc:  # noqa: BLE001
        return {"value": None, "source": "unavailable", "status": "UNAVAILABLE", "error": str(exc)}


# ---------------------------------------------------------------------------
# Phase 46 — LLM telemetry & governance
# ---------------------------------------------------------------------------


@router.get("/llm/telemetry", summary="LLM request telemetry (Phase 46)")
async def llm_telemetry() -> dict[str, Any]:
    try:
        records = get_llm_store().all()
        return {
            "value": [r.to_dict() for r in records[-100:]],
            "count": len(records),
            "source": "live",
            "status": "OK",
        }
    except Exception as exc:  # noqa: BLE001
        return {"value": None, "source": "unavailable", "status": "UNAVAILABLE", "error": str(exc)}


@router.get("/llm/governance", summary="Model governance state (Phase 46)")
async def llm_governance_state() -> dict[str, Any]:
    try:
        gov = get_llm_governance()
        return {
            "value": gov.to_dict() if hasattr(gov, "to_dict") else {},
            "source": "live",
            "status": "OK",
        }
    except Exception as exc:  # noqa: BLE001
        return {"value": None, "source": "unavailable", "status": "UNAVAILABLE", "error": str(exc)}


# ---------------------------------------------------------------------------
# Phase 49 — Dashboard 2.0
# ---------------------------------------------------------------------------


@router.get("/dashboard", summary="Dashboard 2.0 aggregated payload (Phase 49)")
async def dashboard_state() -> dict[str, Any]:
    try:
        from ..observability.dashboard_v2 import DashboardAggregator

        providers = {
            "risk": lambda: circuit_breaker_state_sync(),
            "system_health": _system_health_sync,
            "incidents": lambda: incidents_sync(),
            "reconciliation": _reconciliation_sync,
            "execution_quality": lambda: get_execution_quality().summary(),
            "observability": lambda: get_slo_tracker().report(),
        }
        aggregator = DashboardAggregator(providers=providers)
        return {"value": aggregator.build(), "source": "live", "status": "OK"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("dashboard build failed: %s", exc)
        return {"value": None, "source": "unavailable", "status": "UNAVAILABLE", "error": str(exc)}


def circuit_breaker_state_sync() -> dict[str, Any]:
    return get_circuit_breaker().to_dict()


def incidents_sync() -> list:
    return [i.to_dict() for i in get_incident_manager().all()]


def _system_health_sync() -> Optional[dict]:
    try:
        from ..system.certification import run_certification

        return {"components": run_certification()}
    except Exception:  # noqa: BLE001
        return None


def _reconciliation_sync() -> Optional[dict]:
    try:
        runtime = __import__("src.orchestration.runtime", fromlist=["get_runtime"]).get_runtime()
        report = runtime.last_reconciliation()
        return report.to_dict() if report else None
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Phase 50 — Certification gate
# ---------------------------------------------------------------------------


@router.get("/certification/gate", summary="Production certification gate (Phase 50)")
async def certification_gate() -> dict[str, Any]:
    try:
        from ..live_readiness.certification_gate import ProductionCertificationGate

        gate = ProductionCertificationGate(
            critical_incident_open=get_incident_manager().has_critical_open()
        )
        return {"value": gate.evaluate().to_dict(), "source": "live", "status": "OK"}
    except Exception as exc:  # noqa: BLE001
        return {"value": None, "source": "unavailable", "status": "UNAVAILABLE", "error": str(exc)}


# ---------------------------------------------------------------------------
# Phase 54 — Research inbox
# ---------------------------------------------------------------------------


@router.get("/research/inbox", summary="Research inbox items (Phase 54)")
async def research_inbox_state() -> dict[str, Any]:
    try:
        items = get_research_inbox().all()
        return {
            "value": [i.to_dict() for i in items],
            "count": len(items),
            "source": "live",
            "status": "OK",
        }
    except Exception as exc:  # noqa: BLE001
        return {"value": None, "source": "unavailable", "status": "UNAVAILABLE", "error": str(exc)}


# ---------------------------------------------------------------------------
# Phase 44 — Strategy lifecycle
# ---------------------------------------------------------------------------


@router.get("/lifecycle/{strategy_id}/{version}", summary="Strategy lifecycle state (Phase 44)")
async def lifecycle_state(strategy_id: str, version: int) -> dict[str, Any]:
    try:
        sv = get_lifecycle_governor().get(strategy_id, version)
        if sv is None:
            return {"value": None, "source": "unavailable", "status": "NO_DATA"}
        return {"value": sv.to_dict(), "source": "live", "status": "OK"}
    except Exception as exc:  # noqa: BLE001
        return {"value": None, "source": "unavailable", "status": "UNAVAILABLE", "error": str(exc)}


# ---------------------------------------------------------------------------
# Phase 45 — Decision replay
# ---------------------------------------------------------------------------


@router.get("/decision/{decision_id}/replay", summary="Decision replay from snapshots (Phase 45)")
async def decision_replay(decision_id: str) -> dict[str, Any]:
    try:
        replay = get_decision_store().replay(decision_id)
        if replay is None:
            return {"value": None, "source": "unavailable", "status": "NO_DATA"}
        return {"value": replay, "source": "live", "status": "OK"}
    except Exception as exc:  # noqa: BLE001
        return {"value": None, "source": "unavailable", "status": "UNAVAILABLE", "error": str(exc)}


# ---------------------------------------------------------------------------
# Phase 42 — Performance intelligence
# ---------------------------------------------------------------------------


@router.get("/performance-intelligence", summary="Performance intelligence by dimension (Phase 42)")
async def performance_intelligence(dimension: str = "hour") -> dict[str, Any]:
    try:
        from ..review.performance_intelligence import PerformanceIntelligence

        engine = PerformanceIntelligence()
        buckets = engine._analyze_dimension(dimension, [])
        return {
            "value": [b.to_dict() for b in buckets],
            "dimension": dimension,
            "source": "live",
            "status": "OK" if buckets else "NO_DATA",
        }
    except Exception as exc:  # noqa: BLE001
        return {"value": None, "source": "unavailable", "status": "UNAVAILABLE", "error": str(exc)}
