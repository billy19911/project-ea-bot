# -*- coding: utf-8 -*-
"""Tests for the Telegram read-only command providers (chat commands).

Providers answer ``/status``, ``/positions``, ``/risk``, ``/why`` and
``/review`` from live process state. They must:

* be read-only (no execution/order imports; guard test),
* degrade honestly instead of raising when a subsystem is missing,
* never fabricate data (empty → explicit "no data" payloads).

No real MT5 / network: the runtime and connector are faked via monkeypatch.
"""

from __future__ import annotations

import ast
import inspect

from src.telegram import providers as providers_module
from src.telegram.providers import build_default_providers


# ---------------------------------------------------------------------------
# Shape — every command has a provider
# ---------------------------------------------------------------------------
def test_build_default_providers_exposes_all_commands() -> None:
    providers = build_default_providers()
    for key in (
        "status_provider",
        "positions_provider",
        "risk_provider",
        "decision_trace_provider",
        "review_provider",
    ):
        assert key in providers
        assert callable(providers[key])


# ---------------------------------------------------------------------------
# /status — scheduler stats + MT5 mode
# ---------------------------------------------------------------------------
def test_status_provider_reads_scheduler_stats(monkeypatch) -> None:
    class _Scheduler:
        def stats(self):
            return {"running": True, "queue_size": 3, "events_processed": 7, "trades_blocked": 1}

    class _Runtime:
        scheduler = _Scheduler()

    monkeypatch.setattr(
        "src.orchestration.runtime.get_runtime",
        lambda: _Runtime(),
    )

    out = build_default_providers()["status_provider"]()

    assert out["state"] == "RUNNING"
    assert out["scheduler"]["queue_size"] == 3
    assert out["scheduler"]["events_processed"] == 7
    assert "mt5_live_data" in out


# ---------------------------------------------------------------------------
# /positions — honest empty + rows from connector
# ---------------------------------------------------------------------------
def test_positions_provider_formats_rows(monkeypatch) -> None:
    class _Pos:
        symbol = "EURUSD"
        side = "BUY"
        quantity = 0.1
        price_open = 1.0850
        profit = 12.5

    class _Connector:
        @staticmethod
        def get_positions():
            return [_Pos()]

        @staticmethod
        def is_live_mode():
            return True

    monkeypatch.setattr("src.mt5.connector.get_positions", _Connector.get_positions)
    monkeypatch.setattr("src.mt5.connector.is_live_mode", _Connector.is_live_mode)

    out = build_default_providers()["positions_provider"]()

    assert out["count"] == 1
    assert "EURUSD BUY 0.1" in out["positions"][0]
    assert out["mode"] == "live"


def test_positions_provider_degrades_when_connector_missing(monkeypatch) -> None:
    def _boom():
        raise RuntimeError("no mt5")

    monkeypatch.setattr("src.mt5.connector.get_positions", lambda: _boom())

    out = build_default_providers()["positions_provider"]()

    # Honest empty payload — never raises, never fabricates.
    assert out["positions"] == []
    assert out["count"] == 0


# ---------------------------------------------------------------------------
# /why — structured summary + evidence, never chain-of-thought
# ---------------------------------------------------------------------------
def test_decision_trace_provider_returns_summary_and_evidence(monkeypatch) -> None:
    class _Runtime:
        def recent_decisions(self, limit=1):
            return [
                {
                    "summary": "No trade: spread too wide.",
                    "decision": "NO_TRADE",
                    "trace": [
                        {"stage": "risk", "status": "BLOCKED", "detail": "spread 3.2 pips"},
                    ],
                }
            ]

    monkeypatch.setattr("src.orchestration.runtime.get_runtime", lambda: _Runtime())

    out = build_default_providers()["decision_trace_provider"]()

    assert out["summary"] == "No trade: spread too wide."
    assert out["decision"] == "NO_TRADE"
    assert any("spread 3.2 pips" in item for item in out["evidence"])


def test_decision_trace_provider_is_honest_when_empty(monkeypatch) -> None:
    class _Runtime:
        def recent_decisions(self, limit=1):
            return []

    monkeypatch.setattr("src.orchestration.runtime.get_runtime", lambda: _Runtime())

    out = build_default_providers()["decision_trace_provider"]()

    assert "No decisions" in out["summary"]
    assert out["evidence"] == []


# ---------------------------------------------------------------------------
# /review — latest lesson
# ---------------------------------------------------------------------------
def test_review_provider_returns_latest_lesson(monkeypatch) -> None:
    class _Store:
        def get_lessons(self):
            return [{"outcome": "win", "text": "Keep executing signal-consistent entries."}]

    monkeypatch.setattr(
        "agents.analysts.review_agent.get_lesson_store",
        lambda: _Store(),
    )

    out = build_default_providers()["review_provider"]()

    assert "[win]" in out["summary"]
    assert "signal-consistent" in out["summary"]


def test_review_provider_is_honest_when_empty(monkeypatch) -> None:
    class _Store:
        def get_lessons(self):
            return []

    monkeypatch.setattr(
        "agents.analysts.review_agent.get_lesson_store",
        lambda: _Store(),
    )

    out = build_default_providers()["review_provider"]()

    assert "No lessons" in out["summary"]


# ---------------------------------------------------------------------------
# Safety invariant — no execution / MT5 imports at module level
# ---------------------------------------------------------------------------
def test_providers_module_has_no_execution_imports() -> None:
    source = inspect.getsource(providers_module)
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
    # Lazy imports inside functions are allowed for read-only reads, but no
    # execution/order module may be referenced at all.
    assert not any("execution" in n for n in names)
    assert not any(n.startswith("MetaTrader5") for n in names)
