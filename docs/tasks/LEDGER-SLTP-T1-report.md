# LEDGER-SLTP T1 — Ledger closure lifecycle (Report)

Status: DONE. No commit. Non-interactive run — every ambiguous point resolved by
choosing the safest option and documenting it below.

Parent task: LEDGER-SLTP T1 (T2 backfill, T3 live SL/TP, T4 evidence are out of scope).
Repo: `project-ea-bot` (branch `main`). Python service cwd: `services/python`.

## Problem recap (verified in code before changing)

`services/python/logs/order_state.jsonl` is an append-only ledger that never wrote a
`closed` state, so every historical `position_confirmed`/`filled` record counts as an
open internal position forever. `internal_positions_from_store()`
(`src/execution/reconciliation_providers.py`) reports those tickets as internal
positions; reconciliation sees them as `missing_in_broker` → `has_critical=True` →
`ReconciliationRunner._last_ok=False` → `ReconciliationGuard.check_can_execute()`
returns `(False, …)` → all new orders are blocked.

The task's "717 lines / 17 confirmed / 0 closed" snapshot was read at task start; the
untracked-and-gitignored ledger grew during pre-existing (unrelated) test runs, but its
content is not part of any diff (see "Ledger safety" below).

## Files changed (minimal diffs; all pre-existing uncommitted work preserved)

1. `src/mt5/connector.py` — added `get_positions_ex() -> tuple[bool, list[Position]]`.
   Live: `mt5.positions_get()` → `None` ⇒ `(False, [])`; empty tuple ⇒ `(True, [])`;
   data ⇒ `(True, [...])`. Simulation ⇒ `(True, simulated)`. `get_positions()` is
   unchanged.
2. `src/execution/state_machine.py` — transition table: `FILLED` now also allows
   `CLOSED` (was `(POSITION_CONFIRMED, UNKNOWN)`).
3. `src/persistence/order_state_store.py` — added `mark_closed(ticket, reason="…",
   at=None)` and an `RLock` guarding the read-modify-append sequence (`set_order`,
   `mark_closed`, `_append_line`).
4. `src/monitoring/position_monitor.py` — new optional `order_state_store` ctor arg;
   `_get_positions_ex()` verified-read helper; `_snapshot_positions(positions=None)`
   now accepts pre-fetched positions; `detect_position_changes()` verifies the broker
   read and calls `_mark_ticket_closed(ticket)` (→ `store.mark_closed(...)`) for each
   verified `POSITION_DISAPPEARED`.
5. `src/execution/reconciliation_providers.py` — `internal_positions_from_store()` now
   resolves the **latest state per ticket** so `closed` supersedes an open state for
   the same ticket.
6. `src/orchestration/runtime.py` — `_build_position_monitor()` now reads the globally
   attached order-state store (`execution.state_machine.get_store()` / `src.*` fallback)
   and passes it as `order_state_store=...`. FIX A edits (TRADE_CLOSE emit) preserved.
7. `tests/test_ledger_closure.py` — new suite (14 tests).
8. `docs/tasks/LEDGER-SLTP-T1-report.md` — this report.

`git diff --stat` (working tree, includes pre-existing uncommitted edits in these files):

```
 src/execution/reconciliation_providers.py |  38 ++-
 src/execution/state_machine.py            |   4 +-
 src/monitoring/position_monitor.py        |  78 +++++-
 src/mt5/connector.py                      | 270 ++++++++++++++++++---   (mostly pre-existing dirty state)
 src/orchestration/runtime.py              |  75 +++++-                  (FIX A + this task)
 src/persistence/order_state_store.py      | 129 ++++++++--
 6 files changed, 526 insertions(+), 68 deletions(-)
```

The large `connector.py` / `order_state_store.py` diffs are dominated by **pre-existing
uncommitted changes in those files** (e.g. HEAD's connector has 675 lines vs 843 in the
working copy) plus CRLF/LF git noise; this task's additions are additive and local
(roughly +44 lines in `connector.py`, +112 in `order_state_store.py`).

## Design decisions

### Guard mechanism (the false-close guard)

`connector.get_positions()` returns `[]` for both "broker has no positions" and "read
failed" — using it to close ledger rows would false-close on a terminal hiccup.
`get_positions_ex()` is the seam that disambiguates: it returns an explicit `ok` flag
that is `False` only when a live read genuinely failed (`positions_get()` → `None` or
exception). In simulation the synthetic list is authoritative, so `ok=True`.

`PositionMonitor.detect_position_changes()` now reads positions **once** via
`_get_positions_ex()`:

- `ok == False` → the entire cycle's diff is skipped: no `POSITION_DISAPPEARED` events,
  no closures, and a `WARNING` is logged. This is the false-close guard.
- `ok == True` → the diff runs as before; a genuine disappearance appends a `closed`
  record and emits the event.

Backward compatibility: a connector with no `get_positions_ex()` is treated as verified
(`(True, get_positions())`), so legacy callers/tests are unaffected. The module-level
`mt5.connector.get_positions_ex` path uses the same convention.

### Seam chosen for the store

`mark_closed` lives on `OrderStateStore` (the single append path) per the task. The
monitor receives the store via a new **optional** `order_state_store` constructor arg.
The runtime wires it by reading the store already attached globally by `main.py`
(`execution.state_machine.set_store(order_store)`), rather than constructing a second
competing ledger. If no store is attached (`get_store() is None`) the monitor degrades
to detection-only — identical to today. `_mark_ticket_closed` is fail-safe: a missing
store, a store without `mark_closed`, or a raising store never breaks the loop; a ticket
with no ledger open record is skipped with a debug log.

### `mark_closed` semantics

- Resolves the **latest** record for a ticket (last record wins in an append-only log;
  iteration over the insertion-ordered dict), so a later open state supersedes an
  earlier close.
- Idempotent: already `closed` ⇒ returns `False`, writes nothing.
- Validates the transition through the state machine (`next_allowed`). Allowed sources
  are `position_confirmed` and `filled` (after adding `FILLED → CLOSED`); any other
  source (e.g. `risk_approved`) or an unknown state string is rejected → `False`.
- Appends `{"intent_id": <latest record's intent_id>, "state": "closed", "ticket": …,
  "timestamp": <ISO-UTC>, "reason": …}` through the existing `_append_line` persistence
  path and updates the in-memory record. Timestamp format matches existing records
  (`datetime.now(timezone.utc).isoformat()`, e.g. `2026-09-26T15:03:53.518086+00:00`).
- Thread-safety: an `RLock` guards the read-modify-append sequence. The store had no
  locking before; the lock is the minimal construct that keeps a concurrent close from
  interleaving a stale record, and it wraps only the mutation/append paths.

### Provider "latest state" resolution

`internal_positions_from_store` now builds `ticket → latest state` (last writer wins)
and only emits a position when that latest state is in `{position_confirmed, filled}`.
This makes a `closed` record supersede an open record for the same ticket even if two
intent rows reference the same ticket. The previous behaviour already worked for the
common one-record-per-intent case; this hardens the ticket-level case the task calls out.

## Ledger safety

- All new tests use `tmp_path` ledgers. Verified: running
  `pytest tests/test_ledger_closure.py` leaves
  `services/python/logs/order_state.jsonl` byte-for-byte unchanged (729 → 729 lines).
- `services/python/logs/order_state.jsonl` is **not tracked** by git (it matches
  `.gitignore`; `git ls-files -v` shows nothing) and was never opened by this task's
  edits or tests. No live orders were run, no services restarted, no secrets logged.

## Commands + observed results (honest, reproducible)

Baseline (before any change, full suite):

```
./.venv/Scripts/python.exe -m pytest -q
=> 2242 passed, 1 warning in 123.33s (0:02:03)
```

Targeted suite (new file):

```
./.venv/Scripts/python.exe -m pytest tests/test_ledger_closure.py -q
=> ................                                                       [100%]
   14 passed in 0.76s
```

Related existing suites (regression check):

```
./.venv/Scripts/python.exe -m pytest tests/persistence/test_order_state_store.py \
  tests/test_reconciliation_providers.py tests/test_position_monitor.py \
  tests/test_position_monitor_changes.py tests/test_reconciliation_wiring.py \
  tests/test_reconciliation_engine.py tests/test_reconciliation_audit.py \
  tests/test_b4_demo_validation.py -q
=> 131 passed, 1 warning in 5.43s
```

Full suite (after change):

```
./.venv/Scripts/python.exe -m pytest -q
=> 2256 passed, 1 warning in 120.66s (0:02:00)
```

2256 = 2242 baseline + 14 new. No failures.

Lint on touched files:

```
./.venv/Scripts/python.exe -m flake8 --max-line-length=100 \
  --extend-ignore=E203,W503 \
  src/mt5/connector.py src/persistence/order_state_store.py \
  src/execution/state_machine.py src/monitoring/position_monitor.py \
  src/execution/reconciliation_providers.py src/orchestration/runtime.py \
  tests/test_ledger_closure.py
=> (no output, exit 0)

./.venv/Scripts/python.exe -m black --check <same files>
=> All done! 7 files would be left unchanged.   (check only — no reformat)
```

Manual smoke (no side effects on the real ledger):

```
get_positions_ex() sim  -> (True, 2 simulated positions)
mark_closed(1001)       -> True   (appends {"state":"closed",...})
mark_closed(1001) again -> False  (idempotent)
internal_positions_from_store({"a": closed t55, ...}) -> []  (closed supersedes)
runtime wiring          -> position_monitor.order_state_store wired when a store is attached
```

## Test coverage (tests/test_ledger_closure.py, 14 tests)

- `get_positions_ex`: simulation verified; live read failure → `(False, [])`.
- `mark_closed`: append (file + memory) + restart survival; unknown ticket no-op;
  double-close idempotent (exactly one `closed` record); `filled` source allowed;
  invalid source (`risk_approved`) and unknown-state source rejected.
- transition table: `FILLED → CLOSED` and `POSITION_CONFIRMED → CLOSED` allowed;
  `CLOSED` terminal.
- provider: drops closed ticket; latest-state-per-ticket resolution.
- monitor: verified disappearance closes the ledger (file + memory) and the provider
  stops counting it, using `get_positions_ex` (asserted via call counter); `ok=False`
  writes nothing and emits no events; disappearance without a ledger record is safe;
  no-store path still detects.

## Deviations / notes

- The `mark_closed` test asserting "invalid source rejected" uses `risk_approved`
  (the state machine does not allow `risk_approved → closed`). This is the specific
  invalid-source case; unknown state strings are covered too.
- A thread lock (`RLock`) was added to `OrderStateStore` although it previously had
  none. Rationale: the task requires closure thread-safety "consistent with existing
  store locking"; with no existing lock the safest reading is to introduce the minimal
  lock and keep it scoped to the mutation/append paths. This is additive and does not
  change single-threaded behaviour.
- Nothing in `src/config.py`, `src/main.py`, `apps/api/src/index.ts` was touched. No
  docs other than this report were written. No commit.

## Acceptance checklist

- [x] `get_positions_ex()` added; `get_positions()` unchanged.
- [x] `OrderStateStore.mark_closed()` added; `FILLED → CLOSED` transition added;
      idempotent; transition-validated; thread-safe; returns `True` only when written.
- [x] Monitor closes the ledger only on a **verified** disappearance; `ok=False` skips
      the cycle (no closures, no events, warning logged); no-record tickets skipped
      (debug); minimal store wiring; `runtime.py` FIX A preserved.
- [x] Provider resolves latest state per ticket so `closed` supersedes open.
- [x] Targeted tests green (14); related suites green (131); full suite green
      (2256 passed); lint clean (flake8 exit 0, black check unchanged).
- [x] `docs/tasks/LEDGER-SLTP-T1-report.md` written (this file).
- [x] No commit; real ledger untouched; no secrets.

## Out of scope (untouched)

- T2 backfill, T3 live SL/TP, T4 evidence.
- Backfilling/pruning the existing historical `position_confirmed` records in the
  untracked ledger (T2 concern).
- Commits (user rule: do not commit).
