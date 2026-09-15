# -*- coding: utf-8 -*-
"""Model registry for 9Router and multi-provider LLM models."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from src.llm.base import ModelInfo

logger = logging.getLogger(__name__)

# Health states reported by :meth:`ModelRegistry.health`.
STATE_CONNECTED = "CONNECTED"
STATE_DEGRADED = "DEGRADED"
STATE_DISCONNECTED = "DISCONNECTED"


class ModelRegistry:
    """Registry maintaining available models, capabilities, and pricing.

    The registry is seeded with conservative defaults so the system can always
    serve *some* model (fail-safe). When a 9Router gateway is reachable, models
    discovered via ``GET /v1/models`` replace the defaults and become the source
    of truth until the next refresh.
    """

    def __init__(self) -> None:
        self._models: dict[str, ModelInfo] = {}
        self._register_defaults()
        # Discovery bookkeeping.
        self._last_discovery: float | None = None
        self._last_attempt: float | None = None
        self._last_error: str | None = None
        self._last_success: bool = False
        self._source: str = "defaults"

    @property
    def source(self) -> str:
        """Where the currently served models came from ("gateway" or "defaults")."""
        return self._source if self._last_success else "defaults"

    @property
    def last_discovery(self) -> float | None:
        """Timestamp of the last successful discovery, or ``None``."""
        return self._last_discovery

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

    # ------------------------------------------------------------------
    # Dynamic gateway discovery
    # ------------------------------------------------------------------

    def discover_from_gateway(
        self,
        client: Any = None,
        force: bool = False,
        cache_ttl: float = 300.0,
    ) -> list[ModelInfo]:
        """Discover models from a 9Router / OpenAI-compatible gateway.

        Calls the gateway's ``GET /v1/models`` endpoint (via
        ``client.models.list()``) and normalizes every entry into a
        :class:`ModelInfo`, replacing the currently served models on success.

        The result is cached: if a successful discovery happened within
        ``cache_ttl`` seconds the network is not hit again unless ``force`` is
        ``True``. On any failure the previous models are left intact
        (fail-safe) and the error is recorded for :meth:`health`.

        Args:
            client: An OpenAI-compatible client exposing ``models.list()``.
                When ``None`` the client from the default ``NineRouterClient``
                is used.
            force: Bypass the TTL cache and always query the gateway.
            cache_ttl: Seconds a successful discovery stays fresh.

        Returns:
            The list of models currently served by the registry.
        """
        now = time.time()
        if not force and self._last_success and self._last_discovery is not None:
            if (now - self._last_discovery) < cache_ttl:
                return self.list_models()

        self._last_attempt = now
        try:
            entries = self._fetch_gateway_models(client)
            discovered: dict[str, ModelInfo] = {}
            for entry in entries:
                info = self._normalize_model(entry)
                if info is not None:
                    discovered[info.name] = info

            if not discovered:
                raise ValueError("Gateway returned no usable models")

            self._models = discovered
            self._last_discovery = now
            self._last_success = True
            self._last_error = None
            self._source = "gateway"
            logger.info("Discovered %d models from gateway", len(discovered))
        except Exception as exc:  # noqa: BLE001 - fail-safe: never raise
            self._last_success = False
            self._last_error = f"{type(exc).__name__}: {exc}"
            self._source = "defaults"
            logger.warning("Model discovery failed, keeping cached models: %s", exc)

        return self.list_models()

    def _fetch_gateway_models(self, client: Any) -> list[Any]:
        """Return the raw model entries from the gateway client."""
        if client is None:
            # Imported lazily to avoid a circular import at module load time.
            from src.llm.nine_router import NineRouterClient

            client = NineRouterClient().client

        response = client.models.list()
        # OpenAI SDK returns an object with ``.data``; tolerate plain lists.
        if hasattr(response, "data"):
            return list(response.data)
        return list(response)

    def _normalize_model(self, entry: Any) -> Optional[ModelInfo]:
        """Normalize a single gateway model entry into a :class:`ModelInfo`."""
        name = getattr(entry, "id", None)
        if not name and isinstance(entry, dict):
            name = entry.get("id")
        if not name:
            return None
        name = str(name)

        return ModelInfo(
            name=name,
            provider=self._parse_provider(name),
            is_free=":free" in name,
            context_window=self._extract_context_window(entry),
            cost_per_prompt_token=0.0,
            cost_per_completion_token=0.0,
            capabilities=self._extract_capabilities(entry),
        )

    @staticmethod
    def _parse_provider(name: str) -> str:
        """Parse the provider from a model name prefix (``provider/model``)."""
        if "/" in name:
            return name.split("/", 1)[0]
        return "unknown"

    @staticmethod
    def _extract_context_window(entry: Any) -> int:
        """Best-effort context window extraction from an entry (default 8192)."""
        for key in ("context_window", "context_length", "max_context_tokens"):
            if isinstance(entry, dict) and entry.get(key):
                try:
                    return int(entry[key])
                except (TypeError, ValueError):
                    continue
            value = getattr(entry, key, None)
            if value:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    continue
        return 8192

    @staticmethod
    def _extract_capabilities(entry: Any) -> list[str]:
        """Derive capabilities from any capability data the gateway exposes."""
        raw = getattr(entry, "capabilities", None)
        if raw is None and isinstance(entry, dict):
            raw = entry.get("capabilities")
        if isinstance(raw, (list, tuple, set)):
            caps = [str(c) for c in raw]
            return caps or ["chat"]
        return ["chat"]

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        """Report gateway health without ever raising.

        States:
            * ``CONNECTED`` — last discovery succeeded (and is fresh/cached).
            * ``DEGRADED`` — we have cached data but the last attempt failed.
            * ``DISCONNECTED`` — never discovered and the last attempt failed
              (or never attempted).
        """
        state = STATE_DISCONNECTED
        if self._last_success:
            state = STATE_CONNECTED
        elif self._last_error is not None:
            state = STATE_DEGRADED if self._has_gateway_cache() else STATE_DISCONNECTED

        result: dict[str, Any] = {
            "state": state,
            "last_discovery": self._last_discovery,
            "model_count": len(self._models),
            "source": self.source,
        }
        if self._last_error is not None:
            result["error"] = self._last_error
        return result

    def _has_gateway_cache(self) -> bool:
        """True if we previously served models parsed from the gateway."""
        return self._last_discovery is not None
