# -*- coding: utf-8 -*-
"""LEDGER-SLTP T2 — stale-ledger backfill (close ticketed rows the broker no
longer holds).

The durable order ledger (``services/python/logs/order_state.jsonl``) is
append-only and, before T1, never wrote a ``closed`` state. Every historical
``position_confirmed``/``filled`` record therefore counted as an *open internal
position* forever; reconciliation reported those tickets as
``missing_in_broker`` (critical), which permanently blocked new orders behind
the reconciliation guard.

This standalone CLI closes exactly the stale subset — the records whose latest
state is ``position_confirmed``/``filled``, that carry a ticket, and whose
ticket is **absent from the broker's verified position list** — by appending a
``closed`` record (reason ``stale_backfill``) through the same
:meth:`OrderStateStore.mark_closed` path the live service uses.

Safety model (fail-closed, mirrors the service):

1. **Verified broker read** — positions come from
   :func:`mt5.connector.get_positions_ex`, which distinguishes a genuinely
   empty book (``ok=True``) from a failed read (``ok=False``). On ``ok=False``
   the run ABORTS with a non-zero exit and closes nothing.
2. **Dry-run by default** — without ``--apply`` nothing is written; the
   candidate table is printed for inspection.
3. **Idempotent** — a re-run finds the already-closed records and reports zero
   candidates; no duplicate ``closed`` rows are appended.
4. **No secrets** — credentials/tokens are never printed.

Import bootstrap: ``import src.*`` only resolves with cwd ``services/python``.
This script resolves the repo root from ``__file__``, chdirs into
``services/python`` and prepends it to ``sys.path`` BEFORE importing ``src.*``
(the same pattern as ``scripts/b4_demo_validation.py``).

Usage:
    python scripts/ledger_close_stale.py                # dry-run (all)
    python scripts/ledger_close_stale.py --ticket 150614
    python scripts/ledger_close_stale.py --apply        # write closes
    python scripts/ledger_close_stale.py --ledger path/to/order_state.jsonl
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Import bootstrap (must run BEFORE any ``src.*`` import)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SERVICES_PY = _REPO_ROOT / "services" / "python"

# Default ledger, resolved from the repo root (NOT the cwd), so the script
# always targets the service's ledger regardless of where it is invoked from.
DEFAULT_LEDGER = _SERVICES_PY / "logs" / "order_state.jsonl"

# Order states that mean "the engine believes a position exists".
POSITION_STATES = frozenset({"position_confirmed", "filled"})

# Close reason persisted on every backfilled record.
BACKFILL_REASON = "stale_backfill"


def _bootstrap_import_path() -> None:
    """chdir into ``services/python`` and put it first on ``sys.path``."""
    target = str(_SERVICES_PY)
    if target in sys.path:
        sys.path.remove(target)
    sys.path.insert(0, target)
    try:
        os.chdir(target)
    except OSError:
        # Leave the cwd unchanged; sys.path alone still makes ``src.*`` import.
        pass


class BackfillAbort(RuntimeError):
    """Raised when a guard aborts the run before anything is written."""


@dataclass
class StaleCandidate:
    """One stale ledger record eligible for backfill."""

    intent_id: str
    ticket: Any
    state: str
    timestamp: Optional[str]

    @property
    def age_days(self) -> Optional[float]:
        ts = _parse_timestamp(self.timestamp)
        if ts is None:
            return None
        return (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0


def _parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp (tolerant of a trailing ``Z``)."""
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


# ---------------------------------------------------------------------------
# Core selection / application
# ---------------------------------------------------------------------------


def latest_state_per_intent(
    orders: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Resolve the latest record per intent (append-only → last wins).

    ``OrderStateStore`` keeps one entry per ``intent_id`` and overwrites it on
    each append, so ``all_orders()`` already reflects the latest state. This
    helper is written defensively so a caller may also pass a raw list of
    records (last occurrence per intent wins), keeping the selection semantics
    identical to the store.
    """
    resolved: dict[str, dict[str, Any]] = {}
    for intent_id, record in orders.items():
        if isinstance(record, dict):
            resolved[intent_id] = record
    return resolved


def select_stale_candidates(
    orders: dict[str, dict[str, Any]],
    broker_tickets: set[str],
    ticket_filter: Optional[Any] = None,
) -> tuple[list[StaleCandidate], int, int]:
    """Return ``(candidates, skipped_no_ticket, skipped_closed)``.

    A record is a stale candidate when its **latest** state is in
    ``POSITION_STATES``, it carries a ticket, and that ticket is not in
    ``broker_tickets``. Records already in ``closed`` are never candidates (the
    edit is idempotent); records without a ticket are counted and skipped (they
    cannot be joined to the broker).
    """
    candidates: list[StaleCandidate] = []
    skipped_no_ticket = 0
    skipped_closed = 0

    if ticket_filter is not None:
        filter_key = str(ticket_filter)

    for intent_id, record in latest_state_per_intent(orders).items():
        state = str(record.get("state", "")).lower()
        if state == "closed":
            skipped_closed += 1
            continue

        ticket = record.get("ticket")
        if ticket is None:
            # Only count no-ticket records that would otherwise be eligible, so
            # the "skipped" number means "open record we could not join".
            if state in POSITION_STATES:
                skipped_no_ticket += 1
            continue

        if state not in POSITION_STATES:
            continue

        if ticket_filter is not None and str(ticket) != filter_key:
            continue

        if str(ticket) in broker_tickets:
            # Ticket still open on the broker → not stale.
            continue

        candidates.append(
            StaleCandidate(
                intent_id=intent_id,
                ticket=ticket,
                state=state,
                timestamp=record.get("timestamp"),
            )
        )

    candidates.sort(key=lambda c: str(c.ticket))
    return candidates, skipped_no_ticket, skipped_closed


def apply_backfill(store: Any, candidates: list[StaleCandidate]) -> int:
    """Append a ``closed`` record per candidate via ``mark_closed``.

    Returns the number of records actually written (``mark_closed`` returns
    ``False`` for an already-closed/no-op ticket, so a re-run reports 0).
    """
    written = 0
    for candidate in candidates:
        if store.mark_closed(candidate.ticket, reason=BACKFILL_REASON):
            written += 1
    return written


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class StaleBackfill:
    """Orchestrates the read → select → (apply) flow for one ledger."""

    def __init__(
        self,
        *,
        ledger_path: Path,
        apply: bool = False,
        ticket: Optional[Any] = None,
        connector_module: Any = None,
        store: Any = None,
        stdout: Any = None,
    ) -> None:
        self.ledger_path = Path(ledger_path)
        self.apply = bool(apply)
        self.ticket = ticket
        self._connector_module = connector_module
        self._store = store
        self._out = stdout or sys.stdout

    # -- infrastructure -----------------------------------------------------

    @property
    def connector(self) -> Any:
        if self._connector_module is None:
            from src.mt5 import connector

            self._connector_module = connector
        return self._connector_module

    def _log(self, message: str) -> None:
        print(message, file=self._out)

    def _open_store(self) -> Any:
        """Instantiate the durable store pointed at the same ledger file."""
        if self._store is not None:
            return self._store
        from src.persistence.order_state_store import OrderStateStore

        return OrderStateStore(path=str(self.ledger_path))

    # -- broker read --------------------------------------------------------

    def _broker_position_tickets(self) -> set[str]:
        """Read broker positions via the verified connector path.

        ``get_positions_ex()`` returns ``(ok, positions)``. ``ok=False`` means
        the read failed (terminal detached) — the caller must ABORT rather than
        treat the empty list as "no positions" (the T1 false-close guard).
        """
        get_positions_ex = getattr(self.connector, "get_positions_ex", None)
        if get_positions_ex is None:  # pragma: no cover - legacy connector
            raise BackfillAbort(
                "connector has no get_positions_ex() — cannot verify the broker "
                "read; refusing to close anything."
            )
        ok, positions = get_positions_ex()
        if not ok:
            raise BackfillAbort(
                "broker position read was NOT verified (get_positions_ex() -> ok=False). "
                "The MT5 terminal may be detached. Aborting without closing anything."
            )
        tickets: set[str] = set()
        for pos in positions or []:
            ticket = getattr(pos, "ticket", None)
            if ticket is None and isinstance(pos, dict):
                ticket = pos.get("ticket")
            if ticket is not None:
                tickets.add(str(ticket))
        return tickets

    # -- run ----------------------------------------------------------------

    def run(self) -> int:
        """Execute the backfill flow. Returns a process exit code."""
        try:
            if not self.ledger_path.exists():
                raise BackfillAbort(f"ledger not found: {self.ledger_path}")

            broker_tickets = self._broker_position_tickets()
            self._log(f"Ledger: {self.ledger_path}")
            self._log(f"Broker positions: {len(broker_tickets)} ticket(s)")
            if self.ticket is not None:
                self._log(f"Ticket filter: {self.ticket}")
            mode = "APPLY" if self.apply else "DRY-RUN"
            self._log(f"Mode: {mode}")
            self._log("")

            store = self._open_store()
            orders = store.all_orders()
            candidates, skipped_no_ticket, skipped_closed = select_stale_candidates(
                orders, broker_tickets, ticket_filter=self.ticket
            )

            self._print_table(candidates)
            self._log("")
            self._log(f"Candidates: {len(candidates)}")
            self._log(f"Skipped (no ticket, open state): {skipped_no_ticket}")
            self._log(f"Already closed: {skipped_closed}")

            if not self.apply:
                self._log("")
                self._log("DRY-RUN — nothing written. Re-run with --apply to close.")
                return 0

            written = apply_backfill(store, candidates)
            self._log("")
            self._log(
                f"Backfilled: {written} record(s) closed (reason={BACKFILL_REASON})."
            )
            return 0

        except BackfillAbort as exc:
            self._log(f"ABORTED: {exc}")
            return 2
        except Exception as exc:  # noqa: BLE001 - surface unexpected failures
            self._log(f"ERROR: {exc}")
            return 1

    def _print_table(self, candidates: list[StaleCandidate]) -> None:
        header = f"{'intent_id':<28} {'ticket':>12} {'state':<20} {'timestamp':<32} {'age(d)':>8}"
        self._log(header)
        self._log("-" * len(header))
        for c in candidates:
            age = c.age_days
            age_text = f"{age:.2f}" if age is not None else "?"
            ts = str(c.timestamp or "")
            self._log(
                f"{str(c.intent_id):<28} {str(c.ticket):>12} {str(c.state):<20} "
                f"{ts:<32} {age_text:>8}"
            )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Close stale ledger records (latest state position_confirmed/filled whose "
            "ticket is absent from the broker) via OrderStateStore.mark_closed."
        )
    )
    parser.add_argument(
        "--ledger",
        default=str(DEFAULT_LEDGER),
        help="Path to the order-state JSONL ledger " f"(default: {DEFAULT_LEDGER}).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the 'closed' records. Without this flag the run is a dry-run.",
    )
    parser.add_argument(
        "--ticket",
        default=None,
        help="Optional single-ticket filter (only this ticket is considered).",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    _bootstrap_import_path()
    args = build_arg_parser().parse_args(argv)
    backfill = StaleBackfill(
        ledger_path=Path(args.ledger),
        apply=args.apply,
        ticket=args.ticket,
    )
    return backfill.run()


if __name__ == "__main__":
    raise SystemExit(main())
