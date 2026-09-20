# -*- coding: utf-8 -*-
"""Failure Injection Lab — PRD_V2 §38.

Proves system safety under fault simulation. The lab provides:

* :class:`ScenarioOutcome` — the required report shape:
  ``trigger / expected state / expected action / actual action / PASS‑FAIL``.
* :class:`FailureInjector` — thin helpers that inject a specific fault into a
  *mock* dependency (never the real MT5 / DB), e.g. mark MT5 disconnected, raise
  an ``order_send`` timeout, or return a malformed LLM payload.
* :class:`ScenarioRunner` — drives a scenario callable and asserts the system
  took the *safe* action (blocked entries, degraded, or halted) — never an
  unsafe order.

The core safety invariant enforced for **every** scenario is:

    a failure must NEVER result in an unsafe order.

Where an order is deemed unsafe if ``allows_new_entries`` is True while a
critical fault is active, or if an order was submitted without risk approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from ..risk.multi_level_breaker import BreakerLevel, MultiLevelBreaker, TriggerType

__all__ = [
    "ScenarioOutcome",
    "FailureInjector",
    "ScenarioRunner",
    "UnsafeOrderError",
]


class UnsafeOrderError(AssertionError):
    """Raised when a scenario allowed an order that should have been blocked."""


@dataclass(frozen=True)
class ScenarioOutcome:
    """Report row for a single failure scenario (PRD §38 format)."""

    trigger: str
    expected_state: str
    expected_action: str
    actual_action: str
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger": self.trigger,
            "expected_state": self.expected_state,
            "expected_action": self.expected_action,
            "actual_action": self.actual_action,
            "result": "PASS" if self.passed else "FAIL",
        }


class FailureInjector:
    """Helpers to inject faults into mock dependencies.

    Each helper returns a deterministic signal that a scenario can feed into a
    safety component (breaker / recovery / reconciler). None of these touch a
    live terminal.
    """

    @staticmethod
    def mt5_unavailable(breakers: Any) -> None:
        """Trip the MT5 dependency breaker by recording failures to threshold."""
        for _ in range(breakers._breakers["mt5"].failure_threshold):
            breakers.record_failure("mt5", detail="simulated: MT5 unavailable")

    @staticmethod
    def mt5_reconnect(breakers: Any) -> None:
        """Simulate a successful MT5 reconnect (records a success)."""
        breakers.record_success("mt5")

    @staticmethod
    def bad_tick() -> dict[str, Any]:
        """A tick with a non-numeric/absurd price (must be rejected upstream)."""
        return {"symbol": "EURUSD", "bid": None, "ask": "n/a", "time": 0}

    @staticmethod
    def stale_tick(age_seconds: float = 999.0) -> dict[str, Any]:
        """A tick older than any sane freshness window."""
        return {"symbol": "EURUSD", "bid": 1.0850, "ask": 1.0852, "age_seconds": age_seconds}

    @staticmethod
    def spread_spike(multiplier: float = 10.0) -> dict[str, Any]:
        """A quote whose spread is ``multiplier``× the normal spread."""
        return {"symbol": "EURUSD", "bid": 1.0850, "ask": 1.0850 + 0.0002 * multiplier}

    @staticmethod
    def price_gap(pct: float = 0.2) -> dict[str, Any]:
        """A quote that gaps ``pct`` away from the previous close."""
        prev = 1.0850
        return {"symbol": "EURUSD", "prev_close": prev, "open": prev * (1 + pct)}

    @staticmethod
    def order_rejection() -> Callable[[], Any]:
        """Return a callable that mimics a broker order rejection."""
        return lambda: {"retcode": 10013, "comment": "invalid request (simulated)"}

    @staticmethod
    def order_timeout() -> Callable[[], Any]:
        """Return a callable that raises a timeout on order send."""

        def _raise() -> Any:
            raise TimeoutError("order_send timed out (simulated)")

        return _raise

    @staticmethod
    def unknown_order() -> dict[str, Any]:
        """An order result with an unknown/ambiguous fill status."""
        return {"retcode": 0, "order": 0, "state": "unknown", "volume": 0}

    @staticmethod
    def partial_fill(requested: float = 1.0, filled: float = 0.3) -> dict[str, Any]:
        """An order result that only partially filled."""
        return {"retcode": 0, "order": 123, "requested": requested, "filled": filled}

    @staticmethod
    def duplicate_event(event_id: str = "evt-1") -> list[dict[str, Any]]:
        """The same event delivered twice."""
        return [{"id": event_id}, {"id": event_id}]

    @staticmethod
    def duplicate_intent(intent_id: str = "intent-1") -> list[dict[str, Any]]:
        """The same execution intent delivered twice."""
        return [{"intent_id": intent_id}, {"intent_id": intent_id}]

    @staticmethod
    def database_unavailable(breakers: Any) -> None:
        """Trip the DB dependency breaker."""
        for _ in range(breakers._breakers["db"].failure_threshold):
            breakers.record_failure("db", detail="simulated: DB down")

    @staticmethod
    def redis_unavailable(breakers: Any) -> None:
        """Trip the QUEUE dependency breaker (stands in for Redis)."""
        for _ in range(breakers._breakers["queue"].failure_threshold):
            breakers.record_failure("queue", detail="simulated: Redis down")

    @staticmethod
    def llm_timeout() -> Callable[[], Any]:
        """Return a callable that raises a timeout when the LLM is called."""

        def _raise() -> Any:
            raise TimeoutError("LLM call timed out (simulated)")

        return _raise

    @staticmethod
    def llm_malformed_output() -> dict[str, Any]:
        """Malformed LLM JSON (unparseable decision)."""
        return {"raw": "{not: valid json,,}", "parsed": None}

    @staticmethod
    def gateway_unavailable(breakers: Any) -> None:
        """Trip the LLM gateway (9Router) breaker."""
        for _ in range(breakers._breakers["llm"].failure_threshold):
            breakers.record_failure("llm", detail="simulated: 9Router down")

    @staticmethod
    def telegram_unavailable() -> bool:
        """Return False to signal the Telegram channel is unreachable."""
        return False

    @staticmethod
    def process_crash() -> Callable[[], Any]:
        """Return a callable that raises to simulate an abrupt process crash."""

        def _crash() -> Any:
            raise RuntimeError("simulated process crash")

        return _crash

    @staticmethod
    def computer_restart() -> dict[str, Any]:
        """Return an in-memory state snapshot to hand to recovery-after-restart."""
        return {
            "risk_state": {"daily_loss": 500.0, "drawdown": 0.12, "consecutive_losses": 4},
        }


class ScenarioRunner:
    """Runs a scenario function and records the safe/unsafe outcome.

    A scenario function receives this runner and the shared
    :class:`~risk.multi_level_breaker.MultiLevelBreaker`, injects its fault, and
    returns the *actual action* string the system took.
    """

    def __init__(self, breaker: Optional[MultiLevelBreaker] = None) -> None:
        self.breaker = breaker or MultiLevelBreaker()
        self.outcomes: list[ScenarioOutcome] = []

    def run(
        self,
        trigger: str,
        expected_state: str,
        expected_action: str,
        action: Callable[["ScenarioRunner"], str],
        expect_block: bool,
    ) -> ScenarioOutcome:
        """Execute *action* and verify it produced no unsafe order.

        Args:
            trigger: Human description of the injected fault.
            expected_state: Expected breaker level (e.g. ``entry_blocked``).
            expected_action: Expected safe action text.
            action: Callable performing the injection; returns actual action.
            expect_block: When True, new entries MUST be blocked afterwards.
        """
        actual = action(self)

        # Safety invariant: entries blocked when required.
        if expect_block and self.breaker.allows_new_entries():
            raise UnsafeOrderError(
                f"[{trigger}] unsafe order permitted — new entries not blocked "
                f"(level={self.breaker.level.value})"
            )

        passed = (
            expected_state in self.breaker.level.value and expected_action.lower() in actual.lower()
        )
        outcome = ScenarioOutcome(
            trigger=trigger,
            expected_state=expected_state,
            expected_action=expected_action,
            actual_action=actual,
            passed=passed,
        )
        self.outcomes.append(outcome)
        return outcome

    def summary(self) -> list[dict[str, Any]]:
        return [o.to_dict() for o in self.outcomes]

    def all_passed(self) -> bool:
        return all(o.passed for o in self.outcomes)


# Convenience re-exports so scenarios can set breaker levels tersely.
LEVEL = BreakerLevel
TRIGGER = TriggerType
