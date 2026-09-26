# LEDGER CLOSURE LIFECYCLE + LIVE SL/TP ATTACH — PLAN

- Date: 2026-09-26
- Status: approved — execution delegated to OpenCode subagents (T1 first, T2–T4 chained)
- Follow-up to: B-4 live demo validation (docs/evidence/B-4-demo-validation.md, docs/audit/RELEASE_BLOCKERS.md B-4 residual)
- Process note (user, verbatim): "tolong sebelum eksekusi di buatkan plannya dulu baru nanti di delegate task nya ke subagent opencode ya" — this document + the T1–T4 briefs satisfy the "plan first" step.

## 1. Background

B-4 closed 2026-09-26 with two documented residuals:

1. **P0 — ledger has no closure lifecycle.** The append-only ledger
   `services/python/logs/order_state.jsonl` never records a `closed` state. Every historical
   `position_confirmed` record therefore counts as an open internal position forever.
   Reconciliation reports them as `missing_in_broker` → `has_critical=True` → `last_ok=False`
   → `ReconciliationGuard.check_can_execute()` fail-closes and blocks **every new order**.
   As of 2026-09-26 the ledger holds 17 stale `position_confirmed` records and 0 `closed`
   records (717 lines; recount at execution time).
2. **Gap — live SL/TP attach never exercised.** The B-4 validation order was placed with
   `sl=0.0 tp=0.0` (harness default); broker confirmed `sl=0 tp=0`. The engine already
   forwards `sl`/`tp` (`OrderRequest.sl/.tp` → `_send_to_mt5` → native `mt5.order_send`
   payload) but this path has never been validated against a live broker position.

## 2. Goals / non-goals

Goals:
- G1 — closure lifecycle: write `closed` to the ledger when a tracked position disappears
  from the broker, guarded against false-close on broker read errors.
- G2 — backfill the existing stale records; reconciliation returns clean; guard unblocks.
- G3 — live demo validation of SL/TP attach (order with SL/TP → broker verify → close →
  ledger closure observed end-to-end).

Non-goals (unchanged, separate items):
- #3 engine native close/modify path (decision pending).
- #4 hardening `/mt5/orders/execute` (paper connector path).
- #5 B-6 close-price residual (last-seen best-effort).

## 3. Design

### 3.1 Closure trigger + false-close guard (G1)
- Reuse existing machinery: `position_monitor.detect_position_changes()` already emits
  `POSITION_DISAPPEARED` and carries a `reconciliation_store` reference;
  `OrderState.CLOSED` + the `POSITION_CONFIRMED → CLOSED` transition already exist in
  `src/execution/state_machine.py` but are never written.
- **Guard (mandatory):** `connector.get_positions()` returns `[]` both for "no positions"
  and for "read failed". Closure decisions must use a read-status-aware API
  (`get_positions_ex() -> (ok, positions)`; live: `positions_get()` returning None → ok=False).
  On ok=False: skip the cycle's diff entirely, write nothing, log a warning.
- Ledger write via the existing store (`src/persistence/order_state_store.py`):
  `mark_closed(ticket, reason, at=None)` — resolves the latest record by ticket; idempotent;
  validates the transition (add `FILLED → CLOSED` if missing); appends
  `{"intent_id","state":"closed","ticket","timestamp","reason"}`; updates memory.
- Provider (`src/execution/reconciliation_providers.py`) resolves open positions by the
  **latest state per intent/ticket** so `closed` supersedes open states.
- Rejected alternative (documented): auto-close inside the reconciliation runner — keeps the
  reporting component read-only; closure stays in the monitor + explicit backfill.
  Residual: closures that happen while the service is down are not observed; the backfill
  script is the documented ops remedy (future enhancement if it recurs).

### 3.2 Backfill (G2)
- Ops script `scripts/ledger_close_stale.py` (standalone, venv python, repo-root paths):
  candidates = latest-state ∈ {`position_confirmed`, `filled`} AND ticket ∉ broker positions,
  evaluated only with a **verified** broker read (ok=True; else abort non-zero).
  Default dry-run; `--apply` appends `closed` via the same `mark_closed` code path.
  Unit tests use tmp ledgers; never touch the real ledger in tests.

### 3.3 Live SL/TP validation (G3)
- Extend `scripts/b4_demo_validation.py` additively: SL/TP fields on the OrderRequest
  (distance from symbol info `trade_stops_level`/`point`/`digits`, default ≈1.5% for
  `#BTCUSD`, always > stops level); place through the same engine path as B-4 T1 (filling
  FOK); read back `positions_get(ticket)` and assert sl/tp ≈ requested; hold ≥2 monitor
  intervals; close via helper; verify ledger `closed` + reconciliation stays clean.
- All 49 existing B-4 tests must stay green; new unit tests for the additive logic.
- If the harness cannot be extended cleanly, a sibling script may be created — documented.

## 4. Task breakdown

| # | Task | Depends on | Deliverable |
|---|------|-----------|-------------|
| T1 | Ledger closure lifecycle (code + unit tests) | — | src changes; `tests/test_ledger_closure.py` green; report |
| T2 | Stale backfill + restart + reconciliation clean | T1 | `scripts/ledger_close_stale.py` + tests; applied; clean evidence; report |
| T3 | Live SL/TP attach validation | T2 | broker-verified sl/tp; closed; ledger closure observed; evidence json; report |
| T4 | Evidence consolidation + docs + final verification | T3 | evidence md/json; RELEASE_BLOCKERS updated; full suite + lint; report |

Briefs: `docs/tasks/LEDGER-SLTP-T{1..4}-*.md`. Reports: `docs/tasks/LEDGER-SLTP-T{n}-report.md`.

## 5. Acceptance criteria

- T1: tests prove verified-disappearance → closed; read-error → no write; idempotency;
  transition validation; provider excludes closed; full suite ≥2242 all green; lint clean.
- T2: POST /reconciliation/run → `has_critical=False`; GET /reconciliation/status →
  `last_ok=True`; ledger stale open records = 0; `closed` count == backfilled count;
  re-run dry-run → 0 candidates.
- T3: demo order with non-zero SL/TP; broker readback matches (tolerance documented);
  position closed; account flat; ledger `closed` recorded via monitor (or deviation
  documented precisely); post-close reconciliation clean; evidence written.
- T4: consolidated evidence; blockers doc updated honestly; full suite + lint green;
  no commit; ledger invariants re-verified.

## 6. Guardrails (all tasks)

- TDD; verify before claiming done; search counts are not evidence; no invented results.
- **NO commit. NO global reformat. Preserve user changes** — do not touch
  `services/python/src/config.py`; `services/python/src/main.py` minimal;
  `runtime.py` preserve the existing uncommitted FIX A edits; `apps/api/src/index.ts` untouched.
- No secrets/credentials in code, docs, logs, briefs, evidence ([REDACTED] policy).
- Python: `services/python/.venv/Scripts/python.exe`; `src.*` imports only with cwd
  `services/python`; lint = flake8 `--max-line-length=100 --extend-ignore=E203,W503` +
  `black --check` (check only — never reformat existing files).
- Service restarts only via `scripts/restart-py.ps1` (wrapper exit 124 expected).
  Demo broker only. `&` is forbidden in terminal commands.
- Deviations documented honestly in reports.

## 7. Risks

- False-close on broker read errors → mitigated by `get_positions_ex` ok-flag (T1).
- Monitor timing (position opened+closed between cycles) → T3 holds ≥2 intervals.
- Paper-origin ledger records without broker positions → included in backfill candidates;
  document any anomaly (e.g. ticket 158731 history).
- Service restart loses the armed terminal → T3 re-selects + re-arms (B-4 pattern).
- Closures while the service is down → not observed by monitor; backfill script is the remedy.
