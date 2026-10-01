# TASK 12 — ADVERSARIAL E2E CERTIFICATION — COMPLETION REPORT

TASK: 12
STATUS: PASS

## FILES CHANGED

- `services/python/tests/test_task12_adversarial_e2e.py` (NEW) — 33 adversarial
  E2E tests covering **all 13 scenarios A–M** end-to-end across the real stack
  (event queue → event gate → scheduler → pipeline → supervisor → canonical
  fan-out → deterministic risk gate → reconciliation/restart recovery →
  review/R pipeline → error taxonomy → terminal arm state). Only the MT5 client
  boundary (`ExecutionEngine` send / broker reads) is faked; every other
  component is the real production module.
- `services/python/src/agents/supervisor.py` — **hardening fix (R1)**: the
  classifier `_classify_agent_exception` now loads the `llm.errors` taxonomy
  under BOTH import identities via a new `_load_llm_errors()` helper (relative
  `..llm.errors`, then absolute `llm.errors`, then `src.llm.errors`). +28/-2.
- `telegram/_oc_task12_report.md` (this file).

## ROOT CAUSE

The task required proving cross-stack invariants with REAL components. Two
genuine defects were surfaced while writing the certification:

- **R1 — provider-503 mis-attribution under the unified dual-import scheme.**
  `SupervisorAgent._classify_agent_exception` imported the taxonomy with a bare
  relative import (`from ..llm.errors import ...`). That spelling is only valid
  when the module is loaded as `src.agents.supervisor` (package `src.agents`).
  When the supervisor is loaded as the top-level `agents.supervisor` (which the
  test suite / dual-import finder can do), `..llm.errors` is a
  *"relative import beyond top-level package"* → the outer `except` silently
  degraded **every** LLM provider 503 into a generic `AGENT_EXCEPTION`. The
  failing layer was therefore lost (violates MASTER_PLAN invariants 18/19). In
  production the correct spelling usually won, but the classifier was
  order/identity-dependent and could not be certified deterministically.
- **R2 — test-environment note (not a product defect).** The repo's `pytest.ini`
  sets `--basetemp=./temp_pytest`, which collides with a directory locked by the
  already-running services. Runs used a fresh `--basetemp` (documented in TASK
  11 as a pre-existing environment quirk) — unchanged here.

No other product defect was found: every other invariant already held under the
real components and was confirmed by the new tests.

## FIX

- **R1:** added `_load_llm_errors()` (`agents/supervisor.py`) trying the relative
  identity first, then the two absolute spellings, so the real failing layer is
  always attributed regardless of load order. `_classify_agent_exception` now
  uses it for both `classify_llm_exception` and `classify`. Behaviour is
  unchanged where the relative import already worked (production); where it
  failed, a provider 503 now correctly classifies as `LLM_PROVIDER_503` instead
  of `AGENT_EXCEPTION`. No trading behaviour, arm default, or risk path changed.
- **Tests:** `tests/test_task12_adversarial_e2e.py` asserts each scenario with an
  explicit invariant (see RUNTIME VERIFICATION). An autouse fixture disarms every
  terminal before and after each test and asserts `is_execution_armed() is False`.

## TESTS

- Command: `./.venv/Scripts/python.exe -m pytest tests/test_task12_adversarial_e2e.py -q -p no:cacheprovider --basetemp=<fresh>`
  - Result: **33 passed**.
- Command: `./.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --basetemp=<fresh>`
  - Result: **3098 passed, 1 warning** (baseline 3065 + 33 new TASK 12 tests).
- Command: `./.venv/Scripts/python.exe -m pytest tests/test_supervisor.py tests/test_supervisor_department_routing.py tests/test_supervisor_kpis.py tests/test_supervisor_policy.py tests/test_task02_event_driven_supervisor.py tests/test_task03_committee_behavior.py tests/test_task06_canonical_fanout.py tests/test_error_taxonomy.py tests/test_agent_activity.py tests/test_task12_adversarial_e2e.py -q`
  - Result: all pass (regression check for the supervisor change + import-order
    robustness).
- Command (Node API boundary, unchanged): `node --test test/error-taxonomy.test.cjs test/pythonClient.test.cjs` (in `apps/api`)
  - Result: **34 pass, 0 fail**.
- Note: `--basetemp=<fresh dir>` is required because the repo `pytest.ini`
  basetemp (`./temp_pytest`) collides with a directory locked by the running
  services (pre-existing env quirk, documented in TASK 11).

## RUNTIME VERIFICATION (per scenario A–M)

All proven by the new tests; concrete observed evidence in parentheses.

- **A. No event** — empty `EventQueue` → `process_available()==0`, committee
  never called, `trades_proposed==0`; a poll yielding only housekeeping
  (`RISK_DRAWDOWN`, `METRICS`) is gated, no proposal. (`events_gated==2`)
- **B. Event** — qualifying `BREAKOUT`/`MOMENTUM_BULLISH` → wake → supervisor →
  committee → exactly ONE signal. (`supervisor.calls==1`, 1 order; a new-bar
  event passes the gate but is held by the live-signal registry → no re-analysis)
- **C. Duplicate event** — 3 identical `(symbol,type,bar)` events → `processed==1`,
  `supervisor.calls==1`, 1 order, `events_gated==2`, trace shows `gated:*`.
- **D. Multi-account** — ONE canonical signal → 3 accounts (2 DEMO + 1 LIVE
  configured) → 3 execution attempts, every dispatch `signal_id=="sig_D"`, every
  order idempotency key `"sig_D:<account>"`. (`executed==3`)
- **E. One account fails** — A ok / B broker-reject / C ok → `supervisor.calls==1`
  (NO second AI analysis); B recorded `FAILED` under the SAME `signal_id`;
  `ledger.all_signals()==1`.
- **F. Risk** — existing exposure 25% + proposal 10% = **35% > 30% limit** →
  gate `approved==False`, `checks_passed["max_exposure"]==False`,
  `current_exposure_pct==0.25`, `projected_exposure_pct==0.35`. Boundary: exactly
  30% allowed, 30%+ε blocked.
- **G. Restart** — durable open intent + broker position → ordered sequence
  `load_durable_intents → connect_mt5 → read_open_positions → read_orders_deals →
  reconcile → rebuild_internal_state → reconciled`; state restored
  (`permits_execution==True`); readiness gate BLOCKS before the run and allows
  after; an orphan broker position → `BLOCKED`.
- **H. R** — entry 2500, initial SL 2495, exit 2510 → R `== 2.0`; canonical
  signal `risk_distance==5.0`, `tp_distance==10.0`, `planned_RR==2.0`; the real
  `ReviewAutoTrigger` close path produces `r_multiple==2.0`.
- **I. Trailing** — trailing SL 2506, exit 2510 → R still `== 2.0` using the
  ORIGINAL 2495; using the trailed SL yields a different number, and the
  persisted entry context keeps `initial_stop_loss==2495.0`.
- **J. AI provider 503** — `classify_llm_exception(503)` → `LLM_PROVIDER_503`
  (layer `llm_provider`, retryable, never `AGENT_EXCEPTION`); the REAL
  `SupervisorAgent.analyze` running an agent that raises a 503 → no proposal
  (`WAIT`) and the AI Control activity record carries `last_error.code ==
  LLM_PROVIDER_503`; no order reaches execution; the web cause label for
  `LLM_PROVIDER_503`/`PYTHON_SERVICE_UNAVAILABLE` never contains "agent".
- **K. Python service down** — the REAL compiled Node `pythonClient.getJson`
  against a closed port returns `{ok:false, source:"unavailable",
  error:"python_service_unavailable"}` (→ 503); the REAL compiled taxonomy
  `classifyProxyFailure` → `PYTHON_SERVICE_UNAVAILABLE` (layer `python_service`,
  retryable); the web label is "Python service tidak tersedia"; the Python
  taxonomy agrees.
- **L. LIVE disarmed** — a LIVE terminal configured (`execution:true`) → startup
  DISARMED (`armed==False`, `is_execution_armed()==False`, no fan-out targets);
  a signal IS analysed (`decision=="BUY"`) but the REAL engine refuses the native
  order ("EXECUTION NOT ARMED"); arming an unattached terminal fails-closed.
- **M. DEMO armed** — DEMO terminal + explicit ARM → `is_execution_armed()==True`,
  it becomes a fan-out target; one signal passes every gate and the fan-out
  executes (`executed==1`); cleanup disarms and re-asserts
  `is_execution_armed()==False`. A global test asserts no terminal stays armed.

**Safety:** every test runs with an autouse fixture that forces all terminals
DISARMED before/after and asserts the invariant; the final scenario asserts
`get_armed_terminals()==[]`. All MT5 execution paths remain DISARMED by default;
no LIVE default was enabled and no default arm state was changed.

## STOP GATE (TASK 12)

- [x] 13/13 scenarios (A–M) have at least one explicit-assertion test.
- [x] Tests use REAL components (pipeline, supervisor, event gate, canonical
  fan-out, deterministic risk gate, reconciliation/restart recovery, review/R,
  error taxonomy, terminal arm state); only the MT5 client boundary is faked.
- [x] Full suite passes (3098 passed).
- [x] No terminal left armed; all terminals DISARMED by default.
- [x] No other task touched; all commands < 60s; no blocking foreground servers.

## REMAINING ISSUES

- R2 (env, pre-existing): `pytest.ini` `--basetemp=./temp_pytest` collides with a
  directory locked by the running services; runs use a fresh `--basetemp`.
- R3 (out of scope): the certification exercises the MT5 boundary with fakes and
  the in-process arm/terminal registry; it does not drive a live MT5 terminal
  (correctly so — execution must stay DISARMED).

## NEXT TASK

NOT STARTED
