# PHASE 8 DISCOVERY REPORT — Operational Hardening

## 1. Persistent state (durable JSONL, corruption-safe load)

order_state, intents, kill_switch, entry_context, position_reconciliation,
lessons, engine_v2, learning_canonical, research_queue, news_patterns,
research_state — all append-only JSONL + in-memory cache + JSONDecodeError
skip + locks where concurrent (order_state RLock). Startup rehydrates.

## 2. Process-local state

SignalRegistry (pending/cooldown), ZoneEntryGate._pending, DebateEngine
ephemeral, CanonicalModelRouter cycle budgets/records/cache, TrendSampler
samples, TraceCollector, MetricsRegistry, AlertManager firing/history,
LLMTelemetryStore records, ExecutionQuality records, PositionMonitor history
(bounded 100/ticket), activity deques (maxlen 20), reconciliation runner
history (bounded 50).

## 3. Restart-sensitive paths

- Pending order ledger → durable (adopt on restart via locator).
- SignalRegistry pending → process-local: after restart a PENDING signal is
  forgotten → committee re-convenes (safe: may re-analyze, cannot duplicate
  execution because the gate+idempotency still guard).
- ZoneEntryGate._pending → process-local (same reasoning: safe re-eval).
- Cycle budgets → process-local (safe: fresh budget per restart).
- SnapshotCache → process-local (safe: miss = recompute).

## 4. Critical recovery paths (all exist)

Crash-after-submit → order ledger + locator adopt. Timeout → UNKNOWN →
locator → adopt/retry. Reconciliation mismatch → BLOCK new orders.
Review hook failures swallowed. Research queue durable + isolated drain.

## 5. Existing health checks

/ops/health (per-component probes, honest DEGRADED), /diagnostics,
/environment, certification gate, SLO evaluator, provider health, trend
sampler, execution-quality monitors. Lifespan startup/shutdown with graceful
stops (trend sampler, feed, risk monitor, poller, scheduler, telegram flush,
connector shutdown).

## 6. Existing SLO/incident logic

monitoring/slo.py (SLI samples, p50/p95/p99), monitoring/incidents.py
(open/resolve/history), observability/alerts.py AlertManager (dedup,
auto-resolve).

## 7. Gaps (Phase 8 hardening targets)

1. **AlertManager._history unbounded** (append-only list; long-run growth).
   Same for LLMTelemetryStore._records, MetricsRegistry histograms, SLO
   samples, TrendSampler._samples (check bound), ExecutionQuality._records.
2. **AlertManager has no cooldown/rate-limit**: 1000 identical evaluations
   re-emit every cycle (dedup only suppresses while firing; no per-alert
   cooldown, no storm budget).
3. **Startup config validation is scattered**: settings applied best-effort at
   startup; invalid safety-critical values (non-positive lot caps, absurd
   exposure) are clamped with warnings in a few places but there is no single
   fail-early gate for the safety core.
4. **Execution recovery after restart is manual**: the ledger + locator exist,
   but no startup routine reconciles UNKNOWN/SUBMITTING intents against the
   broker automatically.

## 8. Likely race conditions

- Engine `_pending/_completed` guarded by RLock ✓; state machine store has
  no lock on the module dict (single-threaded cycle path; low risk).
- JSONL appends are per-call open/append (no cross-process lock) — acceptable
  single-process; documented.

## 9. Resource leak risks

- Unbounded histories listed in §7.1 (alerts, telemetry, metrics, SLO,
  sampler, execution-quality). PositionMonitor already bounded (100/ticket);
  trade_manager/activity use deque(maxlen).
- JSONL files grow unbounded (no rotation) — acceptable for the phase if
  bounded in-memory + documented; rotation is future work.

## 10. Safe hardening plan (minimal, no redesign)

H1. Bound AlertManager history + add per-alert cooldown/rate-limit.
H2. Bound LLMTelemetryStore + MetricsRegistry histograms + SLO samples +
    TrendSampler + ExecutionQuality with maxlen/eviction.
H3. Startup safety-config gate: single fail-early validator for lot caps,
    exposure, spread, retry bounds (clamp + warn already; add explicit
    invalid→safe-default with audit log).
H4. Startup execution-recovery routine: on boot, list ledger intents in
    UNKNOWN/SUBMITTING and mark them for reconciliation (adopt on next
    locator pass; never blind-retry).
H5. Fault-injection + restart + invariant tests (no production behavior change).
