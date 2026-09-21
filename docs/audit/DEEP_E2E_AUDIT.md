# DEEP END-TO-END AUDIT — Project EA Bot

**Repository:** `billy19911/project-ea-bot`
**Audited commit:** `51e6470` (feat(live): realtime WebSocket stream for dashboard prices + P&L)
**Audit date:** 2026-09-21
**Auditor role:** Principal Architect / Quant Systems Engineer / Multi-Agent AI Architect / QA / Security
**Method:** static code trace against actual runtime wiring, cross-checked with tests, config, CI.

> **Verification hierarchy used:** Actual runtime behavior > integration tests > unit tests > source > documentation.
> Where documentation conflicts with code, the discrepancy is reported. Anything not verifiable is marked **UNKNOWN — NOT VERIFIED**.

> **POST-AUDIT UPDATE (same session):** The three P0 issues below were **fixed** with targeted, isolated changes plus regression tests. See §11 "P0 fixes applied". Test count went 1843 → 1860 (all green). P1/P2/P3 remain OPEN pending the fix plan.

---

## 0. Executive Summary

The system is **substantially real** as an *analysis + decision proposal + deterministic risk gate* engine, and the **autonomous feed → event → supervisor → committee → decision → risk-gate → (paper) execution** loop genuinely runs end-to-end **without manual API calls** when `MARKET_FEED_ENABLED=true`.

However, the audit confirms that **several components documented as safety gates are implemented as logic-only and are NOT wired into the production execution path**, and that **the Python backend exposes an unauthenticated control surface** that includes the switch that arms live order execution.

### Status key
- **IMPLEMENTED** — real code, wired into production runtime, exercised by tests.
- **PARTIAL** — logic exists but is either not wired, not enforced, or only covers part of the claim.
- **MISSING** — documented/expected but not present in code.
- **DANGEROUS** — implemented in a way that could cause unsafe behavior if reached.
- **UNKNOWN — NOT VERIFIED** — could not be confirmed from code/tests.

### Top-line verdict

| Area | Status | One-line reason |
|---|---|---|
| Market Feed (MT5→event→queue→pipeline) | **IMPLEMENTED** | `MarketFeedLoop` reads OHLC read-only, dedups, cooldowns, enqueues; scheduler drains |
| Autonomous Trigger | **IMPLEMENTED** | Scheduler runs pipeline per event with no user interaction |
| Supervisor | **PARTIAL** | Real dispatch, but effectively **FIXED ORCHESTRATION** (default `first_match` → 1 lead/cycle) |
| Departments / Specialists | **IMPLEMENTED** | 3 real leads + deterministic specialists; leads do NOT subclass `DepartmentLead` |
| Committee / Debate | **PARTIAL** | Weighted consensus + dissent *recorded*; **no debate/challenge loop**; dissent not consumed downstream |
| Decision | **IMPLEMENTED** | Structured `PipelineResult`; proposal extraction real |
| Risk Engine (deterministic) | **IMPLEMENTED** | `RiskEngine` + thresholds real; used by gate |
| Risk Gate | **IMPLEMENTED** (as the only hard gate) | Enforced in pipeline; **but reconciliation/breaker gates are NOT wired into it** |
| Execution | **PARTIAL / DANGEROUS** | Idempotency + validation real; **default path is SIMULATED success**; retry can double-send on reconnect |
| MT5 | **IMPLEMENTED** | Read-only connector + terminal manager; execution arm switch fail-closed |
| Reconciliation | **PARTIAL / MISSING-as-gate** | Comparator real; **never blocks orders**; production providers are no-ops |
| Position Monitoring | **PARTIAL** | Snapshotting real; **no external SL/TP change, partial-close, or disappearance detection**; no writes |
| Trade Review | **PARTIAL** | `review_agent._RULES` does good/bad-decision; `trade_review` conflates decision quality with outcome |
| Learning | **PARTIAL** | Lesson store + advisory feedback wired; **promotion pipeline unwired** |
| Research | **PARTIAL** | `/research` real; backtest_v2/walk_forward/monte_carlo **not wired**; walk-forward ignores params |
| Strategy Promotion | **MISSING (as enforced gate)** | `PromotionGate.can_promote` never called; `activate` has no evidence check |
| 9Router / Model Routing | **IMPLEMENTED** | Dynamic discovery, cache, health, fallback, complexity routing all real |
| Telegram | **IMPLEMENTED** | Control/interface only; allowlist fail-closed; read-only poller |
| Dashboard / Control Plane | **PARTIAL** | Mostly real data; **`AppShell` fakes LIVE/DEGRADED realtime**; some dead endpoints |
| Security | **DANGEROUS** | Node API authed; **Python API has NO auth**; arm switch reachable unauthenticated; live secrets in `.env.runtime` |
| Observability | **IMPLEMENTED** | Traces, metrics, SLO, incidents real |
| Tests | **IMPLEMENTED** | 1843 Python pass; strong unit/integration; **weak end-to-end enforcement tests** |

---

## 1. Repository map

```
apps/web/            Next.js 15 dashboard (42 routes)
apps/api/            Node/Express API (JWT-authenticated proxy + WS live stream)
services/python/src/ FastAPI trading brain (the core of this audit)
  ├─ mt5/            connector (read-only), terminals (arm switch), write_guard (STUB)
  ├─ trading/        indicators, engine, events, feed_loop, scheduler, risk_gate (dup), modes
  ├─ agents/         supervisor, base, synthesis, departments, evidence, task + analysts/
  ├─ market/         intelligence (MarketLead), news_feed, symbol_spec, endpoints
  ├─ risk/           engine, gate, intelligence (RiskLead), breakers, kill_switch
  ├─ execution/      engine, order_builder, reconciliation(+runner), state_machine, intents
  ├─ orchestration/  pipeline (the seam), runtime, context_builder, endpoints
  ├─ monitoring/     position_monitor, incidents, slo
  ├─ review/         trade_review, advanced_review, auto_trigger, intelligence (ReviewLead)
  ├─ learning/       lesson_store, feedback, engine_v2, loop, performance, pipelines
  ├─ research/       engine, backtest_v2, walk_forward_v2, monte_carlo, scheduler, endpoints
  ├─ strategy/       registry, lifecycle, endpoints
  ├─ llm/            nine_router, model_router, registry, advisor
  ├─ telegram/       gateway, poller, notifier, providers, control_center, transport
  ├─ system/         endpoints, v2_endpoints, settings_store, recovery, certification
  └─ security/       audit_log, tool_permissions
packages/shared/     TS types/config help
infrastructure/      docker-compose, Dockerfiles
.github/workflows/   ci.yml (8 jobs), config-validation.yml
docs/audit/          CURRENT_STATE.md, PRD_V2_CONFORMANCE_AUDIT.md, + this audit
```

---

## 2. Runtime flow verification (actual end-to-end trace)

### 2.1 The autonomous path (verified executable)

```
[opt-in] main.lifespan: MARKET_FEED_ENABLED=true
   → MarketFeedLoop.run()  (trading/feed_loop.py:280, asyncio.to_thread(poll_once))
       poll_once() → _poll_symbol() per symbol
         connector.get_ohlc(symbol, tf, count)          # READ-ONLY (feed_loop.py:136)
         fingerprint dedup (length,last time,last close) # feed_loop.py:149-151
         EventDetector.detect(ohlcv, prev_state)         # trading/events.py
         _build_snapshot() → set_latest_snapshot()       # market evidence cache
         _route_events(): cooldown per (symbol,event_type) + queue.enqueue()  # feed_loop.py:168-212
   → EventQueue (priority queue)                          # trading/event_engine.py
   → AutonomousScheduler._run_loop → process_available   # trading/scheduler.py:213,97
       pipeline.run(event, context)                      # via _RecordingPipelineProxy
   → TradingPipeline.run()                                # orchestration/pipeline.py:227
       Step A: supervisor.analyze(context)               # NO-TRADE on error (fail-closed)
       Step B: risk_gate.validate_proposal(...)          # BLOCK on error (fail-closed)
       Step B2: dependency_guard.check_can_execute()     # ONLY IF INJECTED — NOT in prod
       Step C: execution_engine.execute_order(request)   # ONLY if risk_approved
       _finalise() → result_hook → Telegram report
```

**Verdict:** The autonomous loop **is real and runs without manual API calls** when enabled. Feed is **read-only** and cannot import execution (guard test enforces). Confirmed by `test_market_feed_loop.py` and the CHANGELOG E2E note (`events_processed` rose without POST).

### 2.2 Transition table (per required field)

| Transition | Source | Input | Transform | Output | Next | Error handling | Persistence | Tests |
|---|---|---|---|---|---|---|---|---|
| MT5→Feed | `feed_loop._poll_symbol` | OHLC bars | bar→dict, fingerprint | ohlcv list | detector | try/except → skip symbol | none (in-mem) | ✅ |
| Feed→Event | `EventDetector.detect` | ohlcv, prev_state | rule detection | `DetectedEvent[]` | queue | try/except → skip | in-mem history | ✅ |
| Event→Queue | `_route_events` | events | cooldown filter | enqueue | scheduler | queue-full → drop+log | **none (in-mem)** | ✅ |
| Queue→Scheduler | `process_available` | event | dequeue | pipeline call | pipeline | pipeline exc → count, continue | none | ✅ |
| Scheduler→Supervisor | `pipeline.run` Step A | context | `supervisor.analyze` | analysis dict | proposal extract | exception → WAIT | none | ✅ |
| Supervisor→Decision | `_extract_proposal` | analysis | normalise aliases | proposal dict | risk gate | None → NO_TRADE/WAIT | none | ✅ |
| Decision→RiskGate | `validate_proposal` | proposal+account+market | 8 hard checks | `GateDecision` | execution | exception → BLOCK | none | ✅ |
| RiskGate→Execution | `execute_order` | OrderRequest | validate+send+confirm | `ExecutionResult` | result | exception → ERROR | `order_store` (in-mem) | ✅ |
| Execution→State | `sync_position`/`confirm_execution` | ticket | reconcile | pos summary | cycle end | returns {} | in-mem | ✅ |
| Close→Review | `ReviewAutoTrigger.on_position_closed` | closed position | review rules | lesson | lesson store | fail-safe | **JSONL (persistent)** | ✅ |
| Review→Learning | `record_review_lesson` | ReviewRecord | format | lesson | provider | fail-safe | JSONL | ✅ |

**Critical observation:** the *close → review → learning* leg only fires from `paper/simulated_execution.close_position` and the ReviewLead event path. Since the **production ExecutionEngine never closes positions** (no close path in `engine.py`) and paper engine is not wired in production, **the "trade close → review → lesson" leg is NOT triggered by live trades** — only by manual `POST` / `TRADE_CLOSE` events or the unwired paper engine. **UNKNOWN — NOT VERIFIED in live operation.**

---

## 3. Component-by-component audit

### 3.1 Market Feed — IMPLEMENTED
- `feed_loop.py` reads only `get_ohlc`; guard test forbids execution imports. Dedup + cooldown + snapshot cache real. OFF by default (operator opt-in). Handles: missing bars (`if not bars: return 0`), malformed bars, detector errors, MT5 read errors, queue-full — all fail-safe per symbol.
- **Gap:** no explicit "market closed" or "stale data age" check beyond fingerprint dedup; a frozen market yields repeated identical fingerprints (fine) but a **stale-but-changing** feed is not age-checked. P2.

### 3.2 Supervisor — PARTIAL (FIXED ORCHESTRATION)
- `supervisor.py` selects targets from (a) explicit `context["agents"]`, else (b) `registry.get_by_type("department_lead")` filtered by `can_handle` prefix match, else (c) static `DEFAULT_ROUTING_TABLE`.
- **Production policy default is `first_match`** (`supervisor.py:115`, `_apply_policy` `:280-288` → `agent_names[:1]`). Production builds `SupervisorAgent()` with no args (`runtime.py:162`). Therefore **only one lead runs per cycle**.
- `AgentSynthesizer.plan_agents` (the only planner-like function) is **dead code** in the supervisor path and itself returns a fixed list (`synthesis.py:158-163`).
- **Verdict: FIXED ORCHESTRATION** dressed as routing. Fan-out only happens *inside* a lead over a **hard-coded** specialist set.
- Task state machine (`agents/task.py`) and `DepartmentLead` base (`agents/departments.py`) exist but are **not used** by production leads.

### 3.3 Departments / Specialists — IMPLEMENTED
- 3 real leads registered as `department_lead`: `MarketLead`, `RiskLead`, `ReviewLead`.
- Specialists deterministic: momentum, structure, volatility, news, fundamental. Each returns a dict `{agent, signal, confidence, reasoning|reasons, metrics}`.
- **Gaps:** (1) leads extend `BaseAgent`, not `DepartmentLead` → the base consensus logic is dead; (2) output is **free-form dict**, not the `EvidenceItem`/`DecisionState` schema that exists in `evidence.py`/`decision_state.py` but is never constructed; (3) `reasoning` vs `reasons` key inconsistency papered over in synthesis.

### 3.4 Committee / Debate — PARTIAL
- `MarketLead._weighted_consensus` aggregates `regime_weight × confidence`, records `dissent`, sets `unresolved_conflict`.
- `AgentSynthesizer.detect_conflicts` does pairwise opposition detection.
- **No challenge/rebuttal/re-vote loop exists anywhere.** `dissent`/`unresolved_conflict` are **not consumed downstream** (only logged in reasons). Disagreement reaches WAIT/NO_TRADE **indirectly** via "no actionable proposal" (`pipeline.py:286-294`), not via an explicit challenge vote.
- **Verdict:** aggregation + dissent recording, **not a committee debate**.

### 3.5 Decision — IMPLEMENTED
- `PipelineResult` is a complete structured contract with per-stage `trace`, ids (event/task/decision/proposal/execution/client_order), strategy_version, risk_approved, confidence, summary, trace_id, symbol.

### 3.6 Risk Engine — IMPLEMENTED
- `risk/engine.py` thresholds (drawdown, daily loss, max positions, exposure, margin) + `money_management.py` (R:R, sizing). Deterministic; no LLM path to mutate limits (confirmed).

### 3.7 Risk Gate — IMPLEMENTED (single authoritative gate)
- `risk/gate.py` runs 8 hard checks; `all(checks.values())` required.
- **Enforced in the pipeline** between proposal and execution (`pipeline.py:302-328`). Fail-closed on exception.
- **CRITICAL GAP:** the gate checks account/positions/market **passed by the caller**. The pipeline's `_build_validation_inputs` defaults missing `account_state` to **all zeros** (`pipeline.py:578-585`). With `equity=0`, margin check computes `1.0` (fail), but drawdown/daily are computed against zeros — **the gate is only as good as the context the scheduler supplies**. The scheduler's `context_provider` supplies **news context**, NOT account state (`runtime.py:136`). So in the production autonomous path, **the risk gate frequently evaluates against a zeroed/absent account** → it will reject (`equity=0`) rather than approve (safe failure), but it does **not** implement real account-aware risk in autonomous mode. **UNKNOWN — whether account state is supplied anywhere in prod.** (No provider found.)
- Two `risk_gate.py` files exist (`risk/gate.py` authoritative; `trading/risk_gate.py` is a separate, differently-shaped class used by `/health` only). Not currently harmful, but a confusion hazard.

### 3.8 Execution — PARTIAL / DANGEROUS
- Real: idempotency via `idempotency_key` (`_is_duplicate`), pre-flight validation (symbol, order type, volume bounds, spread tolerance, SL/TP side sanity), exponential-backoff retry on transient codes, fill confirmation, position sync.
- **DANGEROUS #1 — simulated success fallback:** `_send_to_mt5` (engine.py:676-683) returns `{"success": True, "ticket": <fabricated>}` when no connector and no native MT5. Combined with the broad `except (ImportError, Exception)` at `:673` that swallows *any* native error, a real broker exception degrades to a **fake success**. The pipeline then reports `EXECUTED` and records `executed=True` for an order that never reached the broker. **This is the single most dangerous behavior found.**
  - *Mitigating reality:* production wires `ExecutionEngine(mt5_connector=None)` (`runtime.py:166`) → the native path is attempted; if `MetaTrader5` is importable and **armed**, it works; if not importable (the normal case in this repo), it silently simulates. So today it produces **fake paper fills**, not live orders — but the fake-success contract is a latent P0 if the simulation ever becomes "real" mode.
- **DANGEROUS #2 — retry can double-send:** the retry loop re-invokes `_send_to_mt5` with the same request after transient errors including `10031 CONNECTION` / `timeout`. There is **no check that a prior attempt actually landed** before resending. If the broker received attempt #1 but the response was lost, attempt #2 can open a **duplicate position**. Idempotency is enforced **only at process memory** (`_pending_orders`) and **only against re-submission of the same key**, not against a lost-response retry. This is exactly failure Scenario F and it is **not handled**.
- **GAP — no lot-step / digits normalization:** `OrderBuilder` passes volume/price/SL/TP raw (`order_builder.py:140-153`). MT5 requires volume multiples of `volume_step` and prices at symbol `digits`. Not enforced → broker `INVALID_VOLUME`/`INVALID_PRICE` rejections and reconciliation noise.

### 3.9 MT5 — IMPLEMENTED
- Read-only connector (`get_ohlc`, `get_tick`, `get_positions`, `get_orders`, account info). `execute_order` refuses in live mode and otherwise returns a clearly-labelled **paper** order (`connector.py:585-607`).
- **Terminal manager** (`terminals.py`) is the real live gate: `execution_permitted()` is fail-closed (requires armed + selected + `execution_allowed` + running + attached). Defaults: all terminals `execution:false`; switching always disarms.
- **GAP:** broker constraints (volume_step, digits, stops_level, freeze_level, contract_size) exist in `symbol_spec.py`/`symbol_resolver.py` but are **not consulted** by `OrderBuilder`/`ExecutionEngine.validate_order`. `position_monitor.check_risk_change` hardcodes `contract_size=100000.0` and a `10000.0` equity fallback (`position_monitor.py:603,613`).

### 3.10 Reconciliation — PARTIAL / MISSING as a gate
- `Reconciler.compare` is a real pure comparator detecting: missing-in-broker, missing-internal, volume/SL/TP/symbol/magic mismatch, orphan orders. (`reconciliation.py`)
- **CRITICAL:** `has_critical()` is **never read by the order path**. `ReconciliationRunner` stores `_last_ok` but nothing gates on it. Production wiring passes `reconciliation_providers=None` → `ReconciliationProviders()` **no-op providers returning empty lists** (`reconciliation_runner.py:45-55`). So in production, reconciliation reconciles **empty vs empty** forever and always reports "ok".
- `ExecutionRecoveryEngine.is_execution_blocked()` (`order_builder.py:200`) is **never instantiated in production**.
- **Verdict: reconciliation is observability-only. A critical mismatch does NOT block new orders.** This contradicts the documented safety claim.

### 3.11 Position Monitoring — PARTIAL
- `PositionMonitor` snapshots positions, computes ATR, detects price spikes/gaps, computes *candidate* trailing/breakeven SL.
- **Does NOT detect:** external SL/TP modification, partial closes, or unexpected position disappearance (no successive-set diffing). Holds **in-memory only**, has **no write path** — never calls `position_modify`, so its trailing/breakeven suggestions are never applied.
- `monitor_all_positions(account_id=...)` ignores its parameter.

### 3.12 Trade Review — PARTIAL
- `review_agent._RULES` (the wired reviewer) correctly separates: plan-following loss = good decision; win-despite-deviation = bad decision. Outcomes win/loss/breakeven/unknown + `followed_plan`.
- `advanced_review.classify_root_cause` (7 categories) + strategy-vs-execution attribution + no-trade counterfactual = strongest implementation.
- **Weak:** `trade_review.score_decision_quality` adds `+25 if outcome=="WIN"` → **conflates process with result**.

### 3.13 Learning — PARTIAL
- **Wired & real:** `JsonlLessonStore` (persistent), `LessonFeedbackProvider` → advisory context only (`pipeline.py:488-493`), signals/confidence untouched. This is genuinely safe.
- **Unwired:** `LearningEngineV2` (the strongest guardrail, forces lessons to OBSERVATION and only `VALIDATED_FINDING`→candidate) is **never referenced outside its file**. `LearningLoop`/`performance`/`pipelines` only used by tests.

### 3.14 Research — PARTIAL
- `/research` endpoints + `ResearchEngine` (real EMA-crossover backtest, train/test walk-forward split, comparison) are wired and refuse to run without live MT5.
- `backtest_v2`, `walk_forward_v2`, `monte_carlo` are real algorithms but **not wired to any production endpoint**. `WalkForwardValidator` ignores `param_search` (fixed-strategy OOS only, not true walk-forward optimization). `MonteCarloRunner` resamples a single baseline PnL sequence (statistically thin). `ResearchScheduler` default runner is a no-op lambda; inbox `transition` does no state validation.

### 3.15 Strategy Promotion — MISSING (as enforced gate)
- `strategy/registry.py` `PromotionGate.can_promote` is **never called**. `StrategyRegistry.activate` (used by the live POST endpoint) has **no evidence check**.
- `strategy/lifecycle.py` `LifecycleGovernor.propose` is a proper gate but is **unreachable** (GET-only endpoint, nothing registers). `advance` can walk DRAFT→CANDIDATE with **no evidence**.
- `live_readiness/certification_gate.promote_to_production` is **self-approving** over caller-supplied booleans.
- **No enforceable promotion gate exists in the live system.**

### 3.16 9Router / Model Routing — IMPLEMENTED
- Dynamic discovery `GET /v1/models` (httpx + OpenAI SDK fallback), TTL cache (300s), 3-state health, timeout, fallback chain + rule-based mock (clearly labelled `is_fallback`), env-based API key, token tracking, complexity→tier routing. Confirmed.
- **Gaps:** model list **seeded** with 6 hardcoded defaults; `calculate_cost` structurally returns `0.0` for discovered/free models (cost telemetry always $0); advisor preferred-model names are environment-specific hardcodes.

### 3.17 Telegram — IMPLEMENTED
- Interface/control layer only. Allowlist fail-closed (empty ⇒ nobody). Poller is read-only and **cannot place orders** (guard test). Auth checked before every command. OFF unless dedicated token + flag.

### 3.18 Dashboard / Control Plane — PARTIAL
- Most pages consume real API data with honest empty/error states and an explicit "never fabricate zeros" discipline.
- **`AppShell.tsx:287-294` fakes LIVE/DEGRADED realtime** toggling every 12s with an admitted mock comment. Rendered in production (`:428`).
- Dead/data-less endpoints: `/v2/performance-intelligence` passes `[]` (always NO_DATA); `/v2/decision/{id}/replay` store never populated.
- `/health` computes risk gate with hardcoded `10000.0` equity (`main.py:307-314`).

### 3.19 Security — DANGEROUS
- **Python FastAPI has NO authentication** (only CORS middleware; no `Depends`/`Security` anywhere). Binds `0.0.0.0`. **`POST /mt5/terminals/arm` — the arm-live-execution switch — is reachable unauthenticated on port 8787.** Also open: `/pipeline/run`, `/mt5/orders/execute`, `/v2/circuit-breaker/*`, `/settings`, `/reconciliation/run`, `/research/*`.
- **Node API IS JWT-protected** (`PUBLIC_PATHS = /health,/metrics,/auth/token`; everything else requires Bearer). But this is bypassable by hitting Python directly.
- **Live secrets on disk:** `.env.runtime` contains a real 9Router key and a live Telegram bot token. **Gitignored** (verified not in git history). Not committed, but present on the filesystem.
- No command injection (no `subprocess`/`shell=True` in production Python; `psutil` API used). No SQL injection (ORM/parameterized only).
- JWT dev fallback secret is a well-known constant; production boot refuses empty `JWT_SECRET` (Node `auth.ts`), but `websocket.ts` keeps a separate non-enforcing fallback.

### 3.20 Observability — IMPLEMENTED
- `TraceCollector`, metrics endpoint, SLO tracker, incidents, LLM telemetry, execution quality. Real, bounded.

---

## 4. Failure scenario audit (A–I)

| # | Scenario | Expected | Actual behavior | Verdict |
|---|---|---|---|---|
| A | MT5 disconnected | No new trade; reconnect; consistent | Feed read fails → skip symbol (no event). If execution attempted, native send raises → **swallowed → fake success** | **PARTIAL / DANGEROUS** (see Execution) |
| B | 9Router unavailable | No unsafe fallback; WAIT/NO_TRADE | Rule-based mock labelled `is_fallback`; advisor surfaces it; no order impact | **PASS** |
| C | Risk engine unavailable | BLOCK execution | Pipeline catch → `STATUS_BLOCKED` (`pipeline.py:308-317`) | **PASS** |
| D | Supervisor timeout | No forced trade | Exception → `WAIT` (`pipeline.py:266-275`) | **PASS** |
| E | Two agents disagree | Challenge/consensus or WAIT | Dissent recorded (unused); no challenge; may reach NO_TRADE via no-proposal | **PARTIAL** |
| F | MT5 order ok but response lost | Idempotency + reconciliation | Retry resends same order; **no landed-order check; reconciliation not a gate** | **FAIL** |
| G | Duplicate market event | Only one workflow | Fingerprint dedup + per-(symbol,event_type) cooldown | **PASS** |
| H | Telegram unavailable | Autonomy continues | All telegram calls fail-safe; loop continues | **PASS** |
| I | Internal state ≠ MT5 state | BLOCK new orders | Reconciliation computes but **never blocks**; providers are no-ops | **FAIL** |

**Score: 5 PASS, 2 PARTIAL, 2 FAIL.**

---

## 5. Test audit

- **Executed:** `pytest tests/` → **1843 passed, 1 warning, 0 failed** (15.2s). Node API: 45/45. Web: lint clean, `tsc` clean, `next build` 42 routes OK. CI 8/8 success on `51e6470`.
- **Classification:**
  - **Unit (majority):** indicators, risk engine, gate, money management, analysts, event engine, order builder, strategy registry, llm router, telegram, etc.
  - **Integration:** pipeline orchestration, supervisor routing, market intelligence consensus, mt5 guard integration, reconciliation wiring, runtime settings, system endpoints.
  - **E2E (thin):** `tests/e2e/failure_injection/*` are **circuit-breaker-state simulations** (`failure_lab`), not true full-stack E2E. They assert breaker transitions, not that an order is genuinely blocked end-to-end.
  - **MT5 integration:** exercised via fakes/mocks; **no real terminal in CI**.
- **Coverage gaps (what is NOT tested):**
  - ❌ Risk-Gate-bypass attempts (no adversarial test that AI cannot reach execution).
  - ❌ Duplicate execution on lost-response retry (Scenario F).
  - ❌ Reconciliation mismatch blocking orders (Scenario I) — tested only as a comparator.
  - ❌ Simulated-success fallback being treated as a real fill.
  - ❌ Autonomous path supplying real account state to the risk gate.
  - ❌ Trade-close → review → lesson driven by a *live* trade.
  - ❌ Promotion gate enforcement.
- **Assessment:** "1843 passed" reflects **broad unit coverage of real components**, but does **not** prove the safety gates are wired. The passing suite coexists with a non-gating reconciliation engine and an unwired breaker — because there is no test asserting those gates block orders.

---

## 6. Findings

### P0 — CRITICAL

**P0-1. Python backend is completely unauthenticated (port 8787), exposing the arm-execution switch.**
- Evidence: `main.py:280-298` (only CORS); no auth dependency anywhere in `services/python/src`. `mt5/endpoints.py:85` `POST /mt5/terminals/arm`. Node API JWT gate (`index.ts:226`) does not protect the backend port.
- Risk: anyone with network access to the Python service can arm live execution, trigger pipeline cycles, and toggle circuit breakers without a token.
- Note: whether an order then actually fires still depends on `execution_allowed=true` config and a subsequent decision — but the **human arm safety gate itself is unauthenticated**.
- **STATUS: FIXED.** Added `ApiKeyMiddleware` (`security/api_key.py`), enforced when `PYTHON_API_KEY` is set (401 otherwise); default bind changed to loopback `127.0.0.1`. Tests: `test_api_key_auth.py`.

**P0-2. Execution silently fabricates success when MT5 is unreachable.**
- Evidence: `execution/engine.py:673-683` (broad `except` → simulated `success:True` with fabricated ticket).
- Risk: the pipeline records `EXECUTED`/`executed=True` for an order that never reached the broker; trade/review/learning then operate on phantom trades. Latent live-trading danger.
- **STATUS: FIXED.** `_send_to_mt5` now splits `ImportError` (fall through) from real broker exceptions (return honest failure); the simulated fill is **explicit opt-in** via `simulation_mode=True` (labelled `simulated:True`), default `False` → honest `success:False`. Runtime opts in explicitly for paper mode. Tests: `test_execution_engine.py` (Audit P0-2 section).

**P0-3. Reconciliation never blocks new orders; production providers are no-ops.**
- Evidence: `reconciliation.py:16,72-87`; `reconciliation_runner.py:45-55,149`; `runtime.py:114,122-126`; no gate in `pipeline.py`; `ExecutionRecoveryEngine` unwired.
- Risk: on internal↔MT5 divergence the system keeps opening trades. Contradicts documented §14 safety claim.
- **STATUS: FIXED (gate).** Added `ReconciliationGuard` and a pipeline Step B3 that BLOCKS new orders (fail-closed) on a critical mismatch; wired into `OrchestrationRuntime`. Note: providers still default to no-op — the **gate is now real**, but the **data feeding it** must still be supplied by an MT5-backed provider (tracked as an open follow-up in the fix plan). Tests: `test_reconciliation_wiring.py`, `test_pipeline_orchestration.py`.

### P1 — HIGH

**P1-1. Retry can duplicate a live position on lost response (Scenario F).**
- Evidence: `engine.py:356-416` (retry re-invokes `_send_to_mt5`, incl. `CONNECTION`/`timeout` codes; no landed-order verification).

**P1-2. Breaker guards exist but are not wired into the pipeline.**
- Evidence: `DependencyBreakers` never instantiated in prod; `MultiLevelBreaker` only in `v2_endpoints` + tests; `dependency_guard` optional and unset in `runtime.py:179-186`.

**P1-3. Risk gate runs against missing/zero account state in autonomous mode.**
- Evidence: `pipeline.py:577-585` zeroed defaults; scheduler `context_provider` supplies news only (`runtime.py:136`). No account provider found. (Fails safe by rejecting, but is not real account-aware risk.)

**P1-4. No lot-step / price-digits normalization before sending.**
- Evidence: `order_builder.py:140-153`; broker specs unused. Risk of broker rejections + reconciliation noise.

**P1-5. Strategy promotion gate is unenforced.**
- Evidence: `PromotionGate.can_promote` never called; `StrategyRegistry.activate` has no evidence check; `LifecycleGovernor.propose` unreachable; `advance` requires no evidence.

**P1-6. Trade-close → review → learning is not driven by live trades.**
- Evidence: production `ExecutionEngine` has no close path; paper engine (the only auto-close path) is unwired in prod. The "learning loop from live trades" is **UNKNOWN — NOT VERIFIED**.

### P2 — MEDIUM

- **P2-1.** `AppShell.tsx:287-294` fakes LIVE/DEGRADED realtime in production UI.
- **P2-2.** Position monitor cannot detect external SL/TP changes, partial closes, or disappearance; has no write path.
- **P2-3.** Supervisor is effectively fixed orchestration (`first_match` → 1 lead/cycle); `plan_agents` dead; `DepartmentLead`/`Task`/`EvidenceItem`/`DecisionState` scaffolding unused.
- **P2-4.** Committee has no challenge/debate loop; `dissent`/`unresolved_conflict` not consumed.
- **P2-5.** Specialist outputs are unstructured dicts with inconsistent keys (`reasoning` vs `reasons`), not the existing evidence/decision schema.
- **P2-6.** `trade_review.score_decision_quality` conflates outcome with decision quality.
- **P2-7.** Hardcoded magic numbers: `position_monitor.py:603,613` (contract 100000, equity 10000); `write_guard.py:76-78`; `/health` equity 10000 (`main.py:307`).
- **P2-8.** Dead/data-less endpoints: `/v2/performance-intelligence` (`v2_endpoints.py:588` passes `[]`), `/v2/decision/{id}/replay` (store never written).
- **P2-9.** `write_guard.send_order` is a **stub** that sends nothing; daily-loss/exposure checks skipped when args omitted (fail-open), and the guard is not in the engine's write path.
- **P2-10.** `MT5WriteGuard` exposure math uses fictional balance/price.
- **P2-11.** `.env.runtime` holds live 9Router key + Telegram token on disk (gitignored, not committed).
- **P2-12.** Node `cors()` has no origin allowlist (`index.ts:62`); WS token via query string.
- **P2-13.** Two divergent `risk_gate.py` modules; `trading/risk_gate.py` used only by `/health`.
- **P2-14.** `monte_carlo` statistically thin; `walk_forward_v2` ignores `param_search`; research modules unwired.
- **P2-15.** `state_machine` order store is in-memory (not durable); `next_allowed` unused by the engine.

### P3 — LOW

- **P3-1.** `MismatchEvent.timestamp` default is a *format string*, not a timestamp (`order_builder.py:178-182`).
- **P3-2.** `ExecutionRecoveryEngine` docstring claims SL/TP mismatch detection; code checks volume only.
- **P3-3.** `ExecutionEngine.validate_order` uses `symbol.strip().upper()` for lookup but `_normalize_position` compares `.upper()` — suffix handling is inconsistent with the resolver.
- **P3-4.** Duplicate class name `FundamentalAnalystAgent` (stub in `base.py` vs real in `analysts/`) — confusion hazard.
- **P3-5.** `ResearchInbox.transition` does no state-machine validation.
- **P3-6.** Overview page has no loading indicator.

---

## 7. Recommended fixes (priority order)

1. **P0-1** — Add authentication to the Python FastAPI service (shared bearer or network-bind restriction to localhost), and require it on all mutating endpoints (at minimum arm/execute/pipeline/breaker/settings).
2. **P0-2** — Remove the fabricated-success fallback. When no real broker path exists, execution must return `success:False` with an explicit `error_code`/`mode:"simulated"` marker; never a fake ticket. Add a test.
3. **P0-3** — Insert a reconciliation gate into `TradingPipeline.run` (after risk approval, before execution) that consults the latest report / recovery engine and BLOCKS on critical mismatch. Wire real MT5-backed providers. Add a test.
4. **P1-1** — Make retry idempotent against lost responses: query broker state (by client order id / magic+symbol) before resending; or persist an intent and reconcile before retry.
5. **P1-2** — Wire `DependencyBreakers` into the production pipeline as `dependency_guard`.
6. **P1-3** — Supply real account/positions/market to the pipeline context (scheduler context provider) so the risk gate is account-aware.
7. **P1-4** — Normalize volume to `volume_step` and prices to `digits` using `SymbolSpec` before building/sending orders.
8. **P1-5** — Enforce `PromotionGate.can_promote` inside `StrategyRegistry.activate` and expose the gated promotion path.
9. **P2-x / P3-x** — Address the medium/low list per the fix plan.

---

## 8. Final readiness matrix

| Area | Current State | Evidence | Blocking? |
|---|---|---|---|
| Market Feed | IMPLEMENTED | `feed_loop.py`, tests | No |
| Autonomous Trigger | IMPLEMENTED | `scheduler.py`, `main.py:158` | No |
| Supervisor | PARTIAL (fixed) | `supervisor.py:115,280`; `runtime.py:162` | No (works, but fixed) |
| Departments | PARTIAL (real leads, unused base) | `intelligence.py`, `departments.py` | No |
| Specialists | IMPLEMENTED | `analysts/*` | No |
| Committee | PARTIAL (no debate) | `synthesis.py:241`; `intelligence.py:751` | No |
| Decision | IMPLEMENTED | `pipeline.py:82-155` | No |
| Risk Engine | IMPLEMENTED | `risk/engine.py` | No |
| Risk Gate | IMPLEMENTED (only hard gate; zeroed account in auto) | `risk/gate.py`; `pipeline.py:302,577` | **Yes (P1-3)** |
| Execution | PARTIAL/DANGEROUS | `engine.py:673-683,356-416` | **Yes (P0-2, P1-1)** |
| MT5 | IMPLEMENTED (read-only; arm gate) | `connector.py`, `terminals.py` | No (but P0-1) |
| Reconciliation | PARTIAL (no gate, no-op providers) | `reconciliation*.py`, `runtime.py:114` | **Yes (P0-3)** |
| Monitoring | PARTIAL (no change/absence detect, no writes) | `position_monitor.py` | No (P2) |
| Trade Review | PARTIAL | `review_agent.py` vs `trade_review.py` | No |
| Learning | PARTIAL (advisory only; promotion unwired) | `feedback.py`, `lesson_store.py` | No |
| Research | PARTIAL (real `/research`; v2 modules unwired) | `research/*` | No |
| Strategy Promotion | MISSING (unenforced) | `strategy/*` | **Yes for governance (P1-5)** |
| 9Router | IMPLEMENTED | `llm/*` | No |
| Telegram | IMPLEMENTED | `telegram/*` | No |
| Dashboard | PARTIAL (fake realtime status) | `AppShell.tsx:287` | No (P2) |
| Security | DANGEROUS | `main.py` (no auth); `.env.runtime` | **Yes (P0-1)** |
| Observability | IMPLEMENTED | `observability/*` | No |
| Tests | IMPLEMENTED (broad unit; thin E2E; no gate-bypass tests) | suite | No (but gaps) |

---

## 9. Explicitly UNKNOWN — NOT VERIFIED

- Whether any production code path supplies **real account/positions** to the risk gate in autonomous mode (no provider found).
- Whether the **trade-close → review → learning** leg ever fires from a **live** trade (no live close path found).
- Whether `strategies` registered via `register_live_strategy()` map to the registry used by the promotion gate (governance-only; no execution coupling confirmed).
- Real broker (`MetaTrader5` native) behavior under retry/lost-response and volume-step violation — no live terminal in CI.

---

## 10. Conclusion

**Do NOT conclude "READY FOR LIVE".**

The pipeline `market → event → supervisor → agents → committee → decision → risk → gate → (paper) execution → reconciliation(report) → review → lesson` is **real and largely coherent for analysis and paper operation**, and the deterministic risk gate is genuinely non-bypassable **within the pipeline**. But **three P0 issues** must be resolved before any progression toward paper/demo/live confidence:

1. The Python control surface is unauthenticated (arm switch exposed).
2. Execution fabricates success when the broker is unreachable.
3. Reconciliation is not a gate; production reconciliation is a no-op.

Plus P1 items (duplicate-on-retry, unwired breakers, zeroed account risk inputs, no lot-step normalization, unenforced promotion gate). The 1843 passing tests validate **components**, not **inter-gate enforcement** — several "safety" modules pass their unit tests while not being connected to the execution path.

---

## 11. P0 fixes applied (same session)

All three P0 fixes were **isolated, safe, and covered by new regression tests**. No architecture change; no working module rewritten; no existing functionality deleted.

### Files changed
| File | Change |
|---|---|
| `services/python/src/execution/engine.py` | Added `simulation_mode` flag (default `False`); split `ImportError` vs real broker error; removed fabricated-success fallback (P0-2) |
| `services/python/src/execution/reconciliation_runner.py` | Added `ReconciliationGuard.check_can_execute()` (P0-3) |
| `services/python/src/orchestration/pipeline.py` | Added optional `reconciliation_guard` + Step B3 block (P0-3) |
| `services/python/src/orchestration/runtime.py` | Wired `simulation_mode=True` for paper mode; built + wired `ReconciliationGuard` (P0-2, P0-3) |
| `services/python/src/security/api_key.py` | **NEW** — `ApiKeyMiddleware` + `parse_public_paths` (P0-1) |
| `services/python/src/config.py` | Added `python_api_key` / `api_public_paths`; default `HOST=127.0.0.1` (P0-1) |
| `services/python/src/main.py` | Registered `ApiKeyMiddleware` when key set; warning when unset (P0-1) |
| `services/python/tests/test_execution_engine.py` | +3 P0-2 tests |
| `services/python/tests/test_reconciliation_wiring.py` | +4 P0-3 tests |
| `services/python/tests/test_pipeline_orchestration.py` | +3 P0-3 tests |
| `services/python/tests/test_api_key_auth.py` | **NEW** +7 P0-1 tests |
| `.env.example`, `scripts/start-all.ps1` | Document/forward `PYTHON_API_KEY`; `HOST=127.0.0.1` |

### Verification
- Python tests: **1860 passed, 0 failed** (was 1843; +17 new).
- `black --check` clean (180 files unchanged); `isort --check` clean; `flake8` clean.

### Residual / follow-up (NOT fixed here — see fix plan)
- P0-3 gate is real but the **reconciliation providers still default to no-op**; an MT5-backed provider must be supplied for the gate to see real state.
- P0-1 is enforcement-when-configured; the operator/`.env` **must set `PYTHON_API_KEY`** in production for the protection to be active.

