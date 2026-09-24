# -*- coding: utf-8 -*-
"""LLM Observability & Model Governance — PRD_V2 §46.

Collects per-request telemetry for every LLM call and tracks a model lifecycle
registry. Two safety invariants are enforced:

1. **Model failure is never unsafe** — when an LLM call fails, the system either
   uses a deterministic fallback or *skips AI reasoning*; it never proceeds to
   an unsafe trade (the risk stack still gates every order independently).
2. **No small-sample model verdicts** — comparison of models requires a minimum
   sample before a verdict may be drawn.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

__all__ = [
    "ModelState",
    "LLMRequestTelemetry",
    "LLMTelemetryStore",
    "ModelGovernance",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ModelState(str, Enum):
    """Model lifecycle states (PRD §46 Model registry)."""

    ACTIVE = "ACTIVE"
    FALLBACK = "FALLBACK"
    DISABLED = "DISABLED"
    DEPRECATED = "DEPRECATED"


@dataclass(frozen=True)
class LLMRequestTelemetry:
    """Telemetry for a single LLM request (PRD §46 request telemetry)."""

    request_id: str
    agent: str
    provider: str
    model: str
    prompt_version: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency: float = 0.0
    fallback: bool = False
    error: str = ""
    decision_id: str = ""
    structured_output_valid: bool = True
    cost: float = 0.0
    created_at: str = field(default_factory=_now)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "agent": self.agent,
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency": self.latency,
            "fallback": self.fallback,
            "error": self.error,
            "decision_id": self.decision_id,
            "structured_output_valid": self.structured_output_valid,
            "cost": self.cost,
            "created_at": self.created_at,
        }


@dataclass
class LLMTelemetryStore:
    """Bounded, in-memory store of LLM request telemetry (PRD §46)."""

    max_records: int = 5000
    _records: list[LLMRequestTelemetry] = field(default_factory=list, repr=False)

    def record(self, telemetry: LLMRequestTelemetry) -> LLMRequestTelemetry:
        """Append a telemetry record, evicting the oldest on overflow."""
        self._records.append(telemetry)
        if len(self._records) > self.max_records:
            self._records = self._records[-self.max_records :]
        return telemetry

    def all(self) -> list[LLMRequestTelemetry]:
        return list(self._records)

    def for_model(self, model: str) -> list[LLMRequestTelemetry]:
        return [r for r in self._records if r.model == model]

    def failure_rate(self, model: str) -> float:
        records = self.for_model(model)
        if not records:
            return 0.0
        failures = sum(1 for r in records if r.error)
        return failures / len(records)

    def average_latency(self, model: str) -> float:
        records = self.for_model(model)
        if not records:
            return 0.0
        return sum(r.latency for r in records) / len(records)

    def total_tokens(self, model: str) -> int:
        return sum(r.total_tokens for r in self.for_model(model))

    def structured_output_validity(self, model: str) -> float:
        records = self.for_model(model)
        if not records:
            return 0.0
        valid = sum(1 for r in records if r.structured_output_valid)
        return valid / len(records)


@dataclass
class ModelGovernance:
    """Model lifecycle registry + safe-fallback policy (PRD §46).

    Args:
        min_comparison_sample: Minimum telemetry records before a model
            comparison verdict may be drawn (PRD "no small-sample verdicts").
        fallback_model: Deterministic fallback model when an ACTIVE model fails.
    """

    store: LLMTelemetryStore = field(default_factory=LLMTelemetryStore)
    min_comparison_sample: int = 30
    fallback_model: str = "deterministic"
    _states: dict[str, str] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------
    def set_state(self, model: str, state: str) -> None:
        if state not in {s.value for s in ModelState}:
            raise ValueError(f"Unknown model state: {state}")
        self._states[model] = state

    def state(self, model: str) -> str:
        return self._states.get(model, ModelState.ACTIVE.value)

    def active_models(self) -> list[str]:
        return [m for m, s in self._states.items() if s == ModelState.ACTIVE.value]

    def resolve(self, model: str) -> tuple[str, bool]:
        """Resolve which model to use, returning ``(model, is_fallback)``.

        A DISABLED/DEPRECATED model resolves to the deterministic fallback —
        never to another unsafe path.
        """
        state = self.state(model)
        if state in (ModelState.DISABLED.value, ModelState.DEPRECATED.value):
            return self.fallback_model, True
        if state == ModelState.FALLBACK.value:
            return self.fallback_model, True
        return model, False

    # ------------------------------------------------------------------
    # Failure handling (PRD §46 Model failure)
    # ------------------------------------------------------------------
    def on_failure(self, model: str, request_id: str, error: str) -> dict[str, Any]:
        """Handle an LLM failure safely.

        Records the failure telemetry and returns the safe next action:
        either ``use_fallback`` (deterministic fallback) or ``skip_ai``
        (skip AI reasoning). In *both* cases ``unsafe_trade`` is False.
        """
        self.store.record(
            LLMRequestTelemetry(
                request_id=request_id,
                agent="",
                provider="",
                model=model,
                fallback=True,
                error=error,
                structured_output_valid=False,
            )
        )
        action = "use_fallback" if self.fallback_model else "skip_ai"
        return {
            "action": action,
            "fallback_model": self.fallback_model,
            "unsafe_trade": False,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "states": dict(self._states),
            "fallback_model": self.fallback_model,
            "min_comparison_sample": self.min_comparison_sample,
        }

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------
    def compare(self, model_a: str, model_b: str) -> dict[str, Any]:
        """Compare two models using collected telemetry (PRD §46).

        A verdict is only issued when both models have at least
        ``min_comparison_sample`` records — small samples yield
        ``INSUFFICIENT_SAMPLE`` and no conclusion.
        """
        a_records = self.store.for_model(model_a)
        b_records = self.store.for_model(model_b)
        if (
            len(a_records) < self.min_comparison_sample
            or len(b_records) < self.min_comparison_sample
        ):
            return {
                "verdict": "INSUFFICIENT_SAMPLE",
                "sample_a": len(a_records),
                "sample_b": len(b_records),
            }
        return {
            "verdict": "COMPARABLE",
            "a": {
                "failure_rate": self.store.failure_rate(model_a),
                "avg_latency": self.store.average_latency(model_a),
                "total_tokens": self.store.total_tokens(model_a),
                "structured_validity": self.store.structured_output_validity(model_a),
            },
            "b": {
                "failure_rate": self.store.failure_rate(model_b),
                "avg_latency": self.store.average_latency(model_b),
                "total_tokens": self.store.total_tokens(model_b),
                "structured_validity": self.store.structured_output_validity(model_b),
            },
        }
