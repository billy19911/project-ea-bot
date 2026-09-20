# -*- coding: utf-8 -*-
"""Environment Separation — PRD_V2 §51.

Prevents **accidental live execution from development**. Every execution log
records the broker-endpoint identity, and a deterministic guard rejects live
execution unless the environment is LIVE *and* all live preconditions hold.

Environments (PRD §51)::

    DEV, PAPER, DEMO, LIVE

Execution-log identity (PRD §51)::

    environment, broker, server, account, login, terminal_id, strategy_version

Protection (PRD §51)::

    environment != LIVE and a live execution is attempted  → REJECT
    environment == LIVE must have:
        terminal armed + risk gate healthy + reconciliation healthy
        + production strategy
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

__all__ = [
    "Environment",
    "ExecutionIdentity",
    "LivePreconditions",
    "EnvironmentGuard",
    "EnvironmentViolation",
]


class Environment(str, Enum):
    """Trading environments (PRD §51)."""

    DEV = "DEV"
    PAPER = "PAPER"
    DEMO = "DEMO"
    LIVE = "LIVE"


class EnvironmentViolation(RuntimeError):
    """Raised when a live execution is attempted in a non-LIVE environment."""


@dataclass(frozen=True)
class ExecutionIdentity:
    """Broker-endpoint identity stamped on every execution log (PRD §51)."""

    environment: str
    broker: str
    server: str
    account: str
    login: str
    terminal_id: str
    strategy_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "environment": self.environment,
            "broker": self.broker,
            "server": self.server,
            "account": self.account,
            "login": self.login,
            "terminal_id": self.terminal_id,
            "strategy_version": self.strategy_version,
        }


@dataclass
class LivePreconditions:
    """Preconditions that must all hold before live execution (PRD §51)."""

    terminal_armed: bool = False
    risk_gate_healthy: bool = False
    reconciliation_healthy: bool = False
    production_strategy: bool = False

    def all_met(self) -> bool:
        return (
            self.terminal_armed
            and self.risk_gate_healthy
            and self.reconciliation_healthy
            and self.production_strategy
        )

    def missing(self) -> list[str]:
        missing = []
        if not self.terminal_armed:
            missing.append("terminal_armed")
        if not self.risk_gate_healthy:
            missing.append("risk_gate_healthy")
        if not self.reconciliation_healthy:
            missing.append("reconciliation_healthy")
        if not self.production_strategy:
            missing.append("production_strategy")
        return missing


@dataclass
class EnvironmentGuard:
    """Guards live execution against environment mistakes (PRD §51).

    Args:
        environment: The current environment.
        identity: Optional execution identity to stamp on logs.
        preconditions: Live preconditions (only consulted when environment=LIVE).
    """

    environment: str = Environment.DEV.value
    identity: Optional[ExecutionIdentity] = None
    preconditions: LivePreconditions = field(default_factory=LivePreconditions)

    def is_live(self) -> bool:
        return self.environment == Environment.LIVE.value

    def can_execute_live(self) -> tuple[bool, str]:
        """Return ``(allowed, reason)`` for performing a *live* execution.

        Non-LIVE environments are always rejected. LIVE requires all
        preconditions to hold.
        """
        if not self.is_live():
            return (
                False,
                f"REJECT: live execution attempted in environment={self.environment}",
            )
        if not self.preconditions.all_met():
            return (
                False,
                "REJECT: LIVE preconditions unmet: " + ", ".join(self.preconditions.missing()),
            )
        return True, "live execution permitted"

    def check_live(self) -> None:
        """Raise :class:`EnvironmentViolation` when live execution is not allowed."""
        allowed, reason = self.can_execute_live()
        if not allowed:
            raise EnvironmentViolation(reason)

    def stamp(self, strategy_version: str = "") -> ExecutionIdentity:
        """Return the execution identity to log for the current environment."""
        if self.identity is None:
            return ExecutionIdentity(
                environment=self.environment,
                broker="",
                server="",
                account="",
                login="",
                terminal_id="",
                strategy_version=strategy_version,
            )
        return self.identity
