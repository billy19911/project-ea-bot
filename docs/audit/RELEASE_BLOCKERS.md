# RELEASE BLOCKERS — XynnBot

**Audited commit:** `cfc8551`
**Scope:** blockers for **live-money deployment**. None of these block a paper / staging / read-only demo release.
**Companion:** `docs/audit/RELEASE_READINESS_REPORT.md`

---

## B-1 — Python API is unauthenticated in the shipped runtime (arm switch exposed)

- **ID:** B-1
- **Severity:** P0
- **Component:** `services/python/src/main.py`, `services/python/src/security/api_key.py`, `.env.runtime`
- **Evidence:**
  - `main.py:288-308` installs `ApiKeyMiddleware` **only if `settings.python_api_key`** is truthy.
  - `.env.runtime` does **not** define `PYTHON_API_KEY` (verified via key-name enumeration).
  - No endpoint uses FastAPI `Depends`/`Security` for auth (grep-verified).
  - `mt5/endpoints.py:85` `POST /mt5/terminals/arm` — the switch that arms live execution — is subject only to that conditional middleware.
- **Impact:** Anyone able to reach the Python port can arm live execution, run pipeline cycles, toggle circuit breakers, and change settings without a token.
- **Reproduction:**
  1. Start the Python service with the shipped `.env.runtime` (no `PYTHON_API_KEY`).
  2. `POST http://<host>:8787/mt5/terminals/arm` with `{"armed": true}` → accepted without credentials (subject to config `execution:true`).
- **Recommended Fix:** Set `PYTHON_API_KEY` in the production environment and forward it from the Node client (see B-2); or bind to a private Unix socket / loopback and make the Node API the only reachable caller. Add per-endpoint auth as defense in depth.

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
- **Severity:** P0 (structural) — latent in the shipped config
- **Component:** `services/python/src/execution/engine.py`, `services/python/src/mt5/endpoints.py`, `services/python/src/agents/permissions.py`
- **Evidence:**
  - `ExecutionEngine.execute_order()` (`execution/engine.py:314-476`) references no `RiskGate`, `MT5WriteGuard`, `KillSwitch`, or `ExecutionGuard`.
  - `POST /mt5/orders/execute` (`mt5/endpoints.py:204-218`) → `connector.execute_order()` with no gate/guard/permission check.
  - `agents.permissions.send_to_mt5` → `guarded_execute_order` enforces WriteGuard but no RiskGate, and is never called from `src/`.
  - `MT5WriteGuard` is only reachable via `guarded_execute_order`, which production never calls.
- **Impact:** Order dispatch is reachable without the deterministic gate. Currently mitigated because the read-only connector refuses in live mode and the shipped engine is simulated; but the "non-bypassable gate" is enforced by orchestration discipline, not by the executor.
- **Reproduction:** Call `ExecutionEngine.execute_order(request)` directly (or `POST /mt5/orders/execute` with live mode off) — no gate runs.
- **Recommended Fix:** Make the executor require a gate-issued approval token (signed decision id / risk-approved flag) before `_send_to_mt5`, and gate `/mt5/orders/execute` behind the same path. Fail closed if the token is absent. Keep the change minimal (a pre-flight assertion inside `execute_order`).

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

## B-5 — Order/risk state is not durable across restart

- **ID:** B-5
- **Severity:** P1
- **Component:** `services/python/src/execution/state_machine.py`, `services/python/src/execution/intents.py`, `services/python/src/risk/kill_switch.py`, `services/python/src/monitoring/position_monitor.py`
- **Evidence:** All four stores are module-level in-memory dicts; comments explicitly note "In production this would be persisted." Restart resets a TRIGGERED/LOCKED kill switch to ACTIVE and clears the order ledger.
- **Impact:** Restart can lose execution/risk state, mis-drive reconciliation (empty internal ledger), and reset an engaged kill switch — contradicting the restart-recovery safety claim.
- **Recommended Fix:** Persist the order state machine, kill-switch state, and last reconciliation snapshot to the existing store (JSONL/DB). This is the previously **deferred P2-15**.

---

## B-6 — Trade-close → review → learning leg does not fire from runtime trades

- **ID:** B-6
- **Severity:** P1 (governance/learning claim)
- **Component:** `services/python/src/review/close_detector.py`, `services/python/src/monitoring/position_monitor.py`, `services/python/src/review/auto_trigger.py`, `services/python/src/paper/simulated_execution.py`
- **Evidence:** No runtime producer emits `TRADE_CLOSE`/`POST_TRADE_REVIEW`; `PositionCloseDetector` and `PositionMonitor` are never instantiated in `src/`; the only `on_position_closed` caller is the unwired `paper` engine. The persistent `JsonlLessonStore` therefore stays empty in normal operation.
- **Impact:** The claimed "learning loop" is inert at runtime; the P1-6 "FIXED" status in `DEEP_E2E_AUDIT.md` is not substantiated by current source.
- **Reproduction:** Run the autonomous loop to a closed trade (simulated) and observe no lesson is written to `logs/lessons.jsonl`.
- **Recommended Fix:** Instantiate `PositionMonitor` (with a `PositionCloseDetector`) in the runtime and drive it from the scheduler so a disappeared ticket fires `ReviewAutoTrigger.on_position_closed` (observation-only). Add an integration test.

---

## Summary

| ID | Severity | Blocks live? | Blocks paper/staging? |
|---|---|---|---|
| B-1 | P0 | Yes | No |
| B-2 | P0 | Yes | No |
| B-3 | P0 (structural) | Yes | No (mitigated) |
| B-4 | P0 | Yes | No |
| B-5 | P1 | Yes | No |
| B-6 | P1 | No | No |
