# -*- coding: utf-8 -*-
"""LLM Advisor (UI/UX ide #1) — advisory-only 9Router integration.

The project already ships a complete LLM stack (``NineRouterClient`` with
retry/fallback/cost tracking, ``ModelRouter`` with deterministic routing) but
nothing consumed it. This module wires it as an **advisor**, deliberately
outside the trading path:

    Market context -> guardrails -> LLM -> advisory text + usage

Honesty rules (the reason this module exists in this shape):

* The advisor NEVER touches orders, the risk gate, or the pipeline. Its output
  is text for a human; nothing consumes it automatically.
* Guardrails are fail-closed and evaluated in order, cheapest first:
    1. ``llm_advisor_enabled`` runtime knob — default OFF, so no tokens are
       ever spent until an operator opts in;
    2. token budget — commits the estimate through the REAL
       ``SupervisorAgent.check_token_budget`` (the same budget the settings
       page edits), refusing when it would be exceeded;
    3. data availability — the prompt is built from REAL market data; with no
       data there is nothing to analyse and the call is refused;
    4. hard caps — ``max_tokens`` and a timeout on the request itself.
* Every call records model, tokens, cost and latency. ``usage`` reports real
  aggregates from the client, never placeholders.

If the client falls back to its rule-based mock (upstream down), the response
is flagged ``is_fallback`` so the UI can say the text did not come from a model.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["AdvisorResult", "LLMAdvisor", "get_llm_advisor", "reset_llm_advisor"]

# Hard caps for every advisor call — the client is never allowed to run away.
MAX_TOKENS = 512
REQUEST_TIMEOUT_S = 30.0
# Rough estimate committed to the supervisor budget before a call.
DEFAULT_ESTIMATE_TOKENS = 1200
# Only these roles may be analysed; anything else is a programming error.
_ALLOWED_ROLES = ("market", "risk", "research")
# Free models verified working through the local 9Router gateway with this
# project's key. Most other `*free` endpoints are restricted to the OpenCode
# client, so these are preferred (and used as the fallback chain).
_PREFERRED_FREE_MODELS = ("codebuddy-deepseekv4.1flashfree", "codebuddy-free")


@dataclass
class AdvisorResult:
    """Outcome of one advisor call (never raises to the caller)."""

    ok: bool
    reason: str = ""
    content: str = ""
    model: str = ""
    is_fallback: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    guardrails: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for the API layer."""
        return {
            "ok": self.ok,
            "reason": self.reason,
            "content": self.content,
            "model": self.model,
            "is_fallback": self.is_fallback,
            "usage": {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
                "cost_usd": self.cost_usd,
                "latency_s": self.latency_s,
            },
            "guardrails": self.guardrails,
        }


class LLMAdvisor:
    """Guardrailed, advisory-only LLM access.

    The client is injected so tests can supply a mock; production constructs a
    ``NineRouterClient`` pointed at the configured 9Router gateway.
    """

    def __init__(self, client: Any = None, supervisor: Any = None) -> None:
        self._client = client
        self._supervisor = supervisor
        self._lock = threading.Lock()
        self._calls = 0
        self._refusals = 0

    # -- wiring helpers -----------------------------------------------------

    def _fetch_live_model_names(self) -> list[str]:
        """Ask the gateway for its live model list (read-only; no tokens).

        The registry cache can name models the gateway no longer serves, so
        the advisor asks the gateway directly before choosing one.
        """
        import json
        import urllib.request

        base = (os.getenv("NINE_ROUTER_BASE_URL") or "").rstrip("/")
        if not base:
            return []
        key = os.getenv("NINE_ROUTER_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        req = urllib.request.Request(base + "/models", headers={"Authorization": "Bearer " + key})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # discovery must never break the advisor
            logger.warning("advisor: daftar model live gagal: %s", exc)
            return []
        entries = payload.get("data") if isinstance(payload, dict) else payload
        names: list[str] = []
        for entry in entries or []:
            name = entry.get("id") or entry.get("name") if isinstance(entry, dict) else entry
            if name:
                names.append(str(name))
        return names

    def _pick_free_model(self) -> str:
        """Choose a REAL free model that works on the LIVE gateway.

        Preference order: verified free models, then any live ``*free`` model,
        then the registry defaults (free-named only — a paid model is never
        picked silently).
        """
        live = self._fetch_live_model_names()
        for name in _PREFERRED_FREE_MODELS:
            if name in live:
                return name
        for name in live:
            if "free" in name.lower():
                return name

        from .registry import ModelRegistry

        registry = ModelRegistry()
        try:
            registry.discover_from_gateway(force=False)
        except Exception as exc:  # discovery must never break the advisor
            logger.warning("advisor: discovery model gagal: %s", exc)
        for model in registry.list_models(free_only=True):
            if model.name:
                return model.name
        return registry.get_default_model(free_only=True)

    def _ensure_client(self) -> Any:
        """Lazily build the real 9Router client (imports stay off the hot path)."""
        if self._client is None:
            from .nine_router import NineRouterClient

            primary = self._pick_free_model()
            self._client = NineRouterClient(
                default_model=primary,
                timeout=REQUEST_TIMEOUT_S,
                max_retries=1,
                fallback_models=[m for m in _PREFERRED_FREE_MODELS if m != primary],
            )
        return self._client

    def _ensure_supervisor(self) -> Any:
        """Reach the live supervisor through the orchestration runtime."""
        if self._supervisor is None:
            try:
                from ..orchestration.runtime import get_runtime

                self._supervisor = getattr(get_runtime().pipeline, "supervisor", None)
            except Exception:  # runtime not built yet — budget check unavailable
                self._supervisor = None
        return self._supervisor

    # -- guardrails ----------------------------------------------------------

    def _enabled(self) -> bool:
        """Read the opt-in knob from the REAL settings store."""
        from ..system.settings_store import get_settings_store

        return bool(get_settings_store().snapshot().values.get("llm_advisor_enabled", 0.0))

    def _commit_budget(self, estimate: int) -> tuple[bool, str]:
        """Commit ``estimate`` tokens through the supervisor budget.

        Returns ``(allowed, reason)``. When the supervisor is unavailable the
        check refuses — fail-closed, never silently unbounded.
        """
        supervisor = self._ensure_supervisor()
        if supervisor is None:
            return False, "Supervisor tidak tersedia — pemeriksaan budget tidak dapat dilakukan."
        try:
            allowed = bool(supervisor.check_token_budget("llm_advisor", estimate))
        except Exception as exc:  # a broken supervisor must not open the gate
            logger.warning("advisor: budget check gagal: %s", exc)
            return False, f"Pemeriksaan budget gagal: {exc}"
        if not allowed:
            return False, (
                "Budget token supervisor terlampaui — naikkan batas di Pengaturan "
                "atau reset siklus supervisor."
            )
        return True, ""

    def _build_prompt(self, role: str, market: dict[str, Any]) -> str:
        """Build a compact, deterministic prompt from REAL market fields."""
        lines = [
            "Anda penasihat analisis trading. Jawab SINGKAT dalam bahasa Indonesia.",
            "Ini analisis pendamping untuk manusia — bukan perintah eksekusi.",
            f"Peran: {role}",
            "Data pasar nyata (read-only):",
        ]
        for key in ("symbol", "timeframe", "bid", "ask", "spread_pips", "trend", "note"):
            value = market.get(key)
            if value is not None:
                lines.append(f"- {key}: {value}")
        lines.append("Berikan: arah (BULLISH/BEARISH/NEUTRAL), keyakinan 0-1, 2 alasan singkat.")
        return "\n".join(lines)

    # -- main entry point ----------------------------------------------------

    def advise(self, role: str, market: dict[str, Any]) -> AdvisorResult:
        """Run one guardrailed advisor call. Never raises.

        Args:
            role: One of ``market``/``risk``/``research`` (anything else is
                refused — the advisor has no business elsewhere).
            market: Real market context fields to analyse.
        """
        guardrails: dict[str, Any] = {
            "enabled": False,
            "budget_ok": False,
            "data_ok": False,
            "max_tokens": MAX_TOKENS,
            "timeout_s": REQUEST_TIMEOUT_S,
        }

        if role not in _ALLOWED_ROLES:
            self._refusals += 1
            return AdvisorResult(
                ok=False,
                reason=f"Peran tidak diizinkan: {role!r} (hanya {', '.join(_ALLOWED_ROLES)}).",
                guardrails=guardrails,
            )

        # G1 — opt-in (cheapest gate first: no client construction, no tokens)
        if not self._enabled():
            self._refusals += 1
            return AdvisorResult(
                ok=False,
                reason=(
                    "Penasihat LLM nonaktif. Aktifkan 'llm_advisor_enabled' di "
                    "Pengaturan sebelum memakai token."
                ),
                guardrails=guardrails,
            )
        guardrails["enabled"] = True

        # G3 — data availability (before spending a budget commit)
        if not market:
            self._refusals += 1
            return AdvisorResult(
                ok=False,
                reason="Tidak ada data pasar nyata untuk dianalisis.",
                guardrails=guardrails,
            )
        guardrails["data_ok"] = True

        # G2 — token budget through the real supervisor
        allowed, reason = self._commit_budget(DEFAULT_ESTIMATE_TOKENS)
        if not allowed:
            self._refusals += 1
            return AdvisorResult(ok=False, reason=reason, guardrails=guardrails)
        guardrails["budget_ok"] = True
        guardrails["estimate_tokens"] = DEFAULT_ESTIMATE_TOKENS

        # G4 — the call itself, with hard caps
        prompt = self._build_prompt(role, market)
        try:
            client = self._ensure_client()
            response = client.generate(
                prompt,
                system_prompt=(
                    "Anda asisten analisis. Keluaran Anda bersifat saran untuk "
                    "manusia; Anda tidak dapat mengeksekusi order."
                ),
                max_tokens=MAX_TOKENS,
            )
        except Exception as exc:
            logger.warning("advisor: panggilan LLM gagal: %s", exc)
            self._refusals += 1
            return AdvisorResult(
                ok=False,
                reason=f"Panggilan LLM gagal: {exc}",
                guardrails=guardrails,
            )

        with self._lock:
            self._calls += 1

        usage = getattr(response, "usage", None)
        return AdvisorResult(
            ok=True,
            content=str(getattr(response, "content", "")),
            model=str(getattr(response, "model", "")),
            is_fallback=bool(getattr(response, "is_fallback", False)),
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
            cost_usd=float(getattr(usage, "cost_usd", 0.0) or 0.0),
            latency_s=float(getattr(response, "latency_s", 0.0) or 0.0),
            guardrails=guardrails,
        )

    def status(self) -> dict[str, Any]:
        """Report advisor state + real usage aggregates for the UI."""
        client = self._client
        usage: dict[str, Any] = {}
        if client is not None and hasattr(client, "get_usage_stats"):
            try:
                usage = dict(client.get_usage_stats())
            except Exception:
                usage = {}
        supervisor = self._ensure_supervisor()
        budget: dict[str, Any] = {"available": supervisor is not None}
        if supervisor is not None:
            budget.update(
                {
                    "token_budget": int(getattr(supervisor, "token_budget", 0) or 0),
                    "token_used": int(getattr(supervisor, "token_used", 0) or 0),
                }
            )
        return {
            "enabled": self._enabled(),
            "calls": self._calls,
            "refusals": self._refusals,
            "limits": {"max_tokens": MAX_TOKENS, "timeout_s": REQUEST_TIMEOUT_S},
            "usage": usage,
            "budget": budget,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }


_ADVISOR: Optional[LLMAdvisor] = None
_ADVISOR_LOCK = threading.Lock()


def get_llm_advisor() -> LLMAdvisor:
    """Return the process-wide advisor (created on first use)."""
    global _ADVISOR
    with _ADVISOR_LOCK:
        if _ADVISOR is None:
            _ADVISOR = LLMAdvisor()
        return _ADVISOR


def reset_llm_advisor() -> None:
    """Drop the singleton (tests + explicit operator reset)."""
    global _ADVISOR
    with _ADVISOR_LOCK:
        _ADVISOR = None
