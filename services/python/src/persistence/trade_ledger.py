# -*- coding: utf-8 -*-
"""Persistent trade ledger — append-only JSONL store (spec §3.1 / §3.2).

The trade ledger is the single durable record of every trade's full lifecycle:
entry context, risk snapshot, exit result, broker tickets, and the post-trade
review status. It is the source of truth the Performance / R-multiple views and
the review pipeline read from, so it MUST survive a restart.

Design mirrors the other B-5 stores (``order_state_store`` / ``entry_context_store``
/ ``position_reconciliation_store``): append-only JSONL + a bounded in-memory
cache, guarded by an ``RLock``, and fully fail-safe — an OS error is logged and
the cache is kept rather than raising into the caller's trade path.

Memory discipline: the cache is a bounded ``OrderedDict`` trimmed to
``max_entries`` (oldest evicted first), so memory stays bounded regardless of
trade volume. The append-only file remains the complete history.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections import OrderedDict
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["TradeLedger", "get_trade_ledger", "set_trade_ledger"]

_DEFAULT_PATH = os.path.join("logs", "trade_ledger.jsonl")

# Process-wide ledger registry (mirrors review.entry_context's module-level
# store). ``set_trade_ledger`` is called at startup; ``get_trade_ledger`` is the
# read path for the close/review code. Optional so the module works standalone.
_LEDGER: Optional["TradeLedger"] = None
_LEDGER_LOCK = threading.Lock()


def set_trade_ledger(ledger: Optional["TradeLedger"]) -> None:
    """Wire (or clear) the process-wide trade ledger instance."""
    global _LEDGER
    with _LEDGER_LOCK:
        _LEDGER = ledger


def get_trade_ledger() -> Optional["TradeLedger"]:
    """Return the wired trade ledger, or ``None`` when unset."""
    with _LEDGER_LOCK:
        return _LEDGER


# Spec §3.1 — the exact field set of a trade ledger record. ``add_trade`` keeps
# only these keys (missing keys are left absent; unknown keys are dropped) so the
# JSONL stays schema-stable even if a caller passes a fatter dict.
FIELDS = (
    "trade_id",
    "signal_id",
    "opportunity_id",
    "account_id",
    "terminal_id",
    "symbol",
    "direction",
    "volume",
    "entry_price",
    "initial_stop_loss",
    "initial_take_profit",
    "initial_risk_price_distance",
    "initial_risk_money",
    "target_rr",
    "opened_at",
    "closed_at",
    "exit_price",
    "pnl",
    "r_multiple",
    "close_reason",
    "broker_order_ticket",
    "broker_deal_ticket",
    "broker_position_ticket",
    "status",
    "review_status",
    "created_at",
    "updated_at",
)


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now().astimezone().isoformat()


def _slim(trade: dict[str, Any]) -> dict[str, Any]:
    """Return only the spec §3.1 fields present in *trade*."""
    return {key: trade[key] for key in FIELDS if key in trade}


def _parse_since(value: Any) -> Optional[datetime]:
    """Coerce *value* to a ``datetime`` for comparison, or ``None`` if unparseable."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value))
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _as_datetime(value: Any) -> Optional[datetime]:
    """Best-effort coercion of a record timestamp to ``datetime`` (tz-aware)."""
    return _parse_since(value)


class TradeLedger:
    """Append-only JSONL trade ledger with a bounded in-memory cache.

    Args:
        path: File to persist to. Defaults to ``TRADE_LEDGER_PATH`` env or
            ``logs/trade_ledger.jsonl``.
        max_entries: Maximum number of trades kept in the cache (oldest evicted
            first). Bounded memory regardless of trade volume. Defaults to 5000.
    """

    def __init__(self, path: Optional[str] = None, max_entries: int = 5000) -> None:
        self.path = str(path or os.getenv("TRADE_LEDGER_PATH") or _DEFAULT_PATH)
        self._max_entries = max(1, int(max_entries))
        self._trades: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        # Guards the read-modify-append sequence so a concurrent update cannot
        # interleave a stale record into the JSONL.
        self._lock = threading.RLock()
        self._load()

    # ------------------------------------------------------------------ load
    def _load(self) -> None:
        """Load persisted trades; corrupt lines are skipped (fail-safe)."""
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("Skipping corrupt trade ledger line in %s", self.path)
                        continue
                    if not isinstance(entry, dict):
                        continue
                    trade_id = entry.get("trade_id")
                    if trade_id is None:
                        continue
                    key = str(trade_id)
                    # Later lines win (append-only, last record is newest).
                    self._trades.pop(key, None)
                    self._trades[key] = entry
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("Could not read trade ledger store %s: %s", self.path, exc)
        self._trim()

    def _trim(self) -> None:
        """Evict oldest trades beyond the cap (bounded memory)."""
        while len(self._trades) > self._max_entries:
            self._trades.popitem(last=False)

    # ----------------------------------------------------------------- write
    def add_trade(self, trade_data: dict) -> None:
        """Persist a trade record (create or replace by ``trade_id``).

        Only the spec §3.1 fields are kept. ``created_at``/``updated_at`` are
        stamped when absent. A write failure degrades to cache-only (the record
        stays in memory and an OS error is logged) — never raises.
        """
        if not isinstance(trade_data, dict):
            return
        trade_id = trade_data.get("trade_id")
        if trade_id is None:
            logger.warning("add_trade called without trade_id; skipping")
            return
        key = str(trade_id)

        with self._lock:
            record = _slim(trade_data)
            record["trade_id"] = trade_id
            if not record.get("created_at"):
                record["created_at"] = _now_iso()
            record["updated_at"] = _now_iso()
            self._trades.pop(key, None)
            self._trades[key] = record
            self._trim()
            self._append_line(record)

    def update_trade(self, trade_id: Any, updates: dict) -> None:
        """Update specific fields of an existing trade (append-only write).

        Unknown keys are ignored; only spec §3.1 fields are applied.
        """
        if trade_id is None or not isinstance(updates, dict):
            return
        key = str(trade_id)
        with self._lock:
            record = dict(self._trades.get(key, {"trade_id": trade_id}))
            for field, value in updates.items():
                if field in FIELDS:
                    record[field] = value
            record["trade_id"] = trade_id
            if not record.get("created_at"):
                record["created_at"] = _now_iso()
            record["updated_at"] = _now_iso()
            self._trades.pop(key, None)
            self._trades[key] = record
            self._trim()
            self._append_line(record)

    # ------------------------------------------------------------------ read
    def get_trade(self, trade_id: Any) -> dict:
        """Return a shallow copy of the trade for *trade_id*, or ``{}``."""
        if trade_id is None:
            return {}
        key = str(trade_id)
        with self._lock:
            raw = self._trades.get(key)
            if raw is None:
                return {}
            return dict(raw)

    def query(
        self,
        status: Optional[str] = None,
        symbol: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> list[dict]:
        """Return trades matching the given filters (each an exact match).

        Args:
            status: Only trades whose ``status`` equals this value.
            symbol: Only trades whose ``symbol`` equals this value.
            since: Only trades with ``opened_at`` (fallback ``created_at``) at or
                after this ``datetime``. Unparseable timestamps are skipped when
                a ``since`` filter is set.

        Returns:
            A list of shallow copies, newest-first (cache insertion order).
        """
        since_dt = _parse_since(since)
        out: list[dict] = []
        with self._lock:
            records = list(self._trades.values())
        for record in records:
            if status is not None and record.get("status") != status:
                continue
            if symbol is not None and record.get("symbol") != symbol:
                continue
            if since_dt is not None:
                stamp = _as_datetime(record.get("opened_at") or record.get("created_at"))
                if stamp is None:
                    continue
                if _comparable(stamp) < _comparable(since_dt):
                    continue
            out.append(dict(record))
        out.reverse()
        return out

    # ----------------------------------------------------------- cache admin
    def pop(self, trade_id: Any) -> dict:
        """Return and remove the cached trade for *trade_id*.

        Pop only affects the in-memory cache; the append-only file keeps the
        record (a later restart would reload it, which is harmless).
        """
        if trade_id is None:
            return {}
        key = str(trade_id)
        with self._lock:
            raw = self._trades.pop(key, None)
        if raw is None:
            return {}
        return dict(raw)

    def clear(self) -> None:
        """Drop all cached trades and truncate the file."""
        with self._lock:
            self._trades.clear()
            try:
                parent = os.path.dirname(self.path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                with open(self.path, "w", encoding="utf-8"):
                    pass
            except OSError as exc:
                logger.warning("Could not truncate trade ledger store %s: %s", self.path, exc)

    def size(self) -> int:
        """Return the number of cached trades."""
        with self._lock:
            return len(self._trades)

    # --------------------------------------------------------------- persist
    def _append_line(self, record: dict[str, Any]) -> None:
        """Persist one record; a write failure degrades to cache-only."""
        with self._lock:
            try:
                parent = os.path.dirname(self.path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            except OSError as exc:
                logger.warning(
                    "Could not persist trade ledger to %s (cache kept): %s",
                    self.path,
                    exc,
                )


def _comparable(value: datetime) -> float:
    """Normalise a ``datetime`` to an epoch float (naive → local tz) for compare."""
    if value.tzinfo is None:
        return value.timestamp()
    return value.timestamp()
