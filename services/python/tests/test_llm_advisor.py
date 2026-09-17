# -*- coding: utf-8 -*-
"""Tests for the guardrailed LLM advisor (UI/UX ide #1).

Guardrail honesty rules pinned here:

* default OFF — no client is built, no tokens are spent;
* budget gate commits through the REAL supervisor and refuses when exhausted;
* missing real market data refuses BEFORE any budget commit;
* roles outside market/risk/research are refused;
* caps (max_tokens/timeout) are passed to the client;
* a client fallback (rule-based mock) is flagged, not hidden;
* usage aggregates are real values from the client.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.llm.advisor import MAX_TOKENS, LLMAdvisor  # noqa: E402
from src.llm.base import LLMResponse, TokenUsage  # noqa: E402


class FakeClient:
    """Stand-in for NineRouterClient with controllable behaviour."""

    def __init__(self, content: str = "BULLISH 0.7", is_fallback: bool = False) -> None:
        self.content = content
        self.is_fallback = is_fallback
        self.calls: list[dict] = []

    def generate(self, prompt, system_prompt=None, **kwargs):  # noqa: ANN001
        self.calls.append({"prompt": prompt, "system_prompt": system_prompt, **kwargs})
        usage = TokenUsage(prompt_tokens=40, completion_tokens=20, total_tokens=60, cost_usd=0.0)
        return LLMResponse(
            content=self.content,
            model="fake-model",
            usage=usage,
            latency_s=0.12,
            is_fallback=self.is_fallback,
        )

    def get_usage_stats(self):
        return {"request_count": len(self.calls), "total_tokens": 60 * len(self.calls)}


class FakeSupervisor:
    """Stand-in for SupervisorAgent budget accounting."""

    def __init__(self, token_budget: int = 8000) -> None:
        self.token_budget = token_budget
        self.token_used = 0
        self.commits: list[tuple[str, int]] = []

    def check_token_budget(self, agent_name: str, estimate: int = 0) -> bool:
        self.commits.append((agent_name, estimate))
        if self.token_used + estimate > self.token_budget:
            return False
        self.token_used += estimate
        return True


class FakeStore:
    """Minimal settings store: only the opt-in knob matters here."""

    def __init__(self, enabled: bool = False) -> None:
        self.values = {"llm_advisor_enabled": 1.0 if enabled else 0.0}

    def snapshot(self):  # noqa: ANN001
        class Snap:
            values = self.values

        return Snap()


def _patch_store(monkeypatch, enabled: bool) -> None:
    import src.system.settings_store as store_mod

    monkeypatch.setattr(store_mod, "get_settings_store", lambda: FakeStore(enabled))


def _advisor(monkeypatch, enabled: bool, client=None, supervisor=None) -> LLMAdvisor:
    _patch_store(monkeypatch, enabled)
    return LLMAdvisor(
        client=client if client is not None else FakeClient(),
        supervisor=supervisor if supervisor is not None else FakeSupervisor(),
    )


MARKET = {"symbol": "XAUUSD", "timeframe": "H1", "bid": 4300.0, "ask": 4300.3}


def test_disabled_by_default_spends_nothing(monkeypatch):
    client = FakeClient()
    advisor = _advisor(monkeypatch, enabled=False, client=client)
    result = advisor.advise("market", MARKET)
    assert result.ok is False
    assert "nonaktif" in result.reason
    assert client.calls == []  # no request was made
    assert result.guardrails["enabled"] is False


def test_enabled_call_succeeds_with_real_usage(monkeypatch):
    client = FakeClient(content="BULLISH 0.7")
    supervisor = FakeSupervisor()
    advisor = _advisor(monkeypatch, enabled=True, client=client, supervisor=supervisor)

    result = advisor.advise("market", MARKET)

    assert result.ok is True
    assert result.content == "BULLISH 0.7"
    assert result.total_tokens == 60
    assert result.model == "fake-model"
    assert result.is_fallback is False
    # Budget was committed through the real supervisor path.
    assert supervisor.commits and supervisor.commits[0][0] == "llm_advisor"
    assert result.guardrails == {
        "enabled": True,
        "budget_ok": True,
        "data_ok": True,
        "max_tokens": MAX_TOKENS,
        "timeout_s": 30.0,
        "estimate_tokens": 1200,
    }
    # Hard caps reach the client call.
    assert client.calls[0]["max_tokens"] == MAX_TOKENS


def test_budget_exhaustion_refuses_before_any_call(monkeypatch):
    client = FakeClient()
    supervisor = FakeSupervisor(token_budget=100)  # far below the estimate
    advisor = _advisor(monkeypatch, enabled=True, client=client, supervisor=supervisor)

    result = advisor.advise("market", MARKET)

    assert result.ok is False
    assert "Budget token" in result.reason
    assert client.calls == []
    assert result.guardrails["budget_ok"] is False


def test_missing_data_refuses_before_budget_commit(monkeypatch):
    client = FakeClient()
    supervisor = FakeSupervisor()
    advisor = _advisor(monkeypatch, enabled=True, client=client, supervisor=supervisor)

    result = advisor.advise("market", {})

    assert result.ok is False
    assert "data pasar" in result.reason
    assert client.calls == []
    assert supervisor.commits == []  # nothing was committed


def test_disallowed_role_refused(monkeypatch):
    client = FakeClient()
    advisor = _advisor(monkeypatch, enabled=True, client=client)
    result = advisor.advise("execution", MARKET)
    assert result.ok is False
    assert "tidak diizinkan" in result.reason
    assert client.calls == []


def test_client_fallback_is_flagged_not_hidden(monkeypatch):
    client = FakeClient(content="[Rule-Based Mock Response]", is_fallback=True)
    advisor = _advisor(monkeypatch, enabled=True, client=client)
    result = advisor.advise("risk", MARKET)
    assert result.ok is True
    assert result.is_fallback is True  # UI can say it did not come from a model


def test_client_exception_returns_honest_failure(monkeypatch):
    class BoomClient(FakeClient):
        def generate(self, *a, **k):  # noqa: ANN002, ANN003
            raise RuntimeError("gateway down")

    advisor = _advisor(monkeypatch, enabled=True, client=BoomClient())
    result = advisor.advise("market", MARKET)
    assert result.ok is False
    assert "gateway down" in result.reason


def test_status_reports_real_usage_and_budget(monkeypatch):
    client = FakeClient()
    supervisor = FakeSupervisor()
    advisor = _advisor(monkeypatch, enabled=True, client=client, supervisor=supervisor)
    advisor.advise("market", MARKET)

    status = advisor.status()

    assert status["enabled"] is True
    assert status["calls"] == 1
    assert status["usage"]["request_count"] == 1
    assert status["budget"]["token_budget"] == 8000
    assert status["budget"]["token_used"] == 1200  # the real committed estimate
    assert status["limits"]["max_tokens"] == MAX_TOKENS


def test_supervisor_unavailable_is_fail_closed(monkeypatch):
    _patch_store(monkeypatch, True)
    advisor = LLMAdvisor(client=FakeClient(), supervisor=None)
    # Force the "no runtime" path deterministically.
    monkeypatch.setattr(advisor, "_ensure_supervisor", lambda: None)
    result = advisor.advise("market", MARKET)
    assert result.ok is False
    assert "Supervisor tidak tersedia" in result.reason


# -- model selection honesty ------------------------------------------------


def test_model_pick_prefers_verified_free_model(monkeypatch):
    """The live gateway list wins; only a verified free model is picked."""
    advisor = LLMAdvisor()
    monkeypatch.setattr(
        advisor,
        "_fetch_live_model_names",
        lambda: ["some-paid-model", "codebuddy-deepseekv4.1flashfree", "other-free"],
    )
    assert advisor._pick_free_model() == "codebuddy-deepseekv4.1flashfree"


def test_model_pick_falls_back_to_any_live_free_name(monkeypatch):
    """With no verified name present, any live *free* model is acceptable."""
    advisor = LLMAdvisor()
    monkeypatch.setattr(
        advisor, "_fetch_live_model_names", lambda: ["paid-model", "brand-new-free"]
    )
    assert advisor._pick_free_model() == "brand-new-free"


def test_model_pick_never_silently_picks_paid_from_live_list(monkeypatch):
    """When the live list has no free entry, the registry path is used —
    and it is also constrained to free models."""
    advisor = LLMAdvisor()
    monkeypatch.setattr(advisor, "_fetch_live_model_names", lambda: ["paid-only"])

    class FakeRegistry:
        def discover_from_gateway(self, force=False):  # noqa: ANN001
            return []

        def list_models(self, free_only=False):  # noqa: ANN001
            assert free_only is True, "registry must be queried free-only"

            class M:
                name = "registry-free"

            return [M()]

        def get_default_model(self, free_only=False):  # noqa: ANN001
            return "registry-free"

    monkeypatch.setattr("src.llm.registry.ModelRegistry", FakeRegistry)
    assert advisor._pick_free_model() == "registry-free"


def test_live_model_fetch_failure_degrades_to_registry(monkeypatch):
    """A dead gateway must not crash model selection."""
    advisor = LLMAdvisor()
    monkeypatch.setattr(advisor, "_fetch_live_model_names", lambda: [])

    class FakeRegistry:
        def discover_from_gateway(self, force=False):  # noqa: ANN001
            return []

        def list_models(self, free_only=False):  # noqa: ANN001
            class M:
                name = "cached-free"

            return [M()]

        def get_default_model(self, free_only=False):  # noqa: ANN001
            return "cached-free"

    monkeypatch.setattr("src.llm.registry.ModelRegistry", FakeRegistry)
    assert advisor._pick_free_model() == "cached-free"
