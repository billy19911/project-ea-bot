# -*- coding: utf-8 -*-
"""9Router LLM adapter with fallback, retry, and usage tracking."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Iterator

from openai import OpenAI

from src.llm.base import BaseLLMProvider, LLMResponse, TokenUsage
from src.llm.registry import ModelRegistry

logger = logging.getLogger(__name__)


class NineRouterClient(BaseLLMProvider):
    """9Router LLM client with multi-model fallback and retry support."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str = "google/gemini-2.0-flash-lite:free",
        fallback_models: list[str] | None = None,
        timeout: float = 30.0,
        max_retries: int = 2,
        backoff_factor: float = 2.0,
        initial_retry_delay: float = 0.5,
        registry: ModelRegistry | None = None,
        client: Any = None,
    ) -> None:
        super().__init__()
        self.api_key = (
            api_key or os.getenv("NINE_ROUTER_API_KEY") or os.getenv("OPENAI_API_KEY") or "mock-key"
        )
        self.base_url = (
            base_url or os.getenv("NINE_ROUTER_BASE_URL") or "https://api.9router.com/v1"
        )
        self.default_model = default_model
        self.fallback_models = (
            fallback_models if fallback_models is not None else ["deepseek/deepseek-r1:free"]
        )
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.initial_retry_delay = initial_retry_delay
        self.registry = registry or ModelRegistry()

        if client is not None:
            self.client = client
        else:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
            )

    def _prepare_messages(
        self,
        prompt: str | list[dict[str, str]],
        system_prompt: str | None = None,
    ) -> list[dict[str, str]]:
        """Normalize prompts into OpenAI-style message format."""
        if isinstance(prompt, str):
            messages: list[dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            return messages

        messages = [dict(m) for m in prompt]
        if system_prompt and not any(m.get("role") == "system" for m in messages):
            messages.insert(0, {"role": "system", "content": system_prompt})
        return messages

    def generate(
        self,
        prompt: str | list[dict[str, str]],
        model: str | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate response with exponential backoff retry and fallback chains."""
        primary_model = model or self.default_model
        models_to_try = [primary_model] + [m for m in self.fallback_models if m != primary_model]
        messages = self._prepare_messages(prompt, system_prompt)

        last_error: Exception | None = None
        for current_model in models_to_try:
            delay = self.initial_retry_delay
            for attempt in range(self.max_retries + 1):
                start_time = time.perf_counter()
                try:
                    resp = self.client.chat.completions.create(
                        model=current_model,
                        messages=messages,
                        **kwargs,
                    )
                    latency = time.perf_counter() - start_time

                    content = ""
                    if resp.choices and len(resp.choices) > 0:
                        content = resp.choices[0].message.content or ""

                    prompt_tokens = (
                        resp.usage.prompt_tokens
                        if resp.usage and resp.usage.prompt_tokens is not None
                        else self.count_tokens(str(messages))
                    )
                    completion_tokens = (
                        resp.usage.completion_tokens
                        if resp.usage and resp.usage.completion_tokens is not None
                        else self.count_tokens(content)
                    )
                    total_tokens = (
                        resp.usage.total_tokens
                        if resp.usage and resp.usage.total_tokens is not None
                        else prompt_tokens + completion_tokens
                    )

                    cost = self.registry.calculate_cost(
                        current_model, prompt_tokens, completion_tokens
                    )
                    usage = TokenUsage(
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        cost_usd=cost,
                    )
                    self.record_usage(usage, latency)

                    return LLMResponse(
                        content=content,
                        model=current_model,
                        usage=usage,
                        raw=resp.model_dump() if hasattr(resp, "model_dump") else {},
                        latency_s=round(latency, 4),
                        is_fallback=(current_model != primary_model),
                    )
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "Model %s attempt %d/%d failed: %s",
                        current_model,
                        attempt + 1,
                        self.max_retries + 1,
                        exc,
                    )
                    if attempt < self.max_retries:
                        time.sleep(delay)
                        delay *= self.backoff_factor

        logger.error("All models failed. Falling back to rule-based mock: %s", last_error)
        return self._rule_based_fallback(prompt, system_prompt, str(last_error))

    def stream(
        self,
        prompt: str | list[dict[str, str]],
        model: str | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> Iterator[str]:
        """Stream completion tokens with model fallback."""
        primary_model = model or self.default_model
        models_to_try = [primary_model] + [m for m in self.fallback_models if m != primary_model]
        messages = self._prepare_messages(prompt, system_prompt)

        for current_model in models_to_try:
            try:
                stream_resp = self.client.chat.completions.create(
                    model=current_model,
                    messages=messages,
                    stream=True,
                    **kwargs,
                )
                accumulated_text = []
                start_time = time.perf_counter()
                for chunk in stream_resp:
                    if chunk.choices and len(chunk.choices) > 0:
                        delta = chunk.choices[0].delta
                        content = getattr(delta, "content", None)
                        if content:
                            accumulated_text.append(content)
                            yield content

                latency = time.perf_counter() - start_time
                full_text = "".join(accumulated_text)
                prompt_tokens = self.count_tokens(str(messages))
                completion_tokens = self.count_tokens(full_text)
                total_tokens = prompt_tokens + completion_tokens
                cost = self.registry.calculate_cost(current_model, prompt_tokens, completion_tokens)
                usage = TokenUsage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    cost_usd=cost,
                )
                self.record_usage(usage, latency)
                return
            except Exception as exc:
                logger.warning("Stream failed on %s: %s", current_model, exc)

        fallback_resp = self._rule_based_fallback(prompt, system_prompt, "Streaming failure")
        yield fallback_resp.content

    def _rule_based_fallback(
        self,
        prompt: str | list[dict[str, str]],
        system_prompt: str | None = None,
        reason: str = "",
    ) -> LLMResponse:
        """Rule-based heuristic mock response when LLM providers fail."""
        prompt_text = str(prompt).lower()
        signal = "NEUTRAL"
        confidence = 0.5
        details = "Rule-based heuristic applied due to upstream LLM downtime."

        if "buy" in prompt_text or "bullish" in prompt_text:
            signal = "BULLISH"
            confidence = 0.6
        elif "sell" in prompt_text or "bearish" in prompt_text:
            signal = "BEARISH"
            confidence = 0.6

        content = (
            f"[Rule-Based Mock Response]\n"
            f"Signal: {signal}\n"
            f"Confidence: {confidence:.2f}\n"
            f"Reasoning: {details}\n"
            f"Fallback Reason: {reason or 'Upstream provider failure'}"
        )

        prompt_tokens = self.count_tokens(str(prompt))
        completion_tokens = self.count_tokens(content)
        usage = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost_usd=0.0,
        )
        self.record_usage(usage, 0.001)

        return LLMResponse(
            content=content,
            model="rule-based-mock",
            usage=usage,
            latency_s=0.001,
            is_fallback=True,
        )
