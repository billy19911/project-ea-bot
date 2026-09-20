# -*- coding: utf-8 -*-
"""Tests for Telegram Autonomous Control Center (Phase 48)."""

from src.telegram.control_center import COMMANDS, ControlCenter, format_status_panel


def _center(**providers) -> ControlCenter:
    return ControlCenter(providers=providers, allowlist={"42"})


def test_command_list_matches_prd() -> None:
    for cmd in (
        "/status",
        "/market",
        "/positions",
        "/orders",
        "/risk",
        "/trades",
        "/performance",
        "/learning",
        "/strategy",
        "/agents",
        "/health",
        "/reconcile",
        "/why",
        "/replay",
    ):
        assert cmd in COMMANDS


def test_unauthorized_refused() -> None:
    center = _center()
    assert center.handle("999", "/status").startswith("⛔")


def test_status_panel_format() -> None:
    status = {
        "system_health": "HEALTHY",
        "mt5": "CONNECTED",
        "risk": "NORMAL",
        "reconciliation": "MATCH",
        "strategy": "v12 PRODUCTION",
        "open_positions": 1,
        "daily_pnl": "+$18.40",
        "new_trades": "ENABLED",
    }
    panel = format_status_panel(status)
    assert "SYSTEM" in panel
    assert "HEALTHY" in panel
    assert "v12 PRODUCTION" in panel
    assert "ENABLED" in panel


def test_status_panel_degrades_gracefully() -> None:
    panel = format_status_panel({})
    assert "UNKNOWN" in panel


def test_status_command() -> None:
    center = _center(status=lambda: {"system_health": "HEALTHY", "mt5": "CONNECTED"})
    reply = center.handle("42", "/status")
    assert "HEALTHY" in reply


def test_generic_command_render() -> None:
    center = _center(market=lambda: {"symbol": "EURUSD", "bid": 1.085})
    reply = center.handle("42", "/market")
    assert "MARKET" in reply
    assert "EURUSD" in reply


def test_why_has_no_chain_of_thought() -> None:
    center = _center(
        why=lambda: {
            "signal": "long",
            "market_state": "trend",
            "agent_conclusions": "trend+",
            "risk_checks": "passed",
            "decision": "trade",
            "reason": "breakout confirmed",
            "chain_of_thought": "SECRET INTERNAL REASONING",
        }
    )
    reply = center.handle("42", "/why")
    assert "signal" in reply.lower()
    # Private chain-of-thought must never be surfaced.
    assert "SECRET" not in reply


def test_replay_command_found() -> None:
    center = ControlCenter(
        providers={},
        allowlist={"42"},
        replay_fn=lambda did: {
            "decision_id": did,
            "steps": [{"stage": "EVENT", "payload": {"x": 1}}],
        },
    )
    reply = center.handle("42", "/replay D182")
    assert "Replay D182" in reply
    assert "EVENT" in reply


def test_replay_command_not_found() -> None:
    center = ControlCenter(providers={}, allowlist={"42"}, replay_fn=lambda did: None)
    reply = center.handle("42", "/replay NOPE")
    assert "not found" in reply.lower()


def test_replay_requires_argument() -> None:
    center = ControlCenter(providers={}, allowlist={"42"}, replay_fn=lambda did: {})
    reply = center.handle("42", "/replay")
    assert "Usage" in reply


def test_help_lists_commands() -> None:
    center = _center()
    reply = center.handle("42", "/help")
    assert "/status" in reply


def test_provider_error_is_graceful() -> None:
    def boom() -> dict:
        raise RuntimeError("boom")

    center = _center(market=boom)
    reply = center.handle("42", "/market")
    assert "error" in reply.lower()
