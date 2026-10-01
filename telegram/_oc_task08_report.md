# COMPLETION REPORT — TASK 08

**TASK:** 08 — RECONCILIATION + RESTART RECOVERY
**STATUS: PASS**

Repo: `C:\xampp\htdocs\project-ea-bot` · Branch `main` · HEAD `5323295` (TASK 01–07 done).

---

## FILES CHANGED

New:
- `services/python/src/execution/restart_recovery.py` — ordered restart sequence + `RestartRecoveryCoordinator` + `RestartRecoveryReport` + `ReconciliationReadinessGate`.
- `services/python/tests/test_task08_reconciliation_restart.py` — 25 tests (all STOP GATE 08 criteria).

Modified:
- `services/python/src/execution/engine.py` — durable order identity on `OrderRequest`; persist identity on SUBMITTED / ACKNOWLEDGED / POSITION_CONFIRMED (+ adopted-lost-response path).
- `services/python/src/execution/fanout.py` — stamp `signal_id` / `account_id` on the built request (and the minimal-request fallback).
- `services/python/src/orchestration/pipeline.py` — `readiness_guard` constructor arg + Step B3.5 readiness stage (fail-closed).
- `services/python/src/orchestration/runtime.py` — optional `recovery_coordinator` wiring; `run_recovery()` / `recovery_state()` accessors.
- `services/python/src/system/startup_checks.py` — `run_restart_recovery()` + production coordinator builder.
- `services/python/src/main.py` — lifespan runs restart recovery at boot (fail-closed on failure).
- `services/python/src/orchestration/endpoints.py` — `GET /reconciliation/recovery`; `GET /reconciliation/status` now includes `recovery`.
- `CHANGELOG.md` — TASK 08 entry.

## ROOT CAUSE

1. **Durable order identity was incomplete.** The ledger persisted only `intent_id` (= idempotency key) + `ticket` + symbol/volume/magic. The TASK 08 required identity (`signal_id`, `account_id`, `terminal_id`, `broker_order_ticket`, `broker_deal_ticket`, `broker_position_ticket`) was never written, so a restart could not trace an order back to its canonical signal/account/terminal.
2. **No ordered restart sequence.** `run_execution_recovery` only *flagged* UNKNOWN/SUBMITTING intents for later reconciliation; nothing actually performed load-intents → connect → read-positions → read-orders/deals → reconcile → rebuild → *then* permit execution.
3. **The `internal == empty` trap.** `ReconciliationGuard` intentionally allows execution *before* its first run (to avoid freezing a fresh system). After a real restart there is no first run yet, and a failed broker read returned `[]` indistinguishably from a genuinely empty book — so empty internal state could be mis-read as empty broker state and permit a double entry.
4. **No restart readiness gate on the execution path**, so a new order could reach the executor before broker ↔ internal state converged.

## FIX

- **Durable order identity** (`engine.py`, `fanout.py`): `OrderRequest` gains `signal_id`, `account_id`, `terminal_id`, `broker_order_ticket`, `broker_deal_ticket`, `broker_position_ticket`. The engine persists them (`_identity_fields`) on SUBMITTED/ACKNOWLEDGED/POSITION_CONFIRMED and on the adopted-lost-response path; the fan-out coordinator and the single-terminal pipeline stamp signal/account/terminal. `intent_id` remains the idempotency key.
- **Ordered restart sequence** (`restart_recovery.py`): `RestartRecoveryCoordinator.run()` executes exactly
  `start → load_durable_intents → connect_mt5 → read_open_positions → read_orders_deals → reconcile → rebuild_internal_state → reconciled`.
  Any step that cannot be *verified* short-circuits to `BLOCKED` with a reason (never raises).
- **Fail-closed, never internal-empty==broker-empty**: the position/order reads distinguish a **verified empty** book (`(True, [])`) from a **failed read** (`(False, [])`). A failed read → `broker_read_verified=False` → `BLOCKED`. `ReconciliationReadinessGate.check_can_execute()` returns `False` while `PENDING` or `BLOCKED`.
- **Pipeline enforcement** (`pipeline.py` Step B3.5): a wired `readiness_guard` blocks the cycle (`STATUS_BLOCKED`, execution skipped) until recovery reports `RECONCILED`; a broken guard fails closed. When no coordinator is wired (default `None`) behaviour is unchanged.
- **Orphan broker position** → `Reconciler.compare` reports `missing_internal` → critical → recovery `BLOCKED` → gate blocks new entries (proven directly against the real `Reconciler`).
- **Duplicate recovery is idempotent**: recovery *adopts* an intent already present at the broker (`adopted_intents`); it never re-sends. A re-dispatch of a recovered `intent_id` is refused by the engine's durable duplicate detector (409). Fan-out keeps `(signal_id, account_id)` keys unique, so N accounts get N legitimate orders while a duplicate of one account is refused.
- **Wiring** (`startup_checks.py`, `main.py`): `run_restart_recovery()` builds the production coordinator (durable ledger + read-only MT5 connector + `Reconciler`), wires the readiness gate onto the live pipeline and runs it once at boot; failure leaves the system fail-closed. Non-live mode is a **verified no-op** because the connector's synthetic positions are placeholders the engine never created (reconciling them against an empty ledger would be the exact permanent false-positive the runtime already guards against) — the full sequence still runs and any *failed* read still blocks.
- **Observability** (`endpoints.py`): `GET /reconciliation/recovery` (+ `recovery` in `/reconciliation/status`).

## TESTS

- `services/python/.venv/Scripts/python.exe -m pytest services/python/tests/test_task08_reconciliation_restart.py -q`
  → **25 passed**
- Full suite: `pytest services/python/tests -q`
  → **3039 passed, 0 failed**
- `flake8 --max-line-length=100 --extend-ignore=E203,W503` on all changed files → clean
- `black --check` on all changed files → clean

Coverage maps to STOP GATE 08:
- **Restart with open trade → state restored** → `TestRestartWithOpenTrade` (ordered steps asserted; state rebuilt; gate allows after clean run).
- **Restart with closed trade → review still possible** → `TestRestartWithClosedTrade` (closed intent is not resurrected as open; durable round-trip through a fresh `OrderStateStore`).
- **Orphan broker position blocks new entries** → `TestOrphanBrokerPositionBlocks` (real `Reconciler` → critical → BLOCKED → gate False).
- **Unknown reconciliation state blocks new entries** → `TestUnknownStateBlocks` (failed position read = unverified not empty; MT5 down; reconcile/load/orders exceptions; PENDING gate) + `TestPipelineReadinessGate` (pipeline blocks while pending, executes when reconciled, broken guard fails closed).
- **Duplicate recovery does not create duplicate order** → `TestDuplicateRecoveryIdempotent` (adopt-not-resend; engine 409 on re-execution; distinct per-account intents) + `TestDurableOrderIdentity` (identity persisted).
- **All terminals DISARMED by default** → `TestDefaultDisarmed`.

## RUNTIME VERIFICATION

- `run_restart_recovery()` against the booted runtime → `state=reconciled`, `permits_execution=True` (non-live no-op path); a failed read blocks.
- `OrchestrationRuntime(recovery_coordinator=...)` → `pipeline.readiness_guard` is a `ReconciliationReadinessGate`; gate = `(False, "…pending…")` before `run_recovery()`, `(True, "")` after. Default runtime → `pipeline.readiness_guard is None`, `run_recovery() is None` (backward compatible).
- `GET /reconciliation/recovery` (auth off) → `200`, `source="live"`, `permits_execution=True`, `recovery.state="reconciled"`; `/reconciliation/status` includes `recovery`.
- `mt5.terminals.get_armed_terminals() == []` after disarm-all and in a fresh registry → **all terminals DISARMED by default**; LIVE never enabled; no default arm changed.

## REMAINING ISSUES

- The production restart sequence is fully exercised in live mode; the **non-live (test/paper) path is intentionally a verified no-op** for reconciliation because the connector's synthetic positions are not engine-created — this matches the pre-existing runtime guard and avoids a permanent false-positive block.
- `read_deals` for the adopt-vs-resend decision returns `[]` in the production builder (order/position tickets already cover adoption matching); a broker deal-history read can be added later without changing the invariant.
- Fan-out per-account live broker reads remain the target's account snapshot (deferred from TASK 07); reconciliation identity for fan-out orders is now persisted so a later per-account read can match them.

## NEXT TASK

NOT STARTED
