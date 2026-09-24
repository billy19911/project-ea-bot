# -*- coding: utf-8 -*-
"""Signal lifecycle — ONE edit-in-place Telegram message per signal (FOKUS #3).

The user asked for a single, calm signal message instead of a stream of near
identical alerts (one every ~1–3 minutes). This module owns that message's
lifecycle:

* ``observe_cycle_result`` — a finished BUY/SELL cycle either SENDS the one
  signal message (approved), edits it in place (status change / opposite
  direction before entry), or is silently consumed (risk-gate rejected →
  still recorded in ``/decisions``, never spammed to Telegram).
* ``observe_price`` — marks TP1 / TP2 / TPmax / SL hits on the SAME message
  (``editMessageText``) — never a new message.
* ``on_review`` — appends the post-trade review and marks the signal SELESAI,
  then clears the active state so the next signal may open a fresh message.

Design rules (enforced by a guard test):

* Pure formatting + state machine — this module imports NO MT5 / execution
  code. Prices and outcomes are injected by the runtime (``orchestration`` /
  ``main``).
* Fail-safe: every entry point swallows its own errors — a Telegram outage
  must never break the autonomous loop.
* Singleton lives in a shared ``builtins`` slot (same pattern as
  ``notifier.py``) so the ``telegram.*`` and ``src.telegram.*`` import
  identities share ONE tracker.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "SignalState",
    "SignalLifecycleTracker",
    "render_signal_message",
    "get_signal_lifecycle",
    "reset_signal_lifecycle",
]

# Status vocabulary shown in the message (Indonesian, matches the UI copy).
STATUS_WAITING = "MENUNGGU EKSEKUSI"
STATUS_OPEN = "ENTRY TERBUKA"
STATUS_FAILED = "GAGAL EKSEKUSI"
STATUS_DONE = "SELESAI"

# Hit keys in display order.
_HIT_ORDER = ("tp1", "tp2", "tpmax", "sl")
_HIT_LABELS = {"tp1": "TP1", "tp2": "TP2", "tpmax": "TPmax", "sl": "SL"}

_CONF_RE = re.compile(r"conf=([0-9]*\.?[0-9]+)")


# ---------------------------------------------------------------------------
# Pure formatting
# ---------------------------------------------------------------------------
def _hhmm(stamp: float) -> str:
    """Format a unix timestamp as local ``HH:MM`` (fail-safe to ``--:--``)."""
    try:
        return time.strftime("%H:%M", time.localtime(float(stamp)))
    except (TypeError, ValueError, OSError, OverflowError):
        return "--:--"


def _fmt_price(value: Optional[float]) -> str:
    """Render a price level compactly without float noise."""
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number != number:  # NaN
        return "—"
    return f"{number:.10g}"


def _consensus_label(summary: str, confidence: float) -> str:
    """Return a short consensus label (``conf=0.70`` → ``70%``), or ``""``."""
    match = _CONF_RE.search(str(summary or ""))
    raw = match.group(1) if match else ""
    if raw:
        try:
            return f"{float(raw) * 100.0:.0f}%"
        except (TypeError, ValueError):
            return ""
    try:
        number = float(confidence)
    except (TypeError, ValueError):
        number = 0.0
    return f"{number * 100.0:.0f}%" if number > 0 else ""


def render_signal_message(state: "SignalState") -> str:
    """Render the full signal message body (PURE — unit-testable, no I/O).

    Layout::

        🎯 SIGNAL FINAL · XAUUSD SELL
        🕒 22:47 · konsensus 100% · conf 0.86

        📐 RENCANA
        Entry : 4284.97
        SL    : 4294.65
        TP1   : 4275.29
        TP2   : 4265.62
        TPmax : 4255.94

        📌 Status: ENTRY TERBUKA #12345678
           ⏳ TP1
           ✅ TP2 — HIT 22:58
           ⏳ TPmax
           ⏳ SL
    """
    meta = [f"🕒 {_hhmm(state.created_at)}"]
    consensus = str(state.consensus or "").strip()
    if consensus:
        meta.append(f"konsensus {consensus}")
    try:
        conf = float(state.confidence)
    except (TypeError, ValueError):
        conf = 0.0
    meta.append(f"conf {conf:g}")

    lines = [
        f"🎯 SIGNAL FINAL · {state.symbol} {state.direction}",
        " · ".join(meta),
    ]

    # RENCANA block — only when at least one level is available.
    plan_rows: list[str] = []
    for label, value in (
        ("Entry", state.entry),
        ("SL", state.sl),
        ("TP1", state.tp1),
        ("TP2", state.tp2),
        ("TPmax", state.tpmax),
    ):
        if value is not None:
            plan_rows.append(f"{label:<5} : {_fmt_price(value)}")
    if plan_rows:
        lines.append("")
        lines.append("📐 RENCANA")
        lines.extend(plan_rows)

    lines.append("")
    status_line = f"📌 Status: {state.status}"
    detail = str(state.status_detail or "").strip()
    if detail and state.status != STATUS_DONE:
        status_line += f" {detail}" if detail.startswith("#") else f": {detail}"
    lines.append(status_line)

    # Hit checklist (⏳ pending / ✅ hit / ❌ hit for SL).
    for key in _HIT_ORDER:
        label = _HIT_LABELS[key]
        if state.hits.get(key):
            marker = "❌" if key == "sl" else "✅"
            hit_at = str(state.hit_times.get(key) or "").strip()
            suffix = f" — HIT {hit_at}" if hit_at else " — HIT"
            lines.append(f"   {marker} {label}{suffix}")
        else:
            lines.append(f"   ⏳ {label}")

    if state.status == STATUS_DONE:
        lines.append(f"🏁 SELESAI: {detail}".rstrip())
        review = str(state.review_text or "").strip()
        if review:
            lines.append(f"📝 Review: {review}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
@dataclass
class SignalState:
    """The ONE Telegram signal message's state for an active symbol."""

    symbol: str
    direction: str  # BUY / SELL
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    tpmax: Optional[float] = None
    confidence: float = 0.0
    consensus: str = ""  # mis. "100%"
    created_at: float = 0.0
    status: str = STATUS_WAITING
    status_detail: str = ""  # ticket / alasan gagal
    hits: dict = field(default_factory=lambda: {k: False for k in _HIT_ORDER})
    hit_times: dict = field(default_factory=dict)  # {"tp1": "HH:MM", ...}
    review_text: str = ""
    message_ids: dict = field(default_factory=dict)  # {chat_id: message_id}


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------
class SignalLifecycleTracker:
    """State machine driving the edit-in-place signal message.

    Args:
        gateway_provider: Callable returning the outbound gateway (defaults to
            the notifier's report gateway, imported lazily to avoid a cycle).
        clock: Callable returning the current unix time (injectable for tests).
    """

    def __init__(
        self,
        gateway_provider: Optional[Callable[[], Any]] = None,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._gateway_provider = gateway_provider
        self._clock = clock or time.time
        self._states: dict[str, SignalState] = {}

    # -- gateway (lazy, fail-safe) ---------------------------------------
    def _gateway(self) -> Any:
        if self._gateway_provider is not None:
            return self._gateway_provider()
        from .notifier import get_report_gateway  # lazy: avoid import cycle

        return get_report_gateway()

    def _resolve_gateway(self) -> Any:
        """Return the gateway or ``None``; a broken provider never raises here."""
        try:
            return self._gateway()
        except Exception as exc:  # noqa: BLE001 - reporting must never break a cycle
            logger.warning("Signal gateway unavailable (%s)", type(exc).__name__)
            return None

    def _edit_state(self, state: SignalState) -> bool:
        """Re-render ``state`` and edit its tracked message(s) in place."""
        gateway = self._resolve_gateway()
        edit = getattr(gateway, "edit_tracked", None) if gateway is not None else None
        if edit is None:
            return False
        try:
            return bool(edit(state.message_ids, render_signal_message(state)))
        except Exception as exc:  # noqa: BLE001 - never raises
            logger.warning("Signal message edit failed (%s)", type(exc).__name__)
            return False

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _status_from(record: dict) -> tuple[str, str]:
        """Derive ``(status, status_detail)`` from a finished cycle record."""
        execution = record.get("execution_result")
        if not isinstance(execution, dict):
            execution = {}
        ticket = execution.get("ticket")
        if record.get("executed") and ticket not in (None, "", 0):
            return STATUS_OPEN, f"#{ticket}"
        error = str(record.get("error") or "")
        if str(record.get("status") or "").upper() == "ERROR":
            return STATUS_FAILED, error
        return STATUS_WAITING, error

    @staticmethod
    def _level(value: Any) -> Optional[float]:
        """Coerce a level value to float; ``None`` when unavailable."""
        if value in (None, ""):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if number != number:  # NaN
            return None
        return number

    @staticmethod
    def _confidence(record: dict) -> float:
        try:
            return float(record.get("confidence") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _build_state(
        self,
        record: dict,
        symbol: str,
        direction: str,
        levels: dict,
        status: str,
        status_detail: str,
        confidence: float,
    ) -> SignalState:
        return SignalState(
            symbol=symbol,
            direction=direction,
            entry=self._level(levels.get("entry")),
            sl=self._level(levels.get("sl")),
            tp1=self._level(levels.get("tp1")),
            tp2=self._level(levels.get("tp2")),
            tpmax=self._level(levels.get("tpmax")),
            confidence=confidence,
            consensus=_consensus_label(str(record.get("summary") or ""), confidence),
            created_at=float(self._clock()),
            status=status,
            status_detail=status_detail,
            hits={k: False for k in _HIT_ORDER},
            hit_times={},
            review_text="",
            message_ids={},
        )

    def _send_state(self, state: SignalState) -> None:
        """Send the signal message and remember its ids (never raises)."""
        gateway = self._resolve_gateway()
        send = getattr(gateway, "send_tracked", None) if gateway is not None else None
        if send is None:
            state.message_ids = {}
            return
        try:
            state.message_ids = send(render_signal_message(state)) or {}
        except Exception as exc:  # noqa: BLE001 - never raises
            logger.warning("Signal message send failed (%s)", type(exc).__name__)
            state.message_ids = {}

    # -- public API ------------------------------------------------------
    def observe_cycle_result(self, record: dict) -> bool:
        """Offer one finished cycle to the signal lifecycle.

        Returns True when the cycle was CONSUMED (send/edit/silent-reject) so
        the caller must NOT fall back to the old digest; False for anything
        else (non BUY/SELL) or on an unexpected internal error.
        """
        try:
            if not isinstance(record, dict):
                return False
            decision = str(record.get("decision") or "").upper()
            if decision not in ("BUY", "SELL"):
                return False
            # Rejected by the risk gate → silent (still in /decisions).
            if not record.get("risk_approved"):
                return True
            symbol = str(record.get("symbol") or "").strip()
            if not symbol:
                return False

            levels = (
                record.get("levels") if isinstance(record.get("levels"), dict) else {}
            )
            direction = str(levels.get("direction") or decision).upper()
            if direction not in ("BUY", "SELL"):
                direction = decision

            status, status_detail = self._status_from(record)
            confidence = self._confidence(record)

            existing = self._states.get(symbol)
            if existing is None:
                state = self._build_state(
                    record, symbol, direction, levels, status, status_detail, confidence
                )
                self._states[symbol] = state
                self._send_state(state)
                return True

            if existing.direction != direction:
                if existing.status == STATUS_OPEN:
                    # Position still open → the new signal is ignored (log only).
                    logger.info(
                        "Ignoring %s signal for %s: position still open",
                        direction,
                        symbol,
                    )
                    return True
                # Replace the pending state — edit the SAME message (no spam).
                state = self._build_state(
                    record, symbol, direction, levels, status, status_detail, confidence
                )
                state.message_ids = dict(existing.message_ids)
                self._states[symbol] = state
                self._edit_state(state)
                return True

            # Same direction → never a new message; edit ONLY on status change.
            status_changed = (
                existing.status != status or existing.status_detail != status_detail
            )
            if confidence > existing.confidence:
                existing.confidence = confidence
            if status_changed:
                existing.status = status
                existing.status_detail = status_detail
                self._edit_state(existing)
            return True
        except Exception as exc:  # noqa: BLE001 - never raise into the loop
            logger.warning("observe_cycle_result failed (%s)", type(exc).__name__)
            return False

    def observe_price(
        self,
        symbol: str,
        price: float,
        ts: Optional[float] = None,
    ) -> bool:
        """Mark TP/SL hits for ``symbol`` on the SAME message. Never raises.

        BUY: a TP hits when ``price >= level``; the SL when ``price <= sl``.
        SELL: reversed. Returns True only when a hit changed AND an edit was
        delivered.
        """
        try:
            key = str(symbol or "").strip()
            state = self._states.get(key) or self._states.get(key.upper())
            if state is None:
                return False
            price = float(price)
            if price != price or price <= 0:  # NaN / non-positive
                return False
            stamp = float(self._clock()) if ts is None else float(ts)
            hit_at = time.strftime("%H:%M", time.localtime(stamp))

            changed = False
            is_buy = state.direction == "BUY"
            for hit_key in ("tp1", "tp2", "tpmax"):
                level = getattr(state, hit_key, None)
                if level is None or state.hits.get(hit_key):
                    continue
                hit = price >= level if is_buy else price <= level
                if hit:
                    state.hits[hit_key] = True
                    state.hit_times[hit_key] = hit_at
                    changed = True
            if state.sl is not None and not state.hits.get("sl"):
                hit = price <= state.sl if is_buy else price >= state.sl
                if hit:
                    state.hits["sl"] = True
                    state.hit_times["sl"] = hit_at
                    changed = True

            if not changed:
                return False
            return self._edit_state(state)
        except Exception as exc:  # noqa: BLE001 - never raise into the loop
            logger.warning("observe_price failed (%s)", type(exc).__name__)
            return False

    def on_review(self, record: dict) -> bool:
        """Append the post-trade review, mark SELESAI, clear the state.

        The state is matched by ``trade_id``/``ticket`` (string compare against
        the open ticket) or — when exactly one signal is active — by that lone
        state. Never raises; returns True when a state was consumed.
        """
        try:
            if not isinstance(record, dict):
                return False
            ref = (
                str(record.get("trade_id") or record.get("ticket") or "")
                .strip()
                .lstrip("#")
            )
            target: Optional[str] = None
            if ref:
                for sym, state in self._states.items():
                    detail_ref = str(state.status_detail or "").strip().lstrip("#")
                    if detail_ref and detail_ref == ref:
                        target = sym
                        break
            if target is None and len(self._states) == 1:
                target = next(iter(self._states))
            if target is None:
                return False

            state = self._states[target]
            outcome = str(record.get("outcome") or "")
            root_cause = str(record.get("root_cause") or "")
            summary = str(record.get("summary") or "")
            state.review_text = f"{outcome} · {root_cause} · {summary}"[:200]

            pnl = record.get("pnl")
            if pnl is not None and outcome:
                state.status_detail = f"{outcome} · PnL {pnl}"
            elif pnl is not None:
                state.status_detail = f"PnL {pnl}"
            else:
                state.status_detail = outcome
            state.status = STATUS_DONE
            self._edit_state(state)
            self._states.pop(target, None)
            return True
        except Exception as exc:  # noqa: BLE001 - never raise into the loop
            logger.warning("on_review failed (%s)", type(exc).__name__)
            return False

    def active_symbols(self) -> list[str]:
        """Return the symbols with an active (not-yet-SELESAI) signal."""
        return list(self._states.keys())


# ---------------------------------------------------------------------------
# Process-wide singleton (shared builtins slot — see notifier.py)
# ---------------------------------------------------------------------------
_GBL_KEY = "__ea_bot_telegram_singletons__"
_SLOT_KEY = "signal_lifecycle"


def _shared_slot() -> dict:
    import builtins

    slot = getattr(builtins, _GBL_KEY, None)
    if slot is None:
        slot = {}
        setattr(builtins, _GBL_KEY, slot)
    return slot


def get_signal_lifecycle() -> SignalLifecycleTracker:
    """Return the process-wide tracker, constructing it on first use."""
    slot = _shared_slot()
    tracker = slot.get(_SLOT_KEY)
    if tracker is None:
        tracker = SignalLifecycleTracker()
        slot[_SLOT_KEY] = tracker
    return tracker


def reset_signal_lifecycle() -> None:
    """Drop the process-wide tracker (used by tests)."""
    _shared_slot()[_SLOT_KEY] = None
