# B-4 T4 — Evidence Consolidation + Blocker Closure (Report)

Status: DONE (evidence consolidated + blocker B-4 closed). No commit.
Parent plan: `docs/plans/B4-LIVE-DEMO-VALIDATION.md` (T4)
Blocker ref: `docs/audit/RELEASE_BLOCKERS.md` → B-4
Depends on: T1 (`docs/tasks/B4-T1-report.md`), T2 (`docs/tasks/B4-T2-report.md`),
T3 (`docs/tasks/B4-T3-report.md`) — all DONE and passed.

## What was consolidated

All three validation legs passed, so B-4 is closed (not PARTIAL):

- **T1 — order placed / filled.** Live DEMO fill: ticket `1353670649`, `#BTCUSD` BUY
  vol `0.01`, magic `84004`, comment `B4DEMO`, order_check retcode `0`, position left
  OPEN. Source: `docs/evidence/B-4-demo-validation.json` → `t1`.
- **T2 — live reconciliation.** T1 ticket **matched by ticket**
  (`matched == [1353670649]`, `missing_internal == []`, `broker_live == True`), but
  `has_critical == True` due to **expected artifacts**, not bugs: (a) 3 field diffs on
  the matched pair (volume/symbol/magic — ledger `position_confirmed` carries no
  metadata = data-shape gap), and (b) 14 stale `missing_in_broker` tickets (Sep 24–25,
  broker positions already closed — append-only ledger never writes a "closed" state =
  lifecycle artifact). Source: JSON → `t2`. Classification in `docs/tasks/B4-T2-report.md`.
- **T3 — restart recovery.** Two separate OS processes (`recovery-check --stage pre` /
  `--stage post`): pre → ticket in ledger FILE + armed; post (fresh process) → state
  rehydrated from FILE (`position_confirmed`), arm state EMPTY (in-memory by design →
  `arm_cleared=True`), reconciliation matched again, then **re-armed** bil2
  successfully. Source: JSON → `t3`.

## Deliverables produced

1. **`docs/evidence/B-4-demo-validation.md`** — rewritten as the final consolidated
   record. Now leads with:
   - a **Summary** table (T1/T2/T3: what was validated, result, key evidence);
   - an **Environment** table (DEMO login `49662626`, server `HFMarketsGlobal-Demo`,
     `trade_mode 0`, terminal path, symbol `#BTCUSD`, volume `0.01`, Python, timestamps);
   - a **Known gaps** section (documented, not hidden): (a) ledger record data-shape gap;
     (b) stale `position_confirmed` records without closure state → `has_critical=True`
     → `ReconciliationGuard` fail-closes NEW orders → follow-up (closure lifecycle /
     pruning) needed before live deployment; cleaning the ledger is out of B-4 scope.
   - The pre-existing per-leg detail (T1 fill / idempotent re-run, T2, T3 pre/post) is
     preserved below the consolidated sections. The JSON reference is retained.
2. **`docs/audit/RELEASE_BLOCKERS.md`** — B-4 updated with a **minimal diff**:
   - B-4 section heading → `… ✅ FIXED`; added `- **Status:** ✅ **FIXED** (DEMO validation 2026-09-26)`.
   - Added `- **Evidence:** docs/evidence/B-4-demo-validation.md — …` line (end-to-end
     validation performed: arm → order → fill → confirmation → reconciliation → restart
     recovery).
   - Added a short `- **Residual:** …` line (stale records → guard fail-closed →
     follow-up for ledger closure lifecycle), mirroring B-3's Residual style.
   - Summary table row `B-4` → `✅ Fixed (DEMO validation 2026-09-26)`.
   - Closing paragraph: "Remaining open blocker (B-4) …" → reflects closure
     ("no blocker remains open").
   - **No other blocker, section, or historical document was touched.**
3. **`docs/tasks/B4-T4-report.md`** — this report.

## Final status

**B-4: ✅ FIXED** — the DEMO validation WAS performed end-to-end (arm, order, fill,
confirmation, reconciliation, restart recovery), all recorded in
`docs/evidence/B-4-demo-validation.md` (+ `.json`). No blocker remains open in
`RELEASE_BLOCKERS.md`.

Residual carried forward (see B-4 Residual line + Known gaps): the append-only ledger
has no closure lifecycle, so stale `position_confirmed` records keep
`has_critical=True` and the `ReconciliationGuard` fail-closes NEW orders. This is
correct fail-closed behaviour and requires a follow-up (closure lifecycle / pruning)
before live deployment — out of B-4 scope.

## Files changed

- `docs/evidence/B-4-demo-validation.md` — consolidated record (summary + environment +
  known gaps; existing detail preserved).
- `docs/audit/RELEASE_BLOCKERS.md` — B-4 section status/evidence/residual + summary row
  + closing paragraph (minimal diff; nothing else touched).
- `docs/tasks/B4-T4-report.md` — this report.

`docs/evidence/B-4-demo-validation.json` was **not modified** (T1–T3 already wrote it;
T4 only references it). No `src/**` or other files changed. No commit.

## Acceptance checklist

- [x] Evidence MD + JSON complete and consistent with T1–T3 outputs (JSON unchanged;
      MD summary table, environment, known gaps match `t1`/`t2`/`t3`).
- [x] `RELEASE_BLOCKERS.md` B-4 updated with minimal diff (6 insertions / 3 deletions);
      no other blocker/section/document touched.
- [x] Final report written (this file).

## Out of scope (untouched)

- T5 (hardening `/mt5/orders/execute`) — optional, separate task.
- Closing the open demo position (ticket `1353670649` left OPEN).
- Commits (user rule: do not commit).
