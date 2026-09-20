# -*- coding: utf-8 -*-
"""Tests for LLM Observability & Model Governance (Phase 46)."""

from src.observability.llm_telemetry import (
    LLMRequestTelemetry,
    LLMTelemetryStore,
    ModelGovernance,
    ModelState,
)


def _rec(
    model: str, latency: float = 1.0, error: str = "", valid: bool = True
) -> LLMRequestTelemetry:
    return LLMRequestTelemetry(
        request_id="r1",
        agent="trend",
        provider="9router",
        model=model,
        latency=latency,
        error=error,
        structured_output_valid=valid,
        input_tokens=100,
        output_tokens=50,
    )


def test_store_metrics() -> None:
    store = LLMTelemetryStore()
    for i in range(10):
        store.record(_rec("m1", latency=1.0, error="boom" if i < 2 else ""))
    assert store.failure_rate("m1") == 0.2
    assert store.average_latency("m1") == 1.0
    assert store.total_tokens("m1") == 1500
    assert store.structured_output_validity("m1") == 1.0


def test_governance_states() -> None:
    gov = ModelGovernance()
    gov.set_state("m1", ModelState.ACTIVE.value)
    gov.set_state("m2", ModelState.DISABLED.value)
    assert gov.state("m1") == "ACTIVE"
    assert gov.state("m2") == "DISABLED"
    assert gov.active_models() == ["m1"]


def test_resolve_disabled_uses_fallback() -> None:
    gov = ModelGovernance(fallback_model="deterministic")
    gov.set_state("bad", ModelState.DISABLED.value)
    model, is_fallback = gov.resolve("bad")
    assert model == "deterministic"
    assert is_fallback is True


def test_resolve_active_no_fallback() -> None:
    gov = ModelGovernance()
    gov.set_state("good", ModelState.ACTIVE.value)
    model, is_fallback = gov.resolve("good")
    assert model == "good"
    assert is_fallback is False


def test_on_failure_is_safe() -> None:
    gov = ModelGovernance()
    result = gov.on_failure("m1", request_id="r9", error="timeout")
    assert result["unsafe_trade"] is False
    assert result["action"] in {"use_fallback", "skip_ai"}


def test_compare_insufficient_sample() -> None:
    gov = ModelGovernance(min_comparison_sample=30)
    for _ in range(5):
        gov.store.record(_rec("m1"))
    result = gov.compare("m1", "m2")
    assert result["verdict"] == "INSUFFICIENT_SAMPLE"


def test_compare_with_enough_sample() -> None:
    gov = ModelGovernance(min_comparison_sample=5)
    for i in range(10):
        gov.store.record(_rec("m1", latency=0.5))
        gov.store.record(_rec("m2", latency=2.0))
    result = gov.compare("m1", "m2")
    assert result["verdict"] == "COMPARABLE"
    assert result["a"]["avg_latency"] == 0.5
    assert result["b"]["avg_latency"] == 2.0


def test_bounded_store() -> None:
    store = LLMTelemetryStore(max_records=3)
    for i in range(5):
        store.record(_rec(f"m{i}"))
    assert len(store.all()) == 3
