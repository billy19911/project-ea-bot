# -*- coding: utf-8 -*-
"""Strategy versioning and promotion — EPIC 13.

Registry, version schema, promotion gates, activation, retirement,
and live-parameter protection.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


class StrategyStatus(Enum):
    """Strategy lifecycle status (PRD_V2 §19).

    The canonical set required by the PRD is: DRAFT, RESEARCH, BACKTESTED,
    WALK_FORWARD, PAPER, DEMO, APPROVED, ACTIVE, RETIRED, REJECTED.

    ``TESTING`` is retained as a backwards-compatibility value for older
    code/tests that referenced the pre-PRD lifecycle. New code should prefer
    RESEARCH/BACKTESTED/WALK_FORWARD.
    """

    DRAFT = "DRAFT"
    RESEARCH = "RESEARCH"
    BACKTESTED = "BACKTESTED"
    WALK_FORWARD = "WALK_FORWARD"
    PAPER = "PAPER"
    DEMO = "DEMO"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"
    REJECTED = "REJECTED"
    # Backwards-compat aliases for the pre-PRD lifecycle.
    TESTING = "TESTING"


class ReadOnlyDict(dict):
    """Dictionary that prevents modifications."""

    def __setitem__(self, key: Any, value: Any) -> None:
        raise RuntimeError("Cannot modify parameters for ACTIVE strategy (read-only).")

    def __delitem__(self, key: Any) -> None:
        raise RuntimeError("Cannot delete parameters for ACTIVE strategy (read-only).")

    def update(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Cannot update parameters for ACTIVE strategy (read-only).")

    def pop(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Cannot pop from parameters for ACTIVE strategy (read-only).")

    def clear(self) -> None:
        raise RuntimeError("Cannot clear parameters for ACTIVE strategy (read-only).")


@dataclass
class VersionedStrategy:
    """A versioned strategy with parameters and lifecycle status (PRD_V2 §19).

    Tracks the full PRD §19 metadata set: a stable ``strategy_id``, the
    ``version``, parameters, the risk policy, compatible market regimes, the
    lifecycle ``status``, a ``metrics_summary``, ``validation_evidence``,
    a human-readable ``rationale``, and the lifecycle timestamps
    (created/approved/activated/retired).
    """

    name: str
    version: str
    parameters: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    status: StrategyStatus = StrategyStatus.DRAFT
    # §19 metadata.
    strategy_id: str = field(default_factory=lambda: f"strat_{uuid.uuid4().hex[:12]}")
    risk_policy: dict[str, Any] = field(default_factory=dict)
    compatible_regimes: list[str] = field(default_factory=list)
    metrics_summary: dict[str, Any] = field(default_factory=dict)
    validation_evidence: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    created_at: str = field(default_factory=_utcnow)
    approved_at: Optional[str] = None
    activated_at: Optional[str] = None
    retired_at: Optional[str] = None

    def set_status(self, status: StrategyStatus) -> None:
        """Transition the lifecycle status and stamp the relevant timestamp.

        APPROVED/ACTIVE/RETIRED transitions record ``approved_at`` /
        ``activated_at`` / ``retired_at`` respectively (PRD_V2 §19).
        """
        self.status = status
        if status is StrategyStatus.APPROVED and self.approved_at is None:
            self.approved_at = _utcnow()
        elif status is StrategyStatus.ACTIVE and self.activated_at is None:
            self.activated_at = _utcnow()
        elif status is StrategyStatus.RETIRED and self.retired_at is None:
            self.retired_at = _utcnow()

    def freeze_parameters(self) -> None:
        """Freeze parameters when activating strategy (13.06)."""
        # Convert regular dict to ReadOnlyDict
        self.parameters = ReadOnlyDict(self.parameters)

    def unfreeze_parameters(self) -> None:
        """Unfreeze parameters (e.g. on retirement)."""
        self.parameters = dict(self.parameters)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "name": self.name,
            "version": self.version,
            "parameters": dict(self.parameters),
            "description": self.description,
            "status": self.status.value,
            "strategy_id": self.strategy_id,
            "risk_policy": dict(self.risk_policy),
            "compatible_regimes": list(self.compatible_regimes),
            "metrics_summary": dict(self.metrics_summary),
            "validation_evidence": dict(self.validation_evidence),
            "rationale": self.rationale,
            "created_at": self.created_at,
            "approved_at": self.approved_at,
            "activated_at": self.activated_at,
            "retired_at": self.retired_at,
        }


@dataclass
class PromotionResult:
    """Result of a promotion gate check."""

    allowed: bool
    reason: str = ""


class PromotionError(RuntimeError):
    """Raised when a strategy activation is denied by the promotion gate."""


class PromotionGate:
    """Enforce promotion rules between strategy statuses (13.03)."""

    PROMOTION_RULES = {
        StrategyStatus.DRAFT: [
            StrategyStatus.TESTING,
            StrategyStatus.RESEARCH,
            StrategyStatus.BACKTESTED,
            StrategyStatus.ACTIVE,
        ],
        StrategyStatus.TESTING: [StrategyStatus.ACTIVE, StrategyStatus.DRAFT],
        StrategyStatus.RESEARCH: [StrategyStatus.BACKTESTED, StrategyStatus.DRAFT],
        StrategyStatus.BACKTESTED: [StrategyStatus.WALK_FORWARD, StrategyStatus.ACTIVE],
        StrategyStatus.WALK_FORWARD: [StrategyStatus.PAPER, StrategyStatus.ACTIVE],
        StrategyStatus.PAPER: [StrategyStatus.DEMO, StrategyStatus.ACTIVE],
        StrategyStatus.DEMO: [StrategyStatus.APPROVED, StrategyStatus.ACTIVE],
        StrategyStatus.APPROVED: [StrategyStatus.ACTIVE, StrategyStatus.REJECTED],
        StrategyStatus.ACTIVE: [StrategyStatus.RETIRED],
        StrategyStatus.RETIRED: [],
        StrategyStatus.REJECTED: [StrategyStatus.DRAFT],
    }

    def can_promote(
        self,
        from_status: StrategyStatus,
        to_status: StrategyStatus,
        metrics: Optional[dict[str, float]] = None,
        validation_passed: bool = False,
    ) -> PromotionResult:
        """Check if promotion is allowed (13.03, evidence-enforced).

        Any transition *into* ACTIVE requires positive evidence: either
        ``validation_passed=True`` or backtest metrics with ``win_rate >= 50``.
        DRAFT → TESTING also requires backtest metrics with a ≥ 50% win rate.
        """
        if to_status not in self.PROMOTION_RULES.get(from_status, []):
            return PromotionResult(
                allowed=False,
                reason=(f"Cannot promote from {from_status.value} to " f"{to_status.value}"),
            )

        if from_status == StrategyStatus.DRAFT and to_status == StrategyStatus.TESTING:
            if not metrics:
                return PromotionResult(
                    allowed=False,
                    reason="DRAFT → TESTING requires backtest metrics.",
                )
            if metrics.get("win_rate", 0) < 50.0:
                return PromotionResult(
                    allowed=False,
                    reason="Win rate must be ≥ 50% to proceed to TESTING.",
                )

        if to_status == StrategyStatus.ACTIVE:
            # Audit P1-5: reaching ACTIVE always requires evidence.
            if from_status == StrategyStatus.TESTING:
                # The legacy TESTING → ACTIVE path strictly requires validation.
                if not validation_passed:
                    return PromotionResult(
                        allowed=False,
                        reason="TESTING → ACTIVE requires passed validation.",
                    )
            else:
                has_metrics = (
                    bool(metrics) and float((metrics or {}).get("win_rate", 0) or 0) >= 50.0
                )
                if not validation_passed and not has_metrics:
                    return PromotionResult(
                        allowed=False,
                        reason=(
                            f"{from_status.value} → ACTIVE requires passed validation or "
                            "backtest metrics with win rate ≥ 50%."
                        ),
                    )

        return PromotionResult(allowed=True)


class StrategyRegistry:
    """Registry for strategy versioning and promotion (13.01)."""

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._strategies: dict[tuple[str, str], VersionedStrategy] = {}
        self._active_by_name: dict[str, str] = {}

    def register(
        self,
        name: str,
        version: str,
        parameters: dict[str, Any],
        description: str = "",
    ) -> VersionedStrategy:
        """Register a new strategy version (13.01)."""
        key = (name, version)
        if key in self._strategies:
            raise ValueError(f"Strategy {name} version {version} already exists")

        strategy = VersionedStrategy(
            name=name,
            version=version,
            parameters=parameters,
            description=description,
            status=StrategyStatus.DRAFT,
        )
        self._strategies[key] = strategy
        logger.info(f"Registered strategy {name} v{version}")
        return strategy

    def get(self, name: str, version: str) -> Optional[VersionedStrategy]:
        """Retrieve a strategy by name and version."""
        return self._strategies.get((name, version))

    def list_all(self) -> list[VersionedStrategy]:
        """List all registered strategies."""
        return list(self._strategies.values())

    def list_by_name(self, name: str) -> list[VersionedStrategy]:
        """List all versions of a strategy by name."""
        return [s for s in self._strategies.values() if s.name == name]

    def list_by_status(self, status: StrategyStatus) -> list[VersionedStrategy]:
        """List all strategies with given status."""
        return [s for s in self._strategies.values() if s.status == status]

    def activate(
        self,
        name: str,
        version: str,
        *,
        enforce_evidence: bool = False,
    ) -> None:
        """Activate a strategy version (13.04).

        Args:
            name: Strategy name.
            version: Version to activate.
            enforce_evidence: When True (audit P1-5), the promotion gate must
                approve. Evidence is read from the strategy's
                ``metrics_summary``/``validation_evidence``. Denied promotions
                raise :class:`PromotionError`. Defaults to False so internal
                bootstrap paths and existing callers are unaffected.

        Raises:
            ValueError: strategy version not found.
            PromotionError: promotion denied by the gate.
        """
        # Audit P1-5: enforce the promotion gate when requested.
        if enforce_evidence:
            target = self.get(name, version)
            if target is None:
                raise ValueError(f"Strategy {name} v{version} not found")
            metrics = target.metrics_summary or None
            validation_passed = bool(target.validation_evidence.get("passed", False))
            decision = PromotionGate().can_promote(
                target.status,
                StrategyStatus.ACTIVE,
                metrics=metrics,
                validation_passed=validation_passed,
            )
            if not decision.allowed:
                raise PromotionError(decision.reason or "Promotion denied by gate")

        # Retire old version
        if name in self._active_by_name:
            old_version = self._active_by_name[name]
            old_strategy = self.get(name, old_version)
            if old_strategy:
                old_strategy.set_status(StrategyStatus.RETIRED)
                old_strategy.unfreeze_parameters()

        # Activate new version
        strategy = self.get(name, version)
        if not strategy:
            raise ValueError(f"Strategy {name} v{version} not found")

        strategy.set_status(StrategyStatus.ACTIVE)
        strategy.freeze_parameters()
        self._active_by_name[name] = version
        logger.info(f"Activated strategy {name} v{version}")

    def retire(self, name: str, version: str) -> None:
        """Retire a strategy version (13.05)."""
        strategy = self.get(name, version)
        if not strategy:
            raise ValueError(f"Strategy {name} v{version} not found")

        strategy.set_status(StrategyStatus.RETIRED)
        strategy.unfreeze_parameters()
        if self._active_by_name.get(name) == version:
            del self._active_by_name[name]
        logger.info(f"Retired strategy {name} v{version}")

    def record_status(
        self,
        name: str,
        version: str,
        status: StrategyStatus,
    ) -> VersionedStrategy:
        """Record a lifecycle status transition for a strategy version (§19).

        Raises:
            ValueError: when the strategy version is not registered.
        """
        strategy = self.get(name, version)
        if not strategy:
            raise ValueError(f"Strategy {name} v{version} not found")
        strategy.set_status(status)
        logger.info(f"Strategy {name} v{version} status → {status.value}")
        return strategy

    def get_active_version(self, name: str) -> Optional[VersionedStrategy]:
        """Get the currently active version of a strategy."""
        if name not in self._active_by_name:
            return None
        version = self._active_by_name[name]
        return self.get(name, version)
