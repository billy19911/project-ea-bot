# B-4 T4 — Evidence Consolidation + Blocker Closure

Status: TODO (delegasi OpenCode, setelah T1–T3 selesai)
Parent plan: `docs/plans/B4-LIVE-DEMO-VALIDATION.md` (task T4)
Blocker ref: `docs/audit/RELEASE_BLOCKERS.md` → B-4 (lines 64–79)

## Goal

Consolidate the T1–T3 evidence into a single readable validation record and
update `docs/audit/RELEASE_BLOCKERS.md`: mark B-4 as FIXED with the evidence
reference — ONLY if T1–T3 all passed. If any part failed, mark it PARTIAL and
list exactly what is missing.

## Actual results to consolidate (verified — trust these)

- **T1**: live DEMO fill — ticket `1353670649`, `#BTCUSD` BUY vol `0.01`,
  magic `84004`, comment `B4DEMO`, order_check retcode 0, position left OPEN.
  Evidence: `docs/evidence/B-4-demo-validation.json` → `t1`.
- **T2**: reconciliation run live — T1 ticket **matched by ticket**
  (`matched == [1353670649]`, `missing_internal == []`), BUT
  `has_critical() == True` due to: (a) 3 field diffs on the matched pair
  (volume/symbol/magic — the ledger `position_confirmed` records carry no
  metadata: expected data-shape gap), and (b) **14 stale `missing_in_broker`
  tickets** from Sep 24–25 whose broker positions are already closed — the
  append-only ledger never writes a "closed" state (expected lifecycle
  artifact). Both classified in `docs/tasks/B4-T2-report.md` as expected
  artifacts, NOT bugs. **Implication to document**: the `ReconciliationGuard`
  fail-closes NEW orders while those stale records remain (`last_ok=False`) —
  a follow-up (closure lifecycle / pruning) is needed; cleaning the ledger is
  out of B-4 scope.
- **T3**: two separate processes (`recovery-check --stage pre` / `--stage post`):
  pre → ticket in ledger FILE + armed; post (fresh process) → state rehydrated
  from FILE (`position_confirmed`), arm state EMPTY (in-memory by design),
  reconciliation matched again, then **re-armed** bil2 successfully.
  Evidence: `docs/evidence/B-4-demo-validation.json` → `t3`.

## Deliverables

1. `docs/evidence/B-4-demo-validation.md` — final consolidated record:
   - Summary table: T1 (order placed, ticket, retcode) / T2 (reconciliation
     matched by ticket; has_critical=True due to expected artifacts) / T3
     (restart recovery: ledger persisted, rehydrated, matched, re-arm required
     by design → re-armed).
   - Raw evidence references: `docs/evidence/B-4-demo-validation.json`.
   - Environment: DEMO account (login 49662626, server HFMarketsGlobal-Demo,
     trade_mode 0), terminal path, symbol, volume, timestamps.
   - Known gaps section (documented, not hidden): (a) ledger record data-shape
     gap (no symbol/volume/magic in `position_confirmed`); (b) stale
     `position_confirmed` records without closure state → `has_critical=True`
     → follow-up needed (closure lifecycle/pruning) before live deployment.
2. Update `docs/audit/RELEASE_BLOCKERS.md`:
   - Change B-4 status line(s) from OPEN → FIXED, adding one line:
     `Evidence: docs/evidence/B-4-demo-validation.md` (the validation WAS
     performed end-to-end: arm, order, fill, confirmation, reconciliation,
     restart recovery — all recorded). In the B-4 section also add a short
     `Residual:` line noting the reconciliation findings above (stale records
     → guard fail-closed → follow-up for ledger closure lifecycle), mirroring
     the style of B-3's Residual line.
   - Also update the Summary table row `B-4` → `✅ Fixed (DEMO validation
     2026-09-26)` and the closing paragraph's "Remaining open blocker (B-4)"
     sentence to reflect closure.
   - **Do NOT touch any other blocker, section, or historical document.**
   - **Do NOT reformat other files**; minimal diff only.
3. `docs/tasks/B4-T4-report.md` — what was consolidated, final status, list of
   files changed.

## Acceptance criteria

- [ ] Evidence MD + JSON complete and consistent with T1–T3 outputs.
- [ ] `RELEASE_BLOCKERS.md` B-4 updated with minimal diff; nothing else touched.
- [ ] Final report written.

## Out of scope

- T5 (hardening `/mt5/orders/execute`) — optional, separate task.
- Closing the open demo position.
- Commits (user rule: do not commit).
