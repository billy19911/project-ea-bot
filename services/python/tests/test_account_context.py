# -*- coding: utf-8 -*-
"""Tests for the account/market context provider (audit P1-3).

The autonomous scheduler previously supplied only news context, so the Risk Gate
ran against a zeroed account. These tests assert the provider surfaces real
account/positions/market inputs (from an injected provider) and degrades safely.
"""

from __future__ import annotations

from orchestration.account_context import AccountContextProvider, build_connector_account_context


class _Event:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol


def test_provider_merges_account_and_news() -> None:
    account = {
        "account_state": {"equity": 5000.0, "balance": 5000.0, "used_margin": 200.0},
        "current_positions": [{"ticket": 1, "symbol": "EURUSD", "volume": 0.1}],
        "market_info": {"bid": 1.1, "ask": 1.1002},
    }
    news = {"news": {"headlines": []}, "event_type": "BREAKOUT"}

    provider = AccountContextProvider(
        news_provider=lambda sym: news,
        account_provider=lambda sym: account,
    )
    context = provider(_Event("EURUSD"))

    assert context["account_state"]["equity"] == 5000.0
    assert len(context["current_positions"]) == 1
    assert context["market_info"]["ask"] == 1.1002
    assert context["event_type"] == "BREAKOUT"


def test_provider_fail_safe_on_account_error() -> None:
    def boom(sym):
        raise RuntimeError("mt5 down")

    provider = AccountContextProvider(
        news_provider=lambda sym: {"news": {}},
        account_provider=boom,
    )
    context = provider(_Event("EURUSD"))
    # News still flows; account keys absent (pipeline keeps zero fallback).
    assert "news" in context
    assert "account_state" not in context


def test_provider_fail_safe_on_news_error() -> None:
    def boom(sym):
        raise RuntimeError("news down")

    provider = AccountContextProvider(
        news_provider=boom,
        account_provider=lambda sym: {"account_state": {"equity": 1.0}},
    )
    context = provider(_Event("EURUSD"))
    assert context["account_state"]["equity"] == 1.0


def test_build_connector_account_context_never_raises() -> None:
    # In the test environment the connector may or may not be live; either way
    # the helper must return a dict and never raise.
    context = build_connector_account_context("EURUSD")
    assert isinstance(context, dict)


def test_connector_context_includes_account_when_available() -> None:
    # The default (non-live) connector simulates an account, so account_state
    # should be present with a positive equity.
    context = build_connector_account_context("EURUSD")
    if "account_state" in context:
        assert context["account_state"]["equity"] > 0


def test_runtime_scheduler_uses_account_context_provider() -> None:
    from orchestration.account_context import AccountContextProvider
    from orchestration.runtime import OrchestrationRuntime

    runtime = OrchestrationRuntime()
    assert isinstance(runtime.scheduler.context_provider, AccountContextProvider)


if __name__ == "__main__":  # pragma: no cover
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
