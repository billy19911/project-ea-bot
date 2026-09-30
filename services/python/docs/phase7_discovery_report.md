# PHASE 7 DISCOVERY REPORT — Observability, Control Plane & Operations

## Existing monitoring

| Module | Provides |
|--------|----------|
| observability/metrics.py | MetricsRegistry (counters/gauges/histograms, no-trade tracking) |
| observability/traces.py | Span/Trace/TraceCollector (distributed-trace style spans) |
| observability/alerts.py | AlertManager (threshold rules, dedup, auto-resolve; info/warning/critical) |
| observability/execution_quality.py | ExecutionQualityAnalytics (slippage/spread/latency, rejection rate) |
| observability/llm_telemetry.py | LLMTelemetryStore + ModelGovernance (per-call model/provenance) |
| observability/dashboard_v2.py | DashboardAggregator (SectionPayload sections) |
| observability/sampler.py | TrendSampler (real-sample trend history) |
| monitoring/incidents.py, slo.py | incident + SLO evaluation |
| monitoring/position_monitor.py, trade_manager.py | position lifecycle |

## Existing APIs (routers mounted in main.py)

mt5, charting, trading, events, orchestration, system, v2, strategy, reports,
research, market. Key read surfaces: /dashboard (aggregated), /decisions,
/tasks, /supervisor/status, /observability/metrics+trend, /diagnostics,
/execution-quality, /llm/telemetry+governance, /incidents, /slo, /capital,
/accounts, /certification/gate, /research/inbox, /lifecycle, /ai/models,
/ai/advisor/status, /learning/analytics, /settings (writable allowlist +
read-only risk limits).

## Existing frontend

apps/web (Next.js + Tailwind): app/, components/, lib/. apps/api (Node,
Express+Prisma): src/, test/. Control-plane pages exist under
apps/web/app/control-plane (16 pages per ARCHITECTURE_MAP).

## Data sources (source of truth per metric)

| Metric | Source |
|--------|--------|
| Decisions/cycles | OrchestrationRuntime trace store + /decisions |
| Health | /diagnostics, /environment, certification gate |
| Market | mt5 connector tick + account_context (bid/ask/spread) |
| Setups/signals | signal_registry + pipeline validation inputs |
| Risk | RiskGate thresholds + GateDecision snapshots |
| Execution | ExecutionEngine state machine + order ledger |
| Positions | MT5 positions + PositionMonitor + reconciliation |
| Models | LLMTelemetryStore + advisor model_usage + router records |
| Budget | supervisor token budget + advisor commits |
| Research | ResearchStore + CanonicalStore + ResearchQueue |
| Strategy | strategy registry + lifecycle governor |

## Major gaps (Phase 7 build list)

1. No unified `/ops/*` read-model layer (data scattered across 10+ endpoints).
2. No setup-centric decision trace assembler (setup_id → full lifecycle).
3. No non-trade explanation assembler (WAIT/REJECT with blocking/missing).
4. No alert evaluator wiring AlertManager to runtime signals (module exists,
   unwired to live thresholds).
5. No mutation-audit helper for control-plane writes.
6. No secret-masking helper for operational payloads.
7. No Phase 7 regression tests.

## Reuse plan (no duplication)

New module `src/ops/` (read models only, zero authority):
- `readmodels.py` — pure assembler functions over existing stores/connectors.
- `trace.py` — setup/trade trace assembler from decision graph + ledger + reviews.
- `alerts.py` — alert evaluator binding AlertManager to runtime signals.
- `audit.py` — mutation audit record helper.
- `secrets.py` — secret masking for payloads/logs.
- `router.py` — FastAPI `/ops/*` read endpoints (GET only, except acknowledge).
