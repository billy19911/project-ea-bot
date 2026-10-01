# -*- coding: utf-8 -*-
"""Canonical signal model (TASK 06 — one signal → many accounts).

The desired trading model is::

    1 Supervisor → 1 Committee → 1 Canonical Signal → N MT5 Accounts

A :class:`CanonicalSignal` is created ONCE per market opportunity and is
IMMUTABLE. Every eligible account receives the *same* ``signal_id`` — the
per-account fan-out may only change account-specific values (volume, digits,
point, min/max/step, price normalization, margin, risk budget), never the
signal itself.

This module is deliberately stdlib-only and side-effect free: it defines the
immutable record, its content hash, and the fan-out status vocabularies. The
mutable per-account dispatch state lives in :mod:`execution.fanout`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

__all__ = [
    "CanonicalSignal",
    "SignalStatus",
    "SIGNAL_STATUSES",
    "AccountExecutionStatus",
    "ACCOUNT_STATUSES",
    "TERMINAL_STATUSES",
    "make_canonical_signal",
    "signal_id_for",
]


class SignalStatus:
    """Aggregate status of a canonical signal across all accounts (TASK 06)."""

    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    PARTIALLY_EXECUTED = "PARTIALLY_EXECUTED"
    EXECUTED_ALL = "EXECUTED_ALL"
    REJECTED_ALL = "REJECTED_ALL"
    EXPIRED = "EXPIRED"


SIGNAL_STATUSES = (
    SignalStatus.CREATED,
    SignalStatus.VALIDATED,
    SignalStatus.PARTIALLY_EXECUTED,
    SignalStatus.EXECUTED_ALL,
    SignalStatus.REJECTED_ALL,
    SignalStatus.EXPIRED,
)


class AccountExecutionStatus:
    """Per-account fan-out status (TASK 06)."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    FAILED = "FAILED"
    RECONCILED = "RECONCILED"
    CLOSED = "CLOSED"


ACCOUNT_STATUSES = (
    AccountExecutionStatus.PENDING,
    AccountExecutionStatus.APPROVED,
    AccountExecutionStatus.REJECTED,
    AccountExecutionStatus.SUBMITTING,
    AccountExecutionStatus.SUBMITTED,
    AccountExecutionStatus.FILLED,
    AccountExecutionStatus.FAILED,
    AccountExecutionStatus.RECONCILED,
    AccountExecutionStatus.CLOSED,
)

#: Per-account statuses that represent a terminal outcome (no further fan-out).
TERMINAL_STATUSES = frozenset(
    {
        AccountExecutionStatus.REJECTED,
        AccountExecutionStatus.FAILED,
        AccountExecutionStatus.FILLED,
        AccountExecutionStatus.RECONCILED,
        AccountExecutionStatus.CLOSED,
    }
)

#: Per-account statuses that count as "executed" for aggregate status rollup.
_EXECUTED_ACCOUNT_STATUSES = frozenset(
    {
        AccountExecutionStatus.FILLED,
        AccountExecutionStatus.SUBMITTED,
        AccountExecutionStatus.RECONCILED,
        AccountExecutionStatus.CLOSED,
    }
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical_json(payload: dict[str, Any]) -> str:
    """Deterministic JSON for hashing (sorted keys, stable separators)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def signal_id_for(
    *,
    opportunity_id: str,
    symbol: str,
    direction: str,
    strategy_version: str,
    created_at: str,
    evidence_hash: str,
) -> str:
    """Deterministically derive a signal id from its immutable identity fields.

    The same (opportunity, direction, strategy, evidence) always maps to the
    same id, so a duplicate event cannot mint a second signal id.
    """
    seed = _canonical_json(
        {
            "opportunity_id": str(opportunity_id or ""),
            "symbol": str(symbol or "").upper(),
            "direction": str(direction or "").upper(),
            "strategy_version": str(strategy_version or ""),
            "created_at": str(created_at or ""),
            "evidence_hash": str(evidence_hash or ""),
        }
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"sig_{digest}"


@dataclass(frozen=True)
class CanonicalSignal:
    """An immutable, account-agnostic trade signal (TASK 06).

    Frozen: once created it can never be mutated. Fan-out copies account-specific
    context *outside* this object — the signal and its ``signal_id`` are shared
    verbatim by every account.

    Attributes:
        signal_id: Stable id shared by every account.
        opportunity_id: The market opportunity that produced this signal.
        symbol: Instrument (broker-agnostic base symbol).
        direction: ``BUY`` / ``SELL`` (upper-case).
        entry_reference: Reference entry price the decision was made at.
        initial_SL: Original stop-loss price (defines initial risk).
        initial_TP: Original take-profit price.
        planned_RR: Planned reward:risk ratio at signal time.
        risk_policy: Deterministic risk policy snapshot (dict).
        strategy_version: Strategy version tag.
        created_at: ISO-8601 UTC creation timestamp.
        evidence_hash: Hash of the evidence bundle backing the decision.
    """

    signal_id: str
    opportunity_id: str
    symbol: str
    direction: str
    entry_reference: float
    initial_SL: float
    initial_TP: float
    planned_RR: float
    risk_policy: dict[str, Any]
    strategy_version: str
    created_at: str
    evidence_hash: str

    def risk_distance(self) -> float:
        """Absolute entry↔SL distance (initial risk, price units)."""
        try:
            return abs(float(self.entry_reference) - float(self.initial_SL))
        except (TypeError, ValueError):
            return 0.0

    def tp_distance(self) -> float:
        """Absolute entry↔TP distance (price units)."""
        try:
            return abs(float(self.initial_TP) - float(self.entry_reference))
        except (TypeError, ValueError):
            return 0.0

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict view (stable key order, JSON-safe)."""
        return {
            "signal_id": self.signal_id,
            "opportunity_id": self.opportunity_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_reference": self.entry_reference,
            "initial_SL": self.initial_SL,
            "initial_TP": self.initial_TP,
            "planned_RR": self.planned_RR,
            "risk_policy": dict(self.risk_policy),
            "strategy_version": self.strategy_version,
            "created_at": self.created_at,
            "evidence_hash": self.evidence_hash,
        }


def make_canonical_signal(
    *,
    opportunity_id: str,
    symbol: str,
    direction: str,
    entry_reference: float,
    initial_SL: float,
    initial_TP: float,
    planned_RR: float,
    risk_policy: Optional[dict[str, Any]] = None,
    strategy_version: str = "",
    created_at: Optional[str] = None,
    evidence_hash: str = "",
    signal_id: Optional[str] = None,
) -> CanonicalSignal:
    """Build an immutable canonical signal.

    When ``signal_id`` is omitted it is derived deterministically from the
    identity fields (so the same event cannot produce two ids). ``evidence_hash``
    is derived from the risk policy + levels when not supplied.
    """
    created = str(created_at or _now_iso())
    symbol_u = str(symbol or "").upper()
    direction_u = str(direction or "").upper()
    policy = dict(risk_policy or {})

    if not evidence_hash:
        evidence_seed = _canonical_json(
            {
                "symbol": symbol_u,
                "direction": direction_u,
                "entry": entry_reference,
                "sl": initial_SL,
                "tp": initial_TP,
                "rr": planned_RR,
                "risk_policy": policy,
            }
        )
        evidence_hash = hashlib.sha256(evidence_seed.encode("utf-8")).hexdigest()[:16]

    if not signal_id:
        signal_id = signal_id_for(
            opportunity_id=opportunity_id,
            symbol=symbol_u,
            direction=direction_u,
            strategy_version=strategy_version,
            created_at=created,
            evidence_hash=evidence_hash,
        )

    return CanonicalSignal(
        signal_id=str(signal_id),
        opportunity_id=str(opportunity_id or ""),
        symbol=symbol_u,
        direction=direction_u,
        entry_reference=float(entry_reference or 0.0),
        initial_SL=float(initial_SL or 0.0),
        initial_TP=float(initial_TP or 0.0),
        planned_RR=float(planned_RR or 0.0),
        risk_policy=policy,
        strategy_version=str(strategy_version or ""),
        created_at=created,
        evidence_hash=str(evidence_hash),
    )
