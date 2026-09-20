# -*- coding: utf-8 -*-
"""Telegram Autonomous Control Center — PRD_V2 §48.

Telegram is a *control surface*, not the place for reasoning. This module
provides the full command set the PRD specifies and renders a compact status
panel. It **never** surfaces private chain-of-thought (the ``/why`` reply shows
signal, market state, key agent conclusions, risk checks, and the final
decision only).

Commands (PRD §48)::

    /status /market /positions /orders /risk /trades /performance
    /learning /strategy /agents /health /reconcile /why /replay <decision_id>
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

__all__ = [
    "ControlCenter",
    "format_status_panel",
    "COMMANDS",
]

# Canonical command list (PRD §48).
COMMANDS: tuple[str, ...] = (
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
    "/help",
)

_OK = "✅"
_WARN = "⚠️"
_PENDING = "🔄"


def format_status_panel(status: dict[str, Any]) -> str:
    """Render the PRD §48 ``/status`` panel.

    ``status`` is a dict assembled from the system providers. Missing keys
    degrade to ``UNKNOWN`` — the panel never raises.
    """

    def g(key: str, default: str = "UNKNOWN") -> str:
        value = status.get(key, default)
        return str(value) if value is not None else default

    health = g("system_health")
    health_icon = _OK if health.upper() == "HEALTHY" else _WARN

    mt5 = g("mt5")
    mt5_icon = _OK if mt5.upper() == "CONNECTED" else _WARN

    risk = g("risk")
    risk_icon = _OK if risk.upper() == "NORMAL" else _WARN

    recon = g("reconciliation")
    recon_icon = _OK if recon.upper() == "MATCH" else _WARN

    lines = [
        "SYSTEM",
        f"{health_icon} {health}",
        "",
        "MT5",
        f"{mt5_icon} {mt5}",
        "",
        "Risk",
        f"{risk_icon} {risk}",
        "",
        "Reconciliation",
        f"{recon_icon} {recon}",
        "",
        "Strategy",
        g("strategy"),
        "",
        "Open Positions",
        g("open_positions", "0"),
        "",
        "Daily PnL",
        g("daily_pnl", "0"),
        "",
        "New Trades",
        g("new_trades", "UNKNOWN"),
    ]
    return "\n".join(lines)


def format_why(trace: dict[str, Any]) -> str:
    """Render ``/why`` — operational reasoning WITHOUT private chain-of-thought."""

    def g(key: str) -> str:
        return str(trace.get(key, "—"))

    lines = [
        "📋 WHY",
        "",
        "Signal",
        g("signal"),
        "",
        "Market State",
        g("market_state"),
        "",
        "Key Agent Conclusions",
        g("agent_conclusions"),
        "",
        "Risk Checks",
        g("risk_checks"),
        "",
        "Decision",
        g("decision"),
        "",
        "Reason",
        g("reason"),
    ]
    return "\n".join(lines)


@dataclass
class ControlCenter:
    """Command router for the Telegram control surface (PRD §48).

    All data is supplied via injected providers so this module has no
    dependency on the live runtime. Providers are callables returning dicts.
    """

    providers: dict[str, Callable[[], Any]] = field(default_factory=dict)
    allowlist: set = field(default_factory=set)
    replay_fn: Optional[Callable[[str], Any]] = None

    def is_authorized(self, chat_id: Any) -> bool:
        return str(chat_id) in {str(c) for c in self.allowlist}

    def command_names(self) -> tuple[str, ...]:
        return COMMANDS

    # ------------------------------------------------------------------
    def handle(self, chat_id: Any, text: str) -> str:
        """Route an inbound command to its renderer."""
        if not self.is_authorized(chat_id):
            return "⛔ Unauthorized."

        command, args = self._parse(text)

        if command == "/help":
            return "EA Bot commands:\n" + "\n".join(COMMANDS)

        if command == "/status":
            return format_status_panel(self._call("status"))

        if command == "/why":
            return format_why(self._call("why"))

        if command == "/replay":
            return self._handle_replay(args)

        if command in COMMANDS:
            # Generic provider-backed command: /market, /positions, etc.
            name = command.lstrip("/")
            payload = self._call(name)
            return self._render_generic(command, payload)

        return "EA Bot commands:\n" + "\n".join(COMMANDS)

    # ------------------------------------------------------------------
    @staticmethod
    def _parse(text: str) -> tuple[str, list[str]]:
        if not text:
            return "", []
        parts = text.strip().split()
        if not parts:
            return "", []
        return parts[0].lower(), parts[1:]

    def _call(self, name: str) -> Any:
        provider = self.providers.get(name)
        if provider is None:
            return {"notice": "unavailable"}
        try:
            return provider()
        except Exception as exc:  # noqa: BLE001 - Telegram must never break
            return {"error": f"{type(exc).__name__}"}

    def _handle_replay(self, args: list[str]) -> str:
        if not args:
            return "Usage: /replay <decision_id>"
        decision_id = args[0]
        if self.replay_fn is None:
            return f"Replay unavailable for {decision_id}."
        try:
            replay = self.replay_fn(decision_id)
        except Exception as exc:  # noqa: BLE001
            return f"Replay error: {type(exc).__name__}"
        if replay is None:
            return f"Decision {decision_id} not found."
        steps = replay.get("steps", []) if isinstance(replay, dict) else []
        lines = [f"🔁 Replay {decision_id}", ""]
        for step in steps:
            lines.append(f"• {step.get('stage')}: {step.get('payload')}")
        return "\n".join(lines)

    @staticmethod
    def _render_generic(command: str, payload: Any) -> str:
        title = command.lstrip("/").upper()
        if isinstance(payload, dict):
            lines = [f"📊 {title}"]
            for key, value in payload.items():
                lines.append(f"• {key}: {value}")
            return "\n".join(lines)
        return f"📊 {title}\n{payload}"
