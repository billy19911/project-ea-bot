# TASK 11 — OPERATIONAL UI DATA INTEGRITY — COMPLETION REPORT

TASK: 11
STATUS: PASS

## FILES CHANGED

- `docs/audit/UI_DATA_INTEGRITY.md` (NEW) — full trace of all 18 operational pages
  (`UI field → API endpoint → Node handler → Python source → actual data source`)
  with a REAL/DERIVED/SIMULATED/MOCK/UNAVAILABLE classification per field, plus the
  MOCK sweep, cross-page notes and REMAINING ISSUES.
- **F1 — AI Control activity log honesty**
  - `services/python/src/agents/activity.py` — `AgentActivity.record()` stores the
    real per-run `error` flag on each `recent` entry.
  - `services/python/src/system/endpoints.py` — `/tasks` reports `status:"failed"`
    for errored runs and a real `counts.failed` (was hard-coded `"success"` / `0`).
- **F2 — Reconciliation silent false-negative**
  - `services/python/src/execution/reconciliation.py` — `ReconciliationReport.to_dict()`
    now emits `has_critical`, `internal_count`, `broker_count`, `mismatches[]`
    (`kind`/`symbol`/`ticket`/`detail`) + `checked_at`; new `mismatch_list()`.
  - `services/python/src/execution/reconciliation_runner.py` — stamps the real UTC
    run time on `report.checked_at`.
- **F3 — Risk Center honesty**
  - `services/python/src/system/v2_endpoints.py` — `/v2/circuit-breaker` also returns
    the real `execution_guard` (kill switch + dependency breakers) + `value_wired:false`;
    `/v2/capital` binds (read-only) to the live MT5 equity and exposes honest derived
    keys (`total_capital`/`allocated`/`available`/`utilization`/`allocations_configured`/
    `equity_bound`) — no fabricated equity.
  - `apps/web/app/risk-center/page.tsx` — exec-guard panel, manual-breaker label,
    correct `risk_limits.limits` binding (was `[object Object]`).
- **F4 — Performance dimensions**
  - `services/python/src/system/v2_endpoints.py` — `_closed_trade_rows()` carries the
    real `closed_at` + a `_session_for()` derivation.
- **F5 — Market sizing honesty**
  - `services/python/src/charting/endpoints.py` — no fabricated `equity=10000.0`;
    `position_size` is `null` and `provenance.sizing_equity_bound=false` when unknown.
  - `apps/web/app/market/page.tsx` — `position_size: number | null` type.
- **Tests**
  - `services/python/tests/test_reconciliation_engine.py` (2 new + shape extension),
    `services/python/tests/test_system_endpoints.py` (1 new failed-run test + count fix),
    `services/python/tests/test_v2_endpoints.py` (3 new).
- `CHANGELOG.md` — TASK 11 entry.

## ROOT CAUSE

The 18 operational pages bind to backend payloads that had drifted from their
viewside contracts. Pages never fabricated rows, but three defects let a benign
value silently stand in for a real one (invariant #22/#23):

1. `/tasks` hard-coded `status:"success"` and `counts.failed:0`, so the AI Control
   activity log was **always green** regardless of real agent failures.
2. `ReconciliationReport.to_dict()` emitted `critical`/`missing_*`/`matched`, while
   the Reconciliation page read `has_critical`/`internal_count`/`broker_count`/
   `mismatches`/`checked_at`. Those keys never existed, so the page **silently always
   rendered "CLEAN / 0 mismatches"** — able to mask a real `ReconciliationGuard`
   fail-closed.
3. The Risk Center presented unwired singletons as live: `risk_limits` was read as a
   flat map (rendering `[object Object]`), the multi-level breaker/capital came from
   singletons never fed by the pipeline (`source:"live"`), and capital key names did
   not match `CapitalAllocator.snapshot()`.

Additionally, `_closed_trade_rows()` populated only `symbol`, so the Performance
page's `hour`/`session`/`regime` dimensions always produced zero buckets; and the
chart analysis silently sized on a fabricated `equity = 10000.0` when the real
equity was unknown.

## FIX

- **F1:** `AgentActivity.record()` now persists the per-run `error` flag; `/tasks`
  reports the honest `failed`/`success` per row and a real `counts.failed`.
- **F2:** `to_dict()` emits the real UI keys (counts derived from `matched` +
  `missing_*`, flattened `mismatches[]` with real `kind`/`ticket`/`detail`, and a
  runner-stamped `checked_at`). The page now reflects the true state.
- **F3:** the real `execution_guard` (the state that actually gates orders) is
  surfaced; the manual multi-level breaker is labelled "manual / not auto-fed";
  capital is bound to real equity with honest derived keys; `risk_limits.limits` is
  correctly bound.
- **F4:** performance rows carry the real `closed_at` + a session derived from it.
- **F5:** no fabricated sizing equity; `position_size` is `null` when equity is
  unknown, flagged via `sizing_equity_bound`.
- No trading behaviour/default arm state changed; all terminals remain DISARMED.

## TESTS

- Command: `./.venv/Scripts/python.exe -m pytest tests -q`
  - Result: **3065 passed, 1 warning** (was 3059; +6 new TASK 11 tests).
  - Note: run with `--basetemp=<fresh dir>` because the repo `pytest.ini` basetemp
    (`./temp_pytest`) collides with a directory locked by the running services —
    a pre-existing environment quirk, unrelated to these changes.
- Command: `./.venv/Scripts/python.exe -m pytest tests/test_reconciliation_engine.py
  tests/test_reconciliation_wiring.py tests/test_reconciliation_audit.py
  tests/test_system_endpoints.py tests/test_v2_endpoints.py ... -q`
  - Result: all pass.
- Command: `npx tsc --noEmit` (apps/web + apps/api)
  - Result: clean.
- Command: `npx eslint app/ components/ lib/` (web) and `npx eslint src/` (api)
  - Result: clean.
- Command: `node lib/errorTaxonomy.test.mjs && node lib/liveFlash.test.mjs && node lib/viewport.test.mjs`
  - Result: pass (fail 0).

## RUNTIME VERIFICATION

Used `fastapi.testclient.TestClient` against the real `src.main:app` (with the
runtime `X-API-Key`), no servers started:

- `/reconciliation/status` after one `runtime.run_cycle(...)`:
  `last_report` keys = `[broker_count, checked_at, critical, has_critical,
  internal_count, magic_mismatches, matched, matched_orders, mismatches,
  missing_in_broker, missing_internal, orphan_orders, sltp_mismatches,
  symbol_mismatches, total_mismatches, volume_mismatches]`;
  `checked_at = 2026-10-01T06:30:02Z`, `internal_count=0`, `broker_count=0`,
  `mismatches=[]`, `has_critical=false`.
- `/v2/circuit-breaker`: `200`, `value_wired=False`,
  `execution_guard` keys = `['kill_switch', 'breakers']`.
- `/v2/capital`: `200`, `{total_capital:0.0, allocated:0.0, available:0.0,
  utilization:None, allocations_configured:False, equity_bound:False}` (no 10000).
- `/settings`: `risk_limits.available=True`, `limits` keys =
  `[max_spread_pips, min_rr, max_drawdown, daily_loss_limit, max_exposure,
  margin_threshold, max_positions, max_position_size]`.
- `/tasks`: `counts = {running:0, queued:0, completed:0, failed:0}`.
- `grep` (rg) over `apps/web/app/**/*.tsx` for `MOCK|mock|fake|dummy|hardcode|
  Math.random` → no fabricated data in the 18 operational pages (2 hits are
  comments in the non-operational `control-plane` page).

## REMAINING ISSUES (documented, not silently hidden)

- R1 Trade History: titled "history / closed trades" but binds to `/positions`
  (open positions). Data honest, copy misleading (would need `history_deals_get`
  wiring — a data feature, out of scope).
- R2 Accounts: multi-account registry (`AccountManager`) is never populated → the
  table is empty-by-construction (honest empty state).
- R3 Overview / Trade History: MT5 synthetic (SIMULATED) account/positions are not
  per-record labelled; only the Positions page checks `/mt5/mode`.
- R4 Observability: Node `metrics.ts` token/agent prom counters are never
  incremented (latent zeros) — not rendered by the page today.
- R5 Performance: `regime` dimension remains honestly empty (no regime attribute
  on reviews).

None is a silently-fabricated operational field; all are documented in
`docs/audit/UI_DATA_INTEGRITY.md §20`.

## STOP GATE (TASK 11)

- [x] Audit document covers all 18 operational pages (min 1 trace row each).
- [x] Every field classified REAL/DERIVED/SIMULATED/MOCK/UNAVAILABLE.
- [x] No operational page silently shows MOCK data (grep + per-page review).
- [x] MOCK/false-negative findings fixed (F1–F5); residual items documented.
- [x] `tsc` + `lint` green (web + api); full Python suite green.

## NEXT TASK

NOT STARTED
