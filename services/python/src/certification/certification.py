# -*- coding: utf-8 -*-
"""Phase 9 certification — immutable record, gate, expiry, invalidation.

* ``LiveReadinessCertification`` (§2): immutable evidence record for ONE
  certification run. Status PASS / PASS_WITH_WARNINGS / FAIL / EXPIRED.
* ``CertificationGate`` (§31): deterministic aggregator — PASS iff every
  MANDATORY check passes; WARNING-only failures → PASS_WITH_WARNINGS; any
  mandatory failure → FAIL. No fused scores.
* ``certification_fingerprint`` (§30): material-input hash; any change in
  code/strategy/config/broker/account/symbols/model-policy → fingerprint
  mismatch → INVALIDATED (stale certification is never current, §32).
* NOTHING here can enable live trading (no arm path; all live guards from
  Phase 1/readiness remain the only activation surfaces).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

__all__ = [
    "SEVERITY_MANDATORY",
    "SEVERITY_WARNING",
    "SEVERITY_INFORMATIONAL",
    "ReadinessCheck",
    "LiveReadinessCertification",
    "CertificationGate",
    "certification_fingerprint",
]

SEVERITY_MANDATORY = "MANDATORY"
SEVERITY_WARNING = "WARNING"
SEVERITY_INFORMATIONAL = "INFORMATIONAL"

_VALID_STATUSES = ("NOT_STARTED", "RUNNING", "PASS", "PASS_WITH_WARNINGS", "FAIL", "EXPIRED")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ReadinessCheck:
    """One readiness check result (§3)."""

    check_id: str
    name: str
    category: str
    status: str  # PASS | FAIL | WARNING | UNKNOWN
    severity: str = SEVERITY_MANDATORY
    value: Any = None
    expected: Any = None
    source: str = ""
    timestamp: str = field(default_factory=_now_iso)
    evidence_ref: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        if self.status not in ("PASS", "FAIL", "WARNING", "UNKNOWN"):
            raise ValueError(f"invalid check status {self.status!r}")
        if self.severity not in (SEVERITY_MANDATORY, SEVERITY_WARNING, SEVERITY_INFORMATIONAL):
            raise ValueError(f"invalid severity {self.severity!r}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def certification_fingerprint(identity: dict[str, Any]) -> str:
    """Stable hash of material certification inputs (§30, §32)."""
    canonical = json.dumps(identity, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class LiveReadinessCertification:
    """Immutable certification evidence record (§2)."""

    certification_id: str
    created_at: str = field(default_factory=_now_iso)
    completed_at: str = ""
    system_version: str = ""
    code_version: str = ""
    strategy_version: str = ""
    config_version: str = ""
    broker: str = ""
    account: str = ""
    account_mode: str = ""
    symbols: list[str] = field(default_factory=list)
    environment: str = ""
    run_id: str = ""
    status: str = "NOT_STARTED"
    checks: list[ReadinessCheck] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    expires_at: str = ""
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if self.status not in _VALID_STATUSES:
            raise ValueError(f"invalid certification status {self.status!r}")

    def is_expired(self, now_iso: Optional[str] = None) -> bool:
        """True when expires_at passed (a stale certification is never current)."""
        if not self.expires_at:
            return False
        try:
            now_s = _now_iso() if now_iso is None else now_iso
            exp = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00")).timestamp()
            now = datetime.fromisoformat(str(now_s).replace("Z", "+00:00")).timestamp()
            return now > exp
        except (ValueError, TypeError):
            return True  # unparseable expiry → treat as expired (fail-closed)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # Secrets must never appear in a certification report (§27, CASE 11).
        from ops.secrets import mask_secrets

        return mask_secrets(data)


class CertificationGate:
    """Deterministic gate over a check list (§31). Never fuses a magic score."""

    def evaluate(
        self,
        checks: list[ReadinessCheck],
        *,
        certification_id: str = "",
        identity: Optional[dict[str, Any]] = None,
    ) -> LiveReadinessCertification:
        blockers = [
            c.check_id for c in checks if c.severity == SEVERITY_MANDATORY and c.status != "PASS"
        ]
        warnings = [
            c.check_id
            for c in checks
            if (c.severity == SEVERITY_WARNING and c.status != "PASS") or c.status == "WARNING"
        ]
        if blockers:
            status = "FAIL"
        elif warnings:
            status = "PASS_WITH_WARNINGS"
        else:
            status = "PASS"
        ident = dict(identity or {})
        return LiveReadinessCertification(
            certification_id=certification_id or f"cert-{_now_iso()}",
            completed_at=_now_iso(),
            status=status,
            checks=list(checks),
            blockers=blockers,
            warnings=warnings,
            fingerprint=certification_fingerprint(ident) if ident else "",
        )

    @staticmethod
    def validate_still_current(
        cert: LiveReadinessCertification, current_identity: dict[str, Any]
    ) -> tuple[bool, str]:
        """Check a stored certification against CURRENT material inputs.

        Returns (current, reason). Any fingerprint mismatch or expiry →
        (False, reason) — the stale certification must not be treated as
        current (§32, CASE 1/2/13).
        """
        if cert.is_expired():
            return False, "certification expired"
        if cert.fingerprint and current_identity:
            if certification_fingerprint(current_identity) != cert.fingerprint:
                return False, "material inputs changed (fingerprint mismatch)"
        return True, "current"
