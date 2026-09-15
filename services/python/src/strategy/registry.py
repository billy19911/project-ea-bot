# -*- coding: utf-8 -*-
"""Strategy versioning and promotion — EPIC 13.

Registry, version schema, promotion gates, activation, retirement,
and live-parameter protection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class StrategyStatus(Enum):
    """Strategy lifecycle status."""

    DRAFT = "DRAFT"
    TESTING = "TESTING"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


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
    """A versioned strategy with parameters and lifecycle status."""

    name: str
    version: str
    parameters: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    status: StrategyStatus = StrategyStatus.DRAFT

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
        }


@dataclass
class PromotionResult:
    """Result of a promotion gate check."""

    allowed: bool
    reason: str = ""


class PromotionGate:
    """Enforce promotion rules between strategy statuses (13.03)."""

    PROMOTION_RULES = {
        StrategyStatus.DRAFT: [StrategyStatus.TESTING],
        StrategyStatus.TESTING: [StrategyStatus.ACTIVE, StrategyStatus.DRAFT],
        StrategyStatus.ACTIVE: [StrategyStatus.RETIRED],
        StrategyStatus.RETIRED: [],
    }

    def can_promote(
        self,
        from_status: StrategyStatus,
        to_status: StrategyStatus,
        metrics: Optional[dict[str, float]] = None,
        validation_passed: bool = False,
    ) -> PromotionResult:
        """Check if promotion is allowed (13.03)."""
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

        if from_status == StrategyStatus.TESTING and to_status == StrategyStatus.ACTIVE:
            if not validation_passed:
                return PromotionResult(
                    allowed=False,
                    reason="TESTING → ACTIVE requires passed validation.",
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

    def activate(self, name: str, version: str) -> None:
        """Activate a strategy version (13.04)."""
        # Retire old version
        if name in self._active_by_name:
            old_version = self._active_by_name[name]
            old_strategy = self.get(name, old_version)
            if old_strategy:
                old_strategy.status = StrategyStatus.RETIRED
                old_strategy.unfreeze_parameters()

        # Activate new version
        strategy = self.get(name, version)
        if not strategy:
            raise ValueError(f"Strategy {name} v{version} not found")

        strategy.status = StrategyStatus.ACTIVE
        strategy.freeze_parameters()
        self._active_by_name[name] = version
        logger.info(f"Activated strategy {name} v{version}")

    def retire(self, name: str, version: str) -> None:
        """Retire a strategy version (13.05)."""
        strategy = self.get(name, version)
        if not strategy:
            raise ValueError(f"Strategy {name} v{version} not found")

        strategy.status = StrategyStatus.RETIRED
        strategy.unfreeze_parameters()
        if self._active_by_name.get(name) == version:
            del self._active_by_name[name]
        logger.info(f"Retired strategy {name} v{version}")

    def get_active_version(self, name: str) -> Optional[VersionedStrategy]:
        """Get the currently active version of a strategy."""
        if name not in self._active_by_name:
            return None
        version = self._active_by_name[name]
        return self.get(name, version)
