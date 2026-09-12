# -*- coding: utf-8 -*-
"""Base LLM provider interface and data models."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class TokenUsage:
    """Token usage and cost breakdown for LLM requests."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class ModelInfo:
    """Metadata and pricing info for an LLM model."""

    name: str
    provider: str
    is_free: bool = False
    context_window: int = 8192
    cost_per_prompt_token: float = 0.0
    cost_per_completion_token: float = 0.0
    capabilities: list[str] = field(default_factory=list)


@dataclass
class LLMResponse:
    """Standardized response format from LLM providers."""

    content: str
    model: str
    usage: TokenUsage
    raw: dict[str, Any] = field(default_factory=dict)
    latency_s: float = 0.0
    is_fallback: bool = False


class BaseLLMProvider(ABC):
    """Abstract base provider for LLM integrations."""

    def __init__(self) -> None:
        self.request_count: int = 0
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0
        self.total_cost_usd: float = 0.0
        self.total_latency_s: float = 0.0

    @abstractmethod
    def generate(
        self,
        prompt: str | list[dict[str, str]],
        model: str | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate response for given prompt."""
        ...

    @abstractmethod
    def stream(
        self,
        prompt: str | list[dict[str, str]],
        model: str | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> Iterator[str]:
        """Stream completion tokens for given prompt."""
        ...

    def count_tokens(self, text: str) -> int:
        """Estimate token count for input text (fallback 4 chars per token)."""
        return max(1, len(text) // 4)

    def record_usage(self, usage: TokenUsage, latency_s: float) -> None:
        """Track usage statistics across requests."""
        self.request_count += 1
        self.total_prompt_tokens += usage.prompt_tokens
        self.total_completion_tokens += usage.completion_tokens
        self.total_cost_usd += usage.cost_usd
        self.total_latency_s += latency_s

    def get_usage_stats(self) -> dict[str, Any]:
        """Get aggregate usage and performance stats."""
        avg_latency = self.total_latency_s / self.request_count if self.request_count > 0 else 0.0
        return {
            "request_count": self.request_count,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
            "total_cost_usd": self.total_cost_usd,
            "total_latency_s": round(self.total_latency_s, 4),
            "avg_latency_s": round(avg_latency, 4),
        }

    def reset_usage_stats(self) -> None:
        """Reset aggregate usage stats."""
        self.request_count = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_cost_usd = 0.0
        self.total_latency_s = 0.0
