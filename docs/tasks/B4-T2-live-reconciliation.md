# B-4 T2 — Live Reconciliation Validation

Status: TODO (delegasi OpenCode, setelah T1 selesai)
Parent plan: `docs/plans/B4-LIVE-DEMO-VALIDATION.md` (task T2)
Blocker ref: `docs/audit/RELEASE_BLOCKERS.md` → B-4 (lines 64–79)
Depends on: T1 (`scripts/b4_demo_validation.py`, position left OPEN by design)

## Goal

Extend the T1 harness with the `reconcile` subcommand: run a live reconciliation
comparing the internal order ledger (in-memory `OrderStateStore` rehydrated from
`services/python/logs/order_state.jsonl`) against the broker's actual positions,
and produce evidence that the T1 order is **matched by ticket with 0 critical
mismatches** — or document precisely which non-critical differences exist and
why they are acceptable.

## Verified facts (from recon — trust these)

- The active ledger file is `services/python/logs/order_state.jsonl` (service
  cwd = `services/python`; root `logs/order_state.jsonl` is stale — ignore it).
- Ledger records are only `{intent_id, state, ticket, timestamp}` — **no
  symbol/volume/sl/tp/magic**. Reconciliation matching is by **ticket**.
- `reconciliation_providers.py` (152 lines): `internal_positions_from_store`
  reads `execution.state_machine._order_store` (in-memory, rehydrated from the
  file at `OrderStateStore()` init); `broker_positions` reads the connector.
- `ReconciliationRunner.run_once()` (in `src/execution/reconciliation_runner.py`)
  calls `providers.internal_positions()`, `providers.broker_positions()`,
  `providers.internal_orders()`, `providers.broker_orders()`, then
  `reconciler.compare(...)` → `ReconciliationReport`; never raises.
- `Reconciler._compare_fields` (in `src/execution/reconciliation.py`, ~185–240)
  compares fields EXACTLY. Because ledger records lack volume, an internal
  position reconstructed from a `position_confirmed` record may show volume
  `0.0` vs the broker's real volume — that is a KNOWN data-shape gap. Do NOT
  hack the reconciler to hide it; the evidence must state which fields matched
  and which differed, and the ticket match must be proven.
- The live service exposes `POST /reconciliation/run` (forces a run) and
  `GET /reconciliation/status` (last report) — both require the API key
  (`X-API-Key`). Prefer running reconciliation IN-PROCESS in the harness
  (same code path as the service: `ReconciliationRunner` + the same providers
  wiring as `orchestration/runtime.py` builds), so the harness does not need
  the API key; use the HTTP endpoints only for cross-checking if the service
  is running.
- Import rule: `import src.*` only from cwd `services/python` (harness already
  bootstraps this in T1).

## Deliverables

1. Extend `scripts/b4_demo_validation.py` — implement `reconcile` subcommand:
   - Build the same providers wiring the service uses (read
     `src/orchestration/runtime.py` for how `MT5ReconciliationProviders` is
     constructed; reuse it, do not reinvent).
   - Run `ReconciliationRunner(interval=1, providers=...).run_once()`.
   - Serialize the report (`report.to_dict()`), extract: matched tickets,
     unmatched internal, unmatched broker, field-level differences for matched
     pairs, `has_critical()`.
   - Assert: the T1 ticket (from `docs/evidence/B-4-demo-validation.json` `t1`
     section) is present and matched; record whether `has_critical()` is False.
   - Append the `t2` section to `docs/evidence/B-4-demo-validation.json` +
     the MD evidence file.
   - Exit non-zero if the T1 ticket is NOT matched.
2. Extend `services/python/tests/test_b4_demo_validation.py` — unit tests for
   the reconcile path with fake providers (matched ticket → pass; missing
   ticket → fail; volume-gap field diff → reported, not hidden).
3. Update `docs/tasks/B4-T2-report.md` — what ran, raw report JSON, matched
   ticket, mismatch list (expected volume-gap vs unexpected), verdict.

## Acceptance criteria

- [ ] Unit tests GREEN (mock-based).
- [ ] Live `reconcile` run against bil2: T1 ticket matched, verdict recorded.
- [ ] Evidence JSON `t2` section written with raw report + verdict.
- [ ] Any mismatch is explicitly classified (expected data-shape gap vs real
      bug); no reconciler/gate code changed to force a pass.
- [ ] flake8 (100) + black clean.

## Out of scope

- Restart recovery (T3).
- Changing reconciliation tolerances, providers, or gates.
- Closing the T1 position.
