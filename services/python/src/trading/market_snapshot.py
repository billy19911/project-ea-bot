# -*- coding: utf-8 -*-
"""Latest market snapshot cache — the evidence bridge between feed and analysis.

The market feed loop reads MT5 OHLC (read-only), detects events, and computes
the market state. This module stores the latest snapshot per symbol so any
pipeline cycle — including a manual ``POST /pipeline/run`` that carries no
evidence — can still analyse the market with the most recent real data.

Safety: this module is pure in-memory bookkeeping. It imports no MT5, no
execution and no order code, and it can never place an order.
"""

from __future__ import annotations

import threading
from typing import Any, Optional

__all__ = [
    "set_latest_snapshot",
    "get_latest_snapshot",
    "clear_latest_snapshots",
]

# Bounded per-symbol cache (one snapshot per symbol; the newest wins).
_snapshots: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def set_latest_snapshot(symbol: str, snapshot: dict[str, Any]) -> None:
    """Store ``snapshot`` as the latest evidence for ``symbol``.

    Non-dict payloads are ignored so a caller bug can never poison the cache.
    """
    if not isinstance(snapshot, dict) or not snapshot:
        return
    key = str(symbol or "").strip().upper()
    with _lock:
        _snapshots[key] = snapshot


def get_latest_snapshot(symbol: str) -> Optional[dict[str, Any]]:
    """Return the latest snapshot for ``symbol`` (``None`` when absent).

    An empty ``symbol`` falls back to the single cached entry when exactly one
    symbol is tracked (single-symbol deployments), otherwise ``None``.
    """
    key = str(symbol or "").strip().upper()
    with _lock:
        if key:
            snapshot = _snapshots.get(key)
            if snapshot is not None:
                return snapshot
            if len(_snapshots) == 1:
                return next(iter(_snapshots.values()))
            return None
        if len(_snapshots) == 1:
            return next(iter(_snapshots.values()))
        return None


def clear_latest_snapshots() -> None:
    """Drop every cached snapshot (used by tests and resets)."""
    with _lock:
        _snapshots.clear()
