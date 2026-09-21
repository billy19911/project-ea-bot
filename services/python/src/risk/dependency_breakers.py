# -*- coding: utf-8 -*-
"""Per-dependency circuit breakers — PRD_V2 §24 Circuit Breakers.

A dedicated :class:`~risk.circuit_breaker.CircuitBreaker` is maintained for each
external dependency the system relies on:

* ``LLM``          — the 9Router / LLM gateway,
* ``MARKET_DATA``  — market data feeds,
* ``MT5``          — the MT5 terminal connection,
* ``DB``           — the database,
* ``QUEUE``        — the internal event queue,
* ``EXECUTION``    — order execution (execution-critical).

Failures for one dependency never affect another. The most important safety
guarantee is that when the **EXECUTION** breaker is open, new trading orders
must be blocked — exposed via :meth:`DependencyBreakers.check_can_execute`.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Callable, Optional

from .circuit_breaker import BreakerState, BreakerTripReason, CircuitBreaker
from .kill_switch import KillSwitch

logger = logging.getLogger(__name__)

__all__ = ["Dependency", "DependencyBreakers", "ExecutionGuard"]


class Dependency(str, Enum):
    """External dependencies tracked by the breaker registry (§24)."""

    LLM = "llm"
    MARKET_DATA = "market_data"
    MT5 = "mt5"
    DB = "db"
    QUEUE = "queue"
    EXECUTION = "execution"


# §24: "When an execution-critical circuit is open, new trading orders must be
# blocked." The EXECUTION dependency is the execution-critical one.
EXECUTION_CRITICAL: tuple[Dependency, ...] = (Dependency.EXECUTION,)


class DependencyBreakers:
    """Registry of per-dependency circuit breakers (§24).

    Args:
        failure_threshold: Consecutive failures before a breaker opens.
        reset_window_seconds: Cooldown before an OPEN breaker allows a
            HALF_OPEN trial.
        time_fn: Injectable monotonic clock (seconds) for deterministic tests.
        kill_switch: Optional kill switch propagated to every breaker so a trip
            can auto-halt trading.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        reset_window_seconds: float = 60.0,
        time_fn: Optional[Callable[[], float]] = None,
        kill_switch: Any = None,
    ) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
        for dep in Dependency:
            kwargs: dict[str, Any] = {
                "failure_threshold": failure_threshold,
                "reset_window_seconds": reset_window_seconds,
            }
            if time_fn is not None:
                kwargs["time_fn"] = time_fn
            if kill_switch is not None:
                kwargs["kill_switch"] = kill_switch
            self._breakers[dep.value] = CircuitBreaker(**kwargs)

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------
    def _breaker(self, name: str) -> CircuitBreaker:
        try:
            return self._breakers[name]
        except KeyError as exc:
            raise KeyError(f"Unknown dependency: {name}") from exc

    def record_success(self, name: str) -> BreakerState:
        """Record a successful call to ``name`` (resets its failure counter)."""
        return self._breaker(name).record_success()

    def record_failure(
        self,
        name: str,
        reason: BreakerTripReason = BreakerTripReason.EXECUTION_ERROR,
        detail: str = "",
    ) -> BreakerState:
        """Record a failed call to ``name`` (may trip its breaker)."""
        return self._breaker(name).record_failure(reason, detail)

    def is_open(self, name: str) -> bool:
        """Return True when ``name``'s breaker is OPEN (applying cooldown).

        A breaker whose cooldown has elapsed transitions to HALF_OPEN and
        reports ``False`` (a trial call is permitted).
        """
        return not self._breaker(name).check_allow()

    def state(self, name: str) -> BreakerState:
        """Return the raw breaker state for ``name`` (without cooldown probe)."""
        return self._breaker(name).state

    def execution_critical_open(self) -> bool:
        """True when any execution-critical breaker is OPEN (§24)."""
        return any(self.is_open(dep.value) for dep in EXECUTION_CRITICAL)

    def check_can_execute(self) -> tuple[bool, str]:
        """Return ``(allowed, reason)`` for placing a NEW order (§24).

        When an execution-critical breaker is open, new orders must be blocked.
        """
        for dep in EXECUTION_CRITICAL:
            if self.is_open(dep.value):
                return False, f"execution blocked — {dep.value} circuit breaker is OPEN"
        return True, ""

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Serialise every breaker for the control plane."""
        return {name: breaker.to_dict() for name, breaker in self._breakers.items()}


class ExecutionGuard:
    """Single execution gate combining dependency breakers + the kill switch.

    Audit P1-2: the per-dependency circuit breakers (§24) and the kill switch
    existed but were never wired into the trade path. This adapter exposes the
    ``check_can_execute() -> (bool, reason)`` contract the
    :class:`~orchestration.pipeline.TradingPipeline` already understands, so an
    open EXECUTION breaker **or** an engaged kill switch BLOCKS new orders.

    It also records execution outcomes so the breaker can actually trip:

    * :meth:`record_execution_result` — call after every execution attempt; a
      failure counts toward the EXECUTION breaker, a success resets it.

    Fail-closed: when either authority is blocked the guard refuses execution.
    """

    def __init__(
        self,
        breakers: Optional[DependencyBreakers] = None,
        kill_switch: Optional[KillSwitch] = None,
    ) -> None:
        self.kill_switch = kill_switch if kill_switch is not None else KillSwitch()
        self.breakers = (
            breakers if breakers is not None else DependencyBreakers(kill_switch=self.kill_switch)
        )

    # ------------------------------------------------------------------
    # Gate
    # ------------------------------------------------------------------
    def check_can_execute(self) -> tuple[bool, str]:
        """Return ``(allowed, reason)``; blocked on kill switch or open breaker."""
        if self.kill_switch.is_blocked():
            return (
                False,
                f"execution blocked — kill switch is {self.kill_switch.state.value}",
            )
        return self.breakers.check_can_execute()

    # ------------------------------------------------------------------
    # Outcome recording
    # ------------------------------------------------------------------
    def record_execution_result(self, success: bool, detail: str = "") -> None:
        """Feed one execution outcome into the EXECUTION breaker (§24).

        Success resets the breaker; failure counts toward tripping it. When the
        breaker trips it auto-triggers + locks the kill switch (via the breaker's
        kill switch wiring), which then blocks all further orders.
        """
        if success:
            self.breakers.record_success(Dependency.EXECUTION.value)
            return
        try:
            self.breakers.record_failure(
                Dependency.EXECUTION.value,
                reason=BreakerTripReason.EXECUTION_ERROR,
                detail=detail,
            )
        except Exception as exc:  # never let breaker bookkeeping break a cycle
            logger.warning("Could not record execution failure: %s", exc)

    def snapshot(self) -> dict[str, Any]:
        """Serialise guard state for the control plane."""
        return {
            "kill_switch": self.kill_switch.to_dict(),
            "breakers": self.breakers.snapshot(),
        }
