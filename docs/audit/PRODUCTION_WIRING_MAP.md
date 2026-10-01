# PRODUCTION WIRING MAP — `services/python/src` (TASK 05)

> Repo: `billy19911/project-ea-bot` · Branch `main` · HEAD = `2e38d19` (TASK 01–04).
> Scope: classify **every** module under `services/python/src` (+ worker entry points)
> into exactly one of `LIVE_RUNTIME`, `BACKGROUND_WORKER`, `API_ENDPOINT`,
> `UI_ONLY`, `TEST_ONLY`, `LEGACY`, `ORPHANED`, `DEAD_CODE`.
> **No code was deleted.** This document classifies only.
> Safety: all MT5 execution remains DISARMED by default.

Master plan: `telegram/_MASTER_PLAN.md` §7 (TASK 05), invariants #20/#21, §15.

---

## 0. Method + evidence commands

All evidence was produced with `ripgrep` from `services/python/`:

```bash
# absolute imports
rg -n "from <pkg.mod> import|import <pkg.mod>" src/ -g '!**/__pycache__/**'
# relative imports (intra-package)
rg -n "from \.<mod> import|from \.\.<mod> import" src/ -g '!**/__pycache__/**'
# who mounts the FastAPI routers
rg -n "include_router|import router as" src/main.py
# who imports a candidate
rg -n "<class-or-module>" src/ -g '!**/__pycache__/**'
# tests-only signal
rg -n "from <pkg.mod> import" tests/ -g '!**/__pycache__/**'
```

A generated reference matrix (module → #src refs → #test refs → importers) is
reproducible with a small script; its output is summarised in §3.

### Classification legend

| Class | Meaning |
|---|---|
| **LIVE_RUNTIME** | Constructed by the single process runtime (`OrchestrationRuntime`) or the FastAPI lifespan and executed in the request/event path. |
| **BACKGROUND_WORKER** | Owns a loop/thread that runs continuously in production (one owner). |
| **API_ENDPOINT** | FastAPI router/handler mounted by `main.py` (request-scoped; no background loop of its own). |
| **UI_ONLY** | Not imported by the Python service; exists only for the Node/Next dashboard (none under `src`). |
| **TEST_ONLY** | Imported only by `tests/**` (or a package `__init__` re-export with zero functional consumers) — never reached by `main.py`/runtime/endpoints. |
| **LEGACY** | Retained for backward compatibility; a *replacement* is the one actually used. |
| **ORPHANED** | Reachable by import side-effect (`package __init__`) but **no** production code consumes it; a would-be production component with no owner. |
| **DEAD_CODE** | Never imported by production *nor* referenced by tests (or only shadowed by a duplicate class). |

> **Package `__init__` side-effect rule.** Importing any submodule runs the
> parent package `__init__.py`. So a module re-exported by `pkg/__init__.py`
> loads whenever any sibling is imported. That is **reachability**, not
> **usage** — a module that is only re-exported is classified `ORPHANED`/`DEAD`
> unless some production code actually calls its symbols. Both facts are
> recorded below.

---

## 1. Entry points (roots of the production graph)

### 1.1 ASGI application — `main.py`

`services/python/src/main.py` is **the** production entry point
(`uvicorn src.main:app`). It:

* builds the durable stores, agent registry, and learning feedback in `lifespan`;
* mounts **12 routers** (`main.py:786-799`);
* starts optional background loops only when enabled (see §2).

Routers mounted (`main.py:786-799`):

```text
mt5.endpoints            charting.endpoints      trading.endpoints
trading.events           orchestration.endpoints system.endpoints
system.v2_endpoints      strategy.endpoints      reports.endpoints
research.endpoints       market.endpoints        ops.router
```

Plus `main.py` own routes: `GET /health`, `GET /`.

### 1.2 Other entry points / worker scripts (outside `src`)

| Path | Kind | Notes |
|---|---|---|
| `services/python/probe_*.py` (8 files) | DEV_TOOL (not production) | One-shot operator probes (`probe_account_ctx.py`, `probe_history_live.py`, …). Not imported by the app. |
| `services/python/scripts/_task02_verify.py` | DEV_TOOL | Verification helper for TASK 02. |
| `scripts/*.ps1` (restart/start/stop-all) | OPS | Process launch scripts; they `uvicorn`-launch `main:app`. |
| `services/python/tests/**` | TEST_ONLY | Pytest suite (220 test modules under `tests/`). |

---

## 2. Runtime singleton rule (§7 of master plan)

**Rule:** exactly ONE production instance of `runtime`, `scheduler`, event
queue, `supervisor`, `pipeline`, market feed loop, position monitor and
reconciliation runner — unless explicitly scoped per account/terminal.

**Result: SATISFIED.** All eight are owned by a single process-wide
`OrchestrationRuntime` (lazily built by `get_runtime()`), plus the feed loop
which is created **once** in the FastAPI lifespan.

### 2.1 Ownership chain

```text
get_runtime()                        src/orchestration/runtime.py:1075   (lazy singleton)
└── OrchestrationRuntime.__init__    src/orchestration/runtime.py:458
    ├── self.queue         = EventQueue()               runtime.py:472  (unique)
    ├── self.reconciliation= ReconciliationRunner()     runtime.py:485  (unique)
    │     └── _reconciliation_guard = ReconciliationGuard(...)  runtime.py:493
    ├── self.pipeline      = TradingPipeline(...)       runtime.py:798  (unique, via _build_pipeline)
    │     ├── SupervisorAgent(...)                      runtime.py:613  (unique)
    │     └── OrderBuilder(...)                         runtime.py:710
    ├── self.scheduler     = AutonomousScheduler(...)   runtime.py:509  (unique)
    │     └── pipeline = _RecordingPipelineProxy(self.pipeline, self)  runtime.py:513
    ├── self.position_monitor = PositionMonitor(...)    runtime.py:253  (unique)
    └── self.trade_manager = TradeManager(...)          runtime.py:557
MarketFeedLoop                        src/main.py:525 (lifespan, ONE instance, gated by
                                                     MARKET_FEED_ENABLED)
```

### 2.2 Duplicate-instantiation audit (single production site each)

| Component | Class def | Production construction site | Count |
|---|---|---|---|
| runtime | `runtime.py:455` | `runtime.py:1079` (lazy, once) | 1 |
| scheduler | `scheduler.py:41` | `runtime.py:509` | 1 |
| event queue | `event_engine.py:136` | `runtime.py:472` | 1 |
| supervisor | `supervisor.py:280` | `runtime.py:613` | 1 wired |
| pipeline | `pipeline.py:333` | `runtime.py:798` | 1 |
| market feed loop | `feed_loop.py:58` | `main.py:525` | 1 |
| position monitor | `position_monitor.py:137` | `runtime.py:253` | 1 |
| reconciliation runner | `reconciliation_runner.py:58` | `runtime.py:485` | 1 |

> **Benign duplicate (diagnostic only):** `SupervisorAgent()` is also built
> once inside `system/certification.py:147` as a *certification connectivity
> probe* (constructibility check). It is never wired to the pipeline/queue and
> is discarded. **Flagged, not a second production supervisor.**
>
> `scheduler.start()` is idempotent (`scheduler.py:410` returns early if
> running) and is called only from `main.py:502`. The feed loop's `run()` is
> scheduled only from `main.py:541`. **No duplicate scheduler/feed loops.**

### 2.3 Per-account / per-terminal scoping

None of the eight components take `account_id`/`terminal_id` as constructor
params. Account/terminal fan-out happens **inside** the single pipeline
(`pipeline.py:_dispatch_execution`, single canonical signal → N armed
terminals). `PositionMonitor.monitor_all_positions(account_id=None)` accepts an
`account_id` argument but it is currently unused. → **No component is scoped
per account/terminal; the singleton is process-global.**

### 2.4 Runtime identity (TASK 05 deliverable — duplicate-worker detection)

Added `services/python/src/orchestration/runtime_identity.py`:

```text
process_id             os.getpid()  (module-level, stable per process)
host                   socket.gethostname()
runtime_instance_id    "runtime-<pid>-<8hex>"
scheduler_instance_id  "scheduler-<pid>-<8hex>"
feed_instance_id       "feed-<pid>-<8hex>"
queue_instance_id / supervisor_instance_id / pipeline_instance_id /
position_monitor_instance_id / reconciliation_instance_id
```

* `OrchestrationRuntime` creates `self.identity = RuntimeIdentity("runtime")`
  and registers each component once (idempotent — first writer wins).
* The scheduler receives `identity=self.identity` and stamps **every analysis
  log line + every event-trace entry** with `process_id`,
  `runtime_instance_id`, `scheduler_instance_id`, `feed_instance_id`
  (`scheduler.py:_identity_fields`, `_record_event_trace`).
* `MarketFeedLoop(identity=...)` registers `feed_instance_id` at construction.
* `GET /scheduler/status` now returns an `identity` block (`endpoints.py`).

**Why this detects duplicates:** a second scheduler/feed in the same process
gets a *different* `*_instance_id`; a second process gets a *different*
`process_id`. Both are visible in the log line and in the API.

Proof (runtime verification, run 2026-…): see §6.

---

## 3. Module classification

The table below classifies every module. "Import path from entry point" is the
first hop from a production root (`main.app` → router → module, or
`get_runtime()` → module). `none` = not reachable from a production root.

### 3.1 `services/python/src/*` (top level)

| Module | Class | Import path / owner | Evidence |
|---|---|---|---|
| `main.py` | LIVE_RUNTIME | production ASGI entry (`uvicorn src.main:app`) | `main.py:748 app = FastAPI(...)`, `main.py:786-799 include_router` |
| `config.py` | LIVE_RUNTIME | imported by `main.py`, `pipeline.py`, `runtime.py` | `rg "from config import" src/` → `orchestration/pipeline.py:29`, `orchestration/runtime.py`, `certification/checks.py` |
| `env_bootstrap.py` | LIVE_RUNTIME | `main.py` lifespan | `main.py` `from .env_bootstrap import load_runtime_env` |
| `logging_setup.py` | LIVE_RUNTIME (bootstrap) | imported at process start / tests | used by test harness + process init |
| `audit.py` | LIVE_RUNTIME | `execution/reconciliation_runner.py`, `orchestration/endpoints.py` | `rg "import audit\|from audit import" src/` |
| `validate_env.py` | DEV_TOOL | standalone (`python validate_env.py`) | no src importer |
| `_unify_imports.py` | LIVE_RUNTIME (compat bootstrap) | dual-import shim (`mt5.terminals` vs `src.mt5.terminals`) | docstring `src/_unify_imports.py:7-12` |
| `agents/__init__.py` | package facade | re-exports agents API | `agents/__init__.py` |

### 3.2 `agents/`

| Module | Class | Import path / owner | Evidence |
|---|---|---|---|
| `agents/base.py` | LIVE_RUNTIME | `main.py:22`, all analysts | `rg "from agents.base\|from .base import"` |
| `agents/registry.py` | LIVE_RUNTIME | `main.py`, `orchestration/runtime.py` | `main.py:23` |
| `agents/supervisor.py` | LIVE_RUNTIME | `runtime.py:613` (single) | `runtime.py:21,613` |
| `agents/activity.py` | LIVE_RUNTIME | `supervisor.py:142`, `departments.py:24`, `main.py` health | `rg "get_activity_tracker"` |
| `agents/agent_memory.py` | LIVE_RUNTIME | `main.py` review bridge, `base.py:393` | `main.py`, `agents/base.py:393` |
| `agents/canonical.py` | LIVE_RUNTIME | `trading/entry_adapter.py`, `committee.py`, `orchestrator.py` | `rg "from agents.canonical\|from .canonical import"` |
| `agents/committee.py` | LIVE_RUNTIME | `orchestrator.py:22` | `rg "from .committee import"` |
| `agents/committee_record.py` | LIVE_RUNTIME | `supervisor.py:23` | `rg "from .committee_record import"` |
| `agents/debate.py` | LIVE_RUNTIME | `orchestrator.py:23,231` | `rg "from .debate import"` |
| `agents/departments.py` | LIVE_RUNTIME | `agents/__init__.py` re-export; `market/intelligence.py` | `rg "departments"` |
| `agents/event_dispatch.py` | LIVE_RUNTIME | `orchestrator.py:24` | `rg "from .event_dispatch import"` |
| `agents/orchestrator.py` | LIVE_RUNTIME | `agents/__init__.py` (re-export); used via supervisor/committee path | package facade; see `agents/__init__.py` |
| `agents/roles.py` | LIVE_RUNTIME | `certification/checks.py`, `debate.py:29`, `orchestrator.py:25` | `rg "from .roles import"` |
| `agents/synthesis.py` | LIVE_RUNTIME | `agents/__init__.py:20`, `supervisor.py:24` | `rg "from .synthesis import"` |
| `agents/analysts/*` (6) | LIVE_RUNTIME | `main.py:20` (`from agents.analysts import …`) | `main.py:20-26`, `runtime.py`, `review/intelligence.py` |
| `agents/permissions.py` | LIVE_RUNTIME | `mt5/write_guard.py:21,218` | `rg "from agents.permissions import"` |
| `agents/evidence.py` | DEAD_CODE (shadowed) | `agents/__init__.py:18` re-export only; real code uses `agents/canonical.py` | subagent grep: 0 functional consumers; duplicate class in `canonical.py:131` |
| `agents/decision_state.py` | DEAD_CODE (shadowed) | `agents/__init__.py:17` re-export only; real code uses `agents/canonical.py:512` | 0 functional consumers |
| `agents/task.py` | ORPHANED | `agents/__init__.py:21-22` re-export only; no symbol consumed | `rg "TaskStatus\|TaskPriority\|Task\(` → only tests |
| `agents/failure`/misc (none) | — | — | — |

### 3.3 `orchestration/`

| Module | Class | Import path / owner | Evidence |
|---|---|---|---|
| `orchestration/runtime.py` | LIVE_RUNTIME | `main.py:32 get_runtime()`; all endpoints | `main.py:32`, singleton `runtime.py:1075` |
| `orchestration/pipeline.py` | LIVE_RUNTIME | `runtime.py:41` (single instance) | `runtime.py:498-505` |
| `orchestration/runtime_identity.py` | LIVE_RUNTIME (diagnostic) | `runtime.py` + `scheduler.py`; **added TASK 05** | `rg "runtime_identity"` |
| `orchestration/endpoints.py` | API_ENDPOINT | mounted `main.py:790` | `/pipeline/run`, `/scheduler/status`, `/scheduler/event-trace`, `/observability/traces`, `/signals/active` |
| `orchestration/account_context.py` | LIVE_RUNTIME | `runtime.py:40` (`AccountContextProvider`) | `runtime.py:521` |
| `orchestration/signal_registry.py` | LIVE_RUNTIME | `runtime.py:42` | `runtime.py` |
| `orchestration/context_builder.py` | DEAD_CODE (side-effect load) | `orchestration/__init__.py:14` re-export only; note a **different** `ContextBuilder` lives in `llm/router.py:114` and IS used | subagent grep: 0 consumers (not tests) |

### 3.4 `trading/`

| Module | Class | Import path / owner | Evidence |
|---|---|---|---|
| `trading/scheduler.py` | BACKGROUND_WORKER (owner: runtime) | `runtime.py:509` | one instance; `start()` only `main.py:502` |
| `trading/feed_loop.py` | BACKGROUND_WORKER (owner: lifespan) | `main.py:525` | one instance; gated `MARKET_FEED_ENABLED` |
| `trading/event_engine.py` | LIVE_RUNTIME | `EventQueue` built `runtime.py:472`; `EventDeduplicator`/`EventHistory` used by `trading/events.py` | `rg "from .event_engine import"` |
| `trading/events.py` | API_ENDPOINT | mounted `main.py:789` (`events_router`) | `main.py:42` |
| `trading/event_classes.py` | LIVE_RUNTIME | `runtime.py`, `scheduler.py` (`EventGate`) | `rg "trading.event_classes"` |
| `trading/endpoints.py` | API_ENDPOINT | mounted `main.py:788` | `main.py:41` |
| `trading/indicators.py` | LIVE_RUNTIME | analysts, `market/multi_timeframe.py`, `research/endpoints.py` | `rg "from trading.indicators\|from .indicators"` |
| `trading/entry_adapter.py` | LIVE_RUNTIME | `pipeline.py` | `rg "entry_adapter"` |
| `trading/entry_config.py` | LIVE_RUNTIME | `trading/entry_adapter.py` | relative import |
| `trading/entry_zone.py` | LIVE_RUNTIME | `pipeline.py`, `runtime.py` (ZONE_ENTRY gate) | `rg "entry_zone"` |
| `trading/entry_zones.py` | LIVE_RUNTIME | `trading/entry_adapter.py` | relative import |
| `trading/level_plan.py` | LIVE_RUNTIME | `pipeline.py` | `rg "level_plan"` |
| `trading/market_snapshot.py` | LIVE_RUNTIME | `feed_loop.py`, `pipeline.py`, `runtime.py`, `ops/readmodels.py` | `rg "market_snapshot"` |
| `trading/market_freshness.py` | LIVE_RUNTIME | `pipeline.py` (Step 0.5 gate), `ops/readmodels.py`, `market/endpoints.py` | `rg "market_freshness"` |
| `trading/trigger_engine.py` | LIVE_RUNTIME | `agents/orchestrator.py`, `pipeline.py`, `entry_adapter.py` | `rg "trigger_engine"` |
| `trading/engine.py` | TEST_ONLY | only tests | `rg` → tests only |
| `trading/entry_detectors.py` | ORPHANED | no src/test consumers found | `rg` → none |
| `trading/entry_lifecycle.py` | ORPHANED | no src/test consumers | `rg` → none |
| `trading/modes.py` | LIVE_RUNTIME | `readiness.gates` (LIVE gate); used by execution path | `rg "from readiness.gates"` (modes.py:137,142) |
| `trading/position_sizing.py` | TEST_ONLY | tests only | `rg` |
| `trading/regime.py` | TEST_ONLY | tests only | `rg` |
| `trading/risk.py` | TEST_ONLY | tests only | `rg` |
| `trading/risk_gate.py` | LIVE_RUNTIME | `main.py` `/health` (`RiskGate`), pipeline uses `risk/gate.py` | `main.py` health handler |
| `trading/signal_state_machine.py` | ORPHANED | no consumers | `rg` → none |
| `trading/trend.py` | ORPHANED | no consumers | `rg` → none |
| `trading/volatility.py` | ORPHANED | no consumers | `rg` → none |

### 3.5 `execution/`

| Module | Class | Import path / owner | Evidence |
|---|---|---|---|
| `execution/engine.py` | LIVE_RUNTIME | `pipeline.py`, `runtime.py` | `rg "from execution.engine\|from .engine import"` |
| `execution/order_builder.py` | LIVE_RUNTIME | `pipeline.py:31,362,2345`, `runtime.py:23,710` | `OrderBuilder` used; `ExecutionRecoveryEngine` → TEST_ONLY (same file) |
| `execution/intents.py` | LIVE_RUNTIME | `main.py` durable intent store | `main.py` `from execution.intents import set_store` |
| `execution/state_machine.py` | LIVE_RUNTIME | `main.py`, `ops/readmodels.py`, `ops/trace.py`, `persistence/order_state_store.py`, `system/startup_checks.py` | `rg "execution.state_machine"` |
| `execution/reconciliation.py` | LIVE_RUNTIME | `runtime.py:24` | `rg "execution.reconciliation"` |
| `execution/reconciliation_providers.py` | LIVE_RUNTIME | `runtime.py:578` | `runtime.py:578` |
| `execution/reconciliation_runner.py` | LIVE_RUNTIME | `runtime.py:485`, `scheduler.py` | one instance |
| `execution/sltp_manager.py` | LIVE_RUNTIME | `monitoring/trade_manager.py:29`, `runtime.py:279` | `rg "sltp_manager"` |
| `execution/__init__.py` | package facade | re-exports (incl. `ExecutionRecoveryEngine`) | `execution/__init__.py:10` |

### 3.6 `risk/`

| Module | Class | Import path / owner | Evidence |
|---|---|---|---|
| `risk/gate.py` | LIVE_RUNTIME | `pipeline.py`, `runtime.py`, `certification/checks.py` | deterministic Risk Gate |
| `risk/engine.py` | LIVE_RUNTIME | `risk/gate.py:14`, `runtime.py`, `certification/checks.py` | `rg "from .engine import RiskEngine"` |
| `risk/kill_switch.py` | LIVE_RUNTIME | `main.py` (KillSwitchStateStore) | `main.py` |
| `risk/dependency_breakers.py` | LIVE_RUNTIME | `runtime.py:32,497` (ExecutionGuard) | `runtime.py:497` |
| `risk/money_management.py` | LIVE_RUNTIME | `pipeline.py`, `runtime.py`, `certification/checks.py` | `rg "money_management"` |
| `risk/base.py` | LIVE_RUNTIME | `certification/checks.py` | `rg "risk.base"` |
| `risk/multi_level_breaker.py` | API_ENDPOINT (service) | `system/v2_endpoints.py:73,75` (`get_circuit_breaker()`) | routes `/circuit-breaker*` |
| `risk/capital_allocation.py` | API_ENDPOINT (service) | `system/v2_endpoints.py:112,114` (`CapitalAllocator`) | route `/capital` |
| `risk/monitor.py` | BACKGROUND_WORKER (owner: lifespan, optional) | `main.py` `RiskMonitor`, gated `RISK_MONITOR_ENABLED` | `main.py` risk monitor block |
| `risk/intelligence.py` | LIVE_RUNTIME | `main.py:37` (`RiskLead`) | `main.py:37` |
| `risk/circuit_breaker.py` | TEST_ONLY | tests only | `rg` → tests |
| `risk/__init__.py` | package facade | re-export `RiskEngine` | `risk/__init__.py:8` |

### 3.7 `market/`

| Module | Class | Import path / owner | Evidence |
|---|---|---|---|
| `market/intelligence.py` | LIVE_RUNTIME (`MarketLead`) + **LEGACY** committee API | `main.py:26` imports `MarketLead` (used as department lead). The legacy `create_department`/`synthesize` + 5 analyst classes have **0 consumers**. | `main.py:26`; subagent grep: legacy symbols only re-exported by `market/__init__.py` |
| `market/endpoints.py` | API_ENDPOINT | mounted `main.py:796` | `main.py:25` |
| `market/news_feed.py` | LIVE_RUNTIME | `runtime.py:30` (`get_news_feed_provider`) | `runtime.py:30,522` |
| `market/news_patterns.py` | LIVE_RUNTIME | `main.py` review bridge (`get_news_pattern_memory`) | `main.py` |
| `market/symbol_spec.py` | LIVE_RUNTIME | `pipeline.py`, `position_monitor.py`, `certification/checks.py` (+ runtime `_default_symbol_spec_provider`) | `rg "market.symbol_spec"` |
| `market/multi_timeframe.py` | LIVE_RUNTIME | analysts / `market/endpoints.py` | `rg "multi_timeframe"` |
| `market/health.py` | API_ENDPOINT (service) | `market/endpoints.py:97` (`compute_market_data_health`) | `rg "from .health import"` |
| `market/news_keypoints.py` | API_ENDPOINT (service) | `market/endpoints.py:33,70` | `rg "news_keypoints"` |
| `market/sessions.py` | LIVE_RUNTIME | `feed_loop.py` session check | `feed_loop.py:158` |
| `market/__init__.py` | package facade (LEGACY re-exports) | re-exports legacy committee classes; no importer | subagent grep |
| `market` legacy committee members | LEGACY | retained for backward compat, replaced by `MarketLead` committee path | `market/intelligence.py:6-8,367,498` |

### 3.8 `monitoring/`

| Module | Class | Import path / owner | Evidence |
|---|---|---|---|
| `monitoring/position_monitor.py` | LIVE_RUNTIME | `runtime.py:253` (single) | one instance |
| `monitoring/trade_manager.py` | LIVE_RUNTIME | `runtime.py:557` | one instance |
| `monitoring/incidents.py` | TEST_ONLY | tests | `rg` |
| `monitoring/slo.py` | TEST_ONLY | tests | `rg` |

### 3.9 `learning/`

| Module | Class | Import path / owner | Evidence |
|---|---|---|---|
| `learning/engine_v2.py` | LIVE_RUNTIME | `main.py:190`, `system/endpoints.py:632` | `rg "learning.engine_v2"` |
| `learning/engine_v2_store.py` | LIVE_RUNTIME | `main.py:191`, `system/endpoints.py:633` | `rg` |
| `learning/feedback.py` | LIVE_RUNTIME | `main.py:192`, `runtime.py:737`, `market/intelligence.py:22`, `risk/intelligence.py:16` | `rg "learning.feedback"` |
| `learning/lesson_store.py` | LIVE_RUNTIME | `main.py:193` | `rg` |
| `learning/review_bridge.py` | LIVE_RUNTIME | `main.py`, `learning/research_phase5.py` | `rg` |
| `learning/review_store.py` | LIVE_RUNTIME | `ops/alerts.py`, `ops/readmodels.py`, `ops/trace.py`, `persistence/__init__.py` | `rg "learning.review_store"` |
| `learning/performance.py` | LIVE_RUNTIME | `strategy/endpoints.py:144` (`apply_performance_to_registry`) | `rg` |
| `learning/canonical.py` | LIVE_RUNTIME | `certification/checks.py:333` | `rg` |
| `learning/store_paths.py` | LIVE_RUNTIME (internal) | `engine_v2_store.py`, `lesson_store.py` | relative import |
| `learning/loop.py` | TEST_ONLY | only `learning/__init__.py` re-export + tests | subagent grep |
| `learning/pipelines.py` | TEST_ONLY | only `loop.py` + `__init__` + tests | subagent grep |
| `learning/research_phase5.py` | TEST_ONLY | tests only | subagent grep |

### 3.10 `llm/`

| Module | Class | Import path / owner | Evidence |
|---|---|---|---|
| `llm/router.py` | LIVE_RUNTIME | `llm/advisor.py:320`, `certification/checks.py:475` | `rg "llm.router\|from .router import"` |
| `llm/advisor.py` | LIVE_RUNTIME | `live_readiness/…`, endpoints path | `rg "LLMAdvisor"` |
| `llm/canonical.py` | LIVE_RUNTIME | `certification/checks.py`, `advisor.py` | `rg "llm.canonical"` |
| `llm/base.py` | LIVE_RUNTIME | `model_router.py:32`, `router.py:30` | relative import |
| `llm/errors.py` | LIVE_RUNTIME | `advisor.py:385`, `router.py:31` | relative import |
| `llm/nine_router.py` | LIVE_RUNTIME | `advisor.py:183`, `router.py:286` | relative import |
| `llm/registry.py` | LIVE_RUNTIME | `ops/readmodels.py` | `rg "llm.registry"` |
| `llm/model_router.py` | LEGACY (wrapped) | used indirectly by `llm/router.py:263` (`CanonicalModelRouter` wraps `ModelRouter as LegacyRouter`) | `router.py:263,490,491` |
| `llm/__init__.py` | package facade | re-exports | — |

### 3.11 `strategy/`, `system/`, `ops/`, `observability/`

| Module | Class | Import path / owner | Evidence |
|---|---|---|---|
| `strategy/endpoints.py` | API_ENDPOINT | mounted `main.py:793`; `register_live_strategy()` called `main.py` | `main.py:38` |
| `strategy/registry.py` | LIVE_RUNTIME | `certification/checks.py`, `ops/readmodels.py` | `rg "strategy.registry"` |
| `strategy/performance.py` | LIVE_RUNTIME | `strategy/endpoints.py`, `main.py` (backfill) | `rg "strategy.performance"` |
| `strategy/lifecycle.py` | API_ENDPOINT (service) | `system/v2_endpoints.py:175,177` (`LifecycleGovernor`) | route `/lifecycle/{id}/{version}` |
| `system/endpoints.py` | API_ENDPOINT | mounted `main.py:791` | `main.py:39` |
| `system/v2_endpoints.py` | API_ENDPOINT | mounted `main.py:792` | `main.py:40` |
| `system/settings_store.py` | LIVE_RUNTIME | `runtime.py`, `main.py` | `rg "settings_store"` |
| `system/startup_checks.py` | LIVE_RUNTIME | `main.py` lifespan, `certification/checks.py` | `main.py` startup gate |
| `system/certification.py` | LIVE_RUNTIME (service) | `system/endpoints.py:32`, `system/v2_endpoints.py:743` | `run_certification` |
| `system/gate_b_probes.py` | LIVE_RUNTIME (service) | `system/v2_endpoints.py:769` (`build_gate_b_probes()`) | `rg "gate_b_probes"` |
| `system/recovery.py` | LIVE_RUNTIME (service) | `system/v2_endpoints.py:82,276` | `rg "system.recovery"` |
| `ops/router.py` | API_ENDPOINT | mounted `main.py:799` (module-level, always) | `main.py:30` |
| `ops/readmodels.py` | LIVE_RUNTIME (read-model) | `ops/router.py`, `certification/soak.py` | `rg "ops.readmodels"` |
| `ops/alerts.py` | LIVE_RUNTIME (read-model) | `ops/router.py:132`, `ops/readmodels.py:20` | `rg "from .alerts import"` |
| `ops/trace.py` | LIVE_RUNTIME (read-model) | `ops/router.py:60` | `rg "from .trace import"` |
| `ops/secrets.py` | LIVE_RUNTIME | `certification/certification.py`, `certification/checks.py` | `rg "ops.secrets"` |
| `observability/traces.py` | LIVE_RUNTIME | `runtime.py:31` (`TraceCollector`) | `runtime.py:531` |
| `observability/sampler.py` | BACKGROUND_WORKER (owner: lifespan) | `main.py` (`get_trend_sampler().start()`) | `main.py` trend sampler |
| `observability/metrics.py` | LIVE_RUNTIME (via `observability/__init__`) | `observability/__init__.py:5` | package re-export |
| `observability/alerts.py` | LIVE_RUNTIME (via `observability/__init__`) | `observability/__init__.py:4` | package re-export |
| `observability/dashboard_v2.py` | TEST_ONLY | tests | `rg` |
| `observability/execution_quality.py` | TEST_ONLY | tests | `rg` |
| `observability/llm_telemetry.py` | ORPHANED | no production consumer | `rg "llm_telemetry"` → none in src |

### 3.12 `mt5/`, `review/`, `persistence/`, `telegram/`, `paper/`, `memory/`

| Module | Class | Import path / owner | Evidence |
|---|---|---|---|
| `mt5/connector.py` | LIVE_RUNTIME | `main.py:27`, `pipeline.py`, `position_monitor.py` | `rg "mt5.connector\|from ..mt5 import connector"` |
| `mt5/terminals.py` | LIVE_RUNTIME | `main.py` startup, execution engine | `main.py` arm-state block |
| `mt5/write_guard.py` | LIVE_RUNTIME | `mt5/connector.py:15` (`MT5WriteGuard`) | `rg "write_guard"` |
| `mt5/symbol_resolver.py` | LIVE_RUNTIME | `mt5/connector.py:314…`, `execution/engine.py` | `rg "symbol_resolver"` |
| `mt5/connection_manager.py` | LIVE_RUNTIME | `mt5/__init__.py:7` | package facade |
| `mt5/models.py` | LIVE_RUNTIME | `mt5/__init__.py:23`, `mt5/retrieval.py:14` | relative import |
| `mt5/endpoints.py` | API_ENDPOINT | mounted `main.py:786` | `main.py:28` |
| `mt5/retrieval.py` | LIVE_RUNTIME (service) | via `mt5` package | relative import |
| `mt5/_connector_base.py` | TEST_ONLY | tests | `rg` |
| `mt5/schemas.py` | ORPHANED | none | `rg` → none |
| `review/auto_trigger.py` | LIVE_RUNTIME | `main.py`, `runtime.py`, `review/…` | `rg "review.auto_trigger"` |
| `review/close_detector.py` | LIVE_RUNTIME | `runtime.py` | `rg "close_detector"` |
| `review/entry_context.py` | LIVE_RUNTIME | `main.py`, `pipeline.py`, `trade_manager.py` | `rg "review.entry_context"` |
| `review/decision_graph.py` | LIVE_RUNTIME | `runtime.py`, `ops/trace.py` | `rg "decision_graph"` |
| `review/trade_review.py` | LIVE_RUNTIME | `agents/analysts/review_agent.py` | `rg "trade_review"` |
| `review/advanced_review.py` | LIVE_RUNTIME | `agents/analysts/review_agent.py` | `rg "advanced_review"` |
| `review/intelligence.py` | LIVE_RUNTIME | `main.py:36` (`ReviewLead`) | `main.py:36` |
| `review/r_multiple.py` | LIVE_RUNTIME (via pipeline/review) | review path + tests | `rg "review.r_multiple"` |
| `review/performance_intelligence.py` | ORPHANED | no consumers | `rg` → none |
| `persistence/*` | LIVE_RUNTIME | `main.py` wires 7 stores; `persistence/__init__.py` facade | `main.py` durable-state block |
| `telegram/notifier.py` | LIVE_RUNTIME | `runtime.py` (`flush_pipeline_digest`) | `main.py` shutdown |
| `telegram/signal_lifecycle.py` | LIVE_RUNTIME | `main.py`, `runtime.py` | `main.py` price-watch |
| `telegram/poller.py` | BACKGROUND_WORKER (owner: lifespan, optional) | `main.py` (`TELEGRAM_POLLER_ENABLED`) | `main.py` poller block |
| `telegram/gateway.py` / `telegram/transport.py` / `telegram/providers.py` / `telegram/control_center.py` | LIVE_RUNTIME (service) | used by notifier/poller path | `rg "telegram\."` |
| `paper/simulated_execution.py` | TEST_ONLY | only `paper/__init__.py` re-export + tests | subagent grep |
| `paper/paper_account.py` | TEST_ONLY | tests | `rg` |
| `paper/contract_size.py` | ORPHANED | no consumers | `rg` → none |
| `memory/*` (5 modules) | TEST_ONLY (whole package) | only `memory/__init__.py` re-export + `tests/test_memory_types.py`, `test_trade_memory.py` | subagent grep |
| `testing/failure_lab.py` | TEST_ONLY | tests/e2e only | subagent grep |

### 3.13 `db/`, `demo/`, `research/`, `certification/`, `live_readiness/`, `readiness/`, `reports/`, `charting/`, `security/`

| Module | Class | Import path / owner | Evidence |
|---|---|---|---|
| `db/database.py`, `db/base.py`, `db/models/__init__.py` | ORPHANED (scaffold) | engine/session helpers exist; **no production module imports `db.database`** (only `system/certification.py:45` imports `sqlalchemy.text` directly) | `rg "from db.database\|from .database import"` → none |
| `demo/demo_trading.py` | TEST_ONLY | tests only | `rg "demo_trading"` → tests |
| `demo/stability.py` | TEST_ONLY | tests | `rg` |
| `research/endpoints.py` | API_ENDPOINT | mounted `main.py:795` | `main.py:34` |
| `research/engine.py` | LIVE_RUNTIME (service) | `research/endpoints.py:33` | `rg "research.engine"` |
| `research/store.py` | LIVE_RUNTIME (service) | `research/endpoints.py`, `engine.py`, `live_readiness/certification_evidence.py:345` | `rg "research.store"` |
| `research/backtest_v2.py` | LIVE_RUNTIME (service) | `research/endpoints.py:310`, `monte_carlo.py` | `rg "backtest_v2"` |
| `research/monte_carlo.py` | LIVE_RUNTIME (service) | `research/endpoints.py:232` | `rg "monte_carlo"` |
| `research/scheduler.py` | API_ENDPOINT (service) | `system/v2_endpoints.py:166` (`ResearchInbox`); route `/research/inbox` | `rg "research.scheduler"` |
| `research/walk_forward_v2.py` | TEST_ONLY | tests only | subagent grep |
| `certification/checks.py` | LIVE_RUNTIME (service) | `certification/__init__.py:12`; used by system certification | relative import |
| `certification/certification.py` | LIVE_RUNTIME (service) | `certification/__init__.py:3-6` | relative import |
| `certification/soak.py` | LIVE_RUNTIME (service) | `certification/__init__.py:13` | relative import |
| `live_readiness/environment.py` | LIVE_RUNTIME (service) | `system/v2_endpoints.py:93` (`EnvironmentGuard`) | `rg "live_readiness"` |
| `live_readiness/account_manager.py` | LIVE_RUNTIME (service) | `system/v2_endpoints.py:103` (`AccountManager`) | `rg` |
| `live_readiness/certification_evidence.py` | LIVE_RUNTIME (service) | `system/v2_endpoints.py:767` | `rg` |
| `live_readiness/certification_gate.py` | LIVE_RUNTIME (service) | `system/v2_endpoints.py:768` | `rg` |
| `live_readiness/base.py` / `evaluator.py` / `__init__.py` | LIVE_RUNTIME (service) | internal to the readiness path | relative import |
| `readiness/gate.py` | LIVE_RUNTIME | `certification/checks.py:304` (`LiveReadinessGate`) | `rg "readiness.gate"` |
| `readiness/gates.py` | LIVE_RUNTIME | `trading/modes.py:137,142` | `rg "readiness.gates"` |
| `reports/endpoints.py` | API_ENDPOINT | mounted `main.py:794`; `main.py` shutdown digest | `main.py:33` |
| `reports/daily.py` | LIVE_RUNTIME (service) | `reports/endpoints.py:8` | relative import |
| `charting/endpoints.py` | API_ENDPOINT | mounted `main.py:787` | `main.py:23` |
| `charting/series.py` | LIVE_RUNTIME (service) | `charting/endpoints.py:20` | relative import |
| `security/api_key.py` | LIVE_RUNTIME (middleware) | `main.py` (`ApiKeyMiddleware`) | `main.py` auth block |
| `security/audit_log.py` | LIVE_RUNTIME (via `security/__init__`) | `security/__init__.py:4` | package re-export |
| `security/tool_permissions.py` | LIVE_RUNTIME (via `security/__init__`) | `security/__init__.py:5` | package re-export |

---

## 4. Known candidates — explicit verdicts (§7 of master plan)

| Candidate | Verdict | Import path / owner | Evidence |
|---|---|---|---|
| `llm/model_router.py` | **LEGACY** (wrapped, still live) | `llm/router.py:263` wraps `ModelRouter as LegacyRouter`; router is used by advisor/checks | `rg "model_router"` → `router.py:263,490,491` |
| `learning/engine_v2.py` | **LIVE_RUNTIME** | `main.py:190,200,207`; `system/endpoints.py:632,642,645` | `rg "LearningEngineV2"` |
| `learning/*` | Mixed — see §3.9 | most LIVE_RUNTIME; `loop.py`/`pipelines.py`/`research_phase5.py` TEST_ONLY | per-file grep |
| `execution/order_builder.py` · `OrderBuilder` | **LIVE_RUNTIME** | `pipeline.py:31,362,2345`, `runtime.py:23,710` | `rg "OrderBuilder"` |
| · `ExecutionRecoveryEngine` | **TEST_ONLY** | only `execution/__init__.py:10` re-export + tests | `rg "ExecutionRecoveryEngine"` → tests + `__init__` |
| `paper/simulated_execution.py` | **TEST_ONLY** | only `paper/__init__.py:5` re-export + tests | subagent grep |
| `memory/*` | **TEST_ONLY** (entire package) | only `memory/__init__.py` re-export + 2 test files | subagent grep |
| `agents/task.py` | **ORPHANED** | `agents/__init__.py:21-22` re-export; no symbol consumed | `rg "TaskStatus\|TaskPriority"` → tests only |
| `orchestration/context_builder.py` | **DEAD_CODE** | `orchestration/__init__.py:14` re-export only; a *different* `ContextBuilder` in `llm/router.py:114` is the used one | subagent grep |
| `agents/evidence.py` | **DEAD_CODE** (shadowed) | `agents/__init__.py:18`; real evidence model is `agents/canonical.py:131` | subagent grep |
| `agents/decision_state.py` | **DEAD_CODE** (shadowed) | `agents/__init__.py:17`; real model is `agents/canonical.py:512` | subagent grep |
| `agents/permissions.py` | **LIVE_RUNTIME** | `mt5/write_guard.py:21,218` | `rg "agents.permissions"` |
| `risk/MultiLevelBreaker` | **API_ENDPOINT (service)** | `system/v2_endpoints.py:73,75` | `rg "MultiLevelBreaker"` |
| `risk/CapitalAllocator` | **API_ENDPOINT (service)** | `system/v2_endpoints.py:112,114` | `rg "CapitalAllocator"` |
| `trading/EventDeduplicator` | **LIVE_RUNTIME** | defined `trading/event_engine.py:318`; consumed by `trading/events.py:24,153` | `rg "EventDeduplicator"` |
| `research/*` | Mixed — see §3.13 | mostly LIVE_RUNTIME via `research/endpoints.py` + `v2_endpoints`; `walk_forward_v2.py` TEST_ONLY | per-file grep |
| `strategy/LifecycleGovernor` | **API_ENDPOINT (service)** | `system/v2_endpoints.py:175,177` | `rg "LifecycleGovernor"` |
| `market/intelligence` legacy committee | **LEGACY** | `MarketLead` = LIVE_RUNTIME (`main.py:26`); 5 legacy analysts + `create_department`/`synthesize` = LEGACY, 0 consumers | `market/intelligence.py:6-8,367,498`; subagent grep |

---

## 5. Orphans / dead code / legacy inventory (documented, NOT deleted)

### 5.1 ORPHANED (reachable by side-effect, no owner)

| Module | Why orphaned | Recommended action (future task) |
|---|---|---|
| `agents/task.py` | re-exported, never consumed | keep or remove after confirming no external importer |
| `agents/evidence.py` | superseded by `agents/canonical.py` evidence model | keep; delete only after confirming tests migrate |
| `agents/decision_state.py` | superseded by `agents/canonical.py` `DecisionState` | see above |
| `orchestration/context_builder.py` | superseded by `llm/router.py` `ContextBuilder` | see above |
| `db/database.py`, `db/base.py`, `db/models/__init__.py` | SQLAlchemy scaffold; no production importer | scaffold; keep |
| `trading/entry_detectors.py`, `trading/entry_lifecycle.py`, `trading/signal_state_machine.py`, `trading/trend.py`, `trading/volatility.py` | no consumer | verify vs tests before removal |
| `paper/contract_size.py` | no consumer | verify |
| `review/performance_intelligence.py` | no consumer | verify |
| `observability/llm_telemetry.py` | no consumer | verify |
| `mt5/schemas.py` | no consumer | verify |

### 5.2 DEAD_CODE

| Module | Note |
|---|---|
| `agents/evidence.py` (symbols), `agents/decision_state.py` (symbols) | shadowed duplicates of `agents/canonical.py` |
| `orchestration/context_builder.py` | shadowed duplicate of `llm/router.py::ContextBuilder` |

### 5.3 LEGACY (kept for backward compatibility; replacement is the live one)

| Module / API | Replacement |
|---|---|
| `llm/model_router.py` (`ModelRouter`) | `llm/router.py::CanonicalModelRouter` (wraps it) |
| `market/intelligence.py` legacy committee (`create_department`, `synthesize`, 5 analyst classes, `CommitteeDecision`, `AnalystReport`) | `MarketLead` committee path |

---

## 6. Runtime verification (duplicate-worker detection)

Added TASK 05 tests: `services/python/tests/test_runtime_identity.py` (14 tests).

```bash
# 1. identity unit + singleton + duplicate detection
.venv/Scripts/python.exe -m pytest tests/test_runtime_identity.py -q \
    -p no:cacheprovider -o addopts="" --basetemp=./temp_pytest_t05
#    → 14 passed

# 2. runtime wiring (app lifespan) exposes the identity over the API
.venv/Scripts/python.exe -c "...TestClient(src.main.app).get('/scheduler/status')..."
#    → 200 with identity block (see below)
```

Live API proof (`GET /scheduler/status`, authenticated, `SCHEDULER_ENABLED=true`):

```json
{
  "running": true,
  "identity": {
    "process_id": 20808,
    "host": "Billy",
    "runtime_instance_id": "runtime-20808-45a7b9ba",
    "scheduler_instance_id": "scheduler-20808-41c31e0a",
    "feed_instance_id": null,
    "queue_instance_id": "queue-20808-63c447e3",
    "supervisor_instance_id": "supervisor-20808-ffd60003",
    "pipeline_instance_id": "pipeline-20808-14bb83a4",
    "position_monitor_instance_id": "position_monitor-20808-dea94aa6",
    "reconciliation_instance_id": "reconciliation-20808-4a3565ac"
  }
}
```

Analysis log line (from the scheduler, one per qualifying event):

```text
INFO trading.scheduler Event analysis: XAUUSD BREAKOUT cause=qualifying:TRADE_TRIGGER
  decision=WAIT status=REJECTED dur=0.0ms process_id=9632
  runtime=runtime-9632-f6ff6e86 scheduler=scheduler-9632-ee4a317b feed=feed-9632-08d2c830
```

Each event-trace entry (`GET /scheduler/event-trace`) also carries
`process_id`, `runtime_instance_id`, `scheduler_instance_id`,
`feed_instance_id`.

Execution remains **DISARMED** after startup (observed in every run:
`EXECUTION IS DISARMED after startup …`).

---

## 7. STOP GATE 05 checklist

```text
[x] Every production module has a known entry path            (§1/§3 tables)
[x] Every background worker has one owner                     (§2.2: scheduler→runtime;
                                                               feed→lifespan; risk
                                                               monitor→lifespan;
                                                               poller→lifespan;
                                                               sampler→lifespan)
[x] No duplicate scheduler/feed loops                         (§2.2: 1 site each;
                                                               benign probe flagged)
[x] Orphans are documented                                    (§5.1: 11 modules)
[x] Legacy code is not accidentally imported                  (§5.3: model_router wrapped
                                                               deliberately; legacy
                                                               committee has 0 consumers)
[x] No hidden test-only component is assumed to be production  (§5 TEST_ONLY / §4:
                                                               memory/*, paper/simulated,
                                                               ExecutionRecoveryEngine,
                                                               research_phase5, …)
```

### Background workers + owners

| Worker | Owner | Gate |
|---|---|---|
| `AutonomousScheduler` | `OrchestrationRuntime` singleton | `SCHEDULER_ENABLED` |
| `MarketFeedLoop` | FastAPI lifespan | `MARKET_FEED_ENABLED` |
| `RiskMonitor` (thread) | FastAPI lifespan | `RISK_MONITOR_ENABLED` |
| Telegram inbound poller | FastAPI lifespan | `TELEGRAM_POLLER_ENABLED` + token |
| Trend sampler | FastAPI lifespan | always on (read-only) |
| Signal price watch (coro) | FastAPI lifespan | always on (read-only) |
| Reconciliation runner | driven by `AutonomousScheduler.tick()` | part of runtime |
| Position monitor | driven by `_RecordingPipelineProxy.run()` | part of runtime |
| `ResearchInbox` scheduler | `system/v2_endpoints` route (request-scoped) | on-demand |

---

## 8. Summary counts

| Class | Count (modules) |
|---|---|
| LIVE_RUNTIME (+ service/read-model) | ~110 |
| BACKGROUND_WORKER | 5 (scheduler, feed, risk-monitor, poller, sampler; reconciliation/position-monitor are runtime-driven) |
| API_ENDPOINT | 12 mounted routers + service-backed (`multi_level_breaker`, `capital_allocation`, `lifecycle`, `research.scheduler`) |
| UI_ONLY | 0 under `src` (UI lives in the Node/Next app) |
| TEST_ONLY | 14 (`memory/*` ×5, `paper/simulated_execution`, `paper/paper_account`, `ExecutionRecoveryEngine`, `learning/loop`, `learning/pipelines`, `learning/research_phase5`, `research/walk_forward_v2`, `agents/* shadow tests`, `observability/dashboard_v2`, `observability/execution_quality`, `testing/failure_lab`, `mt5/_connector_base`) |
| LEGACY | 2 (`llm/model_router`, `market/intelligence` legacy committee) |
| ORPHANED | ~13 |
| DEAD_CODE | 3 shadowed modules |

**Conclusion:** every production component has a single, traceable owner; the
only duplicate construction is a discarded certification probe; and the runtime
identity stamp now makes any future duplicate scheduler/feed/process visible in
both the analysis log and `GET /scheduler/status`.
