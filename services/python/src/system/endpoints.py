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

import asyncio
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
    raw_allowlist = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS") or os.getenv("TELEGRAM_CHAT_IDS") or ""
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
        # Discovery is blocking network I/O: run it in a worker thread so the
        # event loop (and every other endpoint) is never stalled while the LLM
        # gateway is slow or unreachable. force=False keeps the caches
        # (positive + negative) and discovery itself is fail-safe.
        await asyncio.to_thread(registry.discover_from_gateway, force=False)
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
    """Return recent agent activity as task rows (real, in-process state).

    Rows are built from the process-wide :class:`AgentActivityTracker` — the
    same singleton the pipeline records every agent run into. An empty list is
    returned honestly (``source="live"``) when no agent has run yet. The
    tracker is accessed fail-safe: observability must never break the endpoint.
    """
    try:
        from ..agents.activity import get_activity_tracker

        snapshot = get_activity_tracker().snapshot()
    except Exception as exc:  # noqa: BLE001 - a status endpoint must never raise
        logger.warning("Activity tracker unavailable for /tasks: %s", exc)
        snapshot = {}

    rows: list[dict[str, Any]] = []
    for name, entry in snapshot.items():
        for idx, rec in enumerate(entry.get("recent", [])):
            at = rec.get("at", "")
            rows.append(
                {
                    "id": f"{name}-{idx}-{at}",
                    "timestamp": at,
                    "agent": name,
                    "action": f"analisis {rec.get('signal')} ({rec.get('confidence')})",
                    "status": "success",
                }
            )
    # Newest first; cap the payload for the control plane.
    rows.sort(key=lambda r: r["timestamp"], reverse=True)
    rows = rows[:50]
    return {
        "tasks": rows,
        "counts": {
            "running": 0,
            "queued": 0,
            "completed": len(rows),
            "failed": 0,
        },
        "source": "live",
    }


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------


@router.get("/supervisor/status", summary="Live supervisor runtime status")
async def supervisor_status() -> dict[str, Any]:
    """Expose the REAL in-memory supervisor state (concurrency + budget).

    Reads the same supervisor instance the pipeline dispatches through, so the
    control plane sees live ``max_concurrency``/``token_budget``/``token_used``
    rather than a fabricated placeholder.
    """
    runtime = get_runtime()
    supervisor = getattr(getattr(runtime, "pipeline", None), "supervisor", None)
    if supervisor is None:
        return {"supervisor": None, "source": "unavailable"}
    return {
        "supervisor": {
            "max_concurrency": int(getattr(supervisor, "max_concurrency", 0) or 0),
            "token_budget": int(getattr(supervisor, "token_budget", 0) or 0),
            "token_used": int(getattr(supervisor, "token_used", 0) or 0),
            "routing_policy": str(getattr(supervisor, "routing_policy", "") or ""),
        },
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
    risk_per_trade_pct: float | None = None
    max_lot_per_trade: float | None = None
    sltp_management_enabled: bool | None = None
    sltp_breakeven_enabled: bool | None = None
    sltp_progressive_enabled: bool | None = None
    sltp_trailing_enabled: bool | None = None
    fanout_enabled: bool | None = None
    zone_entry_enabled: bool | None = None


def _apply_to_runtime(values: dict[str, float]) -> dict[str, Any]:
    """Push stored values into the live objects. Returns what was applied.

    Every knob is applied in its OWN try/except so a failure in one never
    aborts the rest — a silent early bail here once let ``max_lot_per_trade``
    keep its unsafe default (a real 1.0-lot order slipped past a 0.05 cap).
    Failures are logged and reported under ``_errors`` rather than swallowed.
    """
    applied: dict[str, Any] = {}
    errors: dict[str, str] = {}
    runtime = get_runtime()

    def _push(key: str, fn: Any) -> None:
        try:
            result = fn()
            if result is not None:
                applied[key] = result
        except Exception as exc:  # noqa: BLE001 - one knob never blocks others
            errors[key] = str(exc)
            logger.warning("Could not apply setting %s: %s", key, exc)

    def _pipeline() -> Any:
        return getattr(runtime, "pipeline", None)

    def _set_attr(obj: Any, attr: str, value: Any) -> Any:
        if obj is not None and hasattr(obj, attr):
            setattr(obj, attr, value)
            return value
        return None

    # Size/risk knobs FIRST — these are the money-safety caps.
    if "max_lot_per_trade" in values:
        cap = float(values["max_lot_per_trade"])
        if not (0 < cap <= 100):
            cap = 0.05  # fail-safe floor
        _push("max_lot_per_trade", lambda: _set_attr(_pipeline(), "max_lot_per_trade", cap))
    if "risk_per_trade_pct" in values:
        _push(
            "risk_per_trade_pct",
            lambda: _set_attr(_pipeline(), "default_risk_pct", float(values["risk_per_trade_pct"])),
        )
    if "supervisor_token_budget" in values:
        _push(
            "supervisor_token_budget",
            lambda: _set_attr(
                getattr(_pipeline(), "supervisor", None),
                "token_budget",
                int(values["supervisor_token_budget"]),
            ),
        )
    if "scheduler_poll_interval" in values:
        _push(
            "scheduler_poll_interval",
            lambda: _set_attr(
                getattr(runtime, "scheduler", None),
                "poll_interval",
                max(0.001, float(values["scheduler_poll_interval"])),
            ),
        )
    if "trend_sample_interval" in values:
        _push(
            "trend_sample_interval",
            lambda: setattr(get_trend_sampler(), "interval", float(values["trend_sample_interval"]))
            or get_trend_sampler().interval,
        )
    if "llm_advisor_enabled" in values:
        # The advisor reads the store directly on every call, so the value is
        # already live; report it so the UI can confirm.
        _push(
            "llm_advisor_enabled",
            lambda: __import__("src.llm.advisor", fromlist=["get_llm_advisor"])
            .get_llm_advisor()
            .status()["enabled"],
        )
    # SLTP knobs: the trade manager reads the store live each cycle, so the
    # value is already in effect; report it so the UI can confirm.
    for sltp_key in (
        "sltp_management_enabled",
        "sltp_breakeven_enabled",
        "sltp_progressive_enabled",
        "sltp_trailing_enabled",
    ):
        if sltp_key in values:
            applied[sltp_key] = bool(values[sltp_key])
    # Fan-out / zone-entry toggles: the pipeline reads the store LIVE each cycle
    # (via a provider), so the value is already in effect; report it so the UI
    # can confirm without a restart.
    for toggle_key in ("fanout_enabled", "zone_entry_enabled"):
        if toggle_key in values:
            applied[toggle_key] = bool(values[toggle_key])
    if errors:
        applied["_errors"] = errors
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
        # ``max_position_size`` is defined on RiskEngine but NEVER enforced by
        # the gate (``check_position_size`` has no caller on the order path).
        # Showing it read-only implies it is active — it is not — so we omit it
        # to keep the "Batas risiko" panel honest. Only limits the gate really
        # checks are shown.
        _not_enforced = {"max_position_size"}
        for key, value in thresholds.items():
            # RiskThreshold.MAX_DRAWDOWN -> "max_drawdown"
            name = getattr(key, "name", None)
            if name is None:
                name = getattr(key, "value", None)
            if isinstance(name, str):
                lowered = name.lower()
                if lowered in _not_enforced:
                    continue
                limits[lowered] = value

    return {"available": True, "limits": limits}


@router.get("/settings", summary="Runtime settings (writable allowlist + read-only risk limits)")
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
                # Guarantee a unique id: trade_id (from the lesson) can repeat
                # across lessons (e.g. several lessons for the same trade, or a
                # shared "T-1" placeholder), so suffix the position to keep the
                # key stable-and-unique for list rendering.
                "id": f"{lesson.get('trade_id') or lesson.get('id') or 'lesson'}#{index}",
                "trade_id": str(lesson.get("trade_id") or ""),
                "category": str(lesson.get("category") or ""),
                "outcome": str(lesson.get("outcome") or ""),
                "symbol": str(lesson.get("symbol") or ""),
                "text": str(lesson.get("lesson") or lesson.get("rule") or ""),
            }
            for index, lesson in enumerate(lessons)
        ],
        "by_outcome": by_outcome,
        "total": len(lessons),
        "learning_engine_v2": _learning_engine_v2_snapshot(),
    }


def _learning_engine_v2_snapshot() -> dict[str, Any]:
    """Evidence-graded Learning Engine 2.0 snapshot (PRD §43).

    Reads the persistent v2 lesson store and aggregates patterns. Fail-safe:
    any error degrades to an honest ``available: false`` — never raises.
    """
    try:
        from learning.engine_v2 import LearningEngineV2
        from learning.engine_v2_store import get_engine_v2_store

        store = get_engine_v2_store()
        if store is None:
            return {"available": False, "source": "not_wired", "lessons": 0, "patterns": []}
        records = store.all_lessons()
        if not records:
            return {"available": False, "source": "engine_v2_store", "lessons": 0, "patterns": []}

        engine = LearningEngineV2()
        for record in records:
            try:
                from learning.engine_v2 import Lesson

                engine.record_lesson(Lesson(**record))
            except Exception:  # noqa: BLE001 - skip malformed record
                continue
        patterns = [agg.to_dict() for agg in engine.aggregate_patterns()]
        return {
            "available": True,
            "source": "engine_v2_store",
            "lessons": len(records),
            "patterns": patterns,
        }
    except Exception as exc:  # noqa: BLE001 - a status endpoint must never raise
        logger.warning("Learning Engine v2 snapshot failed: %s", exc)
        return {"available": False, "source": "unavailable", "lessons": 0, "patterns": []}


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


# ---------------------------------------------------------------------------
# Diagnostics — one actionable "what needs attention" report
# ---------------------------------------------------------------------------


@router.get("/diagnostics", summary="Aggregated operational diagnostics")
async def diagnostics() -> dict[str, Any]:
    """Aggregate REAL health signals into a single actionable report.

    Answers "apa yang perlu diperhatikan?" in one call, instead of the operator
    having to visit many endpoints. Every check is read-only and fail-safe: a
    source that cannot be read is reported as ``unknown`` (never a fake OK).

    Checks:
      * feed       — market data health (tick/bar freshness) for key symbols.
      * sltp       — dynamic SL manager errors (e.g. ARM-gate 403s).
      * r_tracking — closed trades vs trades with a usable R-multiple.
      * execution  — terminal arm state (the REAL order gate).
      * environment — DEV/LIVE reporting gate (informational only).
    """
    checks: list[dict[str, Any]] = []
    runtime = get_runtime()

    # 1) Market feed health for the configured symbols.
    try:
        from ..config import settings

        symbols = [
            s.strip()
            for s in str(getattr(settings, "market_feed_symbols", "XAUUSD") or "XAUUSD").split(",")
            if s.strip()
        ]
        from ..market.health import compute_market_data_health

        for sym in symbols or ["XAUUSD"]:
            h = compute_market_data_health(sym)
            status = str(h.get("status", "UNKNOWN"))
            checks.append(
                {
                    "area": "feed",
                    "target": sym,
                    "status": status,
                    "ok": status in ("HEALTHY", "STALE"),
                    "severity": "info" if status == "HEALTHY" else "warning",
                    "detail": (
                        f"tick_age={h.get('tick_age_ms')}ms bar_age={h.get('bar_age_ms')}ms"
                    ),
                }
            )
    except Exception as exc:  # noqa: BLE001 - diagnostics must never raise
        checks.append(
            {
                "area": "feed",
                "target": "?",
                "status": "UNKNOWN",
                "ok": False,
                "severity": "warning",
                "detail": f"tidak bisa dibaca: {exc}",
            }
        )

    # 2) Dynamic SL manager errors (ARM-gate 403, etc.).
    try:
        manager = getattr(runtime, "trade_manager", None)
        if manager is not None:
            snap = manager.snapshot()
            counts = snap.get("counts", {})
            errors = int(counts.get("errors", 0) or 0)
            modified = int(counts.get("modified", 0) or 0)
            enabled = bool(snap.get("enabled"))
            if not enabled:
                checks.append(
                    {
                        "area": "sltp",
                        "target": "trade_manager",
                        "status": "DISABLED",
                        "ok": True,
                        "severity": "info",
                        "detail": "manajemen SL dinamis OFF (tidak ada modifikasi dikirim).",
                    }
                )
            elif errors > 0 and modified == 0:
                last = (snap.get("recent") or [{}])[0]
                checks.append(
                    {
                        "area": "sltp",
                        "target": "trade_manager",
                        "status": "BLOCKED",
                        "ok": False,
                        "severity": "warning",
                        "detail": (
                            f"{errors} error, 0 berhasil — kemungkinan terminal belum "
                            f"di-ARM ({last.get('message', '')})."
                        ),
                    }
                )
            else:
                checks.append(
                    {
                        "area": "sltp",
                        "target": "trade_manager",
                        "status": "OK" if errors == 0 else "PARTIAL",
                        "ok": True,
                        "severity": "info" if errors == 0 else "warning",
                        "detail": f"modified={modified} errors={errors}",
                    }
                )
    except Exception as exc:  # noqa: BLE001
        checks.append(
            {
                "area": "sltp",
                "target": "trade_manager",
                "status": "UNKNOWN",
                "ok": False,
                "severity": "warning",
                "detail": str(exc),
            }
        )

    # 3) R tracking coverage.
    try:
        from .v2_endpoints import _closed_trade_r_rows, _total_review_count

        total = _total_review_count()
        with_r = sum(1 for row in _closed_trade_r_rows() if row.get("r_multiple") is not None)
        gap = max(0, total - with_r)
        checks.append(
            {
                "area": "r_tracking",
                "target": "closed_trades",
                "status": "OK" if gap == 0 else "PARTIAL",
                "ok": gap == 0,
                "severity": "info" if gap == 0 else "warning",
                "detail": (
                    f"{with_r}/{total} trade punya R"
                    + (f" — {gap} tidak (dibuka sebelum fitur R aktif)." if gap else ".")
                ),
            }
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(
            {
                "area": "r_tracking",
                "target": "closed_trades",
                "status": "UNKNOWN",
                "ok": False,
                "severity": "warning",
                "detail": str(exc),
            }
        )

    # 4) Execution arm state (the REAL order gate).
    try:
        armed = False
        for mod_name in ("mt5.terminals", "src.mt5.terminals"):
            try:
                import importlib

                terms = importlib.import_module(mod_name)
                armed = bool(terms.execution_permitted())
                break
            except ImportError:
                continue
        checks.append(
            {
                "area": "execution",
                "target": "terminal_arm",
                "status": "ARMED" if armed else "NOT_ARMED",
                "ok": armed,
                "severity": "info" if armed else "warning",
                "detail": (
                    "terminal ter-arm; order & modifikasi SL dapat dikirim."
                    if armed
                    else "terminal belum di-arm; order nyata DIBLOKIR (fail-closed)."
                ),
            }
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(
            {
                "area": "execution",
                "target": "terminal_arm",
                "status": "UNKNOWN",
                "ok": False,
                "severity": "warning",
                "detail": str(exc),
            }
        )

    # Summary: worst severity present.
    severities = {c.get("severity") for c in checks}
    if "critical" in severities:
        overall = "CRITICAL"
    elif "warning" in severities:
        overall = "ATTENTION"
    else:
        overall = "OK"
    return {
        "overall": overall,
        "counts": {
            "total": len(checks),
            "ok": sum(1 for c in checks if c.get("ok")),
            "attention": sum(1 for c in checks if not c.get("ok")),
        },
        "checks": checks,
        "source": "live",
        "status": "OK",
    }
