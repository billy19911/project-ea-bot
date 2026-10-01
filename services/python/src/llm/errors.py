# -*- coding: utf-8 -*-
"""TASK 04 — AI Control error taxonomy (Python side).

Mirrors ``apps/api/src/errorTaxonomy.ts``. Every AI Control failure must carry
a real failing-layer code plus the canonical field set so the UI can name the
cause (``LLM_PROVIDER_503``) instead of a generic "agent error" (MASTER_PLAN
invariants 18/19).

The codes and field names are IDENTICAL to the Node module; the Node API
normalises anything Python emits via ``normalizeIncoming``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Optional

__all__ = [
    "ERROR_CODES",
    "ERROR_LAYER",
    "RETRYABLE",
    "ClassifiedError",
    "classify",
    "classify_llm_exception",
    "is_retryable",
]

# The 13 required error classes (MASTER_PLAN §6 / TASK 04).
ERROR_CODES = (
    "NODE_API_UNAVAILABLE",
    "PYTHON_SERVICE_UNAVAILABLE",
    "PYTHON_ENDPOINT_4XX",
    "PYTHON_ENDPOINT_5XX",
    "AGENT_TIMEOUT",
    "AGENT_EXCEPTION",
    "LLM_PROVIDER_4XX",
    "LLM_PROVIDER_5XX",
    "LLM_PROVIDER_503",
    "LLM_TIMEOUT",
    "MODEL_UNAVAILABLE",
    "AUTH_FAILURE",
    "DATA_GUARD_FAILURE",
)

ERROR_LAYER = {
    "NODE_API_UNAVAILABLE": "node_api",
    "PYTHON_SERVICE_UNAVAILABLE": "python_service",
    "PYTHON_ENDPOINT_4XX": "python_endpoint",
    "PYTHON_ENDPOINT_5XX": "python_endpoint",
    "AGENT_TIMEOUT": "agent",
    "AGENT_EXCEPTION": "agent",
    "LLM_PROVIDER_4XX": "llm_provider",
    "LLM_PROVIDER_5XX": "llm_provider",
    "LLM_PROVIDER_503": "llm_provider",
    "LLM_TIMEOUT": "llm_provider",
    "MODEL_UNAVAILABLE": "llm_provider",
    "AUTH_FAILURE": "auth",
    "DATA_GUARD_FAILURE": "data_guard",
}

# Retry policy (MASTER_PLAN §6). Deterministic client errors are NOT retryable:
# invalid schema / 4xx, auth failure, risk rejection, missing data.
RETRYABLE = {
    "NODE_API_UNAVAILABLE": True,
    "PYTHON_SERVICE_UNAVAILABLE": True,
    "PYTHON_ENDPOINT_4XX": False,
    "PYTHON_ENDPOINT_5XX": True,
    "AGENT_TIMEOUT": True,
    "AGENT_EXCEPTION": True,
    "LLM_PROVIDER_4XX": False,
    "LLM_PROVIDER_5XX": True,
    "LLM_PROVIDER_503": True,
    "LLM_TIMEOUT": True,
    "MODEL_UNAVAILABLE": False,
    "AUTH_FAILURE": False,
    "DATA_GUARD_FAILURE": False,
}


def is_retryable(code: str) -> bool:
    return bool(RETRYABLE.get(code, False))


@dataclass
class ClassifiedError:
    """Canonical classified error. Every field is present (None when unknown)."""

    code: str
    layer: str = ""
    trace_id: Optional[str] = None
    service: Optional[str] = None
    endpoint: Optional[str] = None
    status_code: Optional[int] = None
    agent: Optional[str] = None
    event_id: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    timestamp: str = ""
    message: str = ""
    retryable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify(
    code: str,
    *,
    message: str = "",
    trace_id: Optional[str] = None,
    service: Optional[str] = None,
    endpoint: Optional[str] = None,
    status_code: Optional[int] = None,
    agent: Optional[str] = None,
    event_id: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> dict[str, Any]:
    """Build a fully-populated classified error dict (JSON-serialisable)."""
    if code not in ERROR_CODES:
        code = "AGENT_EXCEPTION"
    return ClassifiedError(
        code=code,
        layer=ERROR_LAYER.get(code, "unknown"),
        trace_id=trace_id,
        service=service,
        endpoint=endpoint,
        status_code=int(status_code) if isinstance(status_code, (int, float)) else None,
        agent=agent,
        event_id=event_id,
        model=model,
        provider=provider,
        timestamp=timestamp or _now(),
        message=message or _default_message(code),
        retryable=is_retryable(code),
    ).to_dict()


def _default_message(code: str) -> str:
    return {
        "LLM_PROVIDER_503": "LLM provider reported 503 Service Unavailable.",
        "LLM_PROVIDER_5XX": "LLM provider returned a server error.",
        "LLM_PROVIDER_4XX": "LLM provider rejected the request (client error).",
        "LLM_TIMEOUT": "LLM provider request timed out.",
        "MODEL_UNAVAILABLE": "No capable/available model for the request.",
        "AGENT_TIMEOUT": "Agent exceeded its time budget.",
        "AGENT_EXCEPTION": "Agent raised an exception while analysing.",
        "AUTH_FAILURE": "Authentication/authorization failed.",
        "DATA_GUARD_FAILURE": "Data guard rejected missing/invalid input.",
    }.get(code, "Unknown error.")


def classify_llm_exception(
    exc: BaseException,
    *,
    agent: Optional[str] = None,
    model: Optional[str] = None,
    provider: str = "9router",
    endpoint: Optional[str] = None,
    trace_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    """Classify an exception raised by an LLM provider call.

    Inspects the OpenAI/httpx exception shape (``status_code``/``response``) and
    the message so a provider 503 becomes ``LLM_PROVIDER_503`` — never a generic
    agent error. Timeouts map to ``LLM_TIMEOUT``.
    """
    status_code = _extract_status_code(exc)
    message = str(exc) or exc.__class__.__name__
    lowered = message.lower()

    is_timeout = (
        isinstance(exc, TimeoutError)
        or "timeout" in exc.__class__.__name__.lower()
        or "timed out" in lowered
    )
    if is_timeout and status_code is None:
        return classify(
            "LLM_TIMEOUT",
            message=message,
            agent=agent,
            model=model,
            provider=provider,
            endpoint=endpoint,
            status_code=504,
            trace_id=trace_id,
            event_id=event_id,
        )

    if status_code == 503:
        code = "LLM_PROVIDER_503"
    elif status_code is not None and 400 <= status_code < 500:
        code = "LLM_PROVIDER_4XX"
    elif status_code is not None and status_code >= 500:
        code = "LLM_PROVIDER_5XX"
    elif "503" in lowered or "service unavailable" in lowered:
        code = "LLM_PROVIDER_503"
        status_code = 503
    elif "timeout" in lowered or "timed out" in lowered:
        code = "LLM_TIMEOUT"
    elif "model" in lowered and ("not found" in lowered or "unavailable" in lowered):
        code = "MODEL_UNAVAILABLE"
    elif "auth" in lowered or "unauthor" in lowered or "api key" in lowered:
        code = "AUTH_FAILURE"
    else:
        code = "LLM_PROVIDER_5XX"

    return classify(
        code,
        message=message,
        agent=agent,
        model=model,
        provider=provider,
        endpoint=endpoint,
        status_code=status_code,
        trace_id=trace_id,
        event_id=event_id,
    )


def _extract_status_code(exc: BaseException) -> Optional[int]:
    """Pull an HTTP status off an OpenAI/httpx-style exception (best effort)."""
    for attr in ("status_code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    if response is not None:
        value = getattr(response, "status_code", None)
        if isinstance(value, int):
            return value
    return None
