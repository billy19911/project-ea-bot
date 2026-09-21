# RELEASE READINESS REPORT — XynnBot

**Repository:** `billy19911/project-ea-bot`
**Audited commit:** `cfc8551` (`chore(cleanup): close P3 findings from deep E2E audit`), 2026-09-22
**Audit type:** Final Release-Candidate Audit (read-only; no code modified)
**Method:** Actual source trace + runtime wiring inspection + executed test suites, cross-checked against configuration and documentation.
**Verification hierarchy:** runtime wiring > executed tests > source > documentation.

> This audit was performed against the **actual current source tree**, not against the prior audit's claims.
> Where a prior audit (`docs/audit/DEEP_E2E_AUDIT.md`) marked an item "FIXED", that claim was independently re-verified against source. Two such claims did **not** survive re-verification (see §Component Verification → P1-6, and §Dead/Orphaned Code).

---

## Executive Summary

XynnBot is a **substantially real, coherent, fail-closed analysis + decision + deterministic-risk-gate system**. The autonomous loop `market feed → event → supervisor → departments/specialists → committee consensus → trade proposal → deterministic Risk Gate → dependency/reconciliation guards → execution` is genuinely wired end-to-end and is driven by a scheduler that starts without Telegram/user interaction. Every stage fails **closed**: supervisor error → WAIT, risk-gate error → BLOCK, guard error → BLOCK, execution error → ERROR (no fabricated success).

The system is **NOT a bag of disconnected interfaces** in its core decision path. However, the audit found a real boundary problem and several material disconnects between documented "safety gates" and what the runtime actually enforces:

1. **The deterministic Risk Gate is enforced by the *caller* (pipeline), not by the *executor*.** `ExecutionEngine.execute_order()` contains no reference to the Risk Gate, the `MT5WriteGuard`, or the kill switch. Other reachable call sites (`POST /mt5/orders/execute`, `agents.permissions.send_to_mt5`, `DemoTradingManager.measure_latency`) reach order dispatch without the gate. This is **latent** in the shipped config because the endpoint is read-only/refusing and the write guard is not wired — but it is not a *non-bypassable* boundary in the executor.
2. **The Python API is unauthenticated in the shipped runtime.** The `ApiKeyMiddleware` is only installed when `PYTHON_API_KEY` is set; it is **not set** in `.env.runtime`. The **arm-execution switch** (`POST /mt5/terminals/arm`) and all mutating endpoints are therefore reachable unauthenticated (mitigated only by the loopback bind).
3. **The Node→Python trust chain is broken.** The Node API never forwards `X-API-Key`; setting `PYTHON_API_KEY` (as production guidance requires) would make every proxy call 401. Auth does not compose.
4. **Substantial governance/learning/research scaffolding is orphaned** — defined and unit-tested but never instantiated in the production runtime (`ModelRouter`, `LearningEngineV2`, `ExecutionRecoveryEngine`, `PositionCloseDetector`/`PositionMonitor`, `MultiLevelBreaker`/`CapitalAllocator` in the trade path, the entire `memory` package, `Task`/`DecisionState`/`EvidenceItem` contracts, the permission guards).
5. **The trade-close → review → learning leg does not fire from runtime trades** (the P1-6 "fix" is an uninstantiated bridge).

**Verdict: the system is CODE-READY and STAGING/PAPER-READY for analysis + deterministic decisioning, but it is NOT LIVE-READY for real-money execution.** No live broker validation has ever been performed; execution in the shipped runtime is either blocked (live read-only, unless armed) or simulated. The single largest structural concern for any future live deployment is finding #1 above.

---

## System Maturity

Using factual stages (no numerical score):

| Stage | Status | Basis |
|---|---|---|
| **Implemented** | ✅ YES | Full multi-service monorepo: FastAPI brain, Node API, Next.js dashboard, Telegram, infra. |
| **Unit-tested** | ✅ YES | 1943 Python tests pass; 46 Node tests pass; web typecheck + lint clean. |
| **Integration-tested** | ✅ YES (broad) | Pipeline orchestration, supervisor routing, reconciliation wiring, runtime settings, system endpoints all covered. |
| **End-to-end verified** | ⚠️ PARTIAL | Autonomous feed→decision loop verified by tests + CHANGELOG E2E note; **execution leg is simulated**; trade-close→learning leg does not fire. |
| **Staging / DEMO validated** | ⚠️ PARTIAL | Read-only MT5 live-data mode + paper simulation are coherent; no operator-run DEMO-account validation evidence in repo. |
| **LIVE validated** | ❌ NO | No real broker order has ever been placed by this system in validation. Execution is simulated or blocked. **Do not claim live readiness.** |

---

## E2E Pipeline (as discovered in code)

```
[opt-in: MARKET_FEED_ENABLED=true]  ── shipping .env.runtime sets this TRUE
  main.py lifespan
    → MarketFeedLoop (trading/feed_loop.py)  READ-ONLY get_ohlc
        → fingerprint dedup + per-(symbol,event_type) cooldown
        → EventDetector.detect → EventQueue.enqueue
    → AutonomousScheduler._run_loop (trading/scheduler.py)   [auto-starts, no Telegram]
        → _RecordingPipelineProxy.run → TradingPipeline.run
              Step A  supervisor.analyze()            fail-closed → WAIT
              Step   _extract_proposal → actionable?  no → NO_TRADE/WAIT
              Step B  risk_gate.validate_proposal()   fail-closed → BLOCK   ← DETERMINISTIC GATE
              Step B2 dependency_guard.check_can_execute() (ExecutionGuard: breakers + kill switch) fail-closed → BLOCK
              Step B3 reconciliation_guard.check_can_execute() fail-closed → BLOCK
              Step C  execution_engine.execute_order()
                        → live-data block?  (mt5.connector.is_live_mode)
                            → armed? (mt5.terminals.execution_permitted)  fail-closed
                        → native mt5.order_send  (only when armed + live-data)
                        → else simulation_mode (SHIPPED DEFAULT = True) → labelled simulated fill
              _finalise → result_hook → Telegram report (fail-safe)
```

**Key runtime facts confirmed in source:**

- Supervisor instantiation: `orchestration/runtime.py:271` (only production site; `system/certification.py:103` is a smoke check).
- Pipeline construction: `orchestration/runtime.py:295-304`.
- Execution engine: `orchestration/runtime.py:279` → `ExecutionEngine(mt5_connector=None, simulation_mode=True)`.
- Scheduler auto-start: `main.py:139-152`; loop `scheduler.py:185-221` (`asyncio.create_task`, no Telegram dependency).
- Gate order in pipeline: `orchestration/pipeline.py:307` (risk), `:343` (dependency guard), `:366` (reconciliation guard), `:382-424` (execution).
- MT5 native send + arm check: `execution/engine.py:673-740`.

**Transitions and evidence** (abbreviated; full detail in prior `DEEP_E2E_AUDIT.md` §2.2, re-verified):

| Transition | Source | Error handling | Persistence | Test evidence |
|---|---|---|---|---|
| MT5→Feed | `trading/feed_loop.py` | try/except → skip symbol | in-mem | ✅ `test_market_feed_loop.py` |
| Feed→Queue | `feed_loop.py` + `trading/event_engine.py` | queue-full → drop+log | **none** | ✅ |
| Queue→Scheduler | `trading/scheduler.py` | pipeline exc → count, continue | none | ✅ |
| Scheduler→Supervisor | `orchestration/pipeline.py:275` | exception → WAIT | none | ✅ |
| Proposal→RiskGate | `pipeline.py:310` | exception → BLOCK | none | ✅ `test_risk_gate.py`, `test_pipeline_orchestration.py` |
| RiskGate→Guards | `pipeline.py:343,366` | exception → BLOCK | none | ✅ `test_execution_guard_wiring.py`, `test_reconciliation_wiring.py` |
| →Execution | `pipeline.py:403` | exception → ERROR | in-mem order store | ✅ `test_execution_engine.py` |
| Close→Review | `review/close_detector.py` + `paper/simulated_execution.py` | fail-safe | JSONL | ⚠️ **not reachable from runtime** |

---

## Component Verification

| Component | Status | Evidence | Tests | Remaining Risk |
|---|---|---|---|---|
| Market Feed Loop | **VERIFIED** | `trading/feed_loop.py` read-only, dedup + cooldown; guard test forbids execution imports | `test_market_feed_loop.py` | No stale-data **age** check (only fingerprint) |
| Event Queue | **VERIFIED** | `trading/event_engine.py` priority queue, bounded | `test_event_engine*.py` | In-memory only |
| Autonomous Scheduler | **VERIFIED** | `trading/scheduler.py:185-221` auto-starts; no Telegram dep | `test_scheduler*.py` | Starved unless feed enabled (enabled in shipped `.env.runtime`) |
| Supervisor | **PARTIAL** | Real dispatch `supervisor.py`; policy defaults `all_match` (`runtime.py:264`) | `test_supervisor*.py` | **Agent `timeout_seconds` stored but NEVER enforced** — a hung specialist blocks the cycle indefinitely |
| Departments / Specialists | **VERIFIED** | `MarketLead`/`RiskLead`/`ReviewLead` registered (`main.py:48-87`); `MarketLead` runs 6 real analysts | `test_market_intelligence.py`, `test_risk_intelligence.py` | Leads do not subclass `DepartmentLead`; generic base is dead |
| Committee / Consensus | **PARTIAL** | Regime-weighted consensus + dissent recorded; unresolved conflict → no proposal (`supervisor.py:594`) | `test_committee_conflict.py` | No challenge/rebuttal loop; dissent not consumed downstream |
| Decision / Proposal | **VERIFIED** | Structured `PipelineResult`; proposal extraction real | `test_pipeline_orchestration.py` | — |
| **Risk Engine (deterministic)** | **VERIFIED** | `risk/engine.py` thresholds; pure arithmetic; no LLM path | `test_risk_engine.py` | — |
| **Risk Gate** | **VERIFIED (in-pipeline) / PARTIAL (as boundary)** | `risk/gate.py` 8 hard checks; enforced at `pipeline.py:310` fail-closed | `test_risk_gate.py` | **Gate is caller-enforced, not executor-enforced**; zeroed account state in some paths fails safe by rejecting |
| Execution Engine | **PARTIAL** | Idempotency, validation, retry, honest failure (`engine.py:761-793`); simulated default | `test_execution_engine.py`, `test_execution_retry_idempotency.py` | **No gate/guard/kill-switch check inside `execute_order`**; shipped default `simulation_mode=True` |
| MT5 Integration | **VERIFIED (read-only)** | `connector.py` real `MetaTrader5` lib, lazy; `terminals.py` fail-closed arm gate | `test_mt5_*.py` | No live broker validation ever performed |
| Terminal arm/disarm | **VERIFIED** | `terminals.py:498-668`; disarms before **and** after switch; all config `execution:false` | `temp_pytest` / `test_mt5_terminals*.py` | Endpoint unauthenticated (see Security) |
| Reconciliation | **PARTIAL** | Comparator real (`reconciliation.py`); gate real (`pipeline.py:366`) | `test_reconciliation*.py` | Providers are **no-ops unless MT5 live mode**; internal ledger in-memory; `internal_orders()` always `[]` |
| Position Monitoring | **PARTIAL** | `position_monitor.py` snapshotting + change detection | `test_position_monitor*.py` | **`PositionMonitor` never instantiated in production**; in-memory, no restart recovery |
| Trade Review | **PARTIAL** | `review_agent.py` good/bad-decision rules; `advanced_review.classify_root_cause` real | `test_review_agent.py` | Only `classify_root_cause` reachable; other advanced review classes orphaned |
| **Learning Loop** | **PARTIAL / INERT** | `JsonlLessonStore` persistent + wired (`main.py:97-107`); advisory feedback wired (`runtime.py:287-292`) | `test_jsonl_lesson_store.py`, `test_learning_feedback.py` | **No runtime producer emits `TRADE_CLOSE`/`POST_TRADE_REVIEW`** → store stays empty in normal operation. `LearningEngineV2`, `LearningLoop`, `PerformanceTracker`, `PatternHypothesisPipeline` are **orphaned (test-only)** |
| Research | **PARTIAL** | `/research/*` endpoints + `ResearchEngine` wired | `test_research*.py` | `backtest_v2`/`walk_forward_v2`/`monte_carlo`/`ResearchScheduler` **orphaned** |
| Strategy Versioning + Promotion | **PARTIAL (governance-only)** | `strategy/registry.py`; `PromotionGate.can_promote` **is** called at `registry.py:301` via the HTTP endpoint with `enforce_evidence=True` | `test_strategy_promotion_gate.py` | `enforce_evidence` **defaults False**; bootstrap `register_live_strategy()` activates ungated; no rollback API; `LifecycleGovernor.propose` orphaned. Activation does **not** change what the engine runs |
| 9Router / LLM | **VERIFIED (advisory)** | `llm/nine_router.py` discovery, cache, health, fallback, labels; safe failure | `test_model_discovery.py`, `test_model_router.py` | **`ModelRouter` is dead code** (never instantiated); discovered-model cost always 0.0; no structured-output validation; `advisor.py:_PREFERRED_FREE_MODELS` env-specific hardcode |
| Telegram | **VERIFIED (control/observability)** | Allowlist fail-closed, read-only, no order path, outage-safe | `test_telegram_*.py` | — |
| Dashboard / Control Plane | **PARTIAL** | Most pages consume real API; AppShell realtime badge is **real** (contradicts old note) | web tsc/lint | Hardcoded mock `orders`/`positions` tables; 14 "under construction" stub pages |
| Observability | **VERIFIED** | `observability/*` traces, metrics, SLO, incidents | `test_observability*.py` | — |
| Security / Auth | **BLOCKED (perimeter)** | `security/api_key.py` correct but **not active** (key unset) | `test_api_key_auth.py` | Arm switch & all mutations unauthenticated in shipped config |
| Persistence / Restart | **PARTIAL** | Lessons JSONL persistent; risk-recovery state (`system/recovery.py`) | `test_*store*.py` | Order state machine, intents, kill switch, position monitor all **in-memory** → not durable across restart |

---

## Risk Gate Verification

**Question: Is there ANY path from an AI/agent to MT5 that bypasses the deterministic Risk Gate?**

**Answer: YES — several code paths exist that reach order dispatch without the Risk Gate. None are reachable with unsafe effect in the shipped configuration, but the boundary is not structurally guaranteed.**

Confirmed facts:
- Hard limits live in deterministic code only: `risk/engine.py:24-29` (drawdown 0.15, daily loss 0.05, exposure 0.30, margin 0.20, max positions 5, max pos size 0.10), `risk/gate.py:56-57` (spread 5 pips, min R:R 1.5). No LLM path can mutate them; `risk/intelligence.py` is explicitly advisory.
- The **production autonomous path** enforces the gate: `pipeline.py:310` → `execute_order` at `:403`. Fail-closed on exception (`:316-325`) and on rejection (`:330-336`).
- The gate runs **8 deterministic checks** in `risk/gate.py:87-157`; `approved = all(checks.values())`.

Un-gated order-dispatch surfaces:
| Path | Gate? | Reachable in shipped config? | Evidence |
|---|---|---|---|
| `TradingPipeline.run` | ✅ Yes | ✅ (the normal path) | `pipeline.py:310,403` |
| `POST /mt5/orders/execute` | ❌ No | ⚠️ Endpoint reachable, but `connector.execute_order` **refuses** when `_live_mode` (`connector.py:587-595`); shipped `MT5_LIVE_DATA=true` → refuses | `mt5/endpoints.py:204-218` |
| `agents.permissions.send_to_mt5` → `guarded_execute_order` | ❌ No RiskGate (WriteGuard only) | ❌ Not called from `src/` (test-only) | `agents/permissions.py:104-129` |
| `DemoTradingManager.measure_latency` | ❌ No gate | ❌ Not instantiated in `src/` | `demo/demo_trading.py:198-213` |
| Direct `ExecutionEngine.execute_order()` | ❌ No gate/guard/kill-switch | Reachable by any caller; the method itself never checks | `execution/engine.py:314-476` |

**The `MT5WriteGuard` "second boundary" is NOT on the production path** — `ExecutionEngine` never invokes it; only `guarded_execute_order` does, which production never calls.

**Verdict: the gate is genuinely non-bypassable *within the pipeline*, and the shipped config is additionally protected by the read-only MT5 refusal. But the executor is a bare dispatcher — the boundary rests on orchestration discipline, not on a hard, executor-level guarantee.** For a release candidate claiming a non-bypassable gate, the executor should fail closed if invoked without an approval token.

---

## MT5 Verification

- Real `MetaTrader5` Python binding, lazily imported (`connector.py:77`, `retrieval.py:19`). No live connection until explicitly activated; otherwise simulated data (`_constants.py:25-40`).
- **Fail-safe chain (verified):**
  - Live-data mode (`is_live_mode()`) + not armed → `_send_to_mt5` **blocks** native send (`engine.py:673-713`).
  - `execution_permitted()` (`terminals.py:656-668`) is fail-closed: requires armed + selected + `execution_allowed` + running + attached. Any doubt → `False`.
  - Native send exceptions **never fabricate success** (`engine.py:747-757`); no-broker + simulation-off → honest failure (`:777-793`).
- **Terminal switching cannot leave the previous terminal armed:** `_select_terminal_locked` disarms **before** (`terminals.py:546`) and **after** (`:563`) the switch; failed attach returns disarmed + detached (`:558`).
- **Config ships with all terminals `execution:false`** (`services/python/mt5_terminals.json`). Arming requires an operator action and never inherits state.
- **LIVE OFF → no live execution:** enforced by the arm gate + read-only connector. Confirmed.
- **GAP:** the shipped runtime wires `ExecutionEngine(mt5_connector=None, simulation_mode=True)` (`runtime.py:279`). In pure paper mode (live-data OFF) a missing broker yields a **labelled simulated fill**; in the shipped config `MT5_LIVE_DATA=true`, so the live-data block takes precedence and blocks native sends unless armed.

---

## Reconciliation Verification

- **Comparator is real** (`execution/reconciliation.py`): detects missing-in-broker, missing-internal (orphan), volume/SL/TP/symbol/magic mismatch, orphan orders; `has_critical()` covers all.
- **The gate is real:** `ReconciliationGuard` (`reconciliation_runner.py`) is wired into the pipeline as Step B3 (`pipeline.py:366-379`), **fail-closed** on mismatch and on guard error.
- **Weakness — data feeding the gate:** providers default to **no-op** unless MT5 live mode (`runtime.py:226-253`). In paper/dev the gate reconciles empty-vs-empty and always passes. In live mode `MT5ReconciliationProviders` is used, but:
  - `internal_orders()` **always returns `[]`** (`reconciliation_providers.py:129-133`).
  - Provider read errors are swallowed to `[]`; if **both** sides degrade, reconciliation passes (fail-open).
  - The internal ledger (`execution/state_machine.py`) is **in-memory only** — after a restart the internal side is empty.
- **Scenarios** (internal OPEN vs MT5 CLOSED, etc.): the comparator produces the right report and the gate would block **if** providers supply data. Verified as logic + wiring; **not verified against a live broker**.

---

## Autonomous Operation

**Can the system run without Telegram / manual intervention? YES, with two factual qualifiers.**

- The scheduler **auto-starts** in the lifespan (`main.py:139-152`) and runs `asyncio.create_task` (`scheduler.py:196`) — no Telegram dependency. Verified by tests and the CHANGELOG E2E note (`events_processed` rose without POST).
- Telegram is a control/observability interface only; every Telegram call is fail-safe (`gateway.py:268-269`) and the poller is read-only with no order path. Telegram outage does **not** stop autonomy.
- Lessons are injected into the analysis context each cycle (`pipeline.py:515-522`) — advisory only.

**Qualifiers:**
1. **Event starvation unless fed.** The loop only moves data if `MARKET_FEED_ENABLED=true` (default `false` in `config.py:54`; the **shipped `.env.runtime` sets it true**). Without it, the auto-started scheduler has an empty queue and the system only reacts to manual `POST /pipeline/run`.
2. **Execution is simulated by default.** Approved proposals produce a labelled simulated fill (no broker), because the runtime wires `simulation_mode=True` with no connector.

**Verdict: autonomous *orchestration* is genuine and auto-starting. Autonomous *trading operation* is not active as shipped — it depends on feed enablement and, for real orders, an armed live terminal.**

---

## Failure Scenarios

| # | Scenario | Expected | Actual (verified) | Status | Evidence |
|---|---|---|---|---|---|
| 1 | MT5 disconnected | No new trade; reconnect | Feed read fails → skip symbol; native send blocked/fails honestly | **PASS** | `feed_loop.py`, `engine.py:673-757` |
| 2 | MT5 terminal unavailable | No execution | `execution_permitted()` fail-closed; simulated/blocked | **PASS** | `terminals.py:656`, `engine.py:696` |
| 3 | Stale market data | Detect/skip | Fingerprint dedup only; **no age check** | **PARTIAL** | `feed_loop.py:149` |
| 4 | Invalid market data | Reject | Bar validation + skip on error | **PASS** | `feed_loop.py` |
| 5 | LLM unavailable | Safe failure; no order impact | Rule-based mock labelled `is_fallback`; LLM not in trade path | **PASS** | `nine_router.py:156`, grep: no llm import in pipeline |
| 6 | Malformed LLM output | Rejected | Empty content returned as success; no schema validation | **PARTIAL** | `nine_router.py:104-142` |
| 7 | Risk Gate rejection | BLOCK, no execution | `pipeline.py:330-336` returns BLOCKED | **PASS** | `test_risk_gate.py` |
| 8 | Duplicate event | Only one workflow | Fingerprint + per-(symbol,event_type) cooldown | **PASS** | `test_market_feed_loop.py` |
| 9 | Duplicate order | No double order | Idempotency key + `_completed_orders`; `order_locator` adopts landed order on retry | **PASS (in-mem)** | `test_execution_retry_idempotency.py` |
| 10 | Execution timeout | Retry bounded, no dup | Exponential backoff; order_locator check | **PASS** | `engine.py` retry + locator |
| 11 | Broker rejection | Honest failure | `_parse_send_result` maps retcodes; no fake success | **PASS** | `test_execution_engine.py` |
| 12 | Database unavailable | Graceful | Not on the critical path (JSONL/sqlite); Python service degrades | **PARTIAL** | no DB in trade path |
| 13 | Redis unavailable | Graceful | Redis not used on critical path | **N/A** | grep: no redis dependency in trade path |
| 14 | Application restart | State restored | Lessons persist; **order state / kill switch / monitor state do NOT** | **PARTIAL** | `state_machine.py` in-mem |
| 15 | Partial execution failure | Handled | Failure reported; no fabricated success | **PASS** | `engine.py:747-793` |
| 16 | Orphaned position | Detected → block | Comparator detects; gate blocks **if providers supply data** | **PARTIAL** | `reconciliation.py`, `reconciliation_providers.py:129` |
| 17 | Internal/MT5 state mismatch | BLOCK new orders | Gate wired fail-closed; relies on live-mode providers | **PARTIAL** | `pipeline.py:366` |
| 18 | Emergency stop | Block all new orders | KillSwitch/ExecutionGuard wired fail-closed; **in-memory; no flatten-all** | **PARTIAL** | `dependency_breakers.py:163`, `kill_switch.py` |

**Tally: 10 PASS, 7 PARTIAL, 0 FAIL (as shipped), 1 N/A.** The earlier `DEEP_E2E_AUDIT` "FAIL" items (F, I) are now wired as gates but their data sources remain partial.

---

## Test Results

All commands executed on the audited checkout.

### Python (`services/python`)
```
Command : .venv\Scripts\python.exe -m pytest tests/ -q -p no:cacheprovider
Result  : 1943 passed, 1 warning in 23.04s
Passed  : 1943    Failed: 0    Skipped: 0    Warnings: 1 (starlette DeprecationWarning)
```
Matches the count documented in `DEEP_E2E_AUDIT.md` (1943). **Verified.**

### Node / API (`apps/api`)
```
Command : npm test --workspace=project-ea-bot-api
Result  : tests 46, pass 46, fail 0
Passed  : 46    Failed: 0
```
**Verified.**

### Frontend (`apps/web`)
```
Command : npx --workspace=project-ea-bot-web tsc --noEmit
Result  : exit 0 (no type errors)

Command : npm run lint --workspace=project-ea-bot-web
Result  : clean (no errors)
```
**Verified.** (A production `next build` was not re-run in this session; the prior audit recorded 42 routes OK.)

### Infrastructure
- CI workflow present (`.github/workflows/ci.yml`, `config-validation.yml`). Prior audit recorded 8/8 jobs green on `51e6470`. Not re-executed here (offline); CI `node` availability warnings exist in the workflow.

**Test quality note:** the 1943 passing tests validate **components**, not inter-gate enforcement. There is still **no adversarial test that proves an AI/agent cannot reach MT5 without the gate**, and no live-terminal E2E test. This is why "all green" and "gates wired" are different claims.

---

## Documentation Drift

| Document | Drift | Recommendation |
|---|---|---|
| `README.md` | Describes Risk Gate as always called; does not disclose unauthenticated Python API or simulated default execution | Add a "Runtime security & execution mode" section |
| `ARCHITECTURE_MAP.md` | Claims "Hard-coded RiskGate mandatory (even LLM cannot bypass)" — true within the pipeline, misleading at the boundary; garbled/duplicated text (lines 52-53, 29-30, 120-125) | Correct the boundary claim; clean the corrupted lines |
| `MASTER_TASKS.md` | Full EPIC 00-19 task list reads as a to-do, but EPICs are already implemented | Mark statuses; stop treating as open work |
| `docs/audit/DEEP_E2E_AUDIT.md` | Marks P1-6 "FIXED" and AppShell P2-1 "faked" — both contradicted by current source (P1-6 bridge is uninstantiated; AppShell badge is now real) — **corrected inline in the RC re-verification pass** | Correct the P1-6 status; annotate the stale AppShell note |
| `CHANGELOG.md` | (Verified valid UTF-8 during the RC pass; earlier "mojibake" observation was a terminal rendering artifact, not file corruption — no drift) | No action |
| `.env.example` | Documents `PYTHON_SERVICE_HOST=0.0.0.0`; `config.py` reads `HOST` (default `127.0.0.1`) | Align variable names/defaults |

Source is newer than the docs in several places; **do not change code to satisfy stale docs.**

---

## Dead / Orphaned Code

Classification (none deleted — documented only):

| Symbol | Location | Status |
|---|---|---|
| `ModelRouter` | `llm/model_router.py` | **ORPHANED** — never instantiated in `src/` (verified) |
| `LearningEngineV2` | `learning/engine_v2.py` | **TEST-ONLY** (verified) |
| `LearningLoop`, `LearningMemory`, `PerformanceTracker`, `PatternHypothesisPipeline` | `learning/*` | **TEST-ONLY** |
| `ExecutionRecoveryEngine` | `execution/order_builder.py` | **ORPHANED** (verified) |
| `PositionCloseDetector` | `review/close_detector.py` | **ORPHANED** — hook exists in `position_monitor.py:378` but neither is instantiated in `src/` |
| `PositionMonitor` | `monitoring/position_monitor.py` | **ORPHANED** in production |
| `SimulatedExecutionEngine` | `paper/simulated_execution.py` | **ORPHANED** |
| `memory/*` package | `src/memory/` | **ORPHANED** (no `src/` importers) |
| `Task`/`TaskStatus`/`TaskPriority` | `agents/task.py` | **ORPHANED** |
| `ContextBuilder` | `orchestration/context_builder.py` | **ORPHANED** |
| `EvidenceBundle`/`EvidenceItem`, `DecisionState`/`MarketBias`/`SetupType` | `agents/evidence.py`, `agents/decision_state.py` | **ORPHANED** |
| `submit_to_risk_gate`/`propose_execution`/`send_to_mt5`/`require_permission` | `agents/permissions.py` | **ORPHANED** — guarded ops never called from `src/` (`propose_execution` is an explicit stub; `submit_to_risk_gate` is fail-**open** when `risk_gate=None`) |
| `MultiLevelBreaker`, `CapitalAllocator` | `risk/*` | **PARTIALLY USED** — wired to `/v2/circuit-breaker/*` dashboard endpoints and `failure_lab`, **not** to the trading pipeline |
| `EventDeduplicator` | `trading/event_engine.py` | **TEST-ONLY** in the production feed path |
| `backtest_v2`, `walk_forward_v2`, `monte_carlo`, `ResearchScheduler` | `research/*` | **ORPHANED** |
| `LifecycleGovernor.propose/advance/reject/archive` | `strategy/lifecycle.py` | **ORPHANED** (read endpoint over an empty store) |
| Legacy committee classes, `synthesize()` | `market/intelligence.py` | **LEGACY** — not on the runtime `analyze()` path |
| `UnsupportedFundamentalAgent`/`UnsupportedSentimentAgent` | `agents/base.py` | **DEMO-ONLY stubs** (intentionally not registered) |

---

## Security Findings

(No secret values are reproduced.)

1. **P0 — Python FastAPI is unauthenticated in the shipped runtime.** `ApiKeyMiddleware` is installed only when `PYTHON_API_KEY` is set (`main.py:288-308`); it is **not set** in `.env.runtime` (verified). The arm-execution switch (`POST /mt5/terminals/arm`), `/pipeline/run`, `/mt5/orders/execute`, `/settings`, `/reconciliation/run`, `/v2/circuit-breaker/*`, `/research/*` are all reachable without a token. Mitigated only by the default loopback bind.
2. **P0 — Node→Python auth does not compose.** The Node API is JWT-protected, but `apps/api/src/pythonClient.ts` never forwards `X-API-Key` (verified: no such header anywhere in `apps/api`). Consequence: the JWT guard is bypassable via direct Python access; and if `PYTHON_API_KEY` is set, every Node→Python proxy call returns 401.
3. **P1 — Live secrets on disk.** `.env.runtime` contains a 9Router LLM key and a Telegram bot token (present; **gitignored and not committed** — verified via `git check-ignore` and `git ls-files`). Weak `JWT_SECRET=dev-secret-change-me`; `DEV_AUTH_ENABLED=true`.
4. **P1 — `websocket.ts` JWT fallback lacks the production guard** that `auth.ts` has (`'dev-secret-change-in-production'`).
5. **P2 — No secret-scanning in CI.**
6. Positives: no command injection (`psutil`, no `shell=True`/`subprocess` in production Python); CORS uses explicit allowlists (no wildcard); Telegram allowlist is fail-closed; `hmac.compare_digest` used for key comparison.

---

## Release Blockers

**None block a PAPER / STAGING / read-only DEMO release.** The following are blockers for **any live-money deployment**:

- **B-1 (P0): Python control surface unauthenticated in the shipped config**, including the arm switch. Fix: set `PYTHON_API_KEY` and forward it from the Node client (or restrict to a private socket).
- **B-2 (P0): Node→Python trust chain broken** — auth cannot be enabled without breaking the control plane until the header is forwarded.
- **B-3 (P0, structural): the Risk Gate is not enforced inside the executor.** `ExecutionEngine.execute_order()` and `/mt5/orders/execute` reach order dispatch without a gate/guard/kill-switch check. Currently latent (read-only refuses; simulation labelled), but it means the "non-bypassable gate" claim is not structurally guaranteed.
- **B-4 (P0 for live): no live broker validation has ever been performed.** Execution is simulated or blocked; there is no evidence of a real order, fill, or reconciliation against a live account.

A separate machine-readable blocker file is provided in `docs/audit/RELEASE_BLOCKERS.md`.

---

## Remaining Risks

Non-blocking but requiring operational attention:

- Agent `timeout_seconds` is stored but never enforced → a hung specialist can stall a cycle.
- Order state machine, intents, kill switch, and position monitor are **all in-memory** → restart loses execution/risk state (P2-15, deferred).
- Reconciliation and monitoring supply no protection in paper mode (no-op providers / uninstantiated monitor).
- The learning loop is effectively inert (no runtime `TRADE_CLOSE` producer) → "self-improving" claims are not demonstrated at runtime.
- Two divergent `RiskGate` classes exist (`risk/gate.py` authoritative; `trading/risk_gate.py` used by `/health`) — a confusion hazard.
- Dashboard has hardcoded mock `orders`/`positions` tables and 14 stub pages.
- LLM discovered-model cost is always 0.0; no structured-output validation; `ModelRouter` (documented safety routing) is dead.
- Runaway/duplicate protection is in-memory only; two processes would not coordinate.

---

## Final Status

```
RELEASE CANDIDATE — PARTIALLY VERIFIED
```

**Rationale:** The system is genuinely integrated and operational as an **analysis + deterministic-decision + fail-closed gating engine**, with strong test evidence (1943 Python + 46 Node passing, web clean) and real runtime wiring for the core pipeline. It is **CODE-READY** and suitable for **STAGING / PAPER / read-only DEMO** operation.

It is **NOT LIVE-READY**: there is no live broker validation, the shipped execution mode is simulated/blocked, the control surface is unauthenticated in the shipped config, and the deterministic Risk Gate — while enforced within the pipeline — is not enforced inside the executor, so it is not yet a structurally non-bypassable boundary. Those are concrete, bounded items (see `RELEASE_BLOCKERS.md`), not architecture failures.

---

*No code changes were required or made for this report. The repository passed the available release-candidate validation for its shipped (paper/read-only) mode; the live path requires the operator/engineering actions listed above.*
