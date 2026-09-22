# -*- coding: utf-8 -*-
"""FastAPI router exposing honest, read-only system status endpoints.

These endpoints are consumed by the Node API control plane, replacing the
previously hard-coded demo data (PRD_V2 §25/§26/§27). Design rules:

* **Never fabricate** — an empty list is returned with ``source="live"`` when a
  subsystem simply has no in-process state yet. A missing subsystem returns
  ``source="unavailable"``.
* **Fail-safe** — model discovery and Telegram status never raise; they degrade
  to ``defaults`` / ``connected=false`` instead.
* No network is required to build the app; discovery only happens on request.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from ..audit import get_shared_audit_log
from ..execution.intents import get_intent
from ..llm.registry import ModelRegistry
from ..observability.metrics import MetricsRegistry
from ..observability.sampler import get_trend_sampler
from ..orchestration.runtime import get_runtime
from ..security.audit_log import ProtectedAuditLog
from ..system.certification import run_certification
from ..system.settings_store import get_settings_store
from ..telegram.notifier import get_gateway, get_signal_gateway

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


@router.get("/certify", summary="System certification baseline checks")
async def certify() -> dict:
    """Run all Phase‑31 baseline checks and return a list of component status dicts."""
    return {"components": run_certification()}


# ---------------------------------------------------------------------------
# Execution intent state (Phase 34 – durable execution lifecycle)
# ---------------------------------------------------------------------------


@router.get(
    "/execution/intent/{intent_id}",
    summary="Get durable execution intent state (Phase 34)",
)
async def execution_intent_state(intent_id: str) -> dict:
    """Return the stored intent record and current lifecycle state."""
    try:
        record = get_intent(intent_id)
        return {"intent": record.to_dict(), "source": "live"}
    except KeyError:
        return {"error": f"Intent {intent_id} not found", "source": "unavailable"}


# ---------------------------------------------------------------------------
# Process-wide read-only state
# ---------------------------------------------------------------------------
#
# The ModelRegistry, ProtectedAuditLog and MetricsRegistry below are process
# singletons so the control plane sees the same state the rest of the system
# accumulates. They are intentionally read-only from the HTTP surface.

_model_registry: ModelRegistry = ModelRegistry()
_audit_log: ProtectedAuditLog = get_shared_audit_log()
_metrics_registry: MetricsRegistry = MetricsRegistry()


def get_model_registry() -> ModelRegistry:
    """Return the process-wide model registry."""
    return _model_registry


def get_audit_log() -> ProtectedAuditLog:
    """Return the process-wide protected audit log."""
    return _audit_log


def get_metrics_registry() -> MetricsRegistry:
    """Return the process-wide metrics registry.

    The registry holds the real in-process counters/gauges/histograms the rest
    of the system records (EPIC 16). It is exposed read-only over HTTP so the
    Node API control plane can surface *real* metrics rather than only its own
    Node-side summary (PRD_V2 §25/§26/§27).
    """
    return _metrics_registry


def _telegram_configuration() -> dict[str, Any]:
    """Describe the Telegram gateway configuration without needing a token.

    Reports on the *shared* gateway singleton (the same object the notifier
    sends pipeline reports through), so the state is honest: ``connected`` is
    True only when a real HTTP transport is configured — i.e. a bot token is
    present and at least one chat id is allowlisted.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN") or ""
    raw_allowlist = (
        os.getenv("TELEGRAM_ALLOWED_CHAT_IDS") or os.getenv("TELEGRAM_CHAT_IDS") or ""
    )
    allowlist = [cid.strip() for cid in raw_allowlist.split(",") if cid.strip()]

    gateway = get_gateway()
    connected = bool(gateway.transport is not None and gateway.allowlist)

    poller_raw = (os.getenv("TELEGRAM_POLLER_ENABLED") or "").strip().lower()
    poller_enabled = poller_raw in {"1", "true", "yes", "on"}
    poller_token = (os.getenv("TELEGRAM_POLLER_BOT_TOKEN") or "").strip()

    # Signal bot (optional): when configured, cycle reports (digest / market
    # analysis) are delivered through it instead of the primary bot, keeping
    # the primary chat clean. Reports fall back to the primary bot otherwise.
    signal_token = (os.getenv("TELEGRAM_SIGNAL_BOT_TOKEN") or "").strip()
    signal_gateway = get_signal_gateway()
    signal_configured = bool(
        signal_token
        and signal_gateway is not None
        and getattr(signal_gateway, "transport", None) is not None
        and getattr(signal_gateway, "allowlist", None)
    )

    return {
        "enabled": bool(token) or bool(allowlist),
        "configured": bool(token and allowlist),
        "connected": connected,
        "source": "live",
        "has_token": bool(token),
        "allowlist_size": len(gateway.allowlist),
        "signal_bot_configured": signal_configured,
        "signal_bot_connected": signal_configured,
        "commands": ["/status", "/positions", "/risk", "/why", "/review", "/help"],
        # Inbound commands (chat → bot) require a SECOND bot token: Telegram
        # allows only one getUpdates consumer per bot, and the report bot may
        # already be polled elsewhere (e.g. by the operator's assistant).
        "inbound_poller_enabled": poller_enabled,
        "inbound_poller_configured": bool(poller_token),
    }


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@router.get("/ai/models", summary="List models served by the LLM registry")
async def ai_models() -> dict[str, Any]:
    """Return the models currently served by the registry plus gateway health.

    Discovery is fail-safe: on any gateway error the previously served models
    (defaults on a cold start) are returned with ``source="defaults"``.
    """
    registry = get_model_registry()
    try:
        # force=False keeps the internal TTL cache; discovery itself is fail-safe.
        registry.discover_from_gateway(force=False)
    except Exception as exc:  # noqa: BLE001 - discovery must never break the API
        logger.warning("Model discovery raised unexpectedly: %s", exc)

    models = [
        {
            "id": m.name,
            "name": m.name,
            "provider": m.provider,
            "is_free": m.is_free,
            "context": m.context_window,
            "capabilities": list(m.capabilities),
        }
        for m in registry.list_models()
    ]
    health = registry.health()
    return {
        "models": models,
        "health": health,
        "source": registry.source,
    }


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------


class AdvisorRequest(BaseModel):
    """One advisory call: role + real market context."""

    role: str = "market"
    symbol: str | None = None
    timeframe: str | None = None
    bid: float | None = None
    ask: float | None = None
    spread_pips: float | None = None
    trend: str | None = None
    note: str | None = None


@router.get("/ai/advisor/status", summary="LLM advisor guardrail + usage status")
async def ai_advisor_status() -> dict[str, Any]:
    """Report whether the advisor is enabled, its caps, and REAL usage totals."""
    from ..llm.advisor import get_llm_advisor

    return {"ok": True, **get_llm_advisor().status()}


@router.post("/ai/advisor/advise", summary="Ask the guardrailed LLM advisor")
async def ai_advisor_advise(payload: AdvisorRequest) -> dict[str, Any]:
    """Run one advisory analysis. Advisory-only: nothing consumes the output.

    Guardrails are fail-closed and reported per call (enabled, budget, data,
    caps). When any gate refuses, ``ok: false`` carries the human-readable
    reason — the UI shows it verbatim.
    """
    from ..llm.advisor import get_llm_advisor

    market = payload.model_dump(exclude_none=True, exclude={"role"})
    result = get_llm_advisor().advise(payload.role, market)
    return result.to_dict()


@router.get("/telegram/status", summary="Telegram gateway configuration state")
async def telegram_status() -> dict[str, Any]:
    """Return Telegram configuration state without requiring a live bot."""
    return _telegram_configuration()


# ---------------------------------------------------------------------------
# Audit events
# ---------------------------------------------------------------------------


@router.get("/audit/events", summary="Recent in-process audit events")
async def audit_events(limit: int = 50) -> dict[str, Any]:
    """Return recent audit events from the in-process audit log.

    An empty list is honest: no fabricated demo events are ever returned.
    """
    log = get_audit_log()
    entries = log.entries()
    if limit > 0:
        entries = entries[-limit:]
    events = [
        {
            "index": e["index"],
            "timestamp": e["timestamp"],
            "actor": e["actor"],
            "action": e["action"],
            "target": e["target"],
            "details": e["details"],
            "hash": e["hash"],
        }
        for e in entries
    ]
    return {"events": events, "count": len(events), "source": "live"}


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------


@router.get("/decisions", summary="Recent pipeline decisions")
async def decisions(limit: int = 50) -> dict[str, Any]:
    """Return recent pipeline decision results from the in-process history."""
    runtime = get_runtime()
    records = runtime.recent_decisions(limit=limit)
    return {"decisions": records, "count": len(records), "source": "live"}


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@router.get("/tasks", summary="Recent supervisor tasks")
async def tasks() -> dict[str, Any]:
    """Return recent supervisor tasks.

    No in-process task registry exists yet, so an empty list is returned with
    ``source="live"`` (an honest empty result rather than demo data).
    """
    return {
        "tasks": [],
        "counts": {"running": 0, "queued": 0, "completed": 0, "failed": 0},
        "source": "live",
    }


# ---------------------------------------------------------------------------
# Runtime settings (UI/UX ide #7)
# ---------------------------------------------------------------------------
#
# Only knobs that are *actually consumed* by the running system are writable.
# Risk limits are shown read-only with the real values the live RiskGate was
# constructed with — the dashboard never edits safety logic.


class SettingsPatch(BaseModel):
    """Partial update; validated per-knob by the store."""

    supervisor_token_budget: int | None = None
    scheduler_poll_interval: float | None = None
    trend_sample_interval: float | None = None
    llm_advisor_enabled: bool | None = None


def _apply_to_runtime(values: dict[str, float]) -> dict[str, Any]:
    """Push stored values into the live objects. Returns what was applied.

    Both targets are plain mutable attributes on already-constructed objects:
      * ``runtime.pipeline.supervisor.token_budget``
      * ``runtime.scheduler.poll_interval``
    A failure here is reported, never silently swallowed.
    """
    applied: dict[str, Any] = {}
    runtime = get_runtime()
    if "supervisor_token_budget" in values:
        supervisor = getattr(runtime.pipeline, "supervisor", None)
        if supervisor is not None and hasattr(supervisor, "token_budget"):
            supervisor.token_budget = int(values["supervisor_token_budget"])
            applied["supervisor_token_budget"] = supervisor.token_budget
    if "scheduler_poll_interval" in values:
        scheduler = getattr(runtime, "scheduler", None)
        if scheduler is not None and hasattr(scheduler, "poll_interval"):
            scheduler.poll_interval = max(
                0.001, float(values["scheduler_poll_interval"])
            )
            applied["scheduler_poll_interval"] = scheduler.poll_interval
    if "trend_sample_interval" in values:
        sampler = get_trend_sampler()
        sampler.interval = float(values["trend_sample_interval"])
        applied["trend_sample_interval"] = sampler.interval
    if "llm_advisor_enabled" in values:
        # The advisor reads the store directly on every call, so the value is
        # already live; report it so the UI can confirm what was applied.
        from ..llm.advisor import get_llm_advisor

        applied["llm_advisor_enabled"] = get_llm_advisor().status()["enabled"]
    return applied


def _risk_limits_snapshot() -> dict[str, Any]:
    """Read the REAL limits from the live risk stack (read-only, never edited).

    The live gate is ``risk.gate.RiskGate`` wrapping a ``RiskEngine`` whose
    ``_thresholds`` dict holds the authoritative numbers (keyed by
    ``RiskThreshold``), plus spread/RR limits on the gate itself. These values
    are safety logic: the dashboard renders them read-only.
    """
    runtime = get_runtime()
    gate = getattr(runtime.pipeline, "risk_gate", None)
    if gate is None:
        return {"available": False, "limits": {}}

    limits: dict[str, Any] = {
        "max_spread_pips": getattr(gate, "_max_spread_pips", None),
        "min_rr": getattr(gate, "_min_rr", None),
    }

    engine = getattr(gate, "_engine", None)
    thresholds = getattr(engine, "_thresholds", None)
    if isinstance(thresholds, dict):
        for key, value in thresholds.items():
            # RiskThreshold.MAX_DRAWDOWN -> "max_drawdown"
            name = getattr(key, "name", None)
            if name is None:
                name = getattr(key, "value", None)
            if isinstance(name, str):
                limits[name.lower()] = value

    return {"available": True, "limits": limits}


@router.get(
    "/settings", summary="Runtime settings (writable allowlist + read-only risk limits)"
)
async def get_settings() -> dict[str, Any]:
    """Return writable knobs plus the real, read-only risk limits.

    ``writable`` lists exactly what the UI may change and what each knob is
    wired to. ``risk_limits`` is informational: the dashboard renders it
    read-only because those values are safety logic.

    Read-only by contract: values are persisted at startup (see ``main``
    lifespan) and pushed on PUT — a GET never mutates the runtime.
    """
    store = get_settings_store()
    snapshot = store.snapshot()
    return {
        "source": "live",
        "writable": store.describe(),
        "values": snapshot.to_dict(),
        "risk_limits": _risk_limits_snapshot(),
    }


@router.put("/settings", summary="Update writable runtime settings")
async def put_settings(patch: SettingsPatch) -> dict[str, Any]:
    """Validate, persist, and apply settings. Rejects unknown/invalid input.

    The response reports the applied values and pushes them into the live
    runtime immediately (no restart required). Validation errors return the
    API's own messages so the UI can show them verbatim.
    """
    store = get_settings_store()
    raw = {k: v for k, v in patch.model_dump().items() if v is not None}
    applied, errors = store.update(raw)
    if errors:
        return {"ok": False, "errors": errors, "values": store.snapshot().to_dict()}
    pushed = _apply_to_runtime(applied)
    logger.info("Runtime settings updated: %s (pushed=%s)", applied, pushed)
    return {
        "ok": True,
        "errors": [],
        "values": store.snapshot().to_dict(),
        "applied": pushed,
    }


# ---------------------------------------------------------------------------
# Learning analytics
# ---------------------------------------------------------------------------


@router.get("/learning/analytics", summary="Learning-loop analytics")
async def learning_analytics() -> dict[str, Any]:
    """Report real lesson-store analytics (Fase 7).

    Reads the process-wide lesson store — the same sink both review paths
    (ReviewLead events and the paper-close auto-trigger) write to. An empty
    store reports ``available:false`` honestly; a broken store degrades to
    ``source="unavailable"`` instead of raising. Hour/regime/performance
    breakdowns stay empty until a performance tracker is wired (never
    fabricated).
    """
    try:
        from agents.analysts.review_agent import get_lesson_store

        raw_lessons = get_lesson_store().all_lessons() or []
        lessons = [lesson for lesson in raw_lessons if isinstance(lesson, dict)]
    except Exception as exc:  # fail-safe: a status endpoint must never raise
        logger.warning("Lesson store unavailable for analytics: %s", exc)
        return {
            "available": False,
            "source": "unavailable",
            "by_hour": [],
            "by_regime": [],
            "supervisor_kpis": None,
            "lessons": [],
            "by_outcome": {},
            "total": 0,
        }

    by_outcome: dict[str, int] = {}
    for lesson in lessons:
        outcome = str(lesson.get("outcome") or "").strip().lower()
        if outcome:
            by_outcome[outcome] = by_outcome.get(outcome, 0) + 1

    return {
        "available": bool(lessons),
        "source": "lesson_store",
        "by_hour": [],
        "by_regime": [],
        "supervisor_kpis": None,
        "lessons": [
            {
                "id": str(
                    lesson.get("trade_id") or lesson.get("id") or f"lesson_{index}"
                ),
                "category": str(lesson.get("category") or ""),
                "outcome": str(lesson.get("outcome") or ""),
                "symbol": str(lesson.get("symbol") or ""),
                "text": str(lesson.get("lesson") or lesson.get("rule") or ""),
            }
            for index, lesson in enumerate(lessons)
        ],
        "by_outcome": by_outcome,
        "total": len(lessons),
    }


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@router.get("/observability/metrics", summary="In-process metrics snapshot")
async def observability_metrics() -> dict[str, Any]:
    """Return a JSON snapshot of the in-process :class:`MetricsRegistry`.

    The snapshot is deterministic (``counters`` / ``gauges`` / ``histograms``,
    each keyed by name) so the Node API control plane can merge *real* Python
    metrics into its dashboard response. An empty registry yields a valid empty
    snapshot — never fabricated values.
    """
    registry = get_metrics_registry()
    return {"metrics": registry.snapshot(), "source": "live"}


# ---------------------------------------------------------------------------
# Trend history (UI/UX ide #8)
# ---------------------------------------------------------------------------


@router.get("/observability/trend", summary="Trend history of real samples")
async def observability_trend(limit: int = 0) -> dict[str, Any]:
    """Return the sampler's ring buffer of REAL samples (oldest first).

    Sections that could not be read are ``null`` for that sample — the UI is
    expected to draw a gap, never a fabricated zero. ``capacity``/``interval``
    are included so the chart can label its own window honestly.
    """
    sampler = get_trend_sampler()
    samples = sampler.history(limit=limit)
    return {
        "samples": samples,
        "count": len(samples),
        "capacity": sampler.capacity,
        "interval_s": sampler.interval,
        "sampling": sampler.running,
        "source": "live",
    }
