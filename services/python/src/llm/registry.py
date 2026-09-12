# -*- coding: utf-8 -*-
"""Model registry for 9Router and multi-provider LLM models."""

from __future__ import annotations

from typing import Optional

from src.llm.base import ModelInfo


class ModelRegistry:
    """Registry maintaining available models, capabilities, and pricing."""

    def __init__(self) -> None:
        self._models: dict[str, ModelInfo] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register default free and standard models."""
        defaults = [
            ModelInfo(
                name="google/gemini-2.0-flash-lite:free",
                provider="google",
                is_free=True,
                context_window=1048576,
                cost_per_prompt_token=0.0,
                cost_per_completion_token=0.0,
                capabilities=["chat", "streaming", "fast"],
            ),
            ModelInfo(
                name="deepseek/deepseek-r1:free",
                provider="deepseek",
                is_free=True,
                context_window=65536,
                cost_per_prompt_token=0.0,
                cost_per_completion_token=0.0,
                capabilities=["chat", "streaming", "reasoning"],
            ),
            ModelInfo(
                name="meta-llama/llama-3.3-70b-instruct:free",
                provider="meta",
                is_free=True,
                context_window=131072,
                cost_per_prompt_token=0.0,
                cost_per_completion_token=0.0,
                capabilities=["chat", "streaming"],
            ),
            ModelInfo(
                name="qwen/qwen-2.5-72b-instruct:free",
                provider="qwen",
                is_free=True,
                context_window=32768,
                cost_per_prompt_token=0.0,
                cost_per_completion_token=0.0,
                capabilities=["chat", "streaming"],
            ),
            ModelInfo(
                name="openai/gpt-4o-mini",
                provider="openai",
                is_free=False,
                context_window=128000,
                cost_per_prompt_token=0.15 / 1_000_000,
                cost_per_completion_token=0.60 / 1_000_000,
                capabilities=["chat", "streaming", "vision"],
            ),
            ModelInfo(
                name="anthropic/claude-3-5-sonnet",
                provider="anthropic",
                is_free=False,
                context_window=200000,
                cost_per_prompt_token=3.0 / 1_000_000,
                cost_per_completion_token=15.0 / 1_000_000,
                capabilities=["chat", "streaming", "vision", "reasoning"],
            ),
        ]
        for model in defaults:
            self.register(model)

    def register(self, model_info: ModelInfo) -> None:
        """Register a new or override existing model."""
        self._models[model_info.name] = model_info

    def get(self, name: str) -> Optional[ModelInfo]:
        """Get model details by name."""
        return self._models.get(name)

    def list_models(self, free_only: bool = False) -> list[ModelInfo]:
        """List registered models, optionally filtering by free tier."""
        if free_only:
            return [m for m in self._models.values() if m.is_free]
        return list(self._models.values())

    def get_default_model(self, free_only: bool = True) -> str:
        """Return the default recommended model name."""
        if free_only:
            return "google/gemini-2.0-flash-lite:free"
        return "openai/gpt-4o-mini"

    def calculate_cost(self, model_name: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate estimated cost in USD for token usage."""
        model = self.get(model_name)
        if not model or model.is_free:
            return 0.0
        prompt_cost = prompt_tokens * model.cost_per_prompt_token
        completion_cost = completion_tokens * model.cost_per_completion_token
        return prompt_cost + completion_cost
