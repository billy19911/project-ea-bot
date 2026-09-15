# -*- coding: utf-8 -*-
"""Tests for dynamic 9Router model discovery (P0-5 / PRD_V2 §20 & §32.19).

The registry must call ``GET /v1/models`` on the OpenAI-compatible gateway,
normalize entries into ``ModelInfo``, cache the result with a TTL, expose a
safe ``health()`` state machine, and never lose the previously served models
when discovery fails.
"""

from __future__ import annotations

from typing import Any

from src.llm.base import ModelInfo
from src.llm.registry import STATE_CONNECTED, STATE_DEGRADED, STATE_DISCONNECTED, ModelRegistry


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------
class _StubModel:
    """A gateway model entry exposing only ``.id`` (like the OpenAI SDK)."""

    def __init__(self, model_id: str, **extra: Any) -> None:
        self.id = model_id
        for key, value in extra.items():
            setattr(self, key, value)


class _StubModelsAPI:
    def __init__(self, entries: list[Any]) -> None:
        self._entries = entries
        self.call_count = 0

    def list(self) -> Any:
        self.call_count += 1
        if isinstance(self._entries, Exception):
            raise self._entries
        return _StubModelsResponse(self._entries)


class _StubModelsResponse:
    def __init__(self, data: list[Any]) -> None:
        self.data = data


class StubGatewayClient:
    """Minimal OpenAI-compatible client exposing ``.models.list()``."""

    def __init__(self, entries: Any) -> None:
        self.models = _StubModelsAPI(entries)


def _sample_entries() -> list[_StubModel]:
    return [
        _StubModel("openai/gpt-4o-mini"),
        _StubModel("google/gemini-2.0-flash-lite:free"),
        _StubModel("deepseek/deepseek-r1:free"),
    ]


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
def test_discovery_normalizes_model_list() -> None:
    """Discovery turns gw model ids into ModelInfo entries with parsed provider."""
    registry = ModelRegistry()
    client = StubGatewayClient(_sample_entries())

    models = registry.discover_from_gateway(client=client)
    names = {m.name for m in models}

    assert names == {
        "openai/gpt-4o-mini",
        "google/gemini-2.0-flash-lite:free",
        "deepseek/deepseek-r1:free",
    }
    assert all(isinstance(m, ModelInfo) for m in models)
    assert registry.get("openai/gpt-4o-mini").provider == "openai"
    assert registry.get("google/gemini-2.0-flash-lite:free").provider == "google"
    assert registry.source == "gateway"


def test_discovery_marks_free_models() -> None:
    """Models whose id contains ':free' are flagged is_free=True."""
    registry = ModelRegistry()
    client = StubGatewayClient(
        [
            _StubModel("openai/gpt-4o-mini"),
            _StubModel("meta-llama/llama-3.3-70b-instruct:free"),
        ]
    )

    registry.discover_from_gateway(client=client)

    assert registry.get("meta-llama/llama-3.3-70b-instruct:free").is_free is True
    assert registry.get("openai/gpt-4o-mini").is_free is False


def test_discovery_replaces_defaults() -> None:
    """A successful discovery replaces the fallback defaults."""
    registry = ModelRegistry()
    client = StubGatewayClient([_StubModel("custom/only-model:free")])

    registry.discover_from_gateway(client=client)

    assert registry.get("google/gemini-2.0-flash-lite:free") is None
    assert registry.get("custom/only-model:free") is not None


def test_discovery_records_timestamp() -> None:
    """A successful discovery records last_discovery and source=gateway."""
    registry = ModelRegistry()
    client = StubGatewayClient(_sample_entries())

    assert registry.last_discovery is None
    registry.discover_from_gateway(client=client)

    assert registry.last_discovery is not None
    assert registry.source == "gateway"


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------
def test_discovery_cached_within_ttl() -> None:
    """A second discovery within the TTL does not hit the gateway again."""
    registry = ModelRegistry()
    client = StubGatewayClient(_sample_entries())

    registry.discover_from_gateway(client=client, cache_ttl=300)
    registry.discover_from_gateway(client=client, cache_ttl=300)

    assert client.models.call_count == 1


def test_discovery_force_bypasses_cache() -> None:
    """force=True queries the gateway even within the TTL window."""
    registry = ModelRegistry()
    client = StubGatewayClient(_sample_entries())

    registry.discover_from_gateway(client=client, cache_ttl=300)
    registry.discover_from_gateway(client=client, force=True, cache_ttl=300)

    assert client.models.call_count == 2


# ---------------------------------------------------------------------------
# Health state machine
# ---------------------------------------------------------------------------
def test_health_connected_after_success() -> None:
    """Successful discovery reports CONNECTED with model count and timestamp."""
    registry = ModelRegistry()
    registry.discover_from_gateway(client=StubGatewayClient(_sample_entries()))

    health = registry.health()
    assert health["state"] == STATE_CONNECTED
    assert health["model_count"] == 3
    assert health["last_discovery"] is not None
    assert "error" not in health


def test_health_degraded_after_failure_with_cache() -> None:
    """Cached models + failed refresh → DEGRADED, models still served."""
    registry = ModelRegistry()
    client = StubGatewayClient(_sample_entries())
    registry.discover_from_gateway(client=client)

    failing = StubGatewayClient(RuntimeError("gateway down"))
    models = registry.discover_from_gateway(client=failing, force=True)

    health = registry.health()
    assert health["state"] == STATE_DEGRADED
    assert "error" in health
    # Fail-safe: previously discovered models are still served.
    assert {m.name for m in models} == {e.id for e in _sample_entries()}


def test_health_disconnected_without_cache() -> None:
    """Failure with no prior discovery → DISCONNECTED (defaults still served)."""
    registry = ModelRegistry()
    failing = StubGatewayClient(RuntimeError("never connected"))

    models = registry.discover_from_gateway(client=failing)

    health = registry.health()
    assert health["state"] == STATE_DISCONNECTED
    assert registry.source == "defaults"
    # Defaults remain available so the system keeps running.
    assert len(models) >= 6


def test_health_never_raises() -> None:
    """health() must never raise, even after a catastrophic discovery failure."""

    class ExplodingClient:
        class models:  # noqa: N801 - mimic attribute name
            @staticmethod
            def list() -> Any:
                raise ValueError("boom")

    registry = ModelRegistry()
    registry.discover_from_gateway(client=ExplodingClient())

    health = registry.health()  # must not raise
    assert health["state"] == STATE_DISCONNECTED
    assert "error" in health


def test_health_never_raises_with_none_client_import() -> None:
    """health() is safe even if discovery was never attempted."""
    registry = ModelRegistry()
    health = registry.health()
    assert health["state"] == STATE_DISCONNECTED
    assert health["model_count"] >= 6


# ---------------------------------------------------------------------------
# Fail-safe integrity
# ---------------------------------------------------------------------------
def test_gateway_failure_leaves_previous_models_intact() -> None:
    """A failed discovery must not wipe out the previously served models."""
    registry = ModelRegistry()
    registry.discover_from_gateway(client=StubGatewayClient(_sample_entries()))
    before = {m.name for m in registry.list_models()}

    registry.discover_from_gateway(client=StubGatewayClient(RuntimeError("timeout")), force=True)

    assert {m.name for m in registry.list_models()} == before


def test_empty_gateway_response_is_treated_as_failure() -> None:
    """An empty model list must not blank the registry (treated as failure)."""
    registry = ModelRegistry()
    registry.discover_from_gateway(client=StubGatewayClient(_sample_entries()))

    registry.discover_from_gateway(client=StubGatewayClient([]), force=True)

    # Still serving the earlier discovered models, flagged DEGRADED.
    assert registry.get("openai/gpt-4o-mini") is not None
    assert registry.health()["state"] == STATE_DEGRADED


# ---------------------------------------------------------------------------
# Raw HTTP fidelity (httpx fallback path) — Run 17
# ---------------------------------------------------------------------------
class _FakeHTTPResponse:
    """Minimal ``httpx.Response`` double exposing ``.json()``."""

    def __init__(self, payload: Any, *, error: Exception | None = None) -> None:
        self._payload = payload
        self._error = error

    def json(self) -> Any:
        if self._error is not None:
            raise self._error
        return self._payload

    def raise_for_status(self) -> None:
        return None


def _patch_httpx_get(monkeypatch: Any, responder: Any) -> list[dict[str, Any]]:
    """Patch ``src.llm.registry.httpx.get`` and record the calls made."""
    calls: list[dict[str, Any]] = []

    def _fake_get(url: str, **kwargs: Any) -> Any:
        calls.append({"url": url, **kwargs})
        return responder(url, **kwargs)

    monkeypatch.setattr("src.llm.registry.httpx.get", _fake_get)
    return calls


def test_gateway_raw_json_preserves_context_and_capabilities(monkeypatch: Any) -> None:
    """Raw gateway JSON keeps context_length and the dict capabilities."""
    payload = {
        "data": [
            {
                "id": "gc/gemini-3.1-pro-preview",
                "owned_by": "gc",
                "context_length": 1048576,
                "capabilities": {
                    "vision": True,
                    "pdf": False,
                    "tools": True,
                    "contextWindow": 1048576,
                },
            }
        ]
    }
    _patch_httpx_get(monkeypatch, lambda url, **kw: _FakeHTTPResponse(payload))

    registry = ModelRegistry()
    registry.discover_from_gateway(client=None, force=True)

    model = registry.get("gc/gemini-3.1-pro-preview")
    assert model is not None
    assert model.context_window == 1048576
    assert "vision" in model.capabilities
    assert "tools" in model.capabilities
    assert "contextWindow" not in model.capabilities
    assert "pdf" not in model.capabilities


def test_gateway_raw_json_uses_owned_by_as_provider(monkeypatch: Any) -> None:
    """A model without a ``provider/`` prefix uses ``owned_by`` for the provider."""
    payload = {"data": [{"id": "OpenCodeCombo", "owned_by": "combo"}]}
    _patch_httpx_get(monkeypatch, lambda url, **kw: _FakeHTTPResponse(payload))

    registry = ModelRegistry()
    registry.discover_from_gateway(client=None, force=True)

    assert registry.get("OpenCodeCombo").provider == "combo"


def test_gateway_raw_json_honest_free_detection(monkeypatch: Any) -> None:
    """``free`` is detected as a token (``-free``, ``/free``, ``:free``)."""
    payload = {
        "data": [
            {"id": "opencode-free"},
            {"id": "kc/kilo-auto/free"},
            {"id": "th-harbor/deepseek-v4-flash:free"},
            {"id": "gc/gemini-2.5-pro"},
        ]
    }
    _patch_httpx_get(monkeypatch, lambda url, **kw: _FakeHTTPResponse(payload))

    registry = ModelRegistry()
    registry.discover_from_gateway(client=None, force=True)

    assert registry.get("opencode-free").is_free is True
    assert registry.get("kc/kilo-auto/free").is_free is True
    assert registry.get("th-harbor/deepseek-v4-flash:free").is_free is True
    assert registry.get("gc/gemini-2.5-pro").is_free is False


def test_ambiguous_free_suffix_without_separator_is_not_free() -> None:
    """A trailing ``free`` with no separator is ambiguous and stays paid."""
    registry = ModelRegistry()
    registry.discover_from_gateway(
        client=StubGatewayClient([_StubModel("codebuddy-deepseekv4.1flashfree")]),
    )
    assert registry.get("codebuddy-deepseekv4.1flashfree").is_free is False


def test_httpx_failure_falls_back_without_raising(monkeypatch: Any) -> None:
    """When raw httpx fails the discovery is fail-safe (cached/defaults, no raise)."""

    def _boom(url: str, **kwargs: Any) -> Any:
        raise RuntimeError("network down")

    monkeypatch.setattr("src.llm.registry.httpx.get", _boom)

    registry = ModelRegistry()
    models = registry.discover_from_gateway(client=None, force=True)

    # Defaults remain served and nothing raised.
    assert len(models) >= 6
    assert registry.health()["state"] == STATE_DISCONNECTED
