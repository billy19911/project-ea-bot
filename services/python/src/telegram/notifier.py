# -*- coding: utf-8 -*-
"""Telegram notifier — pipeline reports for the user (Phase 5).

Wires the read-only :class:`TelegramGateway` into the orchestration loop:

* ``summarize_pipeline_result`` — compact, honest summary of a pipeline record,
* ``format_pipeline_report`` / ``format_pipeline_digest`` — human formatting,
* ``queue_pipeline_result`` / ``flush_pipeline_digest`` — anti-spam digest: a
  burst of autonomous cycles becomes ONE compact message per window instead of
  one message per cycle (urgent trade outcomes bypass the digest),
* ``notify_pipeline_result`` — immediate single-report delivery,
* ``build_gateway_from_env`` / ``get_gateway`` / ``set_gateway`` — env-driven
  gateway singleton (no token → transport stays ``None``, feature is off),
* ``build_signal_gateway_from_env`` / ``get_signal_gateway`` — a *second*,
  optional bot (``TELEGRAM_SIGNAL_BOT_TOKEN``) that receives the signal
  reports (digests / market analysis) so the primary bot's chat stays clean;
  without that token reports fall back to the primary bot.

Design rules:

* Fail-safe: a Telegram outage must never break the autonomous loop — every
  helper here catches its own errors.
* No token in logs; the transport never leaks it either.
* No execution / MT5 imports.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections import Counter
from typing import Any, Callable, Optional

from .gateway import TelegramGateway
from .transport import HttpTelegramTransport

logger = logging.getLogger(__name__)

__all__ = [
    "PipelineDigest",
    "build_gateway_from_env",
    "build_signal_gateway_from_env",
    "flush_pipeline_digest",
    "format_pipeline_digest",
    "format_pipeline_report",
    "get_digest",
    "get_gateway",
    "get_report_gateway",
    "get_signal_gateway",
    "notify_pipeline_result",
    "queue_pipeline_result",
    "reset_digest",
    "reset_signal_gateway",
    "set_digest",
    "set_gateway",
    "set_signal_gateway",
    "summarize_pipeline_result",
]

# Max length of the free-text summary carried in a report (Telegram-friendly).
_SUMMARY_MAX_CHARS = 240
# Digest defaults: one compact message per window (or per N cycles, whichever
# comes first). Tune via TELEGRAM_DIGEST_WINDOW_S / TELEGRAM_DIGEST_MAX_ITEMS.
_DIGEST_WINDOW_S_DEFAULT = 600.0
_DIGEST_MAX_ITEMS_DEFAULT = 15
# Distinct (event, decision, direction) groups kept in a digest body.
_DIGEST_GROUP_MAX = 6
# Decisions that bypass the digest and are delivered immediately.
_URGENT_DECISIONS = {"BUY", "SELL"}

_MARKET_DIRECTION_RE = re.compile(r"market_lead:\s*([A-Z_]+)")
_MARKET_CONF_RE = re.compile(r"market_lead:\s*[A-Z_]+\s*\(conf=([0-9]*\.?[0-9]+)\)")
_CONFIDENCE_RE = re.compile(r"conf=([0-9]*\.?[0-9]+)")

# Machine reasons translated for the report body (fallback: raw value).
_REASON_LABELS = {
    "no actionable proposal": "tidak ada proposal layak eksekusi",
    "risk did not approve": "ditolak oleh risk gate",
}

_gateway: Optional[TelegramGateway] = None
_digest: Optional["PipelineDigest"] = None

# The Python service can import this module under two identities
# (``telegram.notifier`` and ``src.telegram.notifier``). A plain module-global
# would give each identity its OWN singleton, so ``set_gateway`` on one would be
# invisible to the other — breaking report delivery. Mirror the project's existing
# shared-slot pattern (see ``agents/base.py``): keep the singletons in a stable
# ``builtins`` slot so both import paths share the same object.
_GBL_KEY = "__ea_bot_telegram_singletons__"


def _shared_slot() -> dict[str, Any]:
    import builtins

    slot = getattr(builtins, _GBL_KEY, None)
    if slot is None:
        slot = {"gateway": None, "digest": None, "signal_gateway": None}
        setattr(builtins, _GBL_KEY, slot)
    return slot


def _get_gateway_singleton() -> Optional[TelegramGateway]:
    return _shared_slot().get("gateway")


def _set_gateway_singleton(value: Optional[TelegramGateway]) -> None:
    _shared_slot()["gateway"] = value


def _get_digest_singleton() -> Optional["PipelineDigest"]:
    return _shared_slot().get("digest")


def _set_digest_singleton(value: Optional["PipelineDigest"]) -> None:
    _shared_slot()["digest"] = value


def _get_signal_gateway_singleton() -> Optional[TelegramGateway]:
    return _shared_slot().get("signal_gateway")


def _set_signal_gateway_singleton(value: Optional[TelegramGateway]) -> None:
    _shared_slot()["signal_gateway"] = value


def _parse_allowlist(raw: str) -> list[str]:
    """Split a comma-separated chat-id list into trimmed non-empty items."""
    return [cid.strip() for cid in (raw or "").split(",") if cid.strip()]


def build_gateway_from_env() -> TelegramGateway:
    """Build a gateway from ``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_ALLOWED_CHAT_IDS``.

    Without a token the transport stays ``None`` — the gateway still works as a
    read-only command surface (legacy behaviour) but sends nothing.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN") or ""
    raw_allowlist = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS") or os.getenv("TELEGRAM_CHAT_IDS") or ""
    allowlist = _parse_allowlist(raw_allowlist)

    transport: Optional[HttpTelegramTransport] = None
    if token.strip():
        try:
            transport = HttpTelegramTransport(token=token)
        except Exception:  # pragma: no cover - defensive; blank handled above
            logger.warning("Could not build Telegram transport; alerts disabled")
            transport = None

    return TelegramGateway(transport=transport, allowlist=allowlist)


def get_gateway() -> TelegramGateway:
    """Return the process-wide gateway, building it from env on first use."""
    gateway = _get_gateway_singleton()
    if gateway is None:
        gateway = build_gateway_from_env()
        _set_gateway_singleton(gateway)
    return gateway


def set_gateway(gateway: Optional[TelegramGateway]) -> None:
    """Override the process-wide gateway (used by tests / startup wiring)."""
    _set_gateway_singleton(gateway)


def build_signal_gateway_from_env() -> Optional[TelegramGateway]:
    """Build the *signal* gateway from ``TELEGRAM_SIGNAL_BOT_TOKEN``.

    Returns ``None`` when the token is unset — callers then fall back to the
    primary gateway, so a missing signal bot degrades to the old behaviour
    (reports on the primary bot) instead of silencing them.

    The signal bot is deliberately *separate* from the primary bot: the user
    wants the signal chatter (cycle digests / market analysis) in its own
    chat while the primary bot stays clean. ``TELEGRAM_SIGNAL_CHAT_IDS``
    defaults to the primary allowlist when unset.
    """
    token = (os.getenv("TELEGRAM_SIGNAL_BOT_TOKEN") or "").strip()
    if not token:
        return None
    raw_allowlist = (
        os.getenv("TELEGRAM_SIGNAL_CHAT_IDS")
        or os.getenv("TELEGRAM_ALLOWED_CHAT_IDS")
        or os.getenv("TELEGRAM_CHAT_IDS")
        or ""
    )
    allowlist = _parse_allowlist(raw_allowlist)

    transport: Optional[HttpTelegramTransport] = None
    try:
        transport = HttpTelegramTransport(token=token)
    except Exception:  # pragma: no cover - defensive; blank handled above
        logger.warning("Could not build Telegram signal transport; falling back")
        return None

    return TelegramGateway(transport=transport, allowlist=allowlist)


def get_signal_gateway() -> Optional[TelegramGateway]:
    """Return the process-wide signal gateway (``None`` when not configured)."""
    gateway = _get_signal_gateway_singleton()
    if gateway is None:
        gateway = build_signal_gateway_from_env()
        if gateway is not None:
            _set_signal_gateway_singleton(gateway)
    return gateway


def set_signal_gateway(gateway: Optional[TelegramGateway]) -> None:
    """Override the process-wide signal gateway (used by tests)."""
    _set_signal_gateway_singleton(gateway)


def reset_signal_gateway() -> None:
    """Drop the signal gateway so the next use rebuilds it from env."""
    _set_signal_gateway_singleton(None)


# ---------------------------------------------------------------------------
# Digest (anti-spam coalescing)
# ---------------------------------------------------------------------------
def _digest_enabled_from_env() -> bool:
    """Return False only for an explicit opt-out (default: enabled)."""
    raw = (os.getenv("TELEGRAM_DIGEST_ENABLED") or "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _float_from_env(name: str, default: float) -> float:
    """Read a float from the environment with a fail-safe default."""
    try:
        return float(os.getenv(name) or default)
    except (TypeError, ValueError):
        return default


def _default_timer(delay: float, callback: Callable[[], None]) -> Any:
    """Arm a daemon timer firing ``callback`` after ``delay`` seconds."""
    timer = threading.Timer(delay, callback)
    timer.daemon = True
    timer.start()
    return timer


class PipelineDigest:
    """Coalesce pipeline summaries into one Telegram message per window.

    A busy market detects several events per poll; without coalescing the user
    receives one message per cycle. This buffer keeps the reports for
    ``window_s`` seconds (or until ``max_items`` accumulate) and then delivers
    a single compact digest.

    Args:
        send: Callable receiving the finished batch; defaults to the shared
            gateway delivery (``_send_digest``).
        window_s: Seconds a batch may wait before it is flushed.
        max_items: Flush threshold — a batch of this size is sent immediately.
        timer_factory: Injectable timer factory ``(delay, callback) -> timer``
            (tests inject a fake; production uses a daemon ``threading.Timer``).
    """

    def __init__(
        self,
        send: Optional[Callable[[list[dict[str, Any]]], bool]] = None,
        window_s: float = _DIGEST_WINDOW_S_DEFAULT,
        max_items: int = _DIGEST_MAX_ITEMS_DEFAULT,
        timer_factory: Optional[Callable[[float, Callable[[], None]], Any]] = None,
    ) -> None:
        self._send = send
        self.window_s = max(0.0, float(window_s))
        self.max_items = max(1, int(max_items))
        self._timer_factory = timer_factory or _default_timer
        self._lock = threading.Lock()
        self._items: list[dict[str, Any]] = []
        self._timer: Any = None

    @property
    def pending(self) -> int:
        """Number of cycles currently waiting in the batch."""
        with self._lock:
            return len(self._items)

    def add(self, item: dict[str, Any]) -> bool:
        """Queue one cycle summary; flushes automatically at the threshold."""
        with self._lock:
            self._items.append(item)
            if len(self._items) >= self.max_items:
                self._flush_locked()
            else:
                self._arm_timer_locked()
            return True

    def flush(self) -> bool:
        """Send the pending batch now (no-op when the batch is empty)."""
        with self._lock:
            return self._flush_locked()

    # -- internals ---------------------------------------------------------
    def _arm_timer_locked(self) -> None:
        if self._timer is not None or self.window_s <= 0:
            return
        self._timer = self._timer_factory(self.window_s, self._on_timer)

    def _on_timer(self) -> None:
        with self._lock:
            self._timer = None
            self._flush_locked()

    def _flush_locked(self) -> bool:
        self._cancel_timer_locked()
        if not self._items:
            return False
        items, self._items = self._items, []
        send = self._send or _send_digest
        try:
            return bool(send(items))
        except Exception as exc:  # noqa: BLE001 - reporting must never break a cycle
            logger.warning("Telegram digest send failed (%s)", type(exc).__name__)
            return False

    def _cancel_timer_locked(self) -> None:
        timer = self._timer
        self._timer = None
        if timer is None:
            return
        try:
            timer.cancel()
        except Exception:  # pragma: no cover - defensive
            pass


def get_digest() -> Optional[PipelineDigest]:
    """Return the process-wide digest, building it from env on first use.

    Returns ``None`` when the digest is disabled via
    ``TELEGRAM_DIGEST_ENABLED=false`` — callers then deliver every report
    immediately.
    """
    digest = _get_digest_singleton()
    if digest is None:
        if not _digest_enabled_from_env():
            return None
        digest = PipelineDigest(
            window_s=_float_from_env("TELEGRAM_DIGEST_WINDOW_S", _DIGEST_WINDOW_S_DEFAULT),
            max_items=int(_float_from_env("TELEGRAM_DIGEST_MAX_ITEMS", _DIGEST_MAX_ITEMS_DEFAULT)),
        )
        _set_digest_singleton(digest)
    return digest


def set_digest(digest: Optional[PipelineDigest]) -> None:
    """Override the process-wide digest (used by tests)."""
    _set_digest_singleton(digest)


def reset_digest() -> None:
    """Drop the process-wide digest so the next use rebuilds it from env."""
    set_digest(None)


# ---------------------------------------------------------------------------
# Formatting (pure helpers)
# ---------------------------------------------------------------------------
def _time_of(stamp: Any) -> str:
    """Format a unix timestamp as local ``HH:MM`` (fail-safe to now)."""
    try:
        value = float(stamp)
    except (TypeError, ValueError):
        value = time.time()
    return time.strftime("%H:%M", time.localtime(value))


def _market_direction(summary: Any) -> str:
    """Extract the market committee direction from a summary string."""
    match = _MARKET_DIRECTION_RE.search(str(summary or ""))
    return match.group(1) if match else ""


def _consensus_pct(summary: str, confidence: Any) -> str:
    """Return a short consensus label (``conf=1.00`` → ``100%``).

    Prefers the market committee's own confidence (``market_lead: X (conf=…)``);
    falls back to the first ``conf=`` in the summary, then to the numeric
    ``confidence`` field.
    """
    raw = ""
    match = _MARKET_CONF_RE.search(summary or "") or _CONFIDENCE_RE.search(summary or "")
    if match:
        raw = match.group(1)
    else:
        try:
            number = float(confidence or 0.0)
        except (TypeError, ValueError):
            number = 0.0
        raw = f"{number:.2f}" if number else ""
    if not raw:
        return ""
    try:
        return f"{float(raw) * 100.0:.0f}%"
    except (TypeError, ValueError):
        return ""


def _reason_label(reason: str) -> str:
    """Translate the common machine reasons; unknown reasons pass through."""
    text = str(reason or "").strip()
    if not text:
        return ""
    for key, label in _REASON_LABELS.items():
        if text == key or text.startswith(f"{key}:"):
            return label
    return text


def _digest_group_lines(batch: list[dict[str, Any]]) -> list[str]:
    """Group a batch by (event, decision, direction) for a compact body."""
    groups: dict[tuple[str, str, str], int] = {}
    for item in batch:
        key = (
            str(item.get("event_type") or "—"),
            str(item.get("decision") or "—"),
            _market_direction(item.get("summary")),
        )
        groups[key] = groups.get(key, 0) + 1

    lines: list[str] = []
    for (event, decision, direction), count in list(groups.items())[:_DIGEST_GROUP_MAX]:
        suffix = f" · {direction}" if direction else ""
        times = f" ×{count}" if count > 1 else ""
        lines.append(f"• {event}{times} → {decision}{suffix}")
    hidden = len(groups) - _DIGEST_GROUP_MAX
    if hidden > 0:
        lines.append(f"… dan {hidden} jenis lainnya")
    return lines


def _format_levels(levels: Any) -> str:
    """Render an Entry/SL/TP1/TP2/TPmax ladder as one compact line.

    The ladder is produced by the pipeline (``trading.level_plan``): from the
    real order when one exists (source "order"), otherwise an indicative ATR
    plan for the setup (source "analysis"). Returns "" when no usable ladder.
    """
    if not isinstance(levels, dict):
        return ""
    entry = levels.get("entry")
    sl = levels.get("sl")
    tp1 = levels.get("tp1")
    tp2 = levels.get("tp2")
    tpmax = levels.get("tpmax")
    if entry in (None, "") or sl in (None, ""):
        return ""
    direction = str(levels.get("direction") or "").upper()
    label = f" {direction}" if direction in ("BUY", "SELL") else ""
    parts = [
        f"Entry {entry}",
        f"SL {sl}",
        f"TP1 {tp1}",
        f"TP2 {tp2}",
        f"TPmax {tpmax}",
    ]
    line = f"📐 Level{label}: " + " · ".join(parts)
    if str(levels.get("source") or "") == "analysis":
        line += " (indikatif)"
    return line


def format_pipeline_report(summary: dict[str, Any]) -> str:
    """Format ONE cycle as a compact multi-line report body."""
    head = [_time_of(summary.get("queued_at"))]
    symbol = str(summary.get("symbol") or "").strip()
    if symbol:
        head.append(symbol)
    event = str(summary.get("event_type") or "").strip()
    if event:
        head.append(event)
    lines = ["🕒 " + " · ".join(head)]

    decision = str(summary.get("decision") or "—")
    direction = _market_direction(summary.get("summary"))
    tail = f" · arah {direction}" if direction else ""
    consensus = _consensus_pct(str(summary.get("summary") or ""), summary.get("confidence"))
    if consensus:
        tail += f" (konsensus {consensus})"
    lines.append(f"🎯 {decision}{tail}")

    reason = _reason_label(str(summary.get("risk_reason") or ""))
    if reason:
        lines.append(f"💬 {reason}")
    level_line = _format_levels(summary.get("levels"))
    if level_line:
        lines.append(level_line)
    if summary.get("executed"):
        lines.append("⚡ dieksekusi")
    trace = str(summary.get("trace_id") or "").strip()
    if trace:
        lines.append(f"🔎 trace {trace}")
    return "\n".join(lines)


def format_pipeline_digest(items: list[dict[str, Any]]) -> str:
    """Format a batch of cycles as ONE compact digest message body."""
    batch = [item for item in items if isinstance(item, dict)]
    if not batch:
        return ""

    span = _time_of(batch[0].get("queued_at"))
    if len(batch) > 1:
        span = f"{span}–{_time_of(batch[-1].get('queued_at'))}"
    symbols = sorted({str(item.get("symbol") or "").strip() for item in batch} - {""})
    header = f"🕒 {span} · {len(batch)} siklus"
    if symbols:
        label = symbols[0] if len(symbols) == 1 else f"{len(symbols)} simbol"
        header += f" · {label}"

    directions = Counter(d for d in (_market_direction(item.get("summary")) for item in batch) if d)
    neutral = len(batch) - sum(directions.values())
    direction_line = " · ".join(f"{name} ({count})" for name, count in directions.most_common())
    if neutral:
        if direction_line:
            direction_line += f" · netral ({neutral})"
        else:
            direction_line = f"netral ({neutral})"

    decisions = Counter(str(item.get("decision") or "—") for item in batch)
    decision_line = " · ".join(f"{name} ({count})" for name, count in decisions.most_common())
    executed = sum(1 for item in batch if item.get("executed"))
    execution_line = f"eksekusi {executed}" if executed else "tanpa eksekusi"

    lines = [
        header,
        f"📈 Arah: {direction_line or 'netral'}",
        f"🎯 Keputusan: {decision_line} · {execution_line}",
    ]
    # A single shared reason (the common no-trade case) is stated once.
    reasons = {
        _reason_label(str(item.get("risk_reason") or ""))
        for item in batch
        if str(item.get("risk_reason") or "").strip()
    }
    if len(reasons) == 1:
        reason = reasons.pop()
        if reason:
            lines.append(f"💬 {reason}")
    # Level ladder: one line per digest — prefer a real order ladder, else the
    # first indicative plan in the batch (keeps the message compact).
    ladders = [item.get("levels") for item in batch if isinstance(item.get("levels"), dict)]
    order_ladders = [lv for lv in ladders if str(lv.get("source") or "") == "order"]
    chosen = order_ladders[0] if order_ladders else (ladders[0] if ladders else None)
    level_line = _format_levels(chosen)
    if level_line:
        lines.append(level_line)
    lines.append("")
    lines.extend(_digest_group_lines(batch))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------
def get_report_gateway() -> Optional[TelegramGateway]:
    """Return the gateway that receives *signal* reports (digest / analysis).

    Prefers the dedicated signal bot (``TELEGRAM_SIGNAL_BOT_TOKEN``) so the
    primary bot's chat stays clean. Falls back to the primary gateway when no
    signal bot is configured — or when it has no usable recipients — so a
    half-configured signal bot never silences reports.
    """
    signal_gateway = get_signal_gateway()
    if (
        signal_gateway is not None
        and getattr(signal_gateway, "transport", None) is not None
        and getattr(signal_gateway, "allowlist", None)
    ):
        return signal_gateway
    return get_gateway()


def _send_digest(items: list[dict[str, Any]]) -> bool:
    """Deliver one digest batch through the report gateway (fail-safe)."""
    gateway = get_report_gateway()
    if gateway is None or getattr(gateway, "transport", None) is None:
        return False
    text = format_pipeline_digest(items)
    if not text:
        return False
    ok = bool(gateway.notify("pipeline_digest", text))
    if ok:
        logger.info("Telegram digest sent (%d cycles)", len(items))
    return ok


def _deliver(summary: dict[str, Any]) -> bool:
    """Send one summary through the report gateway (fail-safe)."""
    gateway = get_report_gateway()
    if gateway is None or getattr(gateway, "transport", None) is None:
        return False
    return bool(gateway.notify("pipeline_result", format_pipeline_report(summary)))


def _is_urgent(summary: dict[str, Any]) -> bool:
    """True when the outcome must bypass the digest (trade-level events)."""
    if summary.get("executed"):
        return True
    return str(summary.get("decision") or "").upper() in _URGENT_DECISIONS


def summarize_pipeline_result(result: dict[str, Any]) -> dict[str, Any]:
    """Return a compact, JSON-friendly summary of a pipeline record.

    Missing fields degrade to honest defaults — never fabricates values.
    """
    record = result if isinstance(result, dict) else {}

    summary_text = str(record.get("summary") or "")
    if len(summary_text) > _SUMMARY_MAX_CHARS:
        summary_text = summary_text[: _SUMMARY_MAX_CHARS - 3] + "..."

    confidence: float = 0.0
    try:
        confidence = float(record.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0

    return {
        "event_type": str(record.get("event_type") or ""),
        "decision": str(record.get("decision") or ""),
        "status": str(record.get("status") or ""),
        "confidence": confidence,
        "summary": summary_text,
        "risk_reason": str(record.get("risk_reason") or ""),
        "executed": bool(record.get("executed", False)),
        "trace_id": str(record.get("trace_id") or ""),
        "symbol": str(record.get("symbol") or ""),
        "levels": record.get("levels") if isinstance(record.get("levels"), dict) else None,
    }


def queue_pipeline_result(result: dict[str, Any]) -> bool:
    """Queue one finished cycle for the anti-spam digest. Never raises.

    Urgent outcomes (executed trades / BUY-SELL decisions) bypass the digest
    and are delivered immediately. Returns True when the report was accepted
    (queued or sent), False when Telegram is not configured.
    """
    try:
        gateway = get_report_gateway()
        if gateway is None or getattr(gateway, "transport", None) is None:
            return False
        summary = summarize_pipeline_result(result)
        if _is_urgent(summary):
            return _deliver(summary)
        digest = get_digest()
        if digest is None:
            return _deliver(summary)
        summary["queued_at"] = time.time()
        return digest.add(summary)
    except Exception as exc:  # noqa: BLE001 - Telegram must never break autonomy
        logger.warning("Telegram cycle report failed (%s); cycle unaffected", type(exc).__name__)
        return False


def flush_pipeline_digest() -> bool:
    """Send the pending digest batch now (no-op when empty or disabled)."""
    digest = _get_digest_singleton()
    if digest is None:
        return False
    return digest.flush()


def notify_pipeline_result(
    result: dict[str, Any],
    gateway: Optional[TelegramGateway] = None,
) -> bool:
    """Send a ``pipeline_result`` report immediately. Never raises.

    Returns True when the message was dispatched, False otherwise (no
    transport / no allowlist / delivery failure — all silently degraded).
    """
    try:
        gw = gateway if gateway is not None else get_report_gateway()
        if gw is None:
            return False
        # Feature off (no bot token configured): stay quiet — a disabled
        # notifier must not log-spam every autonomous cycle.
        if getattr(gw, "transport", "unknown") is None:
            return False
        summary = summarize_pipeline_result(result)
        return bool(gw.notify("pipeline_result", format_pipeline_report(summary)))
    except Exception as exc:  # noqa: BLE001 - Telegram must never break autonomy
        logger.warning("Telegram pipeline report failed (%s); cycle unaffected", type(exc).__name__)
        return False
