# PRD V2 — AI Autonomous Multi-Agent Trading & Research Platform
## Production Hardening, Robust Research & Governed Autonomous Learning Upgrade

**Version:** 2.0  
**Status:** Proposed / Implementation Roadmap  
**Baseline:** PRD V1 + current repository implementation  
**Primary Platform:** MetaTrader 5 (MT5)  
**Primary Instruments:** XAUUSD / XAUUSDC  
**Architecture:** Event-Driven Multi-Agent + Deterministic Trading Engine  
**LLM Gateway:** 9Router  
**Execution:** MT5  
**Web UI:** React + Next.js  
**Backend:** Node.js / TypeScript  
**AI Runtime:** Python  
**Development Executor:** OpenCode  

---

# 1. PRODUCT INTENT

Project ini harus berkembang dari:

```text
AI Trading Platform
```

menjadi:

```text
AUTONOMOUS TRADING OPERATING SYSTEM
```

dengan kemampuan:

```text
OBSERVE
  ↓
VALIDATE DATA
  ↓
UNDERSTAND
  ↓
ANALYZE
  ↓
DELIBERATE
  ↓
RISK CHECK
  ↓
EXECUTE
  ↓
VERIFY BROKER STATE
  ↓
MONITOR
  ↓
RECONCILE
  ↓
REVIEW
  ↓
LEARN
  ↓
RESEARCH
  ↓
VALIDATE
  ↓
PROMOTE / REJECT STRATEGY
  ↓
OBSERVE AGAIN
```

Tujuan V2 bukan menambah jumlah AI agent sebanyak mungkin.

Tujuan V2 adalah membuat sistem:

1. aman terhadap kegagalan software;
2. aman terhadap kegagalan data;
3. aman terhadap kegagalan MT5/broker;
4. dapat memulihkan state setelah crash/restart;
5. dapat membuktikan keputusan trading melalui audit trail;
6. dapat menguji strategi secara robust;
7. dapat belajar dari trade tanpa bebas mengubah live strategy;
8. dapat membedakan data nyata dengan data yang tidak tersedia;
9. dapat berjalan autonomous dengan intervensi manusia hanya pada control-plane tertentu;
10. siap masuk demo dan live secara bertahap.

> **Prinsip utama tetap: AI decides within boundaries. Code enforces boundaries.**

---

# 2. BASELINE REPOSITORY

PRD V1 sudah mendefinisikan event-driven architecture, Supervisor, specialist agents, deterministic risk engine, money management, Risk Gate, Execution Engine, Position Monitor, research loop, token budget, dashboard, security, dan production checklist.

Repository saat ini juga telah mengalami beberapa implementasi penting, antara lain:

- wiring specialist agents;
- multi-terminal MT5 detection/selection/arm-disarm;
- backend-connected settings;
- observability trend;
- reconciliation status di control plane;
- learning feedback loop berbasis persistent lessons;
- live/read-only MT5 data path;
- test suite Python dan frontend verification.

Namun fitur-fitur tersebut perlu dipandang sebagai **foundation**, bukan otomatis sebagai bukti bahwa sistem siap live penuh.

### Aturan baseline

OpenCode wajib memeriksa implementasi existing sebelum membuat module baru.

Tidak boleh membuat:

```text
reconciliation_v2.py
```

jika reconciliation existing masih dapat diperluas.

Tidak boleh membuat:

```text
new_risk_engine/
```

jika Risk Engine existing memenuhi contract dan hanya membutuhkan tambahan gate.

Preferensi:

```text
EXISTING MODULE
     ↓
EXTEND
     ↓
TEST
     ↓
VERIFY
```

bukan:

```text
EXISTING MODULE
     ↓
IGNORE
     ↓
DUPLICATE IMPLEMENTATION
```

---

# 3. V2 ARCHITECTURE TARGET

```text
                         ┌───────────────────────┐
                         │ WEB / TELEGRAM / CLI  │
                         │      CONTROL PLANE    │
                         └───────────┬───────────┘
                                     │
                             API / EVENT BUS
                                     │
                         ┌───────────▼───────────┐
                         │       SUPERVISOR       │
                         │     ORCHESTRATOR AI    │
                         └───────────┬───────────┘
                                     │
        ┌────────────────────────────┼─────────────────────────────┐
        │                            │                             │
        ▼                            ▼                             ▼
 MARKET INTELLIGENCE           RISK INTELLIGENCE            RESEARCH INTELLIGENCE
        │                            │                             │
 ┌──────┼─────────┐            ┌─────┼─────────┐           ┌───────┼────────┐
 │      │         │            │     │         │           │       │        │
Tech  Structure Momentum      Account Position Portfolio  Review  Backtest Experiment
 │      │         │            │     │         │           │       │        │
 Volatility / News            Drawdown / Exposure          WFA / MC / Sensitivity
        │                            │                             │
        └────────────────────────────┼─────────────────────────────┘
                                     ▼
                              DECISION STATE
                                     │
                           ┌─────────▼─────────┐
                           │  DETERMINISTIC    │
                           │    RISK GATE      │
                           └─────────┬─────────┘
                                     │
                             APPROVED PROPOSAL
                                     │
                           ┌─────────▼─────────┐
                           │ EXECUTION ENGINE   │
                           │ + IDEMPOTENCY      │
                           │ + BROKER REALITY   │
                           └─────────┬─────────┘
                                     │
                                    MT5
                                     │
                  ┌──────────────────┼──────────────────┐
                  ▼                  ▼                  ▼
             POSITION STATE      ORDER STATE      ACCOUNT STATE
                  │                  │                  │
                  └──────────────────┼──────────────────┘
                                     ▼
                            RECONCILIATION ENGINE
                                     │
                      ┌──────────────┼──────────────┐
                      ▼              ▼              ▼
                   MATCH         REPAIRABLE       CRITICAL
                      │              │              │
                      ▼              ▼              ▼
                  NORMAL        AUTO-RECOVER     HALT / ALERT
                                     │
                                     ▼
                             TRADE REVIEW ENGINE
                                     │
                                     ▼
                            LEARNING / MEMORY
                                     │
                                     ▼
                             RESEARCH ENGINE
                                     │
                      ┌──────────────┼──────────────┐
                      ▼              ▼              ▼
                  BACKTEST       WALK-FORWARD    MONTE CARLO
                      │              │              │
                      └──────────────┼──────────────┘
                                     ▼
                           STRATEGY VALIDATION
                                     │
                         ┌───────────┴───────────┐
                         ▼                       ▼
                    CANDIDATE                 REJECTED
                         │
                         ▼
                    PAPER / DEMO
                         │
                         ▼
                    PRODUCTION
```

---

# 4. NEW V2 DESIGN PRINCIPLES

## 4.1 No unsafe autonomous escalation

AI boleh:

- membuat hypothesis;
- meminta analisis;
- mengusulkan setup;
- membuat experiment;
- menjelaskan hasil;
- mengusulkan strategy candidate.

AI tidak boleh langsung:

- mengubah hard risk limits;
- mengubah production strategy;
- mengubah max drawdown;
- bypass Risk Gate;
- mengirim order tanpa deterministic validation;
- mempromosikan model/strategy ke production.

---

## 4.2 No fabricated data

Semua subsystem wajib menggunakan state:

```text
AVAILABLE
UNAVAILABLE
STALE
DEGRADED
ERROR
```

Jangan mengganti data yang tidak tersedia dengan:

```text
0
false
normal
healthy
—
```

tanpa status yang menjelaskan bahwa data unavailable.

---

## 4.3 Broker truth > internal state

Untuk posisi/order live:

```text
MT5 / BROKER STATE
        >
INTERNAL CACHE
        >
AI MEMORY
```

Database internal tidak boleh dianggap sebagai sumber kebenaran tertinggi untuk state broker.

---

## 4.4 Research truth > narrative

AI tidak boleh menyatakan strategy membaik hanya berdasarkan reasoning.

Strategy improvement harus dibuktikan dengan:

```text
BACKTEST
→ WALK FORWARD
→ ROBUSTNESS
→ PAPER
→ DEMO
→ PRODUCTION CANDIDATE
```

---

# 5. PHASE 31 — PRODUCTION BASELINE & GAP CERTIFICATION

## Tujuan

Membuat audit otomatis yang menjawab:

> "Apa yang benar-benar sudah berjalan sekarang?"

## Requirement

Buat:

```text
system/certification/
```

dengan checks:

```text
database
python service
node service
web service
MT5 connector
market feed
agent registry
supervisor
risk engine
risk gate
execution
reconciliation
learning
telegram
observability
```

Setiap check menghasilkan:

```json
{
  "component": "risk_gate",
  "status": "PASS",
  "version": "1.2.0",
  "verified_at": "...",
  "details": []
}
```

Status:

```text
PASS
WARN
FAIL
NOT_CONFIGURED
NOT_AVAILABLE
```

## Acceptance Criteria

- startup menampilkan readiness report;
- dashboard memiliki `System Readiness`;
- tidak ada komponen yang dilabeli READY jika test gagal;
- report dapat disimpan sebagai artifact;
- CI dapat menjalankan certification mode tanpa MT5 live menggunakan mocks.

---

# 6. PHASE 32 — MARKET DATA HEALTH & STALE PROTECTION

## Tujuan

Mencegah keputusan berdasarkan market data lama/rusak.

## Data health object

```json
{
  "symbol": "XAUUSD",
  "tick_age_ms": 320,
  "bar_age_ms": 1200,
  "spread_age_ms": 320,
  "feed_connected": true,
  "last_successful_update": "...",
  "status": "HEALTHY"
}
```

## State

```text
HEALTHY
DEGRADED
STALE
DISCONNECTED
INVALID
```

## Gate rules

```text
STALE
→ NO NEW TRADE

DISCONNECTED
→ NO NEW TRADE

INVALID PRICE
→ NO NEW TRADE

ABNORMAL SPREAD
→ NO NEW TRADE / REDUCE SIZE
```

Existing positions tetap dimonitor.

## Acceptance Criteria

- data stale dapat disimulasikan;
- Risk Gate otomatis reject entry;
- Telegram/dashboard menunjukkan penyebab;
- sistem recover otomatis setelah feed normal;
- tidak ada fallback diam-diam ke data lama.

---

# 7. PHASE 33 — BROKER REALITY / SYMBOL SPECIFICATION LAYER

## Tujuan

Memastikan semua perhitungan benar terhadap karakteristik broker.

## Required symbol metadata

```text
symbol
digits
point
tick_size
tick_value
contract_size
volume_min
volume_max
volume_step
stops_level
freeze_level
filling_mode
trade_mode
margin_mode
currency
swap_long
swap_short
spread
```

## Normalized SymbolSpec

```json
{
  "symbol": "XAUUSD",
  "contract_size": 100,
  "volume_min": 0.01,
  "volume_step": 0.01,
  "tick_size": 0.01,
  "tick_value": 1.0,
  "stops_level": 0,
  "freeze_level": 0,
  "currency": "USD"
}
```

Semua broker-specific values harus masuk ke `SymbolSpec`.

Risk Engine tidak boleh hardcode asumsi broker.

## Acceptance Criteria

- lot sizing menggunakan SymbolSpec;
- SL/TP distance divalidasi terhadap stops level;
- unsupported filling mode ditolak;
- tests mencakup minimal dua variasi symbol specification;
- perhitungan `risk_amount` dapat direproduksi.

---

# 8. PHASE 34 — DURABLE EXECUTION LIFECYCLE

## Tujuan

Mencegah duplicate, lost order, dan state ambiguity.

## Order state machine

```text
INTENT_CREATED
      ↓
RISK_APPROVED
      ↓
SUBMITTING
      ↓
SUBMITTED
      ↓
ACKNOWLEDGED
      ↓
PARTIALLY_FILLED
      ↓
FILLED
      ↓
POSITION_CONFIRMED
      ↓
CLOSED
```

Failure branches:

```text
SUBMITTING → TIMEOUT
SUBMITTED → REJECTED
SUBMITTED → UNKNOWN
PARTIALLY_FILLED → PARTIAL_REMAINDER
```

## Idempotency

Setiap order intent memiliki:

```text
intent_id
decision_id
strategy_version
symbol
direction
created_at
```

`intent_id` tidak boleh digunakan untuk dua execution yang berbeda.

## Unknown execution

Jika result MT5 tidak jelas:

```text
UNKNOWN
   ↓
DO NOT RETRY BLINDLY
   ↓
QUERY BROKER
   ↓
RECONCILE
```

## Acceptance Criteria

- duplicate intent menghasilkan maksimal satu broker action;
- timeout tidak otomatis menghasilkan duplicate order;
- partial fill tercatat;
- rejected order tidak dianggap posisi;
- broker query dapat menyelesaikan UNKNOWN state.

---

# 9. PHASE 35 — RECONCILIATION 2.0

## Existing capability

Repository sudah memiliki reconciliation status dan UI yang menampilkan mismatch/critical state.

V2 memperluasnya menjadi continuous reconciliation.

## Compare

```text
MT5
├── positions
├── orders
├── deals
├── account
└── symbol state

        vs

INTERNAL SYSTEM
├── positions
├── orders
├── trades
├── account snapshot
└── execution state
```

## Mismatch types

```text
MISSING_INTERNAL_POSITION
MISSING_BROKER_POSITION
VOLUME_MISMATCH
PRICE_MISMATCH
SL_MISMATCH
TP_MISMATCH
ORDER_STATE_MISMATCH
ACCOUNT_VALUE_MISMATCH
UNKNOWN_ORDER
UNKNOWN_DEAL
```

## Severity

```text
INFO
WARNING
CRITICAL
```

## Policy

```text
INFO
→ record

WARNING
→ alert + block affected symbol

CRITICAL
→ HALT NEW ORDERS
→ reconcile
→ alert
```

## Startup recovery

```text
PROCESS START
    ↓
LOAD INTERNAL STATE
    ↓
QUERY MT5
    ↓
RECONCILE
    ↓
MATCH?
 ┌──┴───────┐
 YES       NO
 │          │
RUN      RECOVERY
```

## Acceptance Criteria

- reconciliation berjalan saat startup;
- reconciliation berjalan periodic;
- mismatch dapat direproduksi dengan mock;
- critical mismatch menghentikan new entry;
- broker truth diprioritaskan;
- recovery tercatat di audit log.

---

# 10. PHASE 36 — MULTI-LEVEL CIRCUIT BREAKER & CAPITAL PRESERVATION

## Tujuan

Mengubah kill switch dari sekadar ON/OFF menjadi layered control.

## State

```text
NORMAL
CAUTION
RISK_REDUCED
ENTRY_BLOCKED
EMERGENCY_FLATTEN
HALTED
```

## Trigger examples

```text
spread spike
feed stale
MT5 disconnected
daily loss threshold
drawdown threshold
consecutive losses
abnormal order frequency
reconciliation mismatch
execution rejection spike
database unavailable
model failure
```

## Example policy

```text
CAUTION
→ alert only

RISK_REDUCED
→ reduce allowed position size

ENTRY_BLOCKED
→ no new trades

EMERGENCY_FLATTEN
→ emergency position handling

HALTED
→ system remains stopped until recovery policy passes
```

Hard limits remain deterministic.

## Acceptance Criteria

- every transition memiliki reason;
- state latched untuk critical conditions;
- reset membutuhkan valid recovery condition;
- no LLM can override;
- dashboard shows current state + trigger.

---

# 11. PHASE 37 — CRASH / RESTART / STATE RECOVERY

## Tujuan

Sistem harus dapat restart tanpa kehilangan trading state.

## Persist

```text
system_state
market_state
decision_state
order_state
position_state
risk_state
circuit_breaker_state
strategy_state
scheduler_state
```

## Recovery flow

```text
START
 ↓
LOAD CHECKPOINT
 ↓
CHECK MT5 CONNECTION
 ↓
QUERY BROKER
 ↓
RECONCILE
 ↓
RESTORE RISK STATE
 ↓
RESTORE STRATEGY VERSION
 ↓
RESTORE CIRCUIT BREAKER
 ↓
READY / DEGRADED / HALTED
```

## Critical rule

Jangan reset:

```text
daily loss
drawdown
consecutive losses
halt state
open position state
```

hanya karena proses restart.

## Acceptance Criteria

Simulasikan:

```text
kill process
restart
MT5 still running
open position exists
```

dan pastikan internal state kembali konsisten.

---

# 12. PHASE 38 — END-TO-END FAILURE INJECTION LAB

## Tujuan

Membuktikan system safety dengan failure simulation.

## Scenarios

```text
MT5 unavailable
MT5 reconnect
bad tick
stale tick
spread spike
price gap
order rejection
order timeout
unknown order
partial fill
duplicate event
duplicate execution intent
database unavailable
Redis unavailable
LLM timeout
LLM malformed output
9Router unavailable
Telegram unavailable
process crash
computer restart
```

## Requirement

Buat:

```text
tests/e2e/failure_injection/
```

setiap scenario wajib menghasilkan:

```text
trigger
expected state
expected action
actual action
PASS/FAIL
```

## Acceptance Criteria

Tidak boleh ada scenario yang:

```text
failure
→ unsafe order
```

---

# 13. PHASE 39 — RESEARCH ENGINE 2.0

## Tujuan

Membuat research pipeline yang dapat membedakan strategy yang robust vs overfit.

## Backtest

Harus mendukung:

```text
OHLC/tick
spread
slippage
commission
swap
execution delay
broker symbol spec
position sizing
risk rules
session filters
```

## Required metrics

```text
total return
net profit
profit factor
expectancy
win rate
loss rate
average R
max drawdown
max consecutive losses
recovery factor
sharpe
sortino
trade frequency
average hold time
profit by session
profit by hour
profit by regime
```

---

# 14. PHASE 40 — WALK-FORWARD VALIDATION

## Tujuan

Menguji strategy di out-of-sample windows.

## Model

```text
TRAIN → TEST
TRAIN → TEST
TRAIN → TEST
```

Contoh:

```text
Window 1
TRAIN 2023 Q1-Q3
TEST  2023 Q4

Window 2
TRAIN 2023 Q2-Q4
TEST  2024 Q1

Window 3
TRAIN 2023 Q3-2024 Q1
TEST  2024 Q2
```

## Required output

```json
{
  "period": "2024-Q2",
  "trades": 143,
  "expectancy_r": 0.19,
  "max_dd_pct": 7.2,
  "profit_factor": 1.31,
  "status": "PASS"
}
```

## Governance

Tidak boleh hanya melihat aggregate result.

Setiap OOS period harus tersimpan.

---

# 15. PHASE 41 — MONTE CARLO & PARAMETER ROBUSTNESS

## Monte Carlo

Minimum:

```text
trade sequence resampling
return bootstrap
slippage variation
spread variation
execution variation
```

Default research run:

```text
>= 5,000 simulations
```

Configurable untuk performance.

## Output

```text
median return
5th percentile return
95th percentile drawdown
worst drawdown
max loss streak
probability of severe drawdown
```

## Parameter sensitivity

Untuk parameter strategy:

```text
baseline
-20%
-10%
+10%
+20%
```

Tujuan bukan menemukan parameter "terbaik", tetapi mendeteksi:

```text
cliff edge
```

yakni strategy yang hanya bekerja pada satu parameter sempit.

## Acceptance Criteria

Research report harus memberi status:

```text
ROBUST
FRAGILE
INSUFFICIENT_DATA
FAILED
```

Status berasal dari rule engine, bukan opini LLM.

---

# 16. PHASE 42 — PERFORMANCE INTELLIGENCE ENGINE

## Tujuan

Mengubah trade history menjadi insight statistik yang bisa digunakan untuk research.

## Dimensions

```text
hour
weekday
session
symbol
timeframe
strategy
setup
regime
volatility
spread bucket
RR bucket
agent consensus
model
direction
holding time
```

## Example output

```text
BY HOUR
hour 14 → 84 trades
hour 15 → 73 trades

BY SESSION
London
NY
Overlap

BY REGIME
trend
range
breakout
high-vol
low-vol
```

## Minimum sample rule

Insight tidak boleh ditampilkan sebagai reliable jika sample terlalu kecil.

```text
N < threshold
→ INSUFFICIENT_SAMPLE
```

## Important

Performance intelligence adalah:

```text
ADVISORY
```

bukan automatic strategy override.

---

# 17. PHASE 43 — LEARNING ENGINE 2.0

## Existing capability

Repository sudah memiliki persistent lesson store dan feedback masuk ke pipeline analisis, sementara signal/confidence tetap tidak diubah langsung oleh lesson.

V2 mempertahankan prinsip tersebut.

## Learning layers

```text
TRADE REVIEW
     ↓
LESSON
     ↓
PATTERN AGGREGATION
     ↓
HYPOTHESIS
     ↓
EXPERIMENT
     ↓
BACKTEST
     ↓
WALK-FORWARD
     ↓
PAPER
     ↓
DEMO
     ↓
CANDIDATE
```

## Lesson structure

```json
{
  "lesson_id": "...",
  "trade_id": "...",
  "symbol": "XAUUSD",
  "strategy_version": "v12",
  "category": "ENTRY_TIMING",
  "outcome": "LOSS",
  "context": {},
  "lesson": "...",
  "confidence": "LOW",
  "sample_size": 1,
  "created_at": "..."
}
```

## Important rule

One trade does not create a strategy change.

System harus membedakan:

```text
OBSERVATION
HYPOTHESIS
EVIDENCE
VALIDATED FINDING
```

---

# 18. PHASE 44 — STRATEGY LIFECYCLE GOVERNANCE

## State machine

```text
DRAFT
 ↓
EXPERIMENT
 ↓
BACKTESTED
 ↓
WALK_FORWARD_PASSED
 ↓
PAPER
 ↓
DEMO
 ↓
CANDIDATE
 ↓
APPROVED
 ↓
PRODUCTION
```

Failure branch:

```text
ANY STATE
   ↓
REJECTED
   ↓
ARCHIVED
```

## StrategyVersion object

```json
{
  "strategy_id": "...",
  "version": 12,
  "parameters": {},
  "risk_policy_id": "...",
  "created_from": "v11",
  "evidence": {
    "backtest": "...",
    "walk_forward": "...",
    "monte_carlo": "...",
    "paper": "...",
    "demo": "..."
  },
  "status": "CANDIDATE"
}
```

## Production promotion

Production promotion harus membutuhkan:

```text
validation evidence
+
risk compatibility
+
test evidence
+
audit record
```

AI boleh mengusulkan promotion.

AI tidak boleh mengubah production status sendirian.

---

# 19. PHASE 45 — DECISION REPLAY & AUDIT GRAPH

## Tujuan

Setiap trade dapat dijelaskan secara operasional tanpa menyimpan chain-of-thought mentah.

## Decision graph

```text
EVENT
 ↓
MARKET SNAPSHOT
 ↓
AGENTS ACTIVATED
 ↓
AGENT OUTPUTS
 ↓
CONFLICTS
 ↓
SUPERVISOR SUMMARY
 ↓
TRADE PROPOSAL
 ↓
RISK CHECKS
 ↓
EXECUTION
 ↓
BROKER RESULT
 ↓
POSITION
 ↓
RESULT
 ↓
REVIEW
```

## Decision ID

Semua object memakai:

```text
decision_id
event_id
trade_id
execution_id
strategy_version
```

## Replay

Dashboard:

```text
Decision #182
[Replay]
```

menampilkan state snapshot dan urutan event.

## Acceptance Criteria

Replay menggunakan snapshot yang tersimpan, bukan kondisi market saat ini.

---

# 20. PHASE 46 — LLM OBSERVABILITY & MODEL GOVERNANCE

## Request telemetry

```text
request_id
agent
provider
model
prompt_version
input_tokens
output_tokens
latency
fallback
error
decision_id
```

## Model registry

```text
ACTIVE
FALLBACK
DISABLED
DEPRECATED
```

## Model failure

```text
LLM failure
→ deterministic fallback
OR
→ skip AI reasoning
→ no unsafe trade
```

## Model comparison

System boleh mengumpulkan:

```text
latency
failure rate
token usage
cost
structured-output validity
linked decision outcomes
```

Tidak boleh menyimpulkan kualitas trading model hanya dari sample kecil.

---

# 21. PHASE 47 — EXECUTION QUALITY ANALYTICS

## Track

```text
requested entry
actual fill
slippage
spread
latency
rejection
partial fill
market state
```

## Metrics

```text
average slippage
p95 slippage
fill delay
rejection rate
partial fill rate
execution by session
execution by volatility
```

Insight digunakan untuk:

```text
execution policy
```

bukan untuk mengubah strategy signal tanpa validation.

---

# 22. PHASE 48 — TELEGRAM AUTONOMOUS CONTROL CENTER

Telegram menjadi control surface, bukan tempat utama untuk reasoning.

## Commands

```text
/status
/market
/positions
/orders
/risk
/trades
/performance
/learning
/strategy
/agents
/health
/reconcile
/why
/replay <decision_id>
```

## `/status`

```text
SYSTEM
🟢 HEALTHY

MT5
🟢 CONNECTED

Risk
🟢 NORMAL

Reconciliation
🟢 MATCH

Strategy
v12 PRODUCTION

Open Positions
1

Daily PnL
+$18.40

New Trades
ENABLED
```

## `/why`

Menampilkan:

```text
signal
market state
key agent conclusions
risk checks
final decision
reason for trade/no-trade
```

Tidak menampilkan private chain-of-thought.

---

# 23. PHASE 49 — OBSERVABILITY DASHBOARD 2.0

Dashboard minimal:

```text
1. Overview
2. Market
3. Positions
4. Orders
5. Agents
6. Supervisor
7. Risk
8. Reconciliation
9. Learning
10. Research
11. Strategies
12. Execution Quality
13. Observability
14. System Health
15. Audit / Decision Replay
16. Settings
```

## Dashboard principle

Jangan menampilkan angka kosong sebagai:

```text
0%
0 trades
NORMAL
HEALTHY
```

jika backend belum memiliki data.

Gunakan:

```text
No data
Unavailable
Not configured
Insufficient sample
```

sesuai konteks.

---

# 24. PHASE 50 — PRODUCTION CERTIFICATION GATE

Ini adalah gate sebelum live.

## Gate A — Engineering

```text
[ ] Python tests pass
[ ] Node tests pass
[ ] Web build pass
[ ] Type check pass
[ ] Lint pass
[ ] Security scan pass
```

## Gate B — Trading Safety

```text
[ ] Risk Gate verified
[ ] Kill switch verified
[ ] Circuit breaker verified
[ ] Duplicate prevention verified
[ ] Broker specification verified
[ ] Reconciliation verified
[ ] Recovery verified
```

## Gate C — Research

```text
[ ] Backtest complete
[ ] Walk-forward complete
[ ] Monte Carlo complete
[ ] Parameter sensitivity complete
[ ] Sufficient sample
```

## Gate D — Operational

```text
[ ] MT5 restart test
[ ] PC restart test
[ ] MT5 disconnect test
[ ] Database failure test
[ ] LLM failure test
[ ] 9Router failure test
[ ] Telegram failure test
```

## Gate E — Forward Validation

```text
[ ] Paper
[ ] Demo
[ ] Monitoring
[ ] Execution quality tracked
[ ] No unresolved critical incident
```

Production status:

```text
NOT_READY
READY_FOR_PAPER
READY_FOR_DEMO
READY_FOR_SMALL_LIVE
PRODUCTION
HALTED
```

Status ditentukan deterministic checklist.

---

# 25. PHASE 51 — PAPER / DEMO / LIVE ENVIRONMENT SEPARATION

Tidak boleh ada accidental live execution dari development.

## Environment

```text
DEV
PAPER
DEMO
LIVE
```

## Broker endpoint identity

Setiap execution log harus menyimpan:

```text
environment
broker
server
account
login
terminal_id
strategy_version
```

## Protection

Jika:

```text
environment != LIVE
```

dan code mencoba live execution:

```text
REJECT
```

Jika:

```text
environment == LIVE
```

harus ada:

```text
terminal armed
+
risk gate healthy
+
reconciliation healthy
+
production strategy
```

---

# 26. PHASE 52 — CAPITAL ALLOCATION & MULTI-STRATEGY SAFETY

Ketika strategi >1:

```text
Account
 ├── Strategy A
 ├── Strategy B
 └── Strategy C
```

harus ada:

```text
strategy allocation
gross exposure
net exposure
correlation exposure
shared daily loss
shared drawdown
```

Tidak boleh setiap strategy menganggap dirinya memiliki seluruh account equity.

---

# 27. PHASE 53 — MULTI-ACCOUNT / MULTI-BROKER FOUNDATION

Ini tahap scalability setelah single-account stabil.

Architecture:

```text
Account Manager
 ├── Broker A
 │    ├── Account 1
 │    └── Account 2
 └── Broker B
      └── Account 3
```

Semua execution harus memiliki:

```text
broker_id
account_id
terminal_id
symbol_spec_id
```

Namun multi-broker bukan blocker untuk menyelesaikan single-broker production.

---

# 28. PHASE 54 — AUTONOMOUS RESEARCH SCHEDULER

Supervisor dapat menjadwalkan research secara otomatis:

```text
DAILY
→ performance aggregation

WEEKLY
→ strategy review

WEEKLY
→ robustness research

MONTHLY
→ parameter sensitivity

AFTER N TRADES
→ learning review
```

Research scheduler tidak boleh mengubah production secara langsung.

Semua hasil masuk:

```text
Research Inbox
```

dengan status:

```text
NEW
REVIEWING
EXPERIMENT
VALIDATED
REJECTED
```

---

# 29. PHASE 55 — INCIDENT MANAGEMENT

Semua incident harus mempunyai:

```text
incident_id
severity
detected_at
component
trigger
system_state
action_taken
recovery_state
resolved_at
```

Severity:

```text
INFO
WARNING
HIGH
CRITICAL
EMERGENCY
```

Contoh:

```text
CRITICAL
Reconciliation mismatch detected
New entries blocked
Position state unresolved
```

---

# 30. PHASE 56 — SYSTEM SLO / HEALTH TARGET

Target internal:

```text
MT5 detection success
Market feed freshness
Execution confirmation latency
Reconciliation freshness
API availability
Scheduler health
LLM availability
```

Gunakan percentile:

```text
p50
p95
p99
```

bukan hanya average.

---

# 31. PHASE DEPENDENCY GRAPH

Urutan implementasi wajib mengikuti:

```text
31 Baseline Certification
          ↓
32 Market Data Health
          ↓
33 Broker Reality
          ↓
34 Durable Execution
          ↓
35 Reconciliation 2.0
          ↓
36 Circuit Breaker
          ↓
37 Recovery
          ↓
38 Failure Injection
          ↓
39 Backtest 2.0
          ↓
40 Walk Forward
          ↓
41 Monte Carlo / Sensitivity
          ↓
42 Performance Intelligence
          ↓
43 Learning 2.0
          ↓
44 Strategy Lifecycle
          ↓
45 Decision Replay
          ↓
46 LLM Observability
          ↓
47 Execution Quality
          ↓
48 Telegram Control
          ↓
49 Dashboard 2.0
          ↓
50 Production Certification
          ↓
51 Environment Separation
          ↓
52 Multi-Strategy
          ↓
53 Multi-Account/Broker
          ↓
54 Autonomous Research
          ↓
55 Incident Management
          ↓
56 SLO
```

---

# 32. WHAT MUST NOT BE DONE YET

Jangan mengejar:

```text
more agents
more LLM models
complex ML
reinforcement learning
huge prompt chains
multi-broker
multi-account
SaaS
```

sebelum:

```text
reconciliation
recovery
failure injection
robust research
strategy governance
production certification
```

benar-benar selesai.

---

# 33. DEFINITION OF DONE V2

Sebuah phase dianggap DONE hanya jika:

```text
[ ] Design implemented
[ ] Existing implementation reused where appropriate
[ ] Unit tests
[ ] Integration tests
[ ] E2E tests when relevant
[ ] Failure test when relevant
[ ] Error handling
[ ] Structured logging
[ ] Persistence/recovery if relevant
[ ] Configuration
[ ] API contract
[ ] Dashboard/Telegram surface if operationally relevant
[ ] Security review
[ ] No fabricated data
[ ] No unsafe path to MT5
[ ] Documentation
[ ] Acceptance criteria PASS
[ ] Git commit
[ ] Changelog updated
```

---

# 34. OPEN CODE EXECUTION PROTOCOL

OpenCode harus mengerjakan:

```text
READ PRD
 ↓
INSPECT REPOSITORY
 ↓
IDENTIFY EXISTING MODULE
 ↓
BUILD PLAN
 ↓
IMPLEMENT ONE TASK
 ↓
RUN TEST
 ↓
RUN RELATED E2E
 ↓
FIX FAILURES
 ↓
VERIFY NO REGRESSION
 ↓
UPDATE DOCS
 ↓
UPDATE CHANGELOG
 ↓
COMMIT
 ↓
CHECKPOINT
```

Tidak boleh:

```text
Phase 31 → 56
```

dikerjakan sekaligus.

---

# 35. MASTER V2 CHECKLIST

## PRODUCTION SAFETY

- [ ] Baseline certification
- [ ] Market data health
- [ ] Stale protection
- [ ] Broker symbol specification
- [ ] Durable order lifecycle
- [ ] Idempotency
- [ ] Partial fill handling
- [ ] Unknown execution handling
- [ ] Reconciliation startup
- [ ] Reconciliation periodic
- [ ] Circuit breaker
- [ ] State recovery
- [ ] Failure injection
- [ ] Emergency stop

## RESEARCH

- [ ] Backtest v2
- [ ] Walk-forward
- [ ] Monte Carlo
- [ ] Parameter sensitivity
- [ ] Performance intelligence
- [ ] Execution quality analytics

## LEARNING

- [ ] Persistent lessons
- [ ] Pattern aggregation
- [ ] Hypothesis store
- [ ] Experiment pipeline
- [ ] Validation evidence
- [ ] Strategy lifecycle
- [ ] Strategy promotion gate

## AUTONOMY

- [ ] Supervisor orchestration
- [ ] Agent routing
- [ ] Conflict resolution
- [ ] Autonomous research scheduler
- [ ] Daily/weekly review
- [ ] Telegram status
- [ ] Decision explanation
- [ ] Decision replay

## OBSERVABILITY

- [ ] System health
- [ ] Agent health
- [ ] LLM telemetry
- [ ] Execution telemetry
- [ ] Reconciliation history
- [ ] Incident management
- [ ] Audit log
- [ ] SLO metrics

## DEPLOYMENT

- [ ] DEV/PAPER/DEMO/LIVE isolation
- [ ] MT5 terminal identity
- [ ] Live arm/disarm
- [ ] Production certification
- [ ] Backup
- [ ] Recovery drill
- [ ] Small-live gate

---

# 36. FINAL SYSTEM MODEL

Target architecture:

```text
                   ┌─────────────────────┐
                   │     CONTROL PLANE   │
                   │ Web / Telegram / CLI │
                   └──────────┬──────────┘
                              │
                         SUPERVISOR
                              │
             ┌────────────────┼────────────────┐
             │                │                │
          MARKET            RISK           RESEARCH
             │                │                │
             └────────────────┼────────────────┘
                              │
                       DECISION STATE
                              │
                         RISK GATE
                              │
                      EXECUTION ENGINE
                              │
                             MT5
                              │
                 ┌────────────┼────────────┐
                 │            │            │
              ORDER       POSITION       ACCOUNT
                 │            │            │
                 └────────────┼────────────┘
                              │
                       RECONCILIATION
                              │
                    ┌─────────┴─────────┐
                    │                   │
                 MATCH               MISMATCH
                    │                   │
                 MONITOR          RECOVER / HALT
                    │
                TRADE REVIEW
                    │
                 LEARNING
                    │
                 RESEARCH
                    │
             VALIDATION PIPELINE
                    │
             STRATEGY VERSION
                    │
          PAPER → DEMO → LIVE
                    │
              OBSERVE AGAIN
```

---

# 37. FINAL PRINCIPLE

Sistem tidak boleh menjadi:

```text
LLM + chart + BUY/SELL
```

Sistem harus menjadi:

```text
Reliable Market Data
+
Deterministic Quant Engine
+
Multi-Agent Reasoning
+
Deterministic Risk
+
Durable Execution
+
Broker Reconciliation
+
Failure Recovery
+
Research & Robustness Testing
+
Governed Learning
+
Strategy Version Control
+
Observability
+
Control Plane
```

### V2 selesai secara konseptual ketika:

```text
SYSTEM CAN TRADE
AND

SYSTEM CAN PROVE WHY
AND

SYSTEM CAN DETECT WHEN ITS STATE IS WRONG
AND

SYSTEM CAN RECOVER
AND

SYSTEM CAN STOP ITSELF
AND

SYSTEM CAN LEARN WITHOUT UNCONTROLLED LIVE CHANGES
AND

SYSTEM CAN TEST A STRATEGY BEFORE PROMOTION
```

---

# 38. IMPLEMENTATION PRIORITY SUMMARY

### P0 — wajib sebelum live

```text
31 Baseline Certification
32 Market Data Health
33 Broker Reality
34 Durable Execution
35 Reconciliation 2.0
36 Circuit Breaker
37 Recovery
38 Failure Injection
50 Production Certification
51 Environment Separation
```

### P1 — wajib untuk autonomous research

```text
39 Backtest 2.0
40 Walk Forward
41 Monte Carlo / Sensitivity
42 Performance Intelligence
43 Learning 2.0
44 Strategy Lifecycle
45 Decision Replay
46 LLM Observability
47 Execution Quality
```

### P2 — control plane & scalability

```text
48 Telegram Control Center
49 Dashboard 2.0
52 Multi-Strategy
53 Multi-Account/Broker
54 Autonomous Research Scheduler
55 Incident Management
56 SLO
```

### Important implementation rule

**P0 harus selesai dan lulus certification sebelum sistem diarahkan ke live trading.**

P1 membangun kemampuan sistem untuk melakukan research dan learning secara disiplin.

P2 memperluas operasional dan scalability setelah core trading system stabil.

---

# 39. REFERENCES / BASELINE SOURCES

Repository baseline yang digunakan untuk menyusun PRD ini:

- PRD V1: https://github.com/billy19911/project-ea-bot/blob/main/PRD_V1_Autonomous_Multi_Agent_Trading_Research_Platform.md
- README: https://github.com/billy19911/project-ea-bot/blob/main/README.md
- Changelog: https://github.com/billy19911/project-ea-bot/blob/main/CHANGELOG.md
