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

from ..llm.registry import ModelRegistry
from ..observability.metrics import MetricsRegistry
from ..orchestration.runtime import get_runtime
from ..security.audit_log import ProtectedAuditLog
from ..telegram.gateway import TelegramGateway

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])

# ---------------------------------------------------------------------------
# Process-wide read-only state
# ---------------------------------------------------------------------------
#
# The ModelRegistry, ProtectedAuditLog and MetricsRegistry below are process
# singletons so the control plane sees the same state the rest of the system
# accumulates. They are intentionally read-only from the HTTP surface.

_model_registry: ModelRegistry = ModelRegistry()
_audit_log: ProtectedAuditLog = ProtectedAuditLog()
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

    Reads only environment configuration. ``connected`` is True only when a real
    transport has been successfully configured; we never claim a live bot when
    only the *possibility* of one exists.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN") or ""
    raw_allowlist = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS") or os.getenv("TELEGRAM_CHAT_IDS") or ""
    allowlist = [cid.strip() for cid in raw_allowlist.split(",") if cid.strip()]

    configured = bool(token and allowlist)
    # A gateway object is only "connected" when a transport is available. Since
    # constructing a real HTTP transport requires a token, and this module never
    # constructs one eagerly, report honestly: connected == False here.
    gateway = TelegramGateway(transport=None, allowlist=allowlist)

    return {
        "enabled": bool(token) or bool(allowlist),
        "configured": configured,
        "connected": False,
        "source": "live",
        "has_token": bool(token),
        "allowlist_size": len(gateway.allowlist),
        "commands": ["/status", "/positions", "/risk", "/why", "/review", "/help"],
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
# Learning analytics
# ---------------------------------------------------------------------------


@router.get("/learning/analytics", summary="Learning-loop analytics")
async def learning_analytics() -> dict[str, Any]:
    """Return learning-loop/performance data if available in-process.

    There is no process-wide performance tracker wired yet, so this honestly
    reports ``unavailable`` rather than fabricating analytics.
    """
    return {
        "available": False,
        "source": "unavailable",
        "by_hour": [],
        "by_regime": [],
        "supervisor_kpis": None,
        "lessons": [],
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
