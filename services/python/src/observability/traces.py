# -*- coding: utf-8 -*-
"""Trace collection for observability — EPIC 16.03–16.04.

Collects event and task traces as spans grouped by trace id.

PRD §26/§27: the :class:`TraceCollector` also provides a bounded
``TraceStore``-style history so real ``PipelineResult`` cycles can be recorded
and exposed through the control-plane API (``GET /observability/traces``).
"""

import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Span:
    """A single timed operation within a trace."""

    span_id: str
    name: str
    trace_id: str
    parent_id: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    status: str = "running"
    attributes: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> Optional[float]:
        if self.finished_at is None:
            return None
        return round((self.finished_at - self.started_at) * 1000, 3)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the span to a JSON-friendly dict."""
        return {
            "span_id": self.span_id,
            "name": self.name,
            "trace_id": self.trace_id,
            "parent_id": self.parent_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "attributes": dict(self.attributes),
        }


@dataclass
class Trace:
    """A group of spans sharing one trace id (task or decision cycle)."""

    task_id: str
    spans: List[Span] = field(default_factory=list)

    @property
    def status(self) -> str:
        if any(s.status == "error" for s in self.spans):
            return "error"
        if all(s.status == "ok" for s in self.spans) and self.spans:
            return "ok"
        return "running"

    @property
    def duration_ms(self) -> Optional[float]:
        finished = [s for s in self.spans if s.finished_at is not None]
        if not finished:
            return None
        start = min(s.started_at for s in finished)
        end = max(s.finished_at for s in finished if s.finished_at)
        return round((end - start) * 1000, 3)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the trace and its spans to a JSON-friendly dict."""
        return {
            "trace_id": self.task_id,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "span_count": len(self.spans),
            "spans": [s.to_dict() for s in self.spans],
        }


class TraceCollector:
    """In-memory span/trace collector with a bounded trace history.

    Args:
        max_traces: Maximum number of traces retained (oldest evicted on
            overflow). ``0`` disables bounding (unbounded, legacy behaviour).
    """

    def __init__(self, max_traces: int = 0) -> None:
        self._spans: Dict[str, Span] = {}
        self._traces: "OrderedDict[str, Trace]" = OrderedDict()
        self._max_traces = max(0, int(max_traces))

    def start_span(
        self,
        name: str,
        trace_id: Optional[str] = None,
        parent_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Span:
        tid = trace_id or uuid.uuid4().hex[:12]
        span = Span(
            span_id=uuid.uuid4().hex[:12],
            name=name,
            trace_id=tid,
            parent_id=parent_id,
            attributes=attributes or {},
        )
        self._spans[span.span_id] = span
        trace = self._traces.get(tid)
        if trace is None:
            trace = Trace(task_id=tid)
            self._traces[tid] = trace
            self._evict()
        trace.spans.append(span)
        return span

    def finish_span(self, span_id: str, status: str = "ok") -> bool:
        span = self._spans.get(span_id)
        if span is None:
            return False
        span.finished_at = time.time()
        span.status = status
        return True

    def get_trace(self, trace_id: str) -> Optional[Trace]:
        return self._traces.get(trace_id)

    def get_span(self, span_id: str) -> Optional[Span]:
        return self._spans.get(span_id)

    def list_traces(self) -> List[Trace]:
        return list(self._traces.values())

    def recent_traces(self, limit: int = 50) -> List[Trace]:
        """Return the most recent traces (newest first), bounded by ``limit``."""
        if limit <= 0:
            return []
        return list(self._traces.values())[-limit:][::-1]

    def recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return the most recent traces serialised to dicts (newest first)."""
        return [t.to_dict() for t in self.recent_traces(limit)]

    def record_pipeline_result(
        self,
        result: Dict[str, Any],
        trace_id: Optional[str] = None,
    ) -> Trace:
        """Record a serialised ``PipelineResult`` as a trace.

        Converts each pipeline stage in ``result["trace"]`` into a finished
        span under a single trace. The ``trace_id`` is taken from the argument
        when supplied, else from the result payload, else generated.

        Args:
            result: A :meth:`PipelineResult.to_dict` style mapping.
            trace_id: Optional externally supplied trace id (e.g. from the
                ``X-Trace-Id`` request header).

        Returns:
            The recorded :class:`Trace`.
        """
        payload = result if isinstance(result, dict) else {}
        tid = (
            trace_id or payload.get("trace_id") or payload.get("event_id") or uuid.uuid4().hex[:12]
        )
        tid = str(tid)

        stages = payload.get("trace") or []
        if not stages:
            # Always record at least one span so an empty cycle is observable.
            span = self.start_span("pipeline", trace_id=tid)
            span.finished_at = span.started_at
            span.status = "error" if payload.get("error") else "ok"
        else:
            for stage in stages:
                name = str(stage.get("stage", "stage"))
                status = str(stage.get("status", "")).lower()
                span = self.start_span(
                    name,
                    trace_id=tid,
                    attributes={"detail": stage.get("detail", "")},
                )
                span.finished_at = span.started_at
                span.status = "error" if status in ("error", "blocked") else "ok"

        return self._traces[tid]

    def _evict(self) -> None:
        """Evict oldest traces (and their spans) when over the bound."""
        if not self._max_traces:
            return
        while len(self._traces) > self._max_traces:
            _, old = self._traces.popitem(last=False)
            for span in old.spans:
                self._spans.pop(span.span_id, None)
