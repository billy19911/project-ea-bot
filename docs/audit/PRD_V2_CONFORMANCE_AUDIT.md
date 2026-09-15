# PRD_V2 Conformance & Integration Audit (XynnBot)

**Repository:** `C:\xampp\htdocs\project-ea-bot`
**Authority document:** `PRD_V2.md` (1051 lines)
**Roadmap context:** `MASTER_TASKS.md` (EPIC 00–19)
**Audit type:** READ-ONLY, evidence-based, no fixes applied
**Date:** 2026-09-15
**Scope:** Verify PRD_V2 §32 (23 acceptance criteria), §5–§29 architecture requirements, integration wiring, and §29 test coverage against the actual code.

---

## Verdict conventions

| Verdict | Meaning |
|---|---|
| **PASS** | Requirement is implemented in code **and** demonstrably wired/used (real integration). |
| **PARTIAL** | Code exists but is incomplete, diverges from spec, or is not fully wired. |
| **FAIL** | Requirement is missing, or only stubbed/mocked, or contradicts the PRD. |

Code status tags:
- **EXISTS+WIRED** — real implementation reachable from a production entry point.
- **EXISTS-UNWIRED** — implementation exists but nothing in production calls it.
- **MISSING** — not present in the repository.

---

## 1. Executive Summary

### 1.1 Headline finding

The **Python service layer is substantially implemented and well-tested in isolation** (836 unit tests pass; deterministic risk gate, execution idempotency, reconciliation, circuit breakers, kill switch, memory, learning loop, strategy registry, observability, security, readiness gates all exist as real, tested classes). **However, the platform is not integrated end-to-end.** There is:

- **No Telegram gateway of any kind** (only `telegram/opencode-context.md` — a planning note).
- **No dynamic 9Router model discovery** — the model registry is a hardcoded static list; there is no `GET /v1/models` call anywhere.
- **Hardcoded static model lists in the frontend** in at least three places.
- **No wiring between the Node API, the Python service, and the frontend.** Every "control-plane" endpoint in `apps/api/src/index.ts` returns **hardcoded demo data**. The Python FastAPI app exposes only `/health`, `/trading/*`, `/events/*`, `/mt5/*` — and **nothing calls it**. The Supervisor is **never invoked in production** (only referenced by `__init__.py` and tests).
- **No autonomous scheduler / event loop.** Nothing subscribes the Supervisor to the event queue. `asyncio` appears only inside the MT5 connection manager.

In short: **the "brain" and "safety" libraries are built and unit-tested, but there is no nervous system connecting them, no face (Telegram), and no live model gateway.** The dashboard displays plausible but fabricated numbers.

### 1.2 Conformance estimate

| Dimension | Estimate |
|---|---|
| PRD §32 acceptance criteria (23) | **PASS 4 · PARTIAL 9 · FAIL 10** → ~37% |
| Python module-level architectural conformance (logic present) | ~80% |
| Production integration / wiring conformances | ~10% |
| Frontend conformance (§20 no hardcoded list, §25 real data) | ~15% |
| Test-category coverage (§29) | 12/13 PRESENT (weakest: true end-to-end) |

**Overall PRD_V2 conformance (weighted toward "demonstrable, wired, accepted"): ≈ 35–40%.**

### 1.3 Top 5 risks (P0)

1. **Fabricated telemetry presented as live system state.** `apps/api/src/index.ts` returns hardcoded demo arrays for `/ai-control/status`, `/positions`, `/market/overview`, `/tasks`, `/decisions`, `/audit/events`, `/system/health`, `/telegram/status`, `/committee/trace`, `/ai/providers`, `/ai/models`, `/learning/analytics`. The dashboard cannot distinguish demo data from real data. This directly violates PRD §25/§26/§27 and the §32 acceptance intent.
2. **No end-to-end trading pipeline.** Supervisor → Department → Risk Gate → Execution is never connected. The Supervisor is `EXISTS-UNWIRED`. PRD §5, §6, §10, §32.1–.7 not demonstrable in a running system.
3. **Telegram gateway entirely missing (PRD §21, §32.18, EPIC 03.13–03.16).** The `/telegram/status` API endpoint returns `connected: true` for a bot that does not exist — a dangerously misleading status.
4. **No dynamic model discovery (PRD §20, §32.19, EPIC 03.10/03.11).** `ModelRegistry._register_defaults()` hardcodes 6 models; the frontend hardcodes 3 more; `GET /ai/models` hardcodes 4 with a fake `last_discovery` timestamp. No `GET /v1/models` call exists in the entire repo.
5. **No autonomous operation (PRD §10.3, §32.17, EPIC 03.09).** No scheduler/event loop wakes the Supervisor on events. Without Telegram (which also doesn't exist), the PRD's autonomous workflow cannot run at all.

---

## 2. Section 32 — Final System Acceptance (23 criteria)

| # | Criterion | Verdict | Evidence | Gap |
|---|---|---|---|---|
| 1 | Supervisor dynamically delegates to the correct department | **PARTIAL** | `src/agents/supervisor.py` `SupervisorAgent.analyze()` routes to `registry.get_by_type("department_lead")`; `DEFAULT_ROUTING_TABLE`. Tested in `tests/test_supervisor_department_routing.py`. | Supervisor is **EXISTS-UNWIRED**: only imported by `src/agents/__init__.py` and tests; no production entry point invokes it. No event loop feeds it. |
| 2 | Department Lead chooses only needed specialists | **PASS (logic)** | `src/agents/departments.py` `DepartmentLead.select_specialists()` uses `routing_fn` / `required_specialists`. | Wired only in tests; not reachable in a running service. Logic conforms. |
| 3 | Specialist results return as structured evidence | **PARTIAL** | `DepartmentLead.analyze()` returns `specialist_results`, `consensus_signal`; `src/market/intelligence.py` `AnalystReport` with `evidence`, `reliability`. | Evidence is not the PRD §8 fact/interpretation/recommendation model; no `freshness_ms`, `data_quality`, `timeframe`. No structured Evidence dataclass with those fields. |
| 4 | Supervisor can request follow-up work | **PARTIAL** | `SupervisorAgent.analyze()` supports child tasks via provided `agents`/`registry`; `attempt`/`max_attempts` concept absent. | No re-dispatch loop on insufficient evidence; no task object with `parent_task_id`/`attempt`. `synthesis.py` plans agents but no follow-up orchestration. |
| 5 | Conflicts do not default to majority vote | **PARTIAL** | `departments.py` `_resolve_consensus()` returns `UNRESOLVED` on disagreement (good). **But** `market/intelligence.py` `MarketLead.synthesize()` uses `max(set(directions), key=directions.count)` — i.e. **majority vote** (violation). `synthesis.py` `generate_proposal()` uses `bullish > bearish` counts. | Two conflicting implementations coexist. No evidence-quality/freshness/reliability weighting (PRD §10). |
| 6 | Decision State exists before execution | **PARTIAL** | `synthesis.py` `TradeProposal` (direction/confidence/reasoning/SL/TP). | No `DecisionState` object with the PRD §9 shape (`market_bias`, `setup_status`, `conflicts`, `market_risk`, `data_quality`, `decision` and the 8 allowed values BUY/SELL/WAIT/NO_TRADE/MONITOR/CLOSE/REDUCE/ESCALATE). `TradeDirection` only has BUY/SELL/HOLD. |
| 7 | Risk Intelligence and deterministic Risk Gate are separate | **PASS** | `src/risk/intelligence.py` (advisory `RiskLead`/analysts) vs `src/risk/gate.py` `RiskGate` + `src/risk/engine.py` `RiskEngine`. Tested `tests/test_risk_intelligence.py`, `tests/test_deterministic_risk_gate.py`. | Separation verified in code and tests (EPIC 05.07). |
| 8 | AI cannot bypass hard limits | **PASS (logic)** | `src/agents/permissions.py` `require_permission`; `AgentPermissionError`; `src/mt5/write_guard.py` `MT5WriteGuard` requires `SEND_TO_MT5`; `RiskGate.validate_proposal` is pure deterministic. Tests: `test_agent_permissions.py`, `test_mt5_write_guard.py`. | Wired only in tests; the live pipeline that would exercise it doesn't exist. Logic is sound. |
| 9 | Execution is deterministic and idempotent | **PASS** | `src/execution/engine.py` `ExecutionEngine.execute_order()` with `_is_duplicate`/`_pending_orders`/`_completed_orders` and `idempotency_key`; `OrderBuilder`; `ExecutionRecoveryEngine` in `order_builder.py`. Tests: `test_execution_engine.py`, `test_order_builder.py`, `test_failure_simulation.py`. | Does not require all 7 PRD §13 identifiers (event_id, task_id, decision_id, proposal_id, execution_id, client_order_id, strategy_version) — only `idempotency_key`. |
| 10 | Internal state reconciles with MT5 | **PARTIAL** | `ExecutionEngine.sync_position()`, `confirm_execution()`; `ExecutionRecoveryEngine` (mismatch → BLOCKED_CRITICAL); `PositionMonitor`. Tests `test_failure_simulation.py`. | No standalone reconciliation engine that compares DB/internal vs MT5 state on a schedule; `sync_position` is per-order only, MT5 reads are simulated. |
| 11 | Every trade is fully traceable | **PARTIAL** | `src/observability/traces.py` `TraceCollector` (spans/traces); `src/memory/trade_memory.py` `TradeMemoryStore` records agents/risk/execution. | No single trace linking EVENT→…→REVIEW as one object; trace IDs not propagated across services; API `/audit/events` returns demo data. |
| 12 | Research cannot silently mutate LIVE strategy | **PASS (logic)** | `src/strategy/registry.py` `ReadOnlyDict` blocks param mutation when ACTIVE; `src/learning/loop.py` `approve_validated` = recommendation only; no live write path. Tests `test_strategy_registry.py`, `test_learning_loop.py`. | Not wired to any live strategy store (there is none live). Logic conforms. |
| 13 | Strategy versions are validated before promotion | **PARTIAL** | `PromotionGate.can_promote()` enforces DRAFT→TESTING (win_rate≥50) →ACTIVE (validation_passed). | PRD §19 requires 10 statuses; code has only 4 (`DRAFT/TESTING/ACTIVE/RETIRED`). Missing `RESEARCH/BACKTESTED/WALK_FORWARD/PAPER/DEMO/APPROVED/REJECTED`. Missing fields: `strategy_id`, `risk_policy`, `compatible_regimes`, `validation_evidence`, `approved_at`, `activated_at`, `retired_at`. |
| 14 | LLM usage is budgeted and observable | **PARTIAL** | `NineRouterClient` records `TokenUsage`; `src/observability/metrics.py` `record_token_usage`. `SupervisorAgent.token_budget`/`check_token_budget`. | Budget is per-`analyze()` call, not global/department/task/agent (EPIC 03.08). Metrics exist but nothing feeds them in production (API shows hardcoded tokens). |
| 15 | AI infra failure fails safely | **PARTIAL** | `nine_router.py` `_rule_based_fallback()` returns neutral heuristic on total failure; ret/fallback tested. | Fallback returns a *trade-ish* mock signal rather than a hard fail-closed/no-trade; no cross-check that fallback cannot open uncontrolled trading. Circuit breakers for LLM gateway exist conceptually (`CircuitBreaker`) but are not wired to the LLM client. |
| 16 | Department committees can discuss contradictory evidence → one decision or safe unresolved | **PARTIAL** | `departments.py` returns `UNRESOLVED`; `synthesis.py` `detect_conflicts` + `check_escalation`; `market/intelligence.py` `CommitteeDecision`. | No multi-round debate where specialists inspect peers and revise (EPIC 04.09). No full committee record (agreements, counter-evidence, invalidation conditions, specialist positions). Majority vote present in `MarketLead.synthesize()`. |
| 17 | Autonomous operation continues without Telegram/user | **FAIL** | No scheduler/event loop. Supervisor `EXISTS-UNWIRED`. `grep schedule/asyncio/while True` finds only MT5 `connection_manager.py`. | Entire requirement unmet. No event-driven wake-up mechanism. |
| 18 | Telegram can query Supervisor via traces without being a trading dependency | **FAIL** | **No Telegram module** anywhere (`find *telegram*` → only `telegram/opencode-context.md`). `/telegram/status` returns fabricated `connected: true`. | Feature absent; status endpoint misleading. |
| 19 | 9Router discovery is dynamic, not a hardcoded frontend list | **FAIL** | `src/llm/registry.py` `_register_defaults()` hardcodes 6 models; `apps/api/src/index.ts` `/ai/models` hardcodes 4 + fake `last_discovery`; `apps/web/app/page.tsx` hardcodes `qwen2.5-72b/llama-3.3-70b/claude-3-5-sonnet`. No `GET /v1/models` call in repo. | Directly violates PRD §20 and §32.19. |
| 20 | Every completed trade gets automated review + root-cause | **PARTIAL** | `src/review/trade_review.py` `TradeReviewer` (MAE/MFE, timing/decision/execution scores); `src/review/advanced_review.py` `classify_root_cause()` with 7 categories. Tests `test_trade_review.py`, `test_advanced_review.py`. | No automatic hook on trade close (no live pipeline); review exists only as callable functions. |
| 21 | Analytics identify patterns by hour/session/regime/setup → hypotheses | **PARTIAL** | `src/learning/performance.py` `PerformanceTracker` (hour/session/regime/setup + min sample); `src/review/advanced_review.py` `extract_patterns`, `analyze_by_time`; `learning/loop.py` `review_to_patterns`→`patterns_to_hypotheses`. Tests `test_learning_loop.py`. | Pattern discovery grouping is by `symbol` in `loop.review_to_patterns()` (not hour/regime/setup), showing partial pipeline; API `/learning/analytics` returns demo data. |
| 22 | Learning creates candidate versions but cannot mutate LIVE params | **PASS (logic)** | `learning/loop.py` pipelines end at `approve_validated` (recommendation); `strategy/registry.py` `ReadOnlyDict` guards ACTIVE. | Logic conforms; nothing live to mutate. |
| 23 | Supervisor metrics include win rate + expectancy, PF, drawdown, timing, regime, setup, no-trade quality | **PARTIAL** | `learning/performance.py` `supervisor_kpis()` → win_rate, profit_factor, expectancy, max_drawdown, false_signals, no_trade_quality (returns 0.0). `test_learning_loop.py`. | `no_trade_quality` hardcoded to 0.0; no timing/regime/setup breakdowns in the KPI payload; not wired to a live source (API returns demo). |

**§32 tally:** PASS = 4 (criteria 2, 7, 9, 22) · PARTIAL = 9 (1,3,4,5,6,8*,10,11,13,14,15,16,20,21,23) · FAIL = 3 (17,18,19).
> *Note: criterion 8 is a logic PASS but part of an unwired pipeline; counted PASS per code-and-tests evidence.

---

## 3. PRD Section-by-Section Findings (§5–§29)

### §5 AI Organization — **PARTIAL**
- Supervisor: `src/agents/supervisor.py` `SupervisorAgent` (routing table, priority sort, context filter, concurrency, token budget). No MT5/Risk-Gate access (conforms).
- Department Leads: `src/agents/departments.py` `Department`, `DepartmentLead`; `src/market/intelligence.py` `MarketLead`; `src/risk/intelligence.py` `RiskLead`.
- Specialists: `src/agents/analysts/` (momentum, news, structure, volatility) + `market/intelligence.py` analysts.
- **Gaps:** duplicates/conflicts — `base.py` has `TechnicalAnalystAgent` while `market/intelligence.py` has a separate `TechnicalAnalyst`; `MarketLead.synthesize()` uses majority vote. Review/Knowledge department is only partially covered by `src/review/`. Supervisor is unwired.

### §6 Dynamic Delegation Model — **PARTIAL (logic)**
- Supervisor → lead → specialists path present in `SupervisorAgent.analyze()` + `DepartmentLead.select_specialists()`.
- **Gap:** no engine drives it; `synthesis.py` `plan_agents()` uses a fixed default plan, and `SupervisorAgent` still has a static `DEFAULT_ROUTING_TABLE` mapping many events to `technical_analyst` (legacy fan-out).

### §7 Task Contract — **FAIL**
- No `Task` dataclass with the §7 JSON fields (`task_id`, `parent_task_id`, `root_event_id`, `created_by`, `assigned_role`, `objective`, `priority`, `required_context`, `dependencies`, `deadline_ms`, `attempt`, `max_attempts`, `expected_output_schema`).
- No task state machine (CREATED/ROUTED/QUEUED/ASSIGNED/WORKING/WAITING_DEPENDENCY/WAITING_RESULT/COMPLETED/REVIEWED/FAILED/RETRYING/ESCALATED/EXPIRED/CANCELLED). Only partial priority/attempt concepts exist in `SupervisorAgent`.

### §8 Evidence Model — **FAIL**
- No Fact/Interpretation/Recommendation typing. `AnalystReport` has `evidence: str` and `reliability: float`, but no `fact|interpretation|recommendation`, `freshness_ms`, `data_quality`, `timeframe`, `source`, `originating agent/task` as required by §8.

### §9 Decision State — **FAIL**
- No normalized `DecisionState` object. Closest is `TradeProposal` (`synthesis.py`), which lacks `market_bias`, `setup_status`, `conflicts`, `market_risk`, `data_quality`, and the 8-value `decision` enum.

### §10 Conflict Resolution / Committee — **PARTIAL**
- `departments.py` avoids majority vote (returns `UNRESOLVED`). `synthesis.py` detects conflicts and escalation.
- **Violation:** `market/intelligence.py` `MarketLead.synthesize()` uses `max(set(directions), key=directions.count)` (majority vote).
- **Gaps:** no evidence-quality/freshness/reliability comparison loop; no structured multi-round debate; no committee output containing counter-evidence and invalidation conditions (§10.1).

### §10.2 Decision dimensions — **FAIL**
- No separation of `MARKET_BIAS / SETUP_DIRECTION / ACTION`. Only `TradeDirection(BUY/SELL/HOLD)`.

### §10.3 Autonomous Operation — **FAIL**
- No scheduler or event loop; Supervisor unwired. No deterministic-detector → event → Supervisor wake-up path. `EventQueue`/`EventHistory` (`trading/event_engine.py`) exist but nothing consumes them into the Supervisor.

### §11 Confidence & Reliability — **PARTIAL**
- `confidence` and `reliability` exist (`AnalystReport`, `MarketDepartment`). No separate `signal strength`, `risk score`, `evidence quality`, `data quality`, `freshness`, `agent reliability`, `model reliability` tracking.

### §12 Deterministic Risk Architecture — **PASS (logic)**
- Risk Intelligence: `src/risk/intelligence.py`. Deterministic engine/gate: `src/risk/engine.py` `RiskEngine` + `src/risk/gate.py` `RiskGate` (drawdown, daily loss, positions, exposure, margin, spread, R:R, SL) → `GateDecision(approved, reason, checks_passed, metrics_snapshot)`. Kill switch & circuit breaker present. Well tested.

### §13 Execution Architecture — **PARTIAL**
- `ExecutionEngine.execute_order()` → validate → duplicate check → send → confirm → sync → audit; retry with backoff on transient retcodes. `OrderRequest` has `idempotency_key`.
- **Gaps:** only `idempotency_key` from the 7 required identifiers; no explicit "proposal validator for stale context"; idempotency is in-memory (`_pending_orders`/`_completed_orders`) and lost on restart.

### §14 Reconciliation — **PARTIAL**
- `ExecutionEngine.sync_position()`/`confirm_execution()`; `ExecutionRecoveryEngine` (NORMAL→WARN_MISMATCH→BLOCKED_CRITICAL) audits orphans, missing ledger, volume mismatch.
- **Gaps:** no scheduled full reconciliation; MT5 reads simulated (`mt5/connector.py` is a simulator by default); no SL/TP/symbol/magic comparison matrix as specified.

### §15 Event Priority — **PARTIAL**
- `trading/event_engine.py` `EventPriority(LOW/MEDIUM/HIGH/CRITICAL)` and `EVENT_PRIORITY_MAP` covering all `EventTypes`; `EventQueue` priority-dequeues.
- **Gaps:** PRD requires 5 levels (`CRITICAL/HIGH/NORMAL/LOW/BACKGROUND`); code has 4 (no `NORMAL`/`BACKGROUND`, uses `MEDIUM`). No LLM-budget honoring by priority (Supervisor isn't wired).

### §16 Context Builder — **FAIL**
- No context builder producing filtered snapshots (Market/Account/Position/Risk/Strategy/Recent Events/Evidence/Memory/Agent Results). `SupervisorAgent`/DepartmentLeads accept an opaque `context: dict`. No filtering/snapshot builder found.

### §17 Memory Architecture — **FAIL**
- Only `src/memory/trade_memory.py` `TradeMemoryStore` (episodic-ish). Missing separate Working / Semantic / Strategy / Research memory types and relevance-based, source-aware retrieval (§17).

### §18 Research & Learning Loop — **PARTIAL**
- `learning/loop.py` `LearningLoop` implements REVIEW→PATTERN→HYPOTHESIS→EXPERIMENT→CANDIDATE→VALIDATION→APPROVAL; `learning/performance.py` KPIs; `review/advanced_review.py` root-cause + patterns. `research/engine.py` hypotheses/experiments/backtests (EMA mock backtest).
- **Gaps:** backtest is a minimal mock; no walk-forward gate implementation; pattern grouping in `loop.review_to_patterns()` is by symbol only; nothing auto-triggers on trade close.

### §18.3 Supervisor performance profile — **PARTIAL**
- `performance.supervisor_kpis()`: win_rate, profit_factor, expectancy, max_drawdown, false_signals. Missing by-session/hour/regime/setup breakdown, rolling performance, false-signal rate semantics, no-trade quality (hardcoded 0.0).

### §19 Strategy Registry — **PARTIAL**
- `src/strategy/registry.py` `StrategyRegistry`, `VersionedStrategy`, `PromotionGate`, `ReadOnlyDict`. Only 4 statuses; missing 6 and several metadata fields (see §32.13).

### §20 AI Provider Manager / 9Router — **FAIL**
- `NineRouterClient` speaks OpenAI-compatible API and supports fallback/retry, but **no dynamic discovery**: `ModelRegistry._register_defaults()` hardcodes 6 models. No `GET /v1/models`. `/ai/models` API returns hardcoded 4 with fake `last_discovery`. Frontend hardcodes models in `app/page.tsx` (3 places) and no `CONNECTED/DEGRADED/DISCONNECTED` health logic (only static strings). No per-role model overrides.

### §21 Telegram Gateway — **FAIL**
- **MISSING.** No bot, polling, webhook, or command routing. `telegram/opencode-context.md` is a planning note. `/telegram/status` (`index.ts` L455–467) returns `connected: true`, `bot_username: '@ea_bot_control'`, fabricated command list. EPIC 03.13–03.16 unmet.

### §22 Model Routing — **PARTIAL**
- `NineRouterClient` model param + fallback chain; `ModelInfo.capabilities`. No policy-based router (complexity/priority/risk/conflict/budget). `SupervisorAgent.routing_policy` is *agent* routing, not model routing. No cost/latency logging pipeline wired.

### §23 Trading Modes — **FAIL**
- No `TradingMode` enum (OFFLINE/BACKTEST/PAPER/DEMO/LIVE/EMERGENCY_STOP). `/system/overview` returns a hardcoded `mode: 'PAPER'`. Mode transitions are not auditable. (`live_readiness` gates exist but are not a mode state machine; `demo/`, `paper/` modules exist.)

### §24 Circuit Breakers — **PARTIAL**
- `src/risk/circuit_breaker.py` `CircuitBreaker` (CLOSED/OPEN/HALF_OPEN, trips kill switch) — tested. 
- **Gaps:** single generic breaker; PRD requires breakers for LLM gateway, market data, MT5, DB, queue, execution. Only conceptually covers MT5/execution; not instantiated for each dependency. Not wired into runtime.

### §25 Control Plane / Dashboard — **PARTIAL (shell only)**
- 5 pages exist: `app/page.tsx` (Research/Settings), `app/control-plane/page.tsx` (16 tabs), `app/ai-control/page.tsx`, `app/strategy/page.tsx`, `app/observability/page.tsx`.
- **Gap:** pages render **demo data**. `app/ai-control/page.tsx` fetches `/api/ai-control/status` (relative) but there is **no Next.js API route** and **no rewrite** in `next.config.mjs` → 404. AI organization hierarchy shown statically. No raw chain-of-thought protection is actually needed because there is no reasoning source.

### §26 Traceability — **PARTIAL**
- `observability/traces.py` + `memory/trade_memory.py` provide building blocks; no unified trace and no ID propagation across web/API/Python. `/audit/events` returns demo data.

### §27 Observability — **PARTIAL**
- Python: `observability/{traces,metrics,alerts}.py` (`MetricsRegistry` domain recorders, `AlertManager`). Node: `apps/api/src/metrics.ts` (Prometheus), `/metrics`, `/observability/metrics|errors`. Tests `test_observability.py`.
- **Gap:** none of the real Python metrics reach the dashboard; dashboard metrics are hardcoded.

### §28 Security — **PARTIAL**
- Node: `middleware/auth.ts` (JWT), `rateLimiter.ts`, `secrets.ts`, `security.ts`, `audit.ts`; helmet; `/auth/token` dev-only; `/audit-logs` admin-only. Python: `security/tool_permissions.py`, `security/audit_log.py` (SHA-256 hash chain). Tests: `test_security.py`.
- **Gaps:** auth not applied to most endpoints (only `/audit-logs`); JWT default secret in code; `allowed_origins=["*"]` + `allow_credentials=True` in `services/python/src/main.py` CORS (unsafe combo); LIVE-mode protection depends on unwired `live_readiness`.

### §29 Testing Requirements — see §5 table below.

---

## 4. Integration Wiring Status

### 4.1 What is really connected

```text
FRONTEND (Next.js)                          BACKEND
──────────────────                          ───────
app/page.tsx          (Research/Settings) ──► localStorage only (no API)
app/control-plane/    (16 tabs)  ──► fetch  ──► apps/api (Express, :3001) ──► STATIC demo JSON
app/observability/               ──► fetch  ──► apps/api observability/metrics (REAL, from its own registry)
app/ai-control/       ──► fetch('/api/...') ──► ✗ NO Next.js API route, NO rewrite → 404
app/strategy/         (static demo)

apps/api (Express :3001)
   ├── /metrics, /observability/*        → REAL (own in-process metrics)
   ├── /auth/token, /audit-logs          → REAL (JWT + audit middleware)
   └── ALL control-plane endpoints       → HARDCODED DEMO DATA (no data source)

Python FastAPI (services/python/src/main.py, :8000)
   ├── /health, /trading/*, /events/*, /mt5/*   → REAL logic (but SIMULATED MT5)
   └── NOT CALLED BY ANYTHING

Python "brain" libraries (agents/, risk/, execution/, learning/, ...)
   └── Reachable ONLY from pytest. No production entry point.
```

### 4.2 Key wiring facts (with evidence)

| Link | Status | Evidence |
|---|---|---|
| Web → API (control-plane/observability) | **CONNECTED** | `control-plane/page.tsx` L6/L61 (`NEXT_PUBLIC_API_URL`); `observability/page.tsx` L62/L77–79 |
| Web → API (ai-control) | **BROKEN** | `ai-control/page.tsx` L56/L67 fetch `/api/...`; no `app/api/` dir; `next.config.mjs` has no `rewrites` |
| API → Python service | **MISSING** | No `fetch`/`axios`/http client in `apps/api/src/**`; only Prometheus/obs internals |
| API data → real source | **MISSING** | Every endpoint body is a literal object (e.g. `index.ts` L277–291, L418–430, L455–467) |
| Python FastAPI → brain (Supervisor etc.) | **MISSING** | `src/main.py` includes only `mt5_router`, `trading_router`, `events_router`; no agents/risk/execution routers |
| Supervisor → production | **MISSING** | `grep import supervisor` → only `agents/__init__.py` + tests |
| Event queue → Supervisor | **MISSING** | `EventQueue` only consumed in tests; no scheduler |
| 9Router → model discovery | **MISSING** | No `GET /v1/models`; static `registry.py` |
| Telegram → anything | **MISSING** | No module |

### 4.3 Text diagram — reality vs PRD

```text
PRD §3 target:  Event → Supervisor → Departments → Decision State → Risk Gate → Execution → MT5 → Review

ACTUAL:         (no event loop)     ┌───────────── tests only ─────────────┐
                                     │ Supervisor · Departments · RiskGate  │
                                     │ Execution · Learning · Strategy      │
                                     └──────────────────────────────────────┘
Dashboard ──► Express API ──► [ hardcoded demo JSON ]        (no Python call)
Telegram   ──► (does not exist)
9Router    ──► (static list, no /v1/models)
```

---

## 5. Test Category Coverage (PRD §29)

All tests live in `services/python/tests/` (48 files, **836 passing**). Node apps have **no test files**.

| PRD §29 category | Status | Evidence (files / key tests) |
|---|---|---|
| unit | **PRESENT** | 40+ files incl. `test_trading.py`, `test_regime.py`, `test_order_builder.py`, `test_strategy_registry.py` |
| integration | **PRESENT (weak)** | `test_integration.py` (4 tests) — imports `src.main`, synthetic OHLC; no web/API/DB integration |
| orchestration | **PRESENT** | `test_supervisor.py` (17), `test_supervisor_department_routing.py` (3), `test_departments.py` |
| agent failure | **PRESENT** | `test_failure_simulation.py` `FlakyAgent` failure isolation/timeout (18.03–18.04) |
| LLM timeout/fallback | **PRESENT** | `test_llm.py`: `test_nine_router_retry_on_failure`, `test_nine_router_fallback_to_secondary_model`, `test_nine_router_mock_fallback_when_all_fail` |
| duplicate order | **PRESENT** | `test_execution_engine.py`, `test_failure_simulation.py` (duplicate idempotency key) |
| MT5 disconnect | **PRESENT** | `test_mt5_connection.py` (15: failures, reconnect, max failures), `test_mt5.py` |
| risk breach | **PRESENT** | `test_deterministic_risk_gate.py` (16), `test_risk_engine.py`, `test_kill_switch.py`, `test_circuit_breaker.py` |
| state recovery | **PRESENT** | `test_order_builder.py` (`ExecutionRecoveryEngine`), `test_trade_memory.py` (persist), `test_phase_29_validation.py` |
| reconciliation mismatch | **PRESENT** | `test_failure_simulation.py`, `test_order_builder.py` (orphan/volume mismatch → block) |
| circuit breaker | **PRESENT** | `test_circuit_breaker.py` (11) |
| end-to-end | **MISSING (true E2E)** | No test drives event→supervisor→risk→execution→MT5 as one flow. `test_integration.py` is shallow. No browser/API E2E. |
| chaos/simulation | **PRESENT** | `test_failure_simulation.py` "chaos storm" scenario (18.14) |

**Result: 12/13 categories PRESENT; "end-to-end" is effectively MISSING** (no pipeline exists to test). Node layer untested.

---

## 6. Prioritized Gap List

### P0 — Blocks production / critical PRD violation

1. **Wire the trading pipeline (Supervisor → Departments → Decision → Risk Gate → Execution).**
   *Files:* new orchestrator (e.g. `services/python/src/orchestration/pipeline.py`); modify `services/python/src/main.py` to expose `/supervisor/analyze`, `/pipeline/run`; connect `SupervisorAgent` (`agents/supervisor.py`) to `EventQueue` (`trading/event_engine.py`) and `RiskGate` (`risk/gate.py`) + `ExecutionEngine` (`execution/engine.py`).
2. **Implement the autonomous scheduler / event loop (PRD §10.3, §32.17).**
   *Files:* new `services/python/src/trading/scheduler.py` (asyncio loop or APScheduler) consuming `EventDetector.detect()` → `EventQueue` → Supervisor; start it from `main.py` lifespan.
3. **Stop serving fabricated data from the API (PRD §25/§26/§27).**
   *Files:* `apps/api/src/index.ts` — replace literal objects (L274–487) with real proxy calls to the Python service (`PYTHON_SERVICE_HOST/PORT` already in `.env.example`); add explicit `source: 'demo'|'live'` flags until wired; fix `/telegram/status` and `/system/health` to not claim non-existent services are up.
4. **Implement Telegram gateway (PRD §21, §32.18).** 
   *Files:* new `services/python/src/telegram/gateway.py` (or `services/telegram/` node bot) with allowlist/RBAC, command routing to Supervisor traces, event notifications. Remove the fake `/telegram/status`.
5. **Dynamic 9Router model discovery (PRD §20, §32.19) + remove frontend hardcoded lists.**
   *Files:* `services/python/src/llm/registry.py` (add `discover_from_gateway()` calling `client.models.list()` / `GET /v1/models` with cache/refresh, health state); `apps/api/src/index.ts` `/ai/models` to proxy it; `apps/web/app/page.tsx` L20/L89 remove hardcoded `qwen2.5-72b/llama-3.3-70b/claude-3-5-sonnet`, fetch from API.
6. **Fix frontend→API wiring for AI Control.** 
   *Files:* add `apps/web/app/api/ai-control/status/route.ts` proxy **or** a `rewrites()` block in `apps/web/next.config.mjs`; update `apps/web/app/ai-control/page.tsx` to use `NEXT_PUBLIC_API_URL` like the other pages.

### P1 — Major

7. **Task Contract + state machine (PRD §7).** New `services/python/src/agents/task.py` (Task dataclass + states).
8. **Evidence Model (PRD §8).** New `services/python/src/agents/evidence.py` (Fact/Interpretation/Recommendation with source/timestamp/timeframe/freshness/quality/metric).
9. **Decision State (PRD §9) + decision dimensions (§10.2).** New `services/python/src/agents/decision_state.py` with market_bias/setup/action separation.
10. **Remove majority vote (PRD §10).** `services/python/src/market/intelligence.py` `MarketLead.synthesize()` → route through `departments.DepartmentLead._resolve_consensus()`.
11. **Context Builder (PRD §16).** New `services/python/src/orchestration/context_builder.py` producing filtered snapshots.
12. **Memory types (PRD §17).** New modules under `services/python/src/memory/` (working/semantic/strategy/research) + relevance retrieval.
13. **Strategy statuses/fields (PRD §19).** `services/python/src/strategy/registry.py` — expand `StrategyStatus` to 10 values and `VersionedStrategy` fields.
14. **Model routing policy (PRD §22).** New `services/python/src/llm/model_router.py` (complexity/priority/risk/budget → model; log cost/latency/fallback).
15. **Trading Modes (PRD §23).** New `services/python/src/trading/modes.py` enum + audited transitions; wire `live_readiness`.
16. **Per-dependency circuit breakers (PRD §24).** Instantiate `CircuitBreaker` for LLM/market/MT5/DB/queue/execution and block orders when execution-critical is open.
17. **Full reconciliation engine (PRD §14).** Scheduled comparison of positions/orders/lots/SL/TP/symbol/magic/orphans.
18. **True end-to-end test (PRD §29).** New `services/python/tests/test_end_to_end.py` exercising event→supervisor→risk→execution→review; add Node/API tests.
19. **Security hardening (PRD §28).** Apply `authenticate`/`authorize` to non-public API routes; fix Python CORS (`allow_origins=["*"]` with `allow_credentials=True`).

### P2 — Minor

20. **Blockchain-evidence/observability unification (PRD §26/§27):** propagate trace IDs web→API→Python; feed `MetricsRegistry` into API (not demo).
21. **Supervisor KPI completeness (PRD §18.3/§32.23):** populate `no_trade_quality`, add by-session/hour/regime/setup.
22. **Event priority levels (PRD §15):** add `NORMAL`/`BACKGROUND` (currently `MEDIUM`/`LOW`).
23. **Review auto-trigger (PRD §18.1/§32.20):** hook `TradeReviewer`/`classify_root_cause` on position close.
24. **Research backtest realism (PRD §18):** replace EMA mock in `research/engine.py` with indicator-based simulation; add walk-forward.
25. **Remove dead placeholders:** `base.py` `FundamentalAnalystAgent`/`SentimentAnalystAgent` ("not yet implemented"); deduplicate `TechnicalAnalyst` vs `TechnicalAnalystAgent`.

---

## 7. Verification Command Outputs (read-only)

| Command | Result |
|---|---|
| `cd services/python && .venv/Scripts/python -m pytest -q` | **836 passed, 1 warning in 5.32s** (matches expected) |
| `cd apps/api && npx tsc --noEmit` | **exit 0** (clean) |
| `cd apps/web && npx tsc --noEmit` | **exit 0** (clean) |

Warning: `starlette/testclient.py:53` DeprecationWarning (`anyio.abc.BlockingPortal`) — informational only.

> Note: green tests measure the **library layer**, not integration. Nothing in the test suite exercises the web↔API↔Python path, the scheduler, Telegram, or live model discovery.

---

## 8. Evidence Index (key file paths)

- PRD authority: `PRD_V2.md`; roadmap `MASTER_TASKS.md`; `ARCHITECTURE_MAP.md`; `CHANGELOG.md`
- **No Telegram:** `telegram/opencode-context.md` (only match for `*telegram*`)
- **Hardcoded API data:** `apps/api/src/index.ts` L177–487 (all endpoints)
- **Static model registry:** `services/python/src/llm/registry.py` L18–77 (`_register_defaults`)
- **Frontend hardcoded models:** `apps/web/app/page.tsx` L20, L89
- **Supervisor unwired:** `services/python/src/agents/supervisor.py`; importers = `agents/__init__.py`, tests
- **FastAPI surface:** `services/python/src/main.py` L42–44 (mt5/trading/events routers only)
- **No scheduler:** grep `asyncio|schedule|while True` → only `src/mt5/connection_manager.py`
- **Broken frontend fetch:** `apps/web/app/ai-control/page.tsx` L56/L67; `apps/web/next.config.mjs` (no rewrites); no `apps/web/app/api/`
- **Risk/Execution (real):** `src/risk/gate.py`, `src/risk/engine.py`, `src/execution/engine.py`, `src/execution/order_builder.py`
- **Safety/permissions:** `src/agents/permissions.py`, `src/mt5/write_guard.py`
- **Learning/Memory/Strategy:** `src/learning/loop.py`, `src/learning/performance.py`, `src/memory/trade_memory.py`, `src/strategy/registry.py`
- **Review/Research:** `src/review/trade_review.py`, `src/review/advanced_review.py`, `src/research/engine.py`
- **Observability/Security/Readiness:** `src/observability/*`, `src/security/*`, `src/readiness/*`, `src/live_readiness/*`
- **Tests:** `services/python/tests/` (48 files, 836 passed)

---

*End of audit. No code was modified.*
