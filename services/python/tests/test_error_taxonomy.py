# -*- coding: utf-8 -*-
"""TASK 04 — AI Control error taxonomy tests (Python side).

Proves the 13 required codes exist, every classified error carries the canonical
field set, the retry policy only retries transient/infra errors, and LLM
provider exceptions (503 / timeout / 4xx) are classified into the correct layer
so a 503 is never surfaced as a generic "agent error".
"""

from __future__ import annotations

from src.llm.errors import ERROR_CODES, ERROR_LAYER, classify, classify_llm_exception, is_retryable

REQUIRED_CODES = {
    "NODE_API_UNAVAILABLE",
    "PYTHON_SERVICE_UNAVAILABLE",
    "PYTHON_ENDPOINT_4XX",
    "PYTHON_ENDPOINT_5XX",
    "AGENT_TIMEOUT",
    "AGENT_EXCEPTION",
    "LLM_PROVIDER_4XX",
    "LLM_PROVIDER_5XX",
    "LLM_PROVIDER_503",
    "LLM_TIMEOUT",
    "MODEL_UNAVAILABLE",
    "AUTH_FAILURE",
    "DATA_GUARD_FAILURE",
}

CANONICAL_FIELDS = {
    "code",
    "layer",
    "trace_id",
    "service",
    "endpoint",
    "status_code",
    "agent",
    "event_id",
    "model",
    "provider",
    "timestamp",
    "message",
    "retryable",
}


def test_exposes_all_thirteen_codes() -> None:
    assert set(ERROR_CODES) == REQUIRED_CODES
    assert len(ERROR_CODES) == 13


def test_every_classified_error_carries_the_canonical_fields() -> None:
    for code in REQUIRED_CODES:
        err = classify(code)
        assert CANONICAL_FIELDS <= set(err.keys()), f"{code} missing a canonical field"
        assert err["code"] == code
        assert isinstance(err["retryable"], bool)
        assert isinstance(err["timestamp"], str) and err["timestamp"]


def test_unknown_fields_default_to_none() -> None:
    err = classify("AGENT_EXCEPTION", message="boom")
    for field in (
        "trace_id",
        "service",
        "endpoint",
        "status_code",
        "agent",
        "event_id",
        "model",
        "provider",
    ):
        assert err[field] is None


def test_retry_policy_matches_spec() -> None:
    for code in (
        "PYTHON_SERVICE_UNAVAILABLE",
        "PYTHON_ENDPOINT_5XX",
        "AGENT_TIMEOUT",
        "AGENT_EXCEPTION",
        "LLM_PROVIDER_5XX",
        "LLM_PROVIDER_503",
        "LLM_TIMEOUT",
        "NODE_API_UNAVAILABLE",
    ):
        assert is_retryable(code) is True, f"{code} should be retryable"
    for code in (
        "PYTHON_ENDPOINT_4XX",
        "LLM_PROVIDER_4XX",
        "MODEL_UNAVAILABLE",
        "AUTH_FAILURE",
        "DATA_GUARD_FAILURE",
    ):
        assert is_retryable(code) is False, f"{code} must NOT be retryable"


def test_layer_attribution_503_is_llm_provider_not_agent() -> None:
    assert ERROR_LAYER["LLM_PROVIDER_503"] == "llm_provider"
    assert ERROR_LAYER["PYTHON_SERVICE_UNAVAILABLE"] == "python_service"
    assert ERROR_LAYER["AGENT_EXCEPTION"] == "agent"


class _HttpError(Exception):
    """Minimal httpx/OpenAI-style error carrying a status code."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def test_provider_503_classifies_as_llm_provider_503() -> None:
    err = classify_llm_exception(
        _HttpError("Service Unavailable", 503),
        agent="technical_analyst",
        model="codebuddy-deepseekv4.1flashfree",
    )
    assert err["code"] == "LLM_PROVIDER_503"
    assert err["layer"] == "llm_provider"
    assert err["status_code"] == 503
    assert err["agent"] == "technical_analyst"
    assert err["model"] == "codebuddy-deepseekv4.1flashfree"
    assert err["retryable"] is True


def test_provider_4xx_classifies_as_not_retryable() -> None:
    err = classify_llm_exception(_HttpError("Bad Request", 400))
    assert err["code"] == "LLM_PROVIDER_4XX"
    assert err["retryable"] is False


def test_provider_timeout_classifies_as_llm_timeout() -> None:
    err = classify_llm_exception(Exception("Request timed out"))
    assert err["code"] == "LLM_TIMEOUT"
    assert err["retryable"] is True


def test_provider_5xx_from_status_code() -> None:
    err = classify_llm_exception(_HttpError("Internal Server Error", 500))
    assert err["code"] == "LLM_PROVIDER_5XX"


def test_missing_model_classifies_as_model_unavailable() -> None:
    err = classify_llm_exception(Exception("model not found: ghost"))
    assert err["code"] == "MODEL_UNAVAILABLE"
    assert err["retryable"] is False
