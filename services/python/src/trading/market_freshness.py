# -*- coding: utf-8 -*-
"""Market freshness gate (TASK 09) — reject stale market data before it trades.

The market feed loop turns MT5 OHLC into events, and the pipeline merges the
snapshot behind each event into the analysis context so the committee runs on
real data. That bridge is only safe if the data is *fresh*: a snapshot whose
bar closed long ago (feed stalled, terminal quiet, clock skew) must never be
handed to the committee as trade-ready context.

This module is the single, deterministic freshness authority:

* Every market snapshot must carry::

      bar_timestamp   — the close time of the newest bar (ISO-8601, tz aware)
      received_at     — when the feed loop received the bars (ISO-8601, tz aware)
      age_seconds     — received_at - bar_timestamp, in seconds
      timeframe       — MT5 timeframe string (``M1``/``M5``/``H1``/…)
      symbol          — instrument

* A snapshot is **rejected** when ``age_seconds > max_allowed_age`` for its
  timeframe (timeframe-aware: M1 is strict, M5/H1 progressively wider — see
  :data:`TIMEFRAME_MAX_AGE_SECONDS`).

* Clock anomalies are rejected **fail-closed**:

  - ``received_at < bar_timestamp`` (the data clock runs backwards), or
  - the bar/receive timestamp is in the future beyond a small tolerance, or
  - ``age_seconds < 0`` (which must never be treated as "fresh").

* A missing/unparseable timestamp is rejected as ``UNKNOWN`` — a snapshot with
  an unverifiable age is not trusted (fail-closed).

Design rules: this module is pure/deterministic — no MT5, no execution, no
order code. It imports nothing that could place an order and can never itself
trigger a trade; it only *withholds* evidence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "TIMEFRAME_MAX_AGE_SECONDS",
    "DEFAULT_MAX_AGE_SECONDS",
    "CLOCK_SKEW_TOLERANCE_SECONDS",
    "max_allowed_age",
    "FreshnessVerdict",
    "evaluate_freshness",
    "STALE_REASON_PREFIX",
]

# ---------------------------------------------------------------------------
# Timeframe-aware thresholds (SECONDS)
# ---------------------------------------------------------------------------
# TASK 09 requires a timeframe-aware threshold, NOT one universal hard-coded
# value. The rule of thumb: allow the bar's own period plus a small grace so a
# *just-closed* bar is fresh, but nothing older (a missed bar means the feed
# stalled). M1 is therefore strict; M5/H1/D1/H4/W1/MN1 scale up with the bar
# length. Each entry is documented so the choice is auditable.
#
# Grace added on top of the bar period (seconds): enough for one poll interval
# plus IPC jitter, without ever accepting a *missing* bar.
_BAR_GRACE_SECONDS = 60.0

# bar period in seconds per MT5 timeframe.
_TIMEFRAME_SECONDS: dict[str, int] = {
    "M1": 60,
    "M2": 120,
    "M3": 180,
    "M5": 300,
    "M10": 600,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H2": 7200,
    "H3": 10800,
    "H4": 14400,
    "H6": 21600,
    "H8": 28800,
    "H12": 43200,
    "D1": 86400,
    "W1": 604800,
    "MN1": 2592000,
}

# Per-timeframe max allowed age = bar period + grace.
#   M1  → 120s  (strict: two M1 bars missed ⇒ reject)
#   M5  → 360s
#   H1  → 3660s
#   H4  → 14460s
#   D1  → 86520s
# Documented constants, not a single universal value.
TIMEFRAME_MAX_AGE_SECONDS: dict[str, float] = {
    tf: float(period) + _BAR_GRACE_SECONDS for tf, period in _TIMEFRAME_SECONDS.items()
}

# Fallback when the timeframe is unknown/empty: treat like M5 (a mid-range,
# deliberately conservative choice) — documented, never a silent universal.
DEFAULT_MAX_AGE_SECONDS: float = TIMEFRAME_MAX_AGE_SECONDS["M5"]

# Tolerance for "future" timestamps: an exchange clock slightly ahead of ours
# is not a clock anomaly. Anything further ahead is rejected.
CLOCK_SKEW_TOLERANCE_SECONDS: float = 5.0

STALE_REASON_PREFIX = "stale_market_data"


def max_allowed_age(timeframe: Any) -> float:
    """Return the max allowed snapshot age (seconds) for *timeframe*.

    Unknown / empty / non-string timeframes fall back to
    :data:`DEFAULT_MAX_AGE_SECONDS` (documented).
    """
    if timeframe is None:
        return DEFAULT_MAX_AGE_SECONDS
    key = str(timeframe).strip().upper()
    if not key:
        return DEFAULT_MAX_AGE_SECONDS
    return TIMEFRAME_MAX_AGE_SECONDS.get(key, DEFAULT_MAX_AGE_SECONDS)


# ---------------------------------------------------------------------------
# Parsing / evaluation
# ---------------------------------------------------------------------------
def _parse_ts(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp (or epoch seconds) to an aware datetime.

    Naive timestamps are assumed UTC (the feed loop stamps UTC). Returns
    ``None`` when the value is missing or unparseable.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        text = str(value).strip()
        if not text:
            return None
        # Support a trailing 'Z' (UTC) marker that fromisoformat rejects on
        # some Python versions.
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class FreshnessVerdict:
    """Deterministic verdict for one snapshot's freshness.

    ``accepted`` is True only when the snapshot is verifiably fresh for its
    timeframe and shows no clock anomaly. ``reason`` is a stable, machine-
    readable code (empty when accepted).
    """

    accepted: bool
    reason: str = ""
    age_seconds: Optional[float] = None
    max_allowed_age: Optional[float] = None
    timeframe: str = ""
    symbol: str = ""
    bar_timestamp: Optional[str] = None
    received_at: Optional[str] = None
    clock_anomaly: bool = False
    detail: str = ""
    fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise the verdict (UI/status surface)."""
        return {
            "accepted": self.accepted,
            "fresh": self.accepted,
            "reason": self.reason,
            "age_seconds": (round(self.age_seconds, 3) if self.age_seconds is not None else None),
            "max_allowed_age": self.max_allowed_age,
            "timeframe": self.timeframe,
            "symbol": self.symbol,
            "bar_timestamp": self.bar_timestamp,
            "received_at": self.received_at,
            "clock_anomaly": self.clock_anomaly,
            "detail": self.detail,
        }


def evaluate_freshness(
    snapshot: Any,
    *,
    timeframe: Any = None,
    symbol: Any = None,
    now: Optional[datetime] = None,
    max_age_override: Optional[float] = None,
) -> FreshnessVerdict:
    """Return the fail-closed freshness verdict for *snapshot*.

    Args:
        snapshot: The market-evidence dict (must carry ``bar_timestamp`` /
            ``received_at`` / ``age_seconds`` / ``timeframe`` / ``symbol``).
        timeframe: Optional explicit timeframe; falls back to the snapshot's
            ``timeframe`` field.
        symbol: Optional explicit symbol; falls back to the snapshot's.
        now: Injectable "now" (tests). Defaults to ``datetime.now(UTC)``.
        max_age_override: Optional hard override for the threshold (used by
            callers that need a stricter gate for a specific cycle).

    A non-dict / empty snapshot is rejected (``reason="snapshot_missing"``).
    Missing or unparseable timestamps are rejected (``reason="timestamp_unknown"``)
    — an unverifiable age is never trusted.
    """
    now = now or datetime.now(timezone.utc)
    if not isinstance(snapshot, dict) or not snapshot:
        return FreshnessVerdict(accepted=False, reason="snapshot_missing")

    tf = (
        str(timeframe if timeframe is not None else snapshot.get("timeframe", "") or "")
        .strip()
        .upper()
    )
    sym = str(symbol if symbol is not None else snapshot.get("symbol", "") or "").strip().upper()

    bar_ts_raw = snapshot.get("bar_timestamp")
    recv_ts_raw = snapshot.get("received_at")
    bar_dt = _parse_ts(bar_ts_raw)
    recv_dt = _parse_ts(recv_ts_raw)

    threshold = float(max_age_override) if max_age_override is not None else max_allowed_age(tf)

    def _reject(reason: str, *, clock: bool = False, detail: str = "") -> FreshnessVerdict:
        return FreshnessVerdict(
            accepted=False,
            reason=reason,
            age_seconds=None,
            max_allowed_age=threshold,
            timeframe=tf,
            symbol=sym,
            bar_timestamp=(str(bar_ts_raw) if bar_ts_raw not in (None, "") else None),
            received_at=(str(recv_ts_raw) if recv_ts_raw not in (None, "") else None),
            clock_anomaly=clock,
            detail=detail,
        )

    if bar_dt is None or recv_dt is None:
        # A snapshot without a verifiable bar/receive time cannot be trusted.
        return _reject(
            "timestamp_unknown",
            detail="bar_timestamp/received_at missing or unparseable",
        )

    # ── Clock anomalies (fail-closed) ───────────────────────────────────
    # 1) received_at < bar_timestamp → the data clock runs backwards.
    if recv_dt < bar_dt:
        return _reject(
            f"{STALE_REASON_PREFIX}:clock_anomaly_received_before_bar",
            clock=True,
            detail=f"received_at {recv_dt.isoformat()} < bar_timestamp {bar_dt.isoformat()}",
        )

    age = (recv_dt - bar_dt).total_seconds()

    # 2) Negative age must never be accepted as fresh.
    if age < 0:
        return _reject(
            f"{STALE_REASON_PREFIX}:negative_age",
            clock=True,
            detail=f"age_seconds={age:.3f} < 0",
        )

    # 3) Future timestamps beyond tolerance → reject.
    tolerance = CLOCK_SKEW_TOLERANCE_SECONDS
    if (recv_dt - now).total_seconds() > tolerance:
        return _reject(
            f"{STALE_REASON_PREFIX}:received_at_in_future",
            clock=True,
            detail=f"received_at {recv_dt.isoformat()} is ahead of now {now.isoformat()}",
        )
    if (bar_dt - now).total_seconds() > tolerance:
        return _reject(
            f"{STALE_REASON_PREFIX}:bar_timestamp_in_future",
            clock=True,
            detail=f"bar_timestamp {bar_dt.isoformat()} is ahead of now {now.isoformat()}",
        )

    # ── Age check (timeframe-aware) ─────────────────────────────────────
    if age > threshold:
        return FreshnessVerdict(
            accepted=False,
            reason=f"{STALE_REASON_PREFIX}:age_exceeded",
            age_seconds=age,
            max_allowed_age=threshold,
            timeframe=tf,
            symbol=sym,
            bar_timestamp=bar_dt.isoformat(),
            received_at=recv_dt.isoformat(),
            clock_anomaly=False,
            detail=f"age {age:.1f}s > max {threshold:.0f}s for {tf or 'unknown'}",
        )

    return FreshnessVerdict(
        accepted=True,
        reason="",
        age_seconds=age,
        max_allowed_age=threshold,
        timeframe=tf,
        symbol=sym,
        bar_timestamp=bar_dt.isoformat(),
        received_at=recv_dt.isoformat(),
        clock_anomaly=False,
        detail="fresh",
    )
