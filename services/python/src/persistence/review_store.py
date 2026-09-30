# -*- coding: utf-8 -*-
"""Review store — durable auto-triggered reviews (spec §3.5 / §3.6).

The review store is a separate ledger from existing lesson stores. Its job is
to persist the *outcome* of post-trade reviews that survive restarts — win rate,
R-multiples, root causes, quality scores. The same record may live in memory for
fast querying while also being append-only to disk so a restart rehydrates the
latest view without recomputing history.

Design mirrors the other B-5 stores (``order_state_store`` / ``entry_context_store``):
append-only JSONL + a bounded in-memory cache, guarded by a plain ``Lock`` (single
operation at a time), and fail-safe — write failures are logged and the cache
stays intact rather than raising into the review path.

Memory discipline: the cache is a bounded ``OrderedDict`` trimmed to
``max_entries`` (oldest evicted first) to keep RSS bounded; the file holds all
reviews indefinitely.

Idempotence: each review is keyed by ``review_id = hash(trade_id + closed_at)``.
Duplicates are detected before persistence and skipped to avoid double-counting.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from collections import OrderedDict
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["ReviewStore", "get_review_store", "set_review_store"]

_DEFAULT_PATH = os.path.join("logs", "reviews.jsonl")

# Process-wide review store registry (mirrors review.entry_context pattern).
# ``set_review_store`` is called at startup; ``get_review_store`` is the read
# path. Optional so the module works standalone.
_REVIEW_STORE: Optional["ReviewStore"] = None
_REVIEW_STORE_LOCK = threading.Lock()


def set_review_store(store: Optional["ReviewStore"]) -> None:
    """Wire (or clear) the process-wide review store instance."""
    global _REVIEW_STORE
    with _REVIEW_STORE_LOCK:
        _REVIEW_STORE = store


def get_review_store() -> Optional["ReviewStore"]:
    """Return the wired review store, or ``None`` when unset."""
    with _REVIEW_STORE_LOCK:
        return _REVIEW_STORE


# Spec §3.5 schema: fields persisted per review. Unknown keys are dropped when
# loading so schema drifts can evolve without breaking old files.
FIELDS = (
    "review_id",
    "trade_id",
    "outcome",
    "pnl",
    "r_multiple",
    "decision_quality_score",
    "execution_quality_score",
    "timing_score",
    "root_cause_primary",
    "root_cause_confidence",
    "secondary_causes",
    "summary",
    "closed_at",
)


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now().astimezone().isoformat()


def _idempotent_key(trade_id: Any, closed_at: Any) -> Optional[str]:
    """Create a deterministic review_id by hashing (trade_id + closed_at)."""
    if trade_id is None or closed_at is None:
        return None
    payload = f"{str(trade_id)}||{str(closed_at)}"
    # 40 chars hex digest → safe for dict keys and short IDs.
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()[:40]


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


def _comparable(value: datetime) -> float:
    """Normalise a ``datetime`` to an epoch float for comparison."""
    if value.tzinfo is None:
        return value.timestamp()
    return value.timestamp()


class ReviewStore:
    """Append-only JSONL review store with a bounded in-memory cache.

    Args:
        path: File to persist to. Defaults to ``REVIEW_STORE_PATH`` env or
            ``logs/reviews.jsonl``.
        max_entries: Maximum number of reviews kept in the cache (oldest evicted
            first). Bounded memory regardless of review volume. Defaults to 2000.
    """

    def __init__(self, path: Optional[str] = None, max_entries: int = 2000) -> None:
        self.path = str(path or os.getenv("REVIEW_STORE_PATH") or _DEFAULT_PATH)
        self._max_entries = max(1, int(max_entries))
        self._reviews: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        # Guards the read-modify-append sequence so a concurrent add cannot
        # interleave a stale record into the JSONL. RLock (reentrant) because
        # add_review holds the lock while _append_line re-acquires it — same
        # pattern as entry_context_store / order_state_store.
        self._lock = threading.RLock()
        self._load()

    # ------------------------------------------------------------------ load
    def _load(self) -> None:
        """Load persisted reviews; corrupt lines are skipped (fail-safe)."""
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("Skipping corrupt review line in %s", self.path)
                        continue
                    if not isinstance(entry, dict):
                        continue
                    review_id = entry.get("review_id")
                    if review_id is None:
                        continue
                    key = str(review_id)
                    # Later lines win (append-only, last record is newest).
                    self._reviews.pop(key, None)
                    self._reviews[key] = entry
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("Could not read review store %s: %s", self.path, exc)
        self._trim()

    def _trim(self) -> None:
        """Evict oldest reviews beyond the cap (bounded memory)."""
        while len(self._reviews) > self._max_entries:
            self._reviews.popitem(last=False)

    # ------------------------------------------------------------------ write
    def add_review(self, review_data: dict) -> bool:
        """Persist a review if it's new; return False on duplicate/skip.

        Returns:
            True if the review was appended to disk (new or reprocessed),
            False if the review was detected as a duplicate by its idempotent
            key and skipped.
        """
        if not isinstance(review_data, dict):
            return False

        # Determine idempotent key unless already provided
        review_id = review_data.get("review_id")
        if review_id is None:
            review_id = _idempotent_key(review_data.get("trade_id"), review_data.get("closed_at"))
        if review_id is None:
            logger.warning("add_review called without a valid review_id; skipping")
            return False

        key = str(review_id)

        with self._lock:
            # Check for duplicate
            if key in self._reviews:
                logger.debug("Duplicate review %s detected; skipping", key)
                return False

            # Keep only spec fields and ensure required metadata
            record = {k: v for k, v in review_data.items() if k in FIELDS}
            record["review_id"] = review_id
            if not record.get("closed_at"):
                record["closed_at"] = _now_iso()

            # Cache update + trim + persist (fail-safe)
            self._reviews.pop(key, None)
            self._reviews[key] = record
            self._trim()
            self._append_line(record)
            return True

    # ------------------------------------------------------------------ query
    def recent(self, limit: int = 50) -> list[dict]:
        """Return the newest reviews up to *limit*, newest first."""
        if limit < 0:
            raise ValueError(f"recent limit must be non-negative, got {limit}")
        with self._lock:
            records = list(self._reviews.values())
        out: list[dict] = []
        for r in reversed(records):
            if len(out) >= limit:
                break
            out.append(dict(r))
        return out

    def stats(self) -> dict[str, Any]:
        """Compute summary statistics across all cached reviews.

        Returns:
            A shallow-dict containing:
              - total_reviews: count of all reviews
              - total_with_r: count where r_multiple is not None and numeric
              - total_without_r: count where r_multiple is missing/invalid
              - win_rate: percentage of wins among those with R (0..100)
              - avg_r: average R-multiple among those with R (or None)
        """
        total = 0
        with_r = 0
        wins = 0
        r_sum: float = 0.0

        with self._lock:
            records = list(self._reviews.values())

        for r in records:
            total += 1
            rm = r.get("r_multiple")
            if rm is not None:
                try:
                    val = float(rm)
                    r_sum += val
                    with_r += 1
                    if val > 0:
                        wins += 1
                except (TypeError, ValueError):
                    pass

        win_rate = 100.0 * wins / with_r if with_r > 0 else None
        avg_r = r_sum / with_r if with_r > 0 else None

        return {
            "total_reviews": total,
            "total_with_r": with_r,
            "total_without_r": total - with_r,
            "win_rate": win_rate,
            "avg_r": avg_r,
        }

    def clear(self) -> None:
        """Drop all cached reviews and truncate the file."""
        with self._lock:
            self._reviews.clear()
            try:
                parent = os.path.dirname(self.path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                with open(self.path, "w", encoding="utf-8"):
                    pass
            except OSError as exc:
                logger.warning("Could not truncate review store %s: %s", self.path, exc)

    def size(self) -> int:
        """Return the number of cached reviews."""
        with self._lock:
            return len(self._reviews)

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
                    "Could not persist review to %s (cache kept): %s",
                    self.path,
                    exc,
                )
