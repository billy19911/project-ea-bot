# -*- coding: utf-8 -*-
"""Unit tests for ``scripts/ledger_close_stale.py`` (LEDGER-SLTP T2).

All tests use a throwaway ledger under ``tmp_path`` and a fake connector — the
real ``services/python/logs/order_state.jsonl`` is never opened.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "ledger_close_stale.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("ledger_close_stale", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["ledger_close_stale"] = module
    spec.loader.exec_module(module)
    return module


backfill_mod = _load_script()


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakePosition:
    def __init__(self, ticket):
        self.ticket = ticket


class FakeConnector:
    """Fake connector exposing the verified ``get_positions_ex`` read."""

    def __init__(self, ok=True, tickets=()):
        self._ok = ok
        self._tickets = list(tickets)
        self.calls = 0

    def get_positions_ex(self):
        self.calls += 1
        return self._ok, [FakePosition(t) for t in self._tickets]


class LegacyConnector:
    """Connector without ``get_positions_ex`` (must be refused)."""

    def get_positions(self):
        return []


def _write_ledger(path: Path, records) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def _record(intent_id, state, ticket=None, ts="2026-09-26T15:00:00+00:00"):
    entry = {"intent_id": intent_id, "state": state, "timestamp": ts}
    if ticket is not None:
        entry["ticket"] = ticket
    return entry


# ---------------------------------------------------------------------------
# Candidate selection (latest-state semantics)
# ---------------------------------------------------------------------------


def test_latest_state_wins_for_same_intent(tmp_path):
    """An intent's later record supersedes an earlier open one."""
    path = tmp_path / "order_state.jsonl"
    _write_ledger(
        path,
        [
            _record("i1", "position_confirmed", 1000),
            # Simulate a later close appended for the same intent.
            _record("i1", "closed", 1000),
        ],
    )
    from src.persistence.order_state_store import OrderStateStore

    store = OrderStateStore(path=str(path))
    candidates, _, skipped_closed = backfill_mod.select_stale_candidates(
        store.all_orders(), broker_tickets=set()
    )
    assert candidates == []
    assert skipped_closed == 1


def test_closed_records_excluded(tmp_path):
    """A latest state of ``closed`` is never a candidate."""
    orders = {"i1": _record("i1", "closed", 42)}
    candidates, _, skipped_closed = backfill_mod.select_stale_candidates(
        orders, broker_tickets=set()
    )
    assert candidates == []
    assert skipped_closed == 1


def test_open_ticket_absent_from_broker_is_candidate():
    orders = {
        "i1": _record("i1", "position_confirmed", 1000),
        "i2": _record("i2", "filled", 2000),
    }
    candidates, _, _ = backfill_mod.select_stale_candidates(
        orders, broker_tickets=set()
    )
    assert {c.intent_id for c in candidates} == {"i1", "i2"}


def test_open_ticket_present_in_broker_not_candidate():
    orders = {"i1": _record("i1", "position_confirmed", 1000)}
    candidates, _, _ = backfill_mod.select_stale_candidates(
        orders, broker_tickets={"1000"}
    )
    assert candidates == []


def test_non_position_state_not_candidate():
    orders = {"i1": _record("i1", "acknowledged", 1000)}
    candidates, _, _ = backfill_mod.select_stale_candidates(
        orders, broker_tickets=set()
    )
    assert candidates == []


def test_no_ticket_records_skipped_and_counted():
    orders = {
        "i1": _record("i1", "position_confirmed"),  # no ticket
        "i2": _record("i2", "position_confirmed", 1000),
    }
    candidates, skipped_no_ticket, _ = backfill_mod.select_stale_candidates(
        orders, broker_tickets=set()
    )
    assert [c.intent_id for c in candidates] == ["i2"]
    assert skipped_no_ticket == 1


# ---------------------------------------------------------------------------
# Abort on unverified broker read
# ---------------------------------------------------------------------------


def test_abort_on_unverified_read(tmp_path):
    path = tmp_path / "order_state.jsonl"
    _write_ledger(path, [_record("i1", "position_confirmed", 1000)])
    runner = backfill_mod.StaleBackfill(
        ledger_path=path,
        connector_module=FakeConnector(ok=False),
        stdout=open(__import__("os").devnull, "w"),
    )
    assert runner.run() == 2
    # Nothing written.
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1


def test_legacy_connector_without_ex_aborts(tmp_path):
    path = tmp_path / "order_state.jsonl"
    _write_ledger(path, [_record("i1", "position_confirmed", 1000)])
    runner = backfill_mod.StaleBackfill(
        ledger_path=path,
        connector_module=LegacyConnector(),
        stdout=open(__import__("os").devnull, "w"),
    )
    assert runner.run() == 2


# ---------------------------------------------------------------------------
# Apply + idempotency
# ---------------------------------------------------------------------------


def test_dry_run_writes_nothing(tmp_path):
    path = tmp_path / "order_state.jsonl"
    _write_ledger(path, [_record("i1", "position_confirmed", 1000)])
    runner = backfill_mod.StaleBackfill(
        ledger_path=path,
        connector_module=FakeConnector(ok=True),
        stdout=open(__import__("os").devnull, "w"),
    )
    assert runner.run() == 0
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_apply_closes_candidate(tmp_path):
    path = tmp_path / "order_state.jsonl"
    _write_ledger(path, [_record("i1", "position_confirmed", 1000)])
    runner = backfill_mod.StaleBackfill(
        ledger_path=path,
        apply=True,
        connector_module=FakeConnector(ok=True),
        stdout=open(__import__("os").devnull, "w"),
    )
    assert runner.run() == 0
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert lines[-1]["state"] == "closed"
    assert lines[-1]["reason"] == backfill_mod.BACKFILL_REASON
    assert lines[-1]["ticket"] == 1000


def test_apply_is_idempotent(tmp_path):
    path = tmp_path / "order_state.jsonl"
    _write_ledger(path, [_record("i1", "position_confirmed", 1000)])

    def _run():
        return backfill_mod.StaleBackfill(
            ledger_path=path,
            apply=True,
            connector_module=FakeConnector(ok=True),
            stdout=open(__import__("os").devnull, "w"),
        ).run()

    assert _run() == 0
    after_first = path.read_text(encoding="utf-8").splitlines()
    assert _run() == 0
    after_second = path.read_text(encoding="utf-8").splitlines()
    # Re-run appended nothing new.
    assert len(after_second) == len(after_first)
    closed = [json.loads(x) for x in after_second if json.loads(x)["state"] == "closed"]
    assert len(closed) == 1


# ---------------------------------------------------------------------------
# Ticket filter
# ---------------------------------------------------------------------------


def test_ticket_filter_selects_single(tmp_path):
    path = tmp_path / "order_state.jsonl"
    _write_ledger(
        path,
        [
            _record("i1", "position_confirmed", 1000),
            _record("i2", "position_confirmed", 2000),
        ],
    )
    runner = backfill_mod.StaleBackfill(
        ledger_path=path,
        apply=True,
        ticket="2000",
        connector_module=FakeConnector(ok=True),
        stdout=open(__import__("os").devnull, "w"),
    )
    assert runner.run() == 0
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    closed = [x for x in lines if x["state"] == "closed"]
    assert len(closed) == 1
    assert closed[0]["ticket"] == 2000


def test_missing_ledger_aborts(tmp_path):
    runner = backfill_mod.StaleBackfill(
        ledger_path=tmp_path / "nope.jsonl",
        connector_module=FakeConnector(ok=True),
        stdout=open(__import__("os").devnull, "w"),
    )
    assert runner.run() == 2
