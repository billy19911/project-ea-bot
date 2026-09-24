# -*- coding: utf-8 -*-
"""Telegram gateway — a read-only communication/control interface.

PRD_V2 §21 / §32.18. Telegram is a *communication and control* surface: it can
query the system using stored decision/task/evidence traces and receive alerts.
It is **never** a dependency of the autonomous loop and can **never** place
broker orders directly.

Design notes
------------
* Transport-agnostic: a ``transport`` object (any object with
  ``send_message(chat_id, text)``) is injected. Tests use an in-memory stub; a
  real HTTP transport can be added behind the same interface. No bot token is
  required at import time.
* Providers are injected callables. The gateway only *reads* from them.
* This module intentionally imports **no** execution / MT5 modules. A guard test
  enforces that invariant.
* ``notify`` swallows transport failures so a Telegram outage can never break
  the autonomous trading loop.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure formatting helpers (unit-testable, side-effect free)
# ---------------------------------------------------------------------------
def format_help() -> str:
    """Return the command list."""
    return (
        "EA Bot — available commands:\n"
        "/status  — system status summary\n"
        "/positions — current positions summary\n"
        "/risk — risk summary\n"
        "/why — explain the last decision (structured summary + evidence)\n"
        "/review — latest trade review summary\n"
        "/help — this message"
    )


def format_status(payload: Any) -> str:
    """Format a ``/status`` response from a raw provider payload."""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        lines = ["📊 System Status"]
        for key, value in payload.items():
            lines.append(f"• {key}: {value}")
        return "\n".join(lines)
    return f"📊 System Status: {payload}"


def format_positions(payload: Any) -> str:
    """Format a ``/positions`` response."""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        lines = ["📈 Positions"]
        if "positions" in payload and isinstance(payload["positions"], list):
            positions = payload["positions"]
            if not positions:
                lines.append("• No open positions")
            for pos in positions:
                lines.append(f"• {pos}")
            for key, value in payload.items():
                if key != "positions":
                    lines.append(f"• {key}: {value}")
        else:
            for key, value in payload.items():
                lines.append(f"• {key}: {value}")
        return "\n".join(lines)
    return f"📈 Positions: {payload}"


def format_risk(payload: Any) -> str:
    """Format a ``/risk`` response."""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        lines = ["🛡️ Risk Summary"]
        for key, value in payload.items():
            lines.append(f"• {key}: {value}")
        return "\n".join(lines)
    return f"🛡️ Risk Summary: {payload}"


def format_why(payload: Any) -> str:
    """Format a ``/why`` response — structured summary + evidence only.

    The provider may return a dict with ``summary`` (str), ``evidence``
    (list/str), and possibly other fields. Any internal ``reasoning`` /
    chain-of-thought field is deliberately ignored and never echoed back to the
    user.
    """
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        lines = ["🧠 Decision Explanation"]
        summary = payload.get("summary")
        if summary:
            lines.append(f"Summary: {summary}")
        decision = payload.get("decision")
        if decision:
            lines.append(f"Decision: {decision}")
        evidence = payload.get("evidence")
        if evidence:
            if isinstance(evidence, (list, tuple)):
                lines.append("Evidence:")
                for item in evidence:
                    lines.append(f"  - {item}")
            else:
                lines.append(f"Evidence: {evidence}")
        return "\n".join(lines)
    return f"🧠 Decision Explanation: {payload}"


def format_review(payload: Any) -> str:
    """Format a ``/review`` response."""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        summary = payload.get("summary")
        if summary:
            return f"📝 Latest Review\n{summary}"
        lines = ["📝 Latest Review"]
        for key, value in payload.items():
            lines.append(f"• {key}: {value}")
        return "\n".join(lines)
    return f"📝 Latest Review: {payload}"


def format_notification(event_type: str, payload: Any) -> str:
    """Format an outbound alert message for a given event type."""
    labels = {
        "trade_proposal": "💡 Trade Proposal",
        "execution": "⚡ Execution",
        "position_opened": "🟢 Position Opened",
        "position_closed": "🔴 Position Closed",
        "risk_alert": "⚠️ Risk Alert",
        "system_alert": "🔔 System Alert",
        "pipeline_result": "🧠 Market Analysis",
        "pipeline_digest": "📊 Ringkasan Siklus",
    }
    title = labels.get(event_type, f"🔔 {event_type}")

    if isinstance(payload, str):
        return f"{title}\n{payload}"
    if isinstance(payload, dict):
        lines = [title]
        for key, value in payload.items():
            lines.append(f"• {key}: {value}")
        return "\n".join(lines)
    return f"{title}\n{payload}"


# ---------------------------------------------------------------------------
# Gateway
# ---------------------------------------------------------------------------
class TelegramGateway:
    """Read-only Telegram control/communication interface.

    Args:
        transport: Object exposing ``send_message(chat_id, text)``.
        allowlist: Chat ids permitted to issue commands (empty = nobody).
        status_provider: Callable returning a system status summary.
        positions_provider: Callable returning a positions summary.
        risk_provider: Callable returning a risk summary.
        decision_trace_provider: Callable returning a structured decision trace
            (dict with at least ``summary``; ``reasoning`` is never surfaced).
        review_provider: Callable returning the latest trade review summary.
    """

    def __init__(
        self,
        transport: Any = None,
        allowlist: Optional[list[Any]] = None,
        status_provider: Optional[Callable[[], Any]] = None,
        positions_provider: Optional[Callable[[], Any]] = None,
        risk_provider: Optional[Callable[[], Any]] = None,
        decision_trace_provider: Optional[Callable[[], Any]] = None,
        review_provider: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.transport = transport
        self.allowlist = {str(c) for c in (allowlist or [])}
        self._status_provider = status_provider
        self._positions_provider = positions_provider
        self._risk_provider = risk_provider
        self._decision_trace_provider = decision_trace_provider
        self._review_provider = review_provider

    # -- authorization ---------------------------------------------------
    def is_authorized(self, chat_id: Any) -> bool:
        """Return True if ``chat_id`` may issue commands."""
        return str(chat_id) in self.allowlist

    # -- command routing -------------------------------------------------
    def handle_message(self, chat_id: Any, text: str) -> str:
        """Route a command message to the appropriate read-only provider."""
        if not self.is_authorized(chat_id):
            logger.info("Refused command from unauthorized chat %s", chat_id)
            return "⛔ Unauthorized. This chat is not permitted to query the system."

        command, _args = self._parse(text)

        if command == "/status":
            return format_status(self._call_provider(self._status_provider))
        if command == "/positions":
            return format_positions(self._call_provider(self._positions_provider))
        if command == "/risk":
            return format_risk(self._call_provider(self._risk_provider))
        if command == "/why":
            return format_why(self._call_provider(self._decision_trace_provider))
        if command == "/review":
            return format_review(self._call_provider(self._review_provider))
        if command == "/help":
            return format_help()

        # Unknown command or empty → help text.
        return format_help()

    @staticmethod
    def _parse(text: str) -> tuple[str, list[str]]:
        """Parse ``"/command arg1 arg2"`` into ``(command, args)``."""
        if not text:
            return "", []
        parts = text.strip().split()
        if not parts:
            return "", []
        command = parts[0].lower()
        return command, parts[1:]

    @staticmethod
    def _call_provider(provider: Optional[Callable[[], Any]]) -> Any:
        """Invoke a provider, returning a graceful message when unavailable."""
        if provider is None:
            return "Provider unavailable."
        try:
            return provider()
        except Exception as exc:  # noqa: BLE001 - never break the loop
            logger.warning("Provider failed: %s", exc)
            return f"Data unavailable: {type(exc).__name__}"

    # -- outbound notifications ------------------------------------------
    def notify(self, event_type: str, payload: Any, chat_id: Any = None) -> bool:
        """Format and send an alert. Never raises.

        Returns True if the message was dispatched, False otherwise.
        """
        message = format_notification(event_type, payload)
        targets = [chat_id] if chat_id is not None else sorted(self.allowlist)
        if not targets:
            logger.warning("No notify target configured; dropping %s alert", event_type)
            return False
        if self.transport is None:
            logger.warning("No transport configured; dropping %s alert", event_type)
            return False

        sent = False
        for target in targets:
            try:
                self.transport.send_message(target, message)
                sent = True
            except (
                Exception
            ) as exc:  # noqa: BLE001 - Telegram must never break autonomy
                logger.error("Failed to send Telegram alert to %s: %s", target, exc)
        return sent

    # -- tracked (edit-in-place) messaging --------------------------------
    def send_tracked(self, text: str, chat_id: Any = None) -> dict[str, Optional[int]]:
        """Send ``text`` and return ``{chat_id: message_id}``. Never raises.

        ``message_id`` is ``None`` for a target whose transport fails or does
        not return an id. When no transport is configured an empty dict is
        returned. Used by the signal lifecycle to edit the SAME message later.
        """
        if self.transport is None:
            return {}
        targets = [chat_id] if chat_id is not None else sorted(self.allowlist)
        result: dict[str, Optional[int]] = {}
        for target in targets:
            try:
                message_id = self.transport.send_message(target, text)
                result[str(target)] = (
                    int(message_id) if message_id is not None else None
                )
            except (
                Exception
            ) as exc:  # noqa: BLE001 - Telegram must never break autonomy
                logger.error("Failed to send Telegram message to %s: %s", target, exc)
                result[str(target)] = None
        return result

    def edit_tracked(self, message_ids: dict, text: str) -> bool:
        """Edit every tracked message in place. Never raises.

        Returns True when at least one edit was delivered. A transport without
        ``edit_message_text`` (or no tracked ids) yields False.
        """
        edit = getattr(self.transport, "edit_message_text", None)
        if self.transport is None or edit is None or not isinstance(message_ids, dict):
            return False
        edited = False
        for chat_id, message_id in message_ids.items():
            if message_id is None:
                continue
            try:
                if edit(chat_id, message_id, text):
                    edited = True
            except (
                Exception
            ) as exc:  # noqa: BLE001 - Telegram must never break autonomy
                logger.error("Failed to edit Telegram message for %s: %s", chat_id, exc)
        return edited
