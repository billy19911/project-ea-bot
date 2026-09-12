# -*- coding: utf-8 -*-
"""Tests for LLM provider abstraction, 9Router client, model registry, and fallback."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from src.llm.base import BaseLLMProvider, LLMResponse, ModelInfo, TokenUsage
from src.llm.nine_router import NineRouterClient
from src.llm.registry import ModelRegistry

# ---------------------------------------------------------------------------
# ModelInfo & TokenUsage dataclass tests
# ---------------------------------------------------------------------------


def test_model_info_creation() -> None:
    """ModelInfo stores all fields correctly."""
    model = ModelInfo(
        name="test-model",
        provider="test",
        is_free=True,
        context_window=4096,
        cost_per_prompt_token=0.001,
        cost_per_completion_token=0.002,
        capabilities=["chat", "streaming"],
    )
    assert model.name == "test-model"
    assert model.is_free is True
    assert model.capabilities == ["chat", "streaming"]


def test_token_usage_creation() -> None:
    """TokenUsage records token counts and cost."""
    usage = TokenUsage(
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cost_usd=0.0005,
    )
    assert usage.total_tokens == 150
    assert usage.cost_usd == 0.0005


def test_llm_response_creation() -> None:
    """LLMResponse captures content, model, usage, and metadata."""
    usage = TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30)
    resp = LLMResponse(
        content="Hello world",
        model="test-model",
        usage=usage,
        latency_s=0.5,
        is_fallback=False,
    )
    assert resp.content == "Hello world"
    assert resp.model == "test-model"
    assert resp.latency_s == 0.5
    assert resp.is_fallback is False


# ---------------------------------------------------------------------------
# BaseLLMProvider tests
# ---------------------------------------------------------------------------


class DummyProvider(BaseLLMProvider):
    """Minimal concrete provider for testing base class behavior."""

    def __init__(self) -> None:
        super().__init__()
        self.call_count = 0

    def generate(self, prompt, model=None, system_prompt=None, **kwargs) -> LLMResponse:
        self.call_count += 1
        return LLMResponse(
            content="dummy response",
            model=model or "dummy",
            usage=TokenUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
            latency_s=0.1,
        )

    def stream(self, prompt, model=None, system_prompt=None, **kwargs):
        yield "chunk 1"
        yield "chunk 2"


def test_base_provider_count_tokens() -> None:
    """Token estimation uses ~4 chars per token fallback."""
    provider = DummyProvider()
    assert provider.count_tokens("") == 1
    assert provider.count_tokens("test") == 1
    assert provider.count_tokens("abcd") == 1
    assert provider.count_tokens("abcdefgh") == 2


def test_base_provider_record_usage() -> None:
    """Usage stats accumulate across requests."""
    provider = DummyProvider()
    usage = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15, cost_usd=0.01)
    provider.record_usage(usage, 0.5)
    provider.record_usage(usage, 0.3)

    stats = provider.get_usage_stats()
    assert stats["request_count"] == 2
    assert stats["total_prompt_tokens"] == 20
    assert stats["total_completion_tokens"] == 10
    assert stats["total_cost_usd"] == 0.02
    assert stats["avg_latency_s"] == 0.4


def test_base_provider_reset_usage() -> None:
    """Reset clears all accumulated stats."""
    provider = DummyProvider()
    usage = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    provider.record_usage(usage, 0.5)
    provider.reset_usage_stats()

    stats = provider.get_usage_stats()
    assert stats["request_count"] == 0
    assert stats["total_prompt_tokens"] == 0


def test_base_provider_abstract_methods() -> None:
    """BaseLLMProvider cannot be instantiated directly."""
    with pytest.raises(TypeError):
        BaseLLMProvider()


# ---------------------------------------------------------------------------
# ModelRegistry tests
# ---------------------------------------------------------------------------


def test_registry_defaults_populated() -> None:
    """Registry initializes with default models."""
    registry = ModelRegistry()
    models = registry.list_models()
    assert len(models) >= 6
    names = {m.name for m in models}
    assert "google/gemini-2.0-flash-lite:free" in names
    assert "deepseek/deepseek-r1:free" in names


def test_registry_free_only_filter() -> None:
    """Free-only filter returns only free models."""
    registry = ModelRegistry()
    free_models = registry.list_models(free_only=True)
    assert all(m.is_free for m in free_models)
    assert len(free_models) >= 4


def test_registry_get_model() -> None:
    """Get returns correct model or None."""
    registry = ModelRegistry()
    model = registry.get("google/gemini-2.0-flash-lite:free")
    assert model is not None
    assert model.provider == "google"
    assert model.is_free is True

    assert registry.get("nonexistent-model") is None


def test_registry_register_override() -> None:
    """Register adds or overrides model entries."""
    registry = ModelRegistry()
    custom = ModelInfo(name="custom-model", provider="custom", is_free=False)
    registry.register(custom)
    assert registry.get("custom-model") == custom

    custom2 = ModelInfo(name="custom-model", provider="custom2", is_free=True)
    registry.register(custom2)
    assert registry.get("custom-model").is_free is True


def test_registry_default_model() -> None:
    """Default model selection works for free and paid."""
    registry = ModelRegistry()
    free_default = registry.get_default_model(free_only=True)
    paid_default = registry.get_default_model(free_only=False)
    assert free_default == "google/gemini-2.0-flash-lite:free"
    assert paid_default == "openai/gpt-4o-mini"


def test_registry_cost_calculation() -> None:
    """Cost calculation for paid models, zero for free."""
    registry = ModelRegistry()
    free_cost = registry.calculate_cost("google/gemini-2.0-flash-lite:free", 1000, 500)
    paid_cost = registry.calculate_cost("openai/gpt-4o-mini", 1_000_000, 1_000_000)

    assert free_cost == 0.0
    assert abs(paid_cost - 0.75) < 0.001  # (0.15 + 0.60) per M tokens


# ---------------------------------------------------------------------------
# NineRouterClient tests (with mocked OpenAI client)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_openai_client() -> Mock:
    """Create a mock OpenAI client with controllable responses."""
    mock_client = Mock()
    mock_completion = Mock()
    mock_completion.choices = [Mock(message=Mock(content="Test response"), finish_reason="stop")]
    mock_completion.usage = Mock(prompt_tokens=20, completion_tokens=10, total_tokens=30)
    mock_completion.model_dump = Mock(return_value={})
    mock_client.chat.completions.create.return_value = mock_completion

    return mock_client


def test_nine_router_init_defaults() -> None:
    """Client initializes with sensible defaults."""
    with patch("src.llm.nine_router.OpenAI"):
        client = NineRouterClient(api_key="test-key")
        assert client.default_model == "google/gemini-2.0-flash-lite:free"
        assert client.fallback_models == ["deepseek/deepseek-r1:free"]
        assert client.timeout == 30.0
        assert client.max_retries == 2


def test_nine_router_generate_success(mock_openai_client: Mock) -> None:
    """Successful generation returns LLMResponse with usage."""
    with patch("src.llm.nine_router.OpenAI", return_value=mock_openai_client):
        client = NineRouterClient(api_key="test-key", client=mock_openai_client)
        resp = client.generate("Hello")

    assert isinstance(resp, LLMResponse)
    assert resp.content == "Test response"
    assert resp.model == "google/gemini-2.0-flash-lite:free"
    assert resp.usage.total_tokens == 30
    assert resp.is_fallback is False


def test_nine_router_generate_with_custom_model(mock_openai_client: Mock) -> None:
    """Custom model parameter overrides default."""
    with patch("src.llm.nine_router.OpenAI", return_value=mock_openai_client):
        client = NineRouterClient(api_key="test-key", client=mock_openai_client)
        client.generate("Hello", model="custom-model")

    call_kwargs = mock_openai_client.chat.completions.create.call_args[1]
    assert call_kwargs["model"] == "custom-model"


def test_nine_router_retry_on_failure(mock_openai_client: Mock) -> None:
    """Retries with exponential backoff on transient failures."""
    mock_openai_client.chat.completions.create.side_effect = [
        Exception("Transient error"),
        Mock(
            choices=[Mock(message=Mock(content="Success"), finish_reason="stop")],
            usage=Mock(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        ),
    ]

    with patch("src.llm.nine_router.OpenAI", return_value=mock_openai_client):
        with patch("src.llm.nine_router.time.sleep") as mock_sleep:
            client = NineRouterClient(
                api_key="test-key",
                client=mock_openai_client,
                max_retries=2,
                initial_retry_delay=0.1,
                backoff_factor=2.0,
            )
            resp = client.generate("Hello")

    assert resp.content == "Success"
    assert mock_sleep.call_count == 1
    # Delay should be 0.1 * 2^0 = 0.1
    mock_sleep.assert_called_once_with(0.1)


def test_nine_router_fallback_to_secondary_model(mock_openai_client: Mock) -> None:
    """Fallback triggers when primary model fails all retries."""
    # Primary fails, secondary succeeds
    mock_openai_client.chat.completions.create.side_effect = [
        Exception("Primary failed"),
        Exception("Primary failed"),
        Exception("Primary failed"),
        Mock(
            choices=[Mock(message=Mock(content="Fallback works"), finish_reason="stop")],
            usage=Mock(prompt_tokens=15, completion_tokens=10, total_tokens=25),
        ),
    ]

    with patch("src.llm.nine_router.OpenAI", return_value=mock_openai_client):
        with patch("src.llm.nine_router.time.sleep"):
            client = NineRouterClient(
                api_key="test-key",
                client=mock_openai_client,
                max_retries=1,
                initial_retry_delay=0.01,
            )
            resp = client.generate("Hello")

    assert resp.content == "Fallback works"
    assert resp.is_fallback is True


def test_nine_router_mock_fallback_when_all_fail(mock_openai_client: Mock) -> None:
    """Rule-based mock activates when all models fail."""
    mock_openai_client.chat.completions.create.side_effect = Exception("All down")

    with patch("src.llm.nine_router.OpenAI", return_value=mock_openai_client):
        with patch("src.llm.nine_router.time.sleep"):
            client = NineRouterClient(
                api_key="test-key",
                client=mock_openai_client,
                max_retries=0,
                initial_retry_delay=0.01,
            )
            resp = client.generate("Hello")

    assert resp.is_fallback is True
    assert resp.model == "rule-based-mock"
    assert "Rule-Based Mock Response" in resp.content
    assert resp.usage.cost_usd == 0.0


def test_nine_router_stream_success(mock_openai_client: Mock) -> None:
    """Streaming yields chunks and accumulates usage."""
    chunks = [
        Mock(choices=[Mock(delta=Mock(content="Hello "))]),
        Mock(choices=[Mock(delta=Mock(content="world"))]),
        Mock(choices=[Mock(delta=Mock(content="!"))]),
    ]
    mock_openai_client.chat.completions.create.return_value = iter(chunks)

    with patch("src.llm.nine_router.OpenAI", return_value=mock_openai_client):
        client = NineRouterClient(api_key="test-key", client=mock_openai_client)
        streamed = list(client.stream("Hello"))

    assert streamed == ["Hello ", "world", "!"]
    assert client.request_count == 1


def test_nine_router_prepare_messages_string_prompt() -> None:
    """String prompts converted to message format correctly."""
    with patch("src.llm.nine_router.OpenAI"):
        client = NineRouterClient(api_key="test-key")
        messages = client._prepare_messages("User prompt", "System prompt")

    assert len(messages) == 2
    assert messages[0] == {"role": "system", "content": "System prompt"}
    assert messages[1] == {"role": "user", "content": "User prompt"}


def test_nine_router_prepare_messages_list_prompt() -> None:
    """List prompts preserved and system prompt prepended."""
    with patch("src.llm.nine_router.OpenAI"):
        client = NineRouterClient(api_key="test-key")
        messages = client._prepare_messages([{"role": "user", "content": "Hello"}], "System msg")

    assert len(messages) == 2
    assert messages[0] == {"role": "system", "content": "System msg"}
    assert messages[1] == {"role": "user", "content": "Hello"}


def test_nine_router_usage_tracking_across_calls(mock_openai_client: Mock) -> None:
    """Aggregate usage stats persist across multiple requests."""
    with patch("src.llm.nine_router.OpenAI", return_value=mock_openai_client):
        client = NineRouterClient(api_key="test-key", client=mock_openai_client)
        client.generate("First")
        client.generate("Second")

    stats = client.get_usage_stats()
    assert stats["request_count"] == 2
    # Mock returns 30 tokens each call (20 prompt + 10 completion)
    # Plus counted tokens from fallback rule-based mock (unused here)
    assert stats["total_tokens"] >= 60


# ---------------------------------------------------------------------------
# Integration-style test
# ---------------------------------------------------------------------------


def test_full_llm_workflow() -> None:
    """End-to-end workflow: registry -> client -> response -> stats."""
    registry = ModelRegistry()
    model = registry.get("google/gemini-2.0-flash-lite:free")
    assert model is not None
    assert model.is_free is True

    mock_client = Mock()
    mock_client.chat.completions.create.return_value = Mock(
        choices=[Mock(message=Mock(content="OK"), finish_reason="stop")],
        usage=Mock(prompt_tokens=100, completion_tokens=50, total_tokens=150),
    )

    with patch("src.llm.nine_router.OpenAI", return_value=mock_client):
        client = NineRouterClient(
            api_key="test",
            default_model="google/gemini-2.0-flash-lite:free",
            registry=registry,
            client=mock_client,
        )
        resp = client.generate("Analyze EURUSD trend")

    assert resp.content == "OK"
    assert resp.model == "google/gemini-2.0-flash-lite:free"
    assert resp.usage.cost_usd == 0.0  # free model

    stats = client.get_usage_stats()
    assert stats["request_count"] == 1
    assert stats["total_cost_usd"] == 0.0
    assert stats["total_tokens"] == 150
