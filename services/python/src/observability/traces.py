# -*- coding: utf-8 -*-
"""Trace collection for observability — EPIC 16.03–16.04.

Collects event and task traces as spans grouped by trace id.
"""

import time
import uuid
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


class TraceCollector:
    """In-memory span/trace collector."""

    def __init__(self) -> None:
        self._spans: Dict[str, Span] = {}
        self._traces: Dict[str, Trace] = {}

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
        self._traces.setdefault(tid, Trace(task_id=tid)).spans.append(span)
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
