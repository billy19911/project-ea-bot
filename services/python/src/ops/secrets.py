# -*- coding: utf-8 -*-
"""Phase 7 ops helpers — secret masking, mutation audit, UNKNOWN semantics.

Small, dependency-light utilities shared by the /ops read models. No trading
authority whatsoever.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

__all__ = [
    "mask_secrets",
    "SENSITIVE_KEYS",
    "UNKNOWN",
    "unknown_if_none",
    "MutationAudit",
    "audit_mutation",
]

# Values are replaced with this sentinel; keys are matched case-insensitively.
SENSITIVE_KEYS = (
    "api_key",
    "apikey",
    "api_secret",
    "secret",
    "token",
    "bot_token",
    "password",
    "passwd",
    "authorization",
    "auth",
    "credential",
    "private_key",
    "access_key",
    "session_id",
    "cookie",
)
# Value patterns that look like secrets regardless of key (§27, CASE 11).
SENSITIVE_VALUE_PREFIXES = ("sk-", "sk_live", "sk-live", "Bearer ", "xoxb-", "ghp_")
_REDACTED = "***REDACTED***"

# Explicit UNKNOWN sentinel for honest UI semantics (§28).
UNKNOWN = "UNKNOWN"


def mask_secrets(payload: Any) -> Any:
    """Recursively mask sensitive keys AND secret-looking values (never raises)."""
    try:
        if isinstance(payload, dict):
            out: dict[str, Any] = {}
            for k, v in payload.items():
                if isinstance(k, str) and any(s in k.lower() for s in SENSITIVE_KEYS):
                    out[k] = _REDACTED
                else:
                    out[k] = mask_secrets(v)
            return out
        if isinstance(payload, (list, tuple)):
            return [mask_secrets(v) for v in payload]
        if isinstance(payload, str) and any(
            payload.startswith(p) or (len(payload) > 12 and p.strip("- ") in payload)
            for p in SENSITIVE_VALUE_PREFIXES
        ):
            return _REDACTED
        return payload
    except Exception:  # noqa: BLE001 - masking must never break a response
        return payload


def unknown_if_none(value: Any) -> Any:
    """Return ``UNKNOWN`` for ``None`` — never fabricate 0/False/HEALTHY (§28)."""
    return UNKNOWN if value is None else value


@dataclass
class MutationRecord:
    """One audited control-plane mutation (§26)."""

    action: str
    identity: str
    resource: str
    timestamp: float = field(default_factory=time.time)
    before: Any = None
    requested: Any = None
    result: str = "PENDING"
    error: str = ""
    record_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "action": self.action,
            "identity": self.identity,
            "resource": self.resource,
            "timestamp": self.timestamp,
            "before": mask_secrets(self.before),
            "requested": mask_secrets(self.requested),
            "result": self.result,
            "error": self.error,
        }


class MutationAudit:
    """Bounded, thread-safe audit log for control-plane mutations."""

    def __init__(self, limit: int = 500) -> None:
        self._lock = threading.RLock()
        self._records: list[MutationRecord] = []
        self._limit = max(16, int(limit))

    def record(
        self,
        *,
        action: str,
        identity: str,
        resource: str,
        before: Any = None,
        requested: Any = None,
        result: str = "OK",
        error: str = "",
    ) -> MutationRecord:
        rec = MutationRecord(
            action=action,
            identity=identity or "anonymous",
            resource=resource,
            before=before,
            requested=requested,
            result=result,
            error=error,
        )
        with self._lock:
            self._records.append(rec)
            if len(self._records) > self._limit:
                self._records = self._records[-self._limit :]
        return rec

    def all(self) -> list[MutationRecord]:
        with self._lock:
            return list(self._records)

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return [r.to_dict() for r in self._records[-max(1, int(limit)) :]]

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


_AUDIT: Optional[MutationAudit] = None
_AUDIT_LOCK = threading.Lock()


def get_mutation_audit() -> MutationAudit:
    global _AUDIT
    with _AUDIT_LOCK:
        if _AUDIT is None:
            _AUDIT = MutationAudit()
        return _AUDIT


def audit_mutation(**kw: Any) -> MutationRecord:
    """Convenience wrapper recording to the process-wide audit log."""
    return get_mutation_audit().record(**kw)
