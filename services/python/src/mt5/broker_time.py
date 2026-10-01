# -*- coding: utf-8 -*-
"""Broker-time conversion helpers (fixed offset, no tz database needed).

Measured live on the attached terminals (epoch probes): every epoch value MT5
reports AND accepts — ticks, bars, deals, ``copy_rates_*`` range endpoints —
lives in *broker server wall-clock* space rendered as if it were UTC, i.e.
``true_utc + 3 h`` for the servers in use. Rendering raw epochs with
``datetime.fromtimestamp`` (naive LOCAL) made every bar look ~10 h in the
future on a UTC+7 host, so the freshness gate rejected all data with
``clock_anomaly_received_before_bar`` and the committee ran on nothing.

Conversions (one rule for every MT5 API):

- out: ``from_broker_epoch(ts)`` → aware-UTC ``ts - 3 h`` (true UTC);
- in:  ``to_broker_epoch(dt)``    → raw epoch ``dt + 3 h`` (naive dt is
  assumed UTC, the documented convention for internal timestamps).

``zoneinfo``/``tzdata`` are not available in the runtime venv, so the offset
is a fixed measured constant instead of a tz database lookup.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

__all__ = ["BROKER_UTC_OFFSET", "from_broker_epoch", "to_broker_epoch"]

# Measured offset of the broker server wall clock vs true UTC (tick probe:
# raw 16:26:06 vs true UTC 13:26:05 → 10800 s).
BROKER_UTC_OFFSET = timedelta(hours=3)


def from_broker_epoch(value) -> datetime:
    """Raw MT5 epoch → aware-UTC datetime carrying the *true* UTC instant."""
    return datetime.fromtimestamp(float(value), tz=timezone.utc) - BROKER_UTC_OFFSET


def to_broker_epoch(value: datetime) -> int:
    """True datetime → raw MT5 epoch (broker wall clock rendered as epoch).

    Naive datetimes are interpreted as UTC — the internal convention — so a
    stripped-tz caller datetime is converted correctly regardless of the host
    timezone.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp()) + int(BROKER_UTC_OFFSET.total_seconds())
