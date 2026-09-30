# -*- coding: utf-8 -*-
"""Phase 5 persistence + review building + research queue.
* ``CanonicalStore``: append-only JSONL keyed by record identity — idempotent
  across duplicates and process restarts (§22). Chunked collection-versioning.
* ``ReviewBuilder``: builds TradeReview/DecisionReview/CounterfactualReview
  from canonical input (deterministic quality criteria first, never LLM-only).
* ``ResearchQueue``: durable async queue (TRADE_CLOSED → persist review →
  enqueue research). Trading path never blocks on research; a research crash
  never breaks safety (§21).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Callable, Optional

from .canonical import CounterfactualReview, DecisionReview, TradeReview

logger = logging.getLogger(__name__)
__all__ = [
    "CanonicalStore",
    "ReviewBuilder",
    "ResearchQueue",
    "MIN_PATTERN_SAMPLE",
]


def _new_id(prefix: str) -> str:
    import uuid

    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# Minimum sample for a pattern to be OBSERVED instead of INSUFFICIENT_SAMPLE.
MIN_PATTERN_SAMPLE = 30


class CanonicalStore:
    """Append-only JSONL store for canonical learning records (fail-safe).
    Idempotent: records are keyed by (kind, identity); writing the same record
    twice does not duplicate. Survives restarts (reload on init).
    """

    def __init__(
        self, path: Optional[str] = None, identity_fn: Optional[Callable[[dict], str]] = None
    ) -> None:
        self.path = str(
            path or os.getenv("LEARNING_CANONICAL_PATH") or "logs/learning_canonical.jsonl"
        )
        self._lock = threading.RLock()
        self._records: dict[str, dict[str, Any]] = {}
        self._identity_fn = identity_fn or (
            lambda rec: str(
                rec.get(
                    "identity",
                    rec.get(
                        "snapshot_id",
                        rec.get(
                            "review_id",
                            rec.get(
                                "counterfactual_id",
                                rec.get("pattern_id", rec.get("hypothesis_id", id(rec))),
                            ),
                        ),
                    ),
                )
            )
        )
        self._load()

    # ------------------------------------------------------------------
    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(entry, dict) and "kind" in entry:
                        # Rebuild the SAME key shape write() uses (audit E2E-10:
                        # the identity_fn alone produced a different key on
                        # reload, so a restarted store duplicated records).
                        reload_key = f"{entry.get('kind')}:{entry.get('identity', '')}"
                        if entry.get("identity"):
                            self._records[reload_key] = entry
                        else:
                            self._records[self._identity_fn(entry)] = entry
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("CanonicalStore read failed: %s", exc)

    def write(self, kind: str, identity: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Write once (dedupe by identity). Returns the stored entry."""
        key = f"{kind}:{identity}"
        with self._lock:
            if key in self._records:
                return self._records[key]
            entry = {"kind": kind, "identity": identity, **dict(payload)}
            self._records[key] = entry
            try:
                parent = os.path.dirname(self.path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            except OSError as exc:
                logger.warning("CanonicalStore write failed (cache kept): %s", exc)
            return entry

    def get(self, kind: str, identity: str) -> Optional[dict[str, Any]]:
        with self._lock:
            return self._records.get(f"{kind}:{identity}")

    def query(
        self, kind: Optional[str] = None, predicate: Optional[Callable[[dict], bool]] = None
    ) -> list[dict[str, Any]]:
        """Deterministic query surface (no LLM) (§23)."""
        with self._lock:
            out = [r for r in self._records.values() if kind is None or r.get("kind") == kind]
        if predicate is not None:
            out = [r for r in out if predicate(r)]
        return out

    def count(self, kind: Optional[str] = None) -> int:
        return len(self.query(kind))

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            try:
                with open(self.path, "w", encoding="utf-8"):
                    pass
            except OSError:
                pass


# ----------------------------------------------------------------------
# Review builder (deterministic criteria first)
# ----------------------------------------------------------------------
class ReviewBuilder:
    """Builds canonical reviews from canonical Phase 4/4.5 inputs (§2)."""

    @staticmethod
    def realized_r(entry: float, exit_p: float, sl: float, direction: str) -> float:
        """Realized R multiple (deterministic)."""
        risk = abs(entry - sl) if sl else 0.0
        if risk <= 0:
            return 0.0
        signed = (exit_p - entry) if str(direction).upper() in ("BUY", "LONG") else (entry - exit_p)
        return round(signed / risk, 4)

    @staticmethod
    def decision_outcome_class(*, pnl: float, decision_quality: float) -> str:
        """GOOD/BAD × WIN/LOSS from deterministic criteria (§4)."""
        won = pnl > 0
        good = decision_quality >= 0.5
        if abs(pnl) == 0:
            return "BREAKEVEN"
        if good and won:
            return "GOOD_DECISION_WIN"
        if good and not won:
            return "GOOD_DECISION_LOSS"
        if not good and won:
            return "BAD_DECISION_WIN"
        return "BAD_DECISION_LOSS"

    def build_trade_review(self, *, review_id: str = "", **kw: Any) -> TradeReview:
        review_id = review_id or _new_id("rev")
        entry = float(kw.get("entry_price", 0.0) or 0.0)
        exit_p = float(kw.get("exit_price", 0.0) or 0.0)
        sl = float(kw.get("stop_loss", 0.0) or 0.0)
        direction = str(kw.get("direction", ""))
        realized_r = kw.get("realized_r")
        if realized_r is None:
            realized_r = self.realized_r(entry, exit_p, sl, direction)
        dq = float(kw.get("decision_quality", 0.0) or 0.0)
        pnl = float(kw.get("net_pnl", kw.get("gross_pnl", 0.0)) or 0.0)
        outcome = kw.get("outcome_class") or self.decision_outcome_class(
            pnl=pnl, decision_quality=dq
        )
        allowed = {
            "trade_id",
            "setup_id",
            "trigger_id",
            "strategy_version",
            "entry_timestamp",
            "exit_timestamp",
            "entry_price",
            "exit_price",
            "stop_loss",
            "take_profit",
            "planned_risk",
            "realized_risk",
            "planned_r",
            "gross_pnl",
            "net_pnl",
            "commission",
            "spread_cost",
            "slippage",
            "mae",
            "mfe",
            "holding_duration_s",
            "zone_type",
            "trigger_type",
            "mitigation_state",
            "retest_count",
            "regime",
            "session",
            "volatility_state",
            "news_state",
            "decision_quality",
            "entry_quality",
            "risk_quality",
            "execution_quality",
            "reason_codes",
            "evidence_refs",
        }
        filtered = {k: v for k, v in kw.items() if k in allowed}
        filtered.pop("net_pnl", None)  # passed explicitly below (computed pnl)
        return TradeReview(
            review_id=review_id,
            realized_r=realized_r,
            outcome_class=outcome,
            net_pnl=pnl,
            **filtered,
        )

    @staticmethod
    def build_decision_review(*, review_id: str = "", **kw: Any) -> DecisionReview:
        review_id = review_id or _new_id("drev")
        allowed = {
            "event_id",
            "decision_timestamp",
            "decision_state",
            "direction",
            "setup_id",
            "zone_type",
            "trigger_type",
            "reason_codes",
            "blocking_conditions",
            "missing_conditions",
            "evidence_refs",
            "risk_decision",
            "strategy_version",
        }
        filtered = {k: v for k, v in kw.items() if k in allowed}
        return DecisionReview(review_id=review_id, **filtered)

    @staticmethod
    def build_counterfactual(
        *,
        counterfactual_id: str = "",
        direction: str,
        entry_reference_price: float,
        hypothetical_sl: float,
        hypothetical_tp: float,
        future_high: float,
        future_low: float,
        review_id: str = "",
        setup_id: str = "",
        decision_timestamp: str = "",
        future_data_used_up_to: str = "",
    ) -> CounterfactualReview:
        """Point-in-time-safe counterfactual (§6).
        Uses ONLY the decision-time entry reference + subsequent realized
        range (future_high/future_low AFTER the decision) to classify.
        Never invents a better entry; if SL and TP were both reachable the
        outcome is INVALID_COUNTERFACTUAL (ambiguous order).
        """
        counterfactual_id = counterfactual_id or _new_id("cf")
        is_long = str(direction).upper() in ("BUY", "LONG")
        if entry_reference_price <= 0 or future_high <= 0 or future_low <= 0:
            outcome = "INSUFFICIENT_FUTURE_DATA"
            move_r = 0.0
        else:
            risk = abs(entry_reference_price - hypothetical_sl) if hypothetical_sl else 0.0
            if risk <= 0:
                outcome, move_r = "INVALID_COUNTERFACTUAL", 0.0
            else:
                if is_long:
                    hit_tp = future_high >= hypothetical_tp > 0
                    hit_sl = future_low <= hypothetical_sl
                else:
                    hit_tp = future_low <= hypothetical_tp > 0 if hypothetical_tp else False
                    hit_sl = future_high >= hypothetical_sl
                if hit_tp and hit_sl:
                    outcome, move_r = "INVALID_COUNTERFACTUAL", 0.0
                elif hit_tp and not hit_sl:
                    outcome = "WOULD_HAVE_WON"
                    move_r = round(abs(hypothetical_tp - entry_reference_price) / risk, 4)
                elif hit_sl and not hit_tp:
                    outcome = "WOULD_HAVE_LOST"
                    move_r = round(-1.0, 4)
                elif hypothetical_tp and (
                    (is_long and future_high < hypothetical_tp and future_low > hypothetical_sl)
                    or (
                        not is_long
                        and future_low > hypothetical_tp
                        and future_high < hypothetical_sl
                    )
                ):
                    outcome, move_r = "WOULD_HAVE_BEEN_BREAKEVEN", 0.0
                else:
                    # Neither target hit within observed range → did not trigger
                    # a resolvable outcome.
                    outcome, move_r = "WOULD_NOT_HAVE_TRIGGERED", 0.0
        return CounterfactualReview(
            counterfactual_id=counterfactual_id,
            review_id=review_id,
            setup_id=setup_id,
            direction=str(direction).upper(),
            decision_timestamp=decision_timestamp,
            entry_reference_price=entry_reference_price,
            hypothetical_sl=hypothetical_sl,
            hypothetical_tp=hypothetical_tp,
            outcome=outcome,
            realized_move_r=move_r,
            future_data_used_up_to=future_data_used_up_to,
        )


# ----------------------------------------------------------------------
# Research queue (async, failure-isolated)
# ----------------------------------------------------------------------
class ResearchQueue:
    """Durable async queue: persist review → enqueue research (§21).
    The trading path calls :meth:`submit` (non-blocking, never raises). A
    worker drains via :meth:`drain` (called by a scheduler, never inline in
    the execution hot path). A research crash is swallowed + counted.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = str(path or os.getenv("RESEARCH_QUEUE_PATH") or "logs/research_queue.jsonl")
        self._lock = threading.RLock()
        self._pending: list[dict[str, Any]] = []
        self.errors = 0
        self.processed = 0
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(entry, dict) and entry.get("status") == "pending":
                        self._pending.append(entry)
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("ResearchQueue read failed: %s", exc)

    def submit(self, payload: dict[str, Any]) -> None:
        """Enqueue one research job (never raises, never blocks trading)."""
        try:
            with self._lock:
                entry = {"status": "pending", **dict(payload)}
                self._pending.append(entry)
                parent = os.path.dirname(self.path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except Exception as exc:  # noqa: BLE001 - queue must never break trading
            logger.warning("ResearchQueue submit failed: %s", exc)

    def drain(self, handler: Callable[[dict[str, Any]], None], limit: int = 25) -> int:
        """Process up to ``limit`` jobs; a handler crash is isolated + counted."""
        done = 0
        with self._lock:
            batch = self._pending[: max(0, int(limit))]
            self._pending = self._pending[len(batch) :]
        for job in batch:
            try:
                handler(job)
                self.processed += 1
                done += 1
            except Exception as exc:  # noqa: BLE001 - isolate research failures
                self.errors += 1
                logger.warning("Research job failed (isolated): %s", exc)
        return done

    def depth(self) -> int:
        with self._lock:
            return len(self._pending)
