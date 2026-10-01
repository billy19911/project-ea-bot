# OPERATIONAL UI DATA INTEGRITY — `docs/audit/UI_DATA_INTEGRITY.md`

> Repo: `billy19911/project-ea-bot` · Branch `main` · HEAD = `445d697` (TASK 01–10).
> Scope (TASK 11): audit **every operational page**, tracing
> `UI field → API endpoint → backend handler → Python source → actual data source`,
> and classify each field `REAL` / `DERIVED` / `SIMULATED` / `MOCK` / `UNAVAILABLE`.
> Master plan: `telegram/_MASTER_PLAN.md` §13 (TASK 11) + invariants #22/#23.
> Safety: all MT5 execution remains **DISARMED by default**. No default arm state changed.

---

## 0. Method + evidence

Commands used (all < 60s, no blocking servers):

```bash
# every operational page reads its data through the shared client helpers
rg -n "apiFetch\(|useApiData<|fetchJson\(" apps/web/app/<page>/page.tsx
# Node route table (proxies vs local handlers)
rg -n "app\.(get|post|put|delete)\(" apps/api/src/index.ts
# Python routers
rg -n "@router\.(get|post|put|delete)" services/python/src/**/endpoints.py
```

Two plumbing facts govern every trace:

* **Node proxy** — `apps/api/src/index.ts:180` `sendProxy()` forwards to the Python
  FastAPI service and labels the response `source: "live"`. On failure it returns
  HTTP `503 { error: "python_service_unavailable", source: "unavailable" }`. It
  **never invents numbers**.
* **Web honesty contract** — `apps/web/lib/useApiData.ts` returns `null`/`"—"` for
  missing fields (never a fake `0`), and turns a 503 into the message
  `"Python service unavailable."`.

### Classification legend

| Class | Meaning |
|---|---|
| **REAL** | real broker/service data (MT5 read-only, durable store, live in-process runtime) |
| **DERIVED** | computed from real data (indicators, aggregates, counts, labels) |
| **SIMULATED** | explicit simulation branch (must be labelled in UI) |
| **MOCK** | fabricated data with no source — **forbidden on operational pages** |
| **UNAVAILABLE** | no source; honestly shown as `—` / empty state |

### Fixes applied in this task (summary)

| # | Page | Defect found | Fix |
|---|---|---|---|
| F1 | AI Control | Activity log status hard-coded `"success"` in Python → always-green | tracker carries real per-run `error` flag; `/tasks` reports `failed`/`success` + real `counts.failed` |
| F2 | Reconciliation | UI bound to keys the payload never emitted → silently always **CLEAN** (could mask a real fail-closed) | `ReconciliationReport.to_dict()` now emits `has_critical`, `internal_count`, `broker_count`, `mismatches[]`, `checked_at`; runner stamps real run time |
| F3 | Risk Center | `risk_limits` mis-bound (`[object Object]`); circuit-breaker + capital shown as live but from **unwired** singletons | real `execution_guard` state surfaced; multi-level breaker labelled **manual / not auto-fed**; capital bound to real equity + honest `allocations_configured`; `risk_limits.limits` correctly bound |
| F4 | Performance | `hour`/`session`/`regime` dimensions **always empty** (only `symbol` was populated) | rows now carry the real `closed_at` timestamp + a session derived from it |
| F5 | Market | silent `equity = 10000.0` fallback for position sizing | no fabricated equity: `position_size` = `null` when equity unknown; `provenance.sizing_equity_bound=false` |

---

## 1. Overview — `apps/web/app/overview/page.tsx`

Endpoints: `GET /trading/overview`, `GET /decisions?limit=1`, plus the WS stream
(`apps/api/src/liveStream.ts` + `apps/web/lib/useLiveQuotes.ts`).

| UI field | API endpoint | Node handler | Python source | actual data source | class |
|---|---|---|---|---|---|
| `account.equity` / `balance` / `free_margin` / `margin_level` | `/trading/overview`, WS `account` | `index.ts:1175`, `liveStream.ts:211` | `mt5/endpoints.py get_account_balance` → `connector.get_account_info()` | MT5 `account_info()` | **REAL** (SIMULATED if terminal not attached — see §19 note) |
| `account.login` / `server` / `name` / `currency` | same | same | same | MT5 account info | **REAL** |
| `open_positions` | `/trading/overview` | `overviewMapping.js` | `mt5/endpoints.py get_positions` → `connector.get_positions()` | MT5 `positions_get()` | **REAL** |
| `recent_trades[].{id,symbol,side,volume,pnl}` | `/trading/overview`, WS `positions` | same | `connector.get_positions()` | MT5 positions | **REAL** |
| `recent_trades[].status` | same | same | literal `'OPEN'` | static label | **DERIVED** |
| `totalPnl` | client sum | `page.tsx:132` | — | sum of real pnl | **DERIVED** |
| `Last Decision` (`decision`,`symbol`) | `/decisions?limit=1` | `index.ts:1413` | `system/endpoints.py decisions` → `runtime.recent_decisions()` | in-process decision deque | **REAL** |
| `liveStatus` / `lastUpdate` | WS | `useLiveQuotes.ts` | tick/positions/account | stream state | **DERIVED** |

**Verdict:** no MOCK. Account/position values collapse to **SIMULATED** when the MT5
connector is not live (paper account `12345678`, tickets `1001/1002`); the Live
toggle reflects stream state, not data-source state. See §19 for the connector note.

---

## 2. Market — `apps/web/app/market/page.tsx`

Endpoints: `/chart/candles`, `/chart/analysis`, `/market/snapshot-status`, WS quotes.

| UI field | API endpoint | Node handler | Python source | actual data source | class |
|---|---|---|---|---|---|
| `bars[]` (OHLCV) | `/chart/candles` | `index.ts:1373` | `charting/endpoints.py get_chart_candles` → `connector.get_ohlc()` | MT5 `copy_rates_from_pos` | **REAL** (refuses `ok:false` when not live) |
| `overlays.ema_*`, `bollinger`, `panels.rsi/macd` | `/chart/candles` | same | `charting/series.py` | computed from real closes | **DERIVED** |
| `provenance.source/mode/bar_count` | `/chart/candles` | same | `charting/endpoints.py:126` | metadata literal (live path only) | **DERIVED** |
| `analysis.signal/confidence/entry/sl/tp/atr` | `/chart/analysis` | `index.ts:1385` | `charting/endpoints.py get_chart_analysis` → `TradingEngine.analyze` | engine over real bars | **DERIVED** |
| `analysis.position_size` | `/chart/analysis` | same | engine sizing | real equity (⚠ F5 fixed: `null` when equity unknown) | **DERIVED** |
| `analysis.provenance.*` | `/chart/analysis` | same | strategy config | config + `sizing_equity_bound` | **REAL** |
| `positions[]` | `/chart/analysis` | same | `connector.get_positions()` | MT5 positions | **REAL** |
| `freshness.*` chip | `/market/snapshot-status` | `index.ts:1081` | `market/endpoints.py` → `trading/market_freshness.py` | cached snapshot | **REAL** / `NO_DATA` honest |
| `livePrice` / bid/ask | WS | `liveStream.ts:181` | `connector.get_tick` | MT5 tick | **REAL** |

**Verdict:** no MOCK. F5 removed the only silent fabrication (`10000.0` sizing
equity). The chart refuses to draw when the terminal is not live.

---

## 3. Orders — `apps/web/app/orders/page.tsx`

Endpoint: `GET /orders` → `index.ts:1199` → `mt5/endpoints.py get_orders` →
`connector.get_orders()`.

| UI field | class |
|---|---|
| `ticket` | **REAL** (MT5 `orders_get()`) |
| `time_setup` / `symbol` / `price` / `quantity` / `filled_qty` | **REAL** |
| `side` | **DERIVED** (`o.type` int → BUY/SELL) |
| `order_type` / `status` | **REAL** (raw enum as string) |

**Verdict:** clean. Non-live returns `[]` (honest empty state), never fabricated rows.

---

## 4. Positions — `apps/web/app/positions/page.tsx`

Endpoints: `GET /positions` → `index.ts:1193` → `mt5/endpoints.py get_positions`;
`GET /mt5/mode` → `connector.is_live_mode()`.

| UI field | class |
|---|---|
| `ticket` / `time` / `symbol` / `quantity` / `price_open` / `price_current` / `profit` | **REAL** |
| `side` (from type) / `status` (literal `"OPEN"`) | **DERIVED** |
| `sl` / `tp` (`>0` else null) | **REAL** (honest null) |
| `mode` (LIVE/PAPER) | **REAL** |

**Verdict:** clean. This is the only page that reads `/mt5/mode` and discloses
"Sesi paper / simulasi" — correct.

---

## 5. Trade History — `apps/web/app/trade-history/page.tsx`

Endpoint: `GET /positions` (same as §4) → open MT5 positions only.

| UI field | class |
|---|---|
| `ticket`/`time`/`symbol`/`side`/`quantity`/`price_open`/`price_current`/`profit`/`status` | **REAL** (open positions) |

**Verdict:** no MOCK, but a **label-vs-data mismatch (documented finding)**: the page
is titled "Posisi & Transaksi" / "riwayat" and its empty state says *"Trade tertutup
muncul di sini"*, yet it binds to `/positions` (currently **open** positions). No
closed-deal source (`mt5.history_deals_get`) is wired here. The data is honest, the
copy is misleading. Left as-is (documented) — see §20 REMAINING ISSUES.

---

## 6. Decisions — `apps/web/app/decisions/page.tsx`

Endpoint: `GET /decisions` → `index.ts:1413` → `system/endpoints.py decisions` →
`runtime.recent_decisions()` → in-process `_decisions` deque from `PipelineResult.to_dict()`.

| UI field | class |
|---|---|
| `count` / `status` / `decision_id` / `event_type` / `symbol` / `decision` | **REAL** |
| `risk_approved` / `risk_reason` / `confidence` / `executed` | **REAL** |
| counts (Executed/Blocked/No-trade) | **DERIVED** |

**Verdict:** clean; honest empty state.

---

## 7. Decision Replay — `apps/web/app/decision-replay/page.tsx`

Endpoints: `/decisions` (list) and `/v2/decision/:id/replay` → `index.ts:1046` →
`system/v2_endpoints.py get_decision_store().replay()` → `review/decision_graph.py`.

| UI field | class |
|---|---|
| `replayValue.decision_id` / `event_id` / `strategy_version` / `created_at` | **REAL** (graph store) |
| `replayValue.steps[]` (stage/payload/timestamp) | **REAL** |
| `replay.status` | **REAL** (constant `"OK"`) — missing snapshot → honest `NO_DATA` |

**Verdict:** clean. `trade_id`/`execution_id` are typed but never emitted; missing
snapshot shows an honest empty state.

---

## 8. Risk Center — `apps/web/app/risk-center/page.tsx`

Endpoints: `/v2/circuit-breaker`, `/v2/capital`, `/settings`.

| UI field | API endpoint | Node handler | Python source | actual data source | class |
|---|---|---|---|---|---|
| Execution enforcement (guard) | `/v2/circuit-breaker` | `index.ts:967` | `v2_endpoints._execution_guard_snapshot()` → `runtime.execution_guard.snapshot()` | real kill switch + per-dependency breakers (**fed by `record_execution_result`**) | **REAL** (F3) |
| Multi-level breaker `level`/`is_triggered`/`reason` | `/v2/circuit-breaker` | `index.ts:967` | `v2_endpoints.get_circuit_breaker()` | `MultiLevelBreaker` singleton **not auto-fed** | **SIMULATED → labelled "manual / not auto-fed"** (F3) |
| Total capital / Allocated / Utilization | `/v2/capital` | `index.ts:991` | `v2_endpoints._capital_snapshot()` | real MT5 equity (read-only) + real allocator exposure | **REAL / DERIVED** (F3) |
| `risk_limits` table | `/settings` | `index.ts:930` | `system/endpoints._risk_limits_snapshot()` → live `RiskGate` thresholds | real `RiskEngine._thresholds` + gate spread/RR | **REAL** (F3) |

**Root cause F3:** the UI bound `risk_limits` as a flat `Record<string,number>` but
the payload is `{available, limits}`; the circuit-breaker/capital cards read
unwired singletons while claiming `source:"live"`. Fixed by surfacing the real
`execution_guard`, labelling the manual breaker, binding the real capital keys and
`risk_limits.limits`.

**Verdict after fix:** no silent MOCK; the manual breaker is explicitly labelled.

---

## 9. Execution — `apps/web/app/execution/page.tsx`

Endpoints: `/v2/execution-quality`, `/decisions`.

| UI field | class |
|---|---|
| `metrics.{average_slippage,p95_slippage,fill_delay,rejection_rate,partial_fill_rate}` | **REAL** (engine-fed `ExecutionQualityAnalytics`) |
| `count` ("Recorded executions") | **REAL** |
| `alerts[]` | **DERIVED** |
| executed rows (`decision_id`/`symbol`/`decision`/`confidence`/`order_id`/`message`) | **REAL** |

**Verdict:** clean. Zero-metric guard (`hasRecords`) correctly shows `—`, not `0`.

---

## 10. AI Control — `apps/web/app/ai-control/page.tsx`

Endpoints: `/ai-control/status` (custom Node handler `index.ts:399-715`),
`/ai/advisor/status`, `/ai-control/reasoning`, `/mt5/market/tick`, `/ai/advisor/advise`.

| UI field | API endpoint | Node handler | Python source | actual data source | class |
|---|---|---|---|---|---|
| `source` badge / `trace_id` | `/ai-control/status` | `index.ts:230,405` | — | Node probe outcome | **DERIVED / REAL** |
| `subsystems[]` tiles | `/ai-control/status` | `index.ts:632` | `/health`, `/ai/advisor/status`, `/supervisor/status` | probe outcomes | **DERIVED** |
| `supervisor.{status,routing_policy,max_concurrency,token_budget,token_used,uptime}` | `/ai-control/status` | `supervisorStatus.js` | `/scheduler/status`, `/supervisor/status`, `/health` | live supervisor instance | **REAL/DERIVED** |
| `models[]` (calls/tokens/cost) | `/ai-control/status` | `supervisorStatus.js:102` | advisor `_model_usage` | real gateway usage only | **REAL** (`—` when no calls) |
| `agents[]` metrics + `lastError` taxonomy | `/ai-control/status` | `index.ts:470-618` | `/health` + `agents/activity.py` | `AgentActivityTracker` | **REAL/DERIVED** |
| **`activity[].status`** (log) | `/ai-control/status` | `index.ts:375-396` | `/tasks` `system/endpoints.py` | tracker `recent[].error` | **REAL** (F1 — was hard-coded `"success"`) |
| `activity[].action` | same | `index.ts:390` | `/tasks` synthesizes text from real signal/conf | tracker | **DERIVED** |
| `activity[].duration` | same | `index.ts:392` | never emitted | — | **UNAVAILABLE** (`—`) |
| `errors[]` classified | `/ai-control/status` | `index.ts:527` | activity `last_error` + `errorTaxonomy.ts` | real | **DERIVED** |
| advisor status/output | `/ai/advisor/status`, `/ai/advisor/advise` | `index.ts:1311,1315` | `ai/advisor.py` | real gateway | **REAL** |

**Root cause F1:** `/tasks` hard-coded `"status": "success"` and `counts.failed: 0`,
so the activity log rendered an always-green success badge. Fixed: the tracker now
stores the real `error` flag per run and `/tasks` reports `failed`/`success` with a
real `failed` count.

**Verdict after fix:** no silent MOCK on the rendered fields.

---

## 11. Agents — `apps/web/app/agents/page.tsx`

Endpoints: `/decisions?limit=20`, `/ai-control/status`, `/learning/analytics`.

| UI field | class |
|---|---|
| Total siklus / Siklus terakhir / Agent aktif / Sumber data (`data_source`) | **REAL / DERIVED** |
| Supervisor bubble narrative | **DERIVED** (built in browser from real symbol/event) |
| Agent bubbles (`name`/`signal`/`confidence`/`reasoning`/`evidence`) | **REAL** (`agent_results` from pipeline) |
| Synthesis (decision/status/levels/risk_reason/ticket/trace_id) | **REAL** |
| Consensus bull/bear/neutral | **DERIVED** (browser count of real signals) |
| Sidebar Anggota (`invocations`/`avgConfidence`/`lastActive`/`type`) | **REAL** |
| Sidebar Pelajaran (`outcome`/`symbol`/`text`) | **REAL** (lesson store; volatile — see §19) |

**Verdict:** clean. `SIMULATED` market data is explicitly labelled via `data_source`.

---

## 12. Performance — `apps/web/app/performance/page.tsx`

Endpoints: `/v2/performance-intelligence?dimension=…`, `/v2/r-performance?period=…`.

| UI field | API endpoint | Node handler | Python source | actual data source | class |
|---|---|---|---|---|---|
| `trade_count` | `/v2/performance-intelligence` | `index.ts:1051` | `v2_endpoints._closed_trade_rows()` | auto-review history (`ReviewRecord`) | **REAL** (process-scoped) |
| bucket `name`/`size`/`win_rate`/`avg_pnl` | same | same | `review/performance_intelligence.py` | grouped real closed trades | **DERIVED** (⚠ F4 fixed: hour/session now bucket real `closed_at`) |
| `overall.avg_r` / `total_r` / `count` | `/v2/r-performance` | `index.ts:1062` | `v2_endpoints._closed_trade_r_rows()` | durable `logs/reviews.jsonl` (rehydrated) | **REAL (durable)** |
| R rows (`key`/`count`/`win_rate`/`avg_r`/`total_r`/`profit_factor`) | same | same | `review/r_multiple.py` | R from ORIGINAL SL vs real close | **REAL/DERIVED** |
| `reviews_total` / `r_unavailable` | same | same | `_total_review_count` | durable-preferred | **REAL / DERIVED** |

**Root cause F4:** `_closed_trade_rows` only populated `pnl`, `r_multiple`, `symbol`,
so the UI's selectable dimensions (`hour`/`session`/`regime`) always produced zero
buckets. Fixed: rows now carry the real close timestamp (enabling `hour`/`weekday`)
and a session derived from it (`session`). `regime` remains honestly empty (no
regime attribute is recorded on reviews).

**Verdict after fix:** hour/session are REAL/DERIVED; r-performance is durable.

---

## 13. Learning — `apps/web/app/learning/page.tsx`

Endpoint: `/learning/analytics` → `index.ts:1593` → `system/endpoints.py learning_analytics`
→ `get_lesson_store().all_lessons()` (append-only JSONL).

| UI field | class |
|---|---|
| `total` / `available` / `source` | **REAL** |
| `by_outcome.{win,loss}` | **DERIVED** |
| lesson rows (`id`/`category`/`outcome`/`symbol`/`text`) | **REAL** |
| `by_hour` / `by_regime` / `supervisor_kpis` | **UNAVAILABLE** (honest empty) |

**Verdict:** clean; empty store honestly reports `available:false`.

---

## 14. Accounts — `apps/web/app/accounts/page.tsx`

Endpoint: `/v2/accounts` → `index.ts:987` → `system/v2_endpoints.py accounts_state()`.

| UI field | class |
|---|---|
| Attached account (`login`/`server`/`trade_mode`/`currency`/`leverage`/`execution_armed`/`terminal_id`) | **REAL** (MT5 read-only; `available:false` when not live) |
| Registry table (`brokers[]`/`accounts[]`) | **UNAVAILABLE** — `AccountManager` is an in-process registry that is **never populated** (no writer calls `add_broker`/`add_account`) |
| `unavailable` reason | **REAL** (honest) |

**Verdict:** no MOCK — the table is empty-by-construction and shows an honest empty
state. Documented finding (§20): the multi-account registry can never populate.

---

## 15. Certification — `apps/web/app/certification/page.tsx`

Endpoint: `/v2/certification/gate` → `index.ts:1032` →
`system/v2_endpoints.py certification_gate()` → `certification_evidence.py` +
`certification_gate.py` (pure deterministic function; unknown stays `None`).

| UI field | class |
|---|---|
| `status` pill | **DERIVED** (pure function over checks) |
| Gate A checks (python_tests/node_tests/build/lint/security) | **REAL-IF-PRESENT** (CI artifact files; else honest `None`) |
| Gate B checks (risk_gate/kill_switch/circuit_breaker/dup/spec/reconciliation/recovery) | **REAL** (live runtime probes) |
| Gate C checks (research) | **REAL** (durable `research_state.jsonl`) |
| Gate D checks (drills) | **REAL-IF-PRESENT** (`logs/ops_drills.jsonl`) |
| Gate E `execution_quality` / `no_critical_incident` | **REAL (process-scoped)** |
| `failed[]` / `reasons[]` | **DERIVED** |

**Verdict:** clean. Subtitle "Deterministic checklist — no LLM opinion" is accurate.

---

## 16. Observability — `apps/web/app/observability/page.tsx`

Endpoints: `/observability/metrics`, `/ai-control/status`, `/observability/errors`,
`/observability/trend`.

| UI field | API endpoint | Node handler | Python source | actual data source | class |
|---|---|---|---|---|---|
| Uptime / Total Requests / Error Requests | `/observability/metrics` | `index.ts:293` → `metrics.ts` | — | Node prom-client counters | **REAL/DERIVED** |
| Active Agents / Total Tokens / LLM Cost | `/ai-control/status` | `supervisorStatus.js` | advisor `_model_usage` | real gateway usage | **REAL/DERIVED** |
| Distribusi Request table | `/observability/metrics` | `metrics.ts:232` | — | Node prom-client | **REAL** |
| Tren Nyata (equity/balance/events/blocked) | `/observability/trend` | `index.ts:320` | `observability/sampler.py` | real sampler ring-buffer (gaps honest) | **REAL** |
| Error Terbaru table | `/observability/errors` | `index.ts:327` | — | Node in-memory error store | **REAL** (volatile) |
| Agent Errors (from supervisor) | `/ai-control/status` | `index.ts:531` | activity `last_error` | real | **DERIVED** |
| Agent detail / token tables | `/ai-control/status` | `supervisorStatus.js` | `/health`, advisor usage | real | **REAL** |

**Verdict:** clean. Note (documented): Node `metrics.ts` exposes `tokenUsage`/
`agentStats` prom counters that are **never incremented**; the page does not render
them (tokens come from `/ai-control/status`), so no MOCK reaches the UI. Latent
risk flagged in §20.

---

## 17. Reconciliation — `apps/web/app/reconciliation/page.tsx`

Endpoint: `/reconciliation/status` → `index.ts:362` →
`orchestration/endpoints.py reconciliation_status()` → `runtime.last_reconciliation()`.

| UI field | API endpoint | Node handler | Python source | actual data source | class |
|---|---|---|---|---|---|
| Status CRITICAL/CLEAN | `/reconciliation/status` | `index.ts:362` | `reconciliation_status()` → `report.has_critical()` / `critical` | MT5-vs-ledger comparison | **REAL** (F2) |
| Internal / Broker positions count | same | same | `internal_count` / `broker_count` | real counts derived from report | **DERIVED/REAL** (F2) |
| Mismatches count + table | same | same | `mismatches[]` (`kind`/`symbol`/`ticket`/`detail`) | real field/position mismatches | **REAL** (F2) |
| Checked at | same | same | `checked_at` (runner stamps run time) | real run time | **REAL** (F2) |
| `history_count` | same | same | `orchestration/endpoints.py` | real bounded history | **REAL** |

**Root cause F2 (highest severity):** the UI bound to `has_critical`, `internal_count`,
`broker_count`, `mismatches`, `checked_at`, but `ReconciliationReport.to_dict()`
emitted only `critical`, `missing_in_broker/internal`, `matched`, etc. The page
therefore **silently always rendered "CLEAN / 0 mismatches"** — a false-negative
that could hide a real `ReconciliationGuard` fail-closed condition. Fixed by emitting
the real keys (and a flattened `mismatches[]`), so the page now reflects the true
state.

**Verdict after fix:** no silent false-negative; status is REAL.

---

## 18. Cross-page data-source notes (honesty items)

1. **MT5 dual-mode connector (`services/python/src/mt5/connector.py`).** When the
   terminal is not attached (`is_live_mode() == False`) `get_account_info`,
   `get_positions`, `get_tick`, `get_ohlc` return **synthetic** values (paper account
   `12345678`, tickets `1001/1002`). The mode IS surfaced via `/mt5/mode`, but not
   per-record. Pages that read `/positions` etc. without checking `/mt5/mode`
   (Overview, Trade History) can therefore render synthetic rows as if real. The
   Market page and the chart endpoints refuse to draw when not live. This is a
   **disclosed** simulation (documented here) — not silent on the API side
   (`/mt5/mode` is real) — but Overview/Trade-History do not surface it. Documented
   in §20.
2. **Risk Center manual breaker.** `MultiLevelBreaker` is a real object but is only
   mutated by the manual `POST /v2/circuit-breaker/trigger|recover` endpoints; the
   pipeline never feeds it. The page now labels it "manual / not auto-fed" and shows
   the real `execution_guard` for the true enforcement state.
3. **Node `metrics.ts` latent counters.** `llmTokensTotal`, `agentExecutionDuration`,
   etc. are exported but never incremented. The Observability page sources
   token/agent data elsewhere, so no MOCK reaches the UI today. Flagged as latent.

---

## 19. MOCK sweep

`rg` over `apps/web/app/**/*.tsx` for `MOCK|mock|fake|dummy|hardcode|Math.random|
placeholder data` returns **no fabricated data** in the 18 operational pages (the two
hits are comments in the non-operational `control-plane` page). All 18 pages render
`null`/`"—"`/empty states for missing data — verified in §1–§17.

The only fabricated-value code paths found were **inputs**, not rendered rows:
* `charting/endpoints.py equity = 10000.0` (F5 — removed),
* `/tasks status:"success"` (F1 — removed),
* `MultiLevelBreaker` singleton shown as live (F3 — relabelled).

No operational page silently shows MOCK data after the fixes above.

---

## 20. REMAINING ISSUES (documented, not fixed)

| # | Page / area | Finding | Severity | Rationale for not fixing here |
|---|---|---|---|---|
| R1 | Trade History | Page labelled "history / closed trades" but binds to `/positions` (**open** positions). The data is honest; the copy is misleading. | Low (copy) | Fixing requires wiring `mt5.history_deals_get` (a data feature) — out of TASK 11 scope; would change trading-side read paths. |
| R2 | Accounts | Multi-account registry (`AccountManager`) is **never populated** (no writer). Table is empty-by-construction. | Low | Honest empty state; wiring a registry is a feature, not an integrity fix. |
| R3 | Overview / Trade History | MT5 synthetic (SIMULATED) account/positions not per-record labelled; only `/positions` page checks `/mt5/mode`. | Medium | Simulation is disclosed at the API (`/mt5/mode`); a full per-record `data_source` flag is a broader change. |
| R4 | Observability | Node `metrics.ts` token/agent prom counters are never incremented (latent zeros). UI does not render them. | Low | Unused today; flagged to avoid a future silent-zero consumer. |
| R5 | Performance | `regime` dimension remains honestly empty (no regime attribute on reviews). | Low | No real source; correctly shows empty rather than fabricating buckets. |

---

*Generated as part of TASK 11 (Master Plan §13). All MT5 execution remains DISARMED
by default; no default arm state was changed.*
