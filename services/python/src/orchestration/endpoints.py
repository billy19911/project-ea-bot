# -*- coding: utf-8 -*-
"""FastAPI router for orchestration — pipeline runs, scheduler status, traces.

Exposes:

* ``POST /pipeline/run`` — run one autonomous pipeline cycle with a supplied
  event/context payload; returns the :class:`PipelineResult` as JSON. Accepts
  an optional ``X-Trace-Id`` request header (PRD §26/§27); the trace id is
  echoed in the response and recorded in the trace store.
* ``GET /scheduler/status`` — scheduler statistics plus running state.
* ``GET /observability/traces`` — recent real pipeline traces (bounded).
* ``GET /reconciliation/status`` — last reconciliation report + bounded history
  count (PRD_V2 §14). Real data only.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field

from .runtime import get_runtime

router = APIRouter(tags=["orchestration"])


class PipelineRunRequest(BaseModel):
    """Payload for a single pipeline cycle.

    Two shapes are accepted (backward compatible):

    * canonical — ``{"event": {...}, "context": {...}}``;
    * flat — ``{"event_type": ..., "symbol": ...}`` sent straight by the
      dashboard button; any flat keys become the event payload so the cycle
      runs against the intended symbol/event instead of an ``UNKNOWN`` event.
    """

    event: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    model_config = {"extra": "allow"}


@router.post("/pipeline/run", summary="Run one autonomous pipeline cycle")
async def run_pipeline(
    payload: PipelineRunRequest,
    x_trace_id: Optional[str] = Header(default=None, alias="X-Trace-Id"),
) -> dict[str, Any]:
    """Run the pipeline once and return the result.

    If an ``X-Trace-Id`` header is present it is used as the trace id and
    echoed in the response; otherwise a new trace id is generated.
    """
    trace_id = (x_trace_id or "").strip() or uuid.uuid4().hex[:12]
    event = dict(payload.event) if payload.event else {}
    if not event:
        # Flat payload (dashboard button): promote the extra top-level keys to
        # the event payload so symbol/timeframe/event_type are honoured.
        extra = dict(getattr(payload, "model_extra", None) or {})
        if extra:
            event = extra
    runtime = get_runtime()
    result = runtime.run_cycle(event, payload.context, trace_id=trace_id)
    result["trace_id"] = trace_id
    return result


@router.get("/scheduler/status", summary="Get scheduler status and statistics")
async def scheduler_status() -> dict[str, Any]:
    """Return scheduler statistics plus its running state."""
    runtime = get_runtime()
    stats = runtime.scheduler.stats()
    return {
        "running": stats.get("running", False),
        "stats": stats,
        "queue_size": stats.get("queue_size", 0),
    }


@router.get("/observability/traces", summary="Get recent pipeline traces")
async def observability_traces(
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    """Return recent real pipeline traces (bounded, newest first)."""
    runtime = get_runtime()
    traces = runtime.recent_traces(limit=limit)
    return {"traces": traces, "count": len(traces)}


@router.get("/reconciliation/status", summary="Get reconciliation status (PRD §14)")
async def reconciliation_status() -> dict[str, Any]:
    """Return the last reconciliation report and bounded history count.

    Real data only (PRD_V2 §14/§25): ``last_report`` is the serialised
    :class:`ReconciliationReport` from the most recent run, or ``None`` when no
    reconciliation has happened yet.
    """
    runtime = get_runtime()
    last = runtime.last_reconciliation()
    history = runtime.reconciliation_history()
    return {
        "last_report": last.to_dict() if last is not None else None,
        "history_count": len(history),
        "source": "live",
    }
