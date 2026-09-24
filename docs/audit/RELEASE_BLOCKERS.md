# RELEASE BLOCKERS — XynnBot

**Audited commit:** `cfc8551`
**Scope:** blockers for **live-money deployment**. None of these block a paper / staging / read-only demo release.
**Companion:** `docs/audit/RELEASE_READINESS_REPORT.md`

---

## B-1 — Python API is unauthenticated in the shipped runtime (arm switch exposed) ✅ FIXED

- **ID:** B-1
- **Severity:** P0
- **Component:** `services/python/src/main.py`, `services/python/src/security/api_key.py`, `.env.runtime`
- **Status:** ✅ **FIXED** (operational: `.env.runtime` patched 2026-09-24)
- **Evidence (before fix):**
  - `main.py:288-308` installs `ApiKeyMiddleware` **only if `settings.python_api_key`** is truthy.
  - `.env.runtime` did **not** define `PYTHON_API_KEY` (verified via key-name enumeration).
  - No endpoint uses FastAPI `Depends`/`Security` for auth (grep-verified).
  - `mt5/endpoints.py:85` `POST /mt5/terminals/arm` — the switch that arms live execution — is subject only to that conditional middleware.
- **Impact (before fix):** Anyone able to reach the Python port can arm live execution, run pipeline cycles, toggle circuit breakers, and change settings without a token.
- **Reproduction (before fix):**
  1. Start the Python service with the shipped `.env.runtime` (no `PYTHON_API_KEY`).
  2. `POST http://<host>:8787/mt5/terminals/arm` with `{"armed": true}` → accepted without credentials (subject to config `execution:true`).
- **Fix applied:** `.env.runtime` now defines `PYTHON_API_KEY` (32-byte urlsafe token, generated `python -c "import secrets; print(secrets.token_urlsafe(32))"`). File is gitignored; key never committed. `scripts/start-all.ps1` line 118 exports `$env:PYTHON_API_KEY` → `Export-CommonEnv` forwards to both Python and Node child processes. Node client (`apps/api/src/pythonClient.ts`) injects `x-api-key` header (B-2 fix, commit `021565e`).
- **Verification (2026-09-24):**
  - Python `/decisions` unauth → `401`, with `x-api-key` → `200` ✅
  - Python `/mt5/terminals/arm` unauth → `401` (fail-closed) ✅
  - Node `/decisions` with Bearer token → `200` (Node injects `x-api-key` to Python automatically) ✅
  - Warning `"PYTHON_API_KEY is not set"` count = `0` ✅

---

## B-2 — Node→Python authentication chain is broken

- **ID:** B-2
- **Severity:** P0
- **Component:** `apps/api/src/pythonClient.ts`, `apps/api/src/index.ts`, `services/python/src/security/api_key.py`
- **Evidence:** `apps/api` contains **no** `X-API-Key`/`PYTHON_API_KEY` reference (grep-verified). The Node proxy builds headers with only `X-Trace-Id`.
- **Impact:** Either the Python service is unauthenticated (key unset → B-1) or, if the key is set as production guidance requires, **every Node→Python proxy call returns 401** and the control plane breaks.
- **Reproduction:** Set `PYTHON_API_KEY` in the environment; any dashboard action proxied through Node fails with 401/503.
- **Recommended Fix:** Add `x-api-key: process.env.PYTHON_API_KEY` to `pythonClient.ts` request headers and pass the same value to the Python process; add an integration test asserting an authenticated proxy round-trip.

---

## B-3 — Deterministic Risk Gate is not enforced inside the executor (structural boundary gap)

- **ID:** B-3
- **Severity:** P0 (structural)
- **Component:** `services/python/src/execution/engine.py`, `services/python/src/mt5/endpoints.py`, `services/python/src/agents/permissions.py`
- **Status:** ✅ **FIXED** (commit `02a577c`)
- **Evidence (before fix):**
  - `ExecutionEngine.execute_order()` (`execution/engine.py:314-476`) referenced no `RiskGate`, `MT5WriteGuard`, `KillSwitch`, or `ExecutionGuard`.
  - `POST /mt5/orders/execute` (`mt5/endpoints.py:204-218`) → `connector.execute_order()` with no gate/guard/permission check.
  - `agents.permissions.send_to_mt5` → `guarded_execute_order` enforces WriteGuard but no RiskGate, and is never called from `src/`.
- **Fix applied:**
  - `OrderRequest` gained an `approval_token` field; `ExecutionEngine(require_approval=True)` **refuses to dispatch** any order whose token is empty (fail-closed, `error_code=403`), before any MT5 call.
  - `TradingPipeline.run` stamps `approval_token = "gate:<decision_id>"` **only after** the Risk Gate approves and both guards pass.
  - The production runtime (`runtime.py`) opts in with `require_approval=True`; the default is `False` to keep existing direct/test usage compatible.
  - Tests: `tests/test_rc_fixes_b3_b6.py`, `tests/test_execution_engine.py` (Audit B-3 section), `tests/test_pipeline_orchestration.py` (`TestApprovalToken`).
- **Residual:** `/mt5/orders/execute` still calls the *connector* (which refuses in live mode); it does not call the executor, so it remains a paper/simulated surface. Gating that endpoint behind the same approval path is optional hardening. The executor-enforced boundary now closes the structural gap for the executor itself.

---

## B-4 — No live broker validation has ever been performed

- **ID:** B-4
- **Severity:** P0 (for live readiness)
- **Component:** Runtime execution path (`orchestration/runtime.py:279`), MT5 connector/terminals
- **Evidence:**
  - Shipped runtime wires `ExecutionEngine(mt5_connector=None, simulation_mode=True)`.
  - All 9 terminals in `mt5_terminals.json` are `execution:false`.
  - No recorded evidence of a real order, fill, or reconciliation against a live account anywhere in the repo.
- **Impact:** Live-mode behavior (order_send, confirmation, retry/lost-response, volume-step, broker rejection handling, reconciliation against a live account) is **unverified**. Do not claim live readiness.
- **Reproduction:** N/A — absence of validation.
- **Recommended Fix:** Perform a controlled DEMO-account validation (arm a demo terminal, place a small order, verify fill/confirmation/reconciliation/restart recovery) and record the evidence before any live deployment.

---

## B-5 — Order/risk state is not durable across restart ✅ FIXED

- **ID:** B-5
- **Severity:** P1
- **Component:** `services/python/src/execution/state_machine.py`, `services/python/src/execution/intents.py`, `services/python/src/risk/kill_switch.py`, `services/python/src/monitoring/position_monitor.py`
- **Status:** ✅ **FIXED** (commit `58d99be`)
- **Evidence (before fix):** All four stores are module-level in-memory dicts; comments explicitly note "In production this would be persisted." Restart resets a TRIGGERED/LOCKED kill switch to ACTIVE and clears the order ledger.
- **Impact:** Restart can lose execution/risk state, mis-drive reconciliation (empty internal ledger), and reset an engaged kill switch — contradicting the restart-recovery safety claim.
- **Fix applied:** Four new append-only JSONL stores (`persistence/order_state_store.py`, `intent_store.py`, `kill_switch_store.py`, `position_reconciliation_store.py`) mirror the existing `JsonlLessonStore` pattern (stdlib only, cache+disk, fail-safe). `main.py` lifespan wires the three global stores after `JsonlLessonStore`; `orchestration/runtime.py` injects the `PositionReconciliationStore` into `PositionMonitor`. On restart, each store reloads its cache from disk, restoring the order ledger, intent registry, kill-switch state, and last reconciliation snapshot. Corrupt JSONL lines are skipped (warning logged); unwritable paths degrade to cache-only; every persistence call is wrapped in `try/except` so a disk error can never break the execution/risk path. `store=None` preserves backward compat (in-memory only).
- **Tests:** `tests/persistence/` (20 tests: restart survival × 4, fail-safe corrupt-skip × 4, unwritable degrade × 1, backward compat × 4, integration × 7); full suite 2102 passed, no regressions. `black --line-length 100` ✅, `isort` ✅, `flake8 --max-line-length=100 --extend-ignore=E203,W503` ✅.

---

## B-6 — Trade-close → review → learning leg does not fire from runtime trades

- **ID:** B-6
- **Severity:** P1 (governance/learning claim)
- **Component:** `services/python/src/review/close_detector.py`, `services/python/src/monitoring/position_monitor.py`, `services/python/src/review/auto_trigger.py`, `services/python/src/orchestration/runtime.py`
- **Status:** ✅ **FIXED** (commit `02a577c`)
- **Evidence (before fix):** No runtime producer emitted `TRADE_CLOSE`/`POST_TRADE_REVIEW`; `PositionCloseDetector` and `PositionMonitor` were never instantiated in `src/`; the only `on_position_closed` caller was the unwired `paper` engine. The persistent `JsonlLessonStore` therefore stayed empty in normal operation.
- **Fix applied:**
  - The runtime builds a read-only `PositionMonitor` with a `PositionCloseDetector` whose `on_close` fires the process-wide `ReviewAutoTrigger` (configured in `main.py` to persist lessons).
  - It observes open positions **once per cycle** (both HTTP-triggered `run_cycle` and scheduler-driven `_RecordingPipelineProxy.run`).
  - **Observation only** — reads positions, detects disappeared tickets; never places, modifies, or closes anything.
  - Tests: `tests/test_rc_fixes_b3_b6.py` (wiring + disappeared-ticket-fires-hook).
- **Residual:** The close price for a disappeared ticket is the last-seen current price (honest best-effort). Review quality depends on position data quality; a real broker close event would be richer.

---

## B-7 — Native `order_send` could be reached without the arm gate (found during entry investigation)

- **ID:** B-7
- **Severity:** P0 (safety, latent)
- **Component:** `services/python/src/execution/engine.py`
- **Status:** ✅ **FIXED** (commit `a2a9258`)
- **Discovery:** While investigating whether a supervisor "command to entry" could execute, the executor's native path was observed to call `mt5.order_send()` on a machine with a **real MetaTrader 5 terminal installed**. The previous guard only blocked the native send when `mt5.connector.is_live_mode()` was True. When the connector was not attached (read-only live-data OFF) but `MetaTrader5` was importable, the engine called `order_send` **without the operator arm gate and without `initialize()`** — returning `None` → `error_code=0, message=''` (a misleading failure), and, in the general case, an un-armed opportunity to reach the broker.
- **Impact:** On any host with a real MT5 terminal, the native send path was not gated by the operator arm switch. This contradicts the "execution requires an explicit arm" safety claim.
- **Fix applied:** `_send_to_mt5` now requires `mt5.terminals.execution_permitted()` (the operator arm switch, itself fail-closed) **before any native `mt5.order_send`, regardless of live-data mode**. Not armed → explicit `error_code=403` "EXECUTION NOT ARMED". Simulation is only reached when native `MetaTrader5` is genuinely unimportable.
- **Tests:** `tests/test_entry_completion.py::test_native_send_requires_armed_terminal`; updated `tests/test_mt5_live_data_mode.py` wording.

---

## B-8 — Entry proposal lacked SL/TP/size → never reached execution

- **ID:** B-8
- **Severity:** P1 (core entry functionality)
- **Component:** `services/python/src/orchestration/pipeline.py`
- **Status:** ✅ **FIXED** (commit `a2a9258`)
- **Discovery:** A supervisor "command to entry" produced a proposal with a direction but **no SL/TP and no size**. The Risk Gate correctly rejected the missing SL/TP; once provided, execution then failed with `Volume must be positive, got 0.0` because nothing sized the position. `MoneyManager.calculate_lot_size`/`calculate_sl_tp` existed but were not called in the pipeline.
- **Impact:** No entry could complete end to end, even when the committee voted a direction and the gate approved.
- **Fix applied:** The pipeline deterministically **completes** missing `entry_price`/`stop_loss`/`take_profit`/`size` from `market_state` (ATR) + account equity via `MoneyManager`. Values the proposal already provides are **never overridden**; any completion error is swallowed so the gate still fails closed. Verified end to end: `supervisor (SELL) → risk OK → guards OK → execution EXECUTED (simulated)`.
- **Tests:** `tests/test_entry_completion.py` (completion, no-override, full path).

---

## Summary

| ID | Severity | Status |
|---|---|---|
| B-1 | P0 | ✅ Fixed (operational: `.env.runtime` 2026-09-24) |
| B-2 | P0 | ✅ Fixed (`021565e`) |
| B-3 | P0 (structural) | ✅ Fixed (`02a577c`) |
| B-4 | P0 | Open (operational: live broker validation) |
| B-5 | P1 | ✅ Fixed (`58d99be`) |
| B-6 | P1 | ✅ Fixed (`02a577c`) |
| B-7 | P0 (safety, latent) | ✅ Fixed (`a2a9258`) |
| B-8 | P1 (entry functionality) | ✅ Fixed (`a2a9258`) |

**Remaining open blocker (B-4)** is an operational/deployment action (live broker validation) that requires a real broker — it is not a code defect that can be safely fixed in an isolated change. **B-1 (auth enforcement) closed operationally 2026-09-24; B-2 (Node→Python key forwarding) fixed in commit `021565e`; B-5 (durable state persistence) fixed in commit `58d99be`.**
