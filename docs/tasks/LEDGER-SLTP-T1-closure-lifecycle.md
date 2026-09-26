# LEDGER-SLTP T1 — Ledger closure lifecycle (code + unit tests)

You are T1 of a 4-task chain (T2 backfill, T3 live SL/TP, T4 evidence). Do ONLY T1 scope.
You run non-interactively: make reasoned decisions, document them in your report, never wait
for input.

## Environment
- Repo: C:/xampp/htdocs/project-ea-bot (branch main). **Never commit.** Never reformat.
- Python: services/python/.venv/Scripts/python.exe — `src.*` imports only with cwd=services/python.
- Tests (from services/python): `./.venv/Scripts/python.exe -m pytest -q` (full suite; baseline 2242 passed).
- Lint on touched files only (from services/python):
  `./.venv/Scripts/python.exe -m flake8 --max-line-length=100 --extend-ignore=E203,W503 <files>`
  `./.venv/Scripts/python.exe -m black --check <files>` (check only — do NOT reformat).

## Problem (P0, verified)
`services/python/logs/order_state.jsonl` (append-only) never records a `closed` state, so
every historical `position_confirmed` record counts as an open internal position forever.
Reconciliation reports them as `missing_in_broker` → `has_critical=True` → `last_ok=False` →
`ReconciliationGuard.check_can_execute()` fail-closes → **all new orders are blocked**.
Current ledger: 17 `position_confirmed`, 0 `closed` (717 lines).

Verified facts (re-read the code to confirm before changing):
- `OrderState.CLOSED` exists in `src/execution/state_machine.py`; transition
  `POSITION_CONFIRMED → CLOSED` is defined but never written.
- `src/execution/reconciliation_providers.py` counts states {`position_confirmed`, `filled`}
  as open positions.
- `src/monitoring/position_monitor.py` already detects `POSITION_DISAPPEARED` via
  `detect_position_changes()` and holds a `reconciliation_store` reference.
- `connector.get_positions()` (`src/mt5/connector.py`) returns `[]` BOTH when the broker
  truly has no positions AND when the read fails → naive handling would false-close on a
  terminal hiccup. THIS MUST BE GUARDED.
- `src/persistence/order_state_store.py` rehydrates the jsonl into memory and is the single
  append path for state records.
- Consumers: `src/execution/reconciliation_runner.py` (`check_can_execute` ~line 205),
  `src/orchestration/pipeline.py` (~lines 414–439), `src/orchestration/runtime.py` (~line 462).
- `runtime.py` has UNCOMMITTED FIX-A edits — preserve them; minimal diff.

## Scope (TDD — write failing tests first)
1) `src/mt5/connector.py`: add `get_positions_ex() -> tuple[bool, list[Position]]` — live:
   `mt5.positions_get()` → None ⇒ (False, []); empty tuple ⇒ (True, []); data ⇒ (True, [...]).
   Sim mode ⇒ (True, simulated). Existing `get_positions()` behavior unchanged.
2) `src/persistence/order_state_store.py`: add `mark_closed(ticket, reason="...", at=None)`:
   - resolve the latest record for the ticket; if already `closed` ⇒ no-op, return False;
   - validate transition via the state machine — allow from `position_confirmed` AND `filled`
     (add `FILLED → CLOSED` to the transition table if missing);
   - append `{"intent_id": <latest record's intent_id>, "state": "closed", "ticket": ...,
     "timestamp": <same ISO-UTC format as existing records>, "reason": ...}` through the
     existing persistence path; update in-memory state; return True when written;
   - thread-safety consistent with existing store locking.
3) `src/monitoring/position_monitor.py`: when `detect_position_changes()` produces
   `POSITION_DISAPPEARED`, call `mark_closed(ticket, reason="broker_position_disappeared")`
   — ONLY when the broker read is verified (`get_positions_ex().ok == True`). If ok=False:
   skip the cycle's diff (no closure, no spurious events), log a warning. Tickets with no
   ledger open record are skipped (debug log). Wire the store with a minimal change
   (constructor/setter); update `runtime.py` wiring minimally (preserve FIX A).
4) `src/execution/reconciliation_providers.py`: ensure open-position resolution uses the
   LATEST state per intent/ticket so `closed` supersedes open states (fix if needed).

## Tests (new: services/python/tests/test_ledger_closure.py; extend existing suites if natural)
Prove at minimum:
- verified disappearance ⇒ `closed` appended (file + memory) and provider no longer counts it;
- read failure (ok=False) ⇒ NO ledger write (false-close guard) and no disappearance events;
- double-close idempotent ⇒ exactly one `closed` record;
- transition validation: invalid source rejected; `FILLED → CLOSED` allowed;
- monitor hook path: uses `get_positions_ex`, skips closure on ok=False.
Use `tmp_path` ledgers — NEVER write to `services/python/logs/order_state.jsonl` in tests.
Do NOT run live orders, do NOT restart services, do NOT touch the real ledger.

## Constraints
- Never commit; never reformat; minimal diffs; read files before editing.
- Do NOT touch: `services/python/src/config.py`, `services/python/src/main.py`,
  `apps/api/src/index.ts`; no other docs than your report.
- No secrets in code/logs/report. Preserve all existing uncommitted work.
- If something is ambiguous: choose the safest option, document it, continue.

## Deliverable + report
- Targeted tests green AND full suite green (`-m pytest -q`), lint clean on touched files.
- Write `docs/tasks/LEDGER-SLTP-T1-report.md`: files changed, exact commands + observed
  results (test counts, lint output), design decisions (guard mechanism, seam chosen),
  deviations. Honest — no invented results. The supervisor will independently verify.
