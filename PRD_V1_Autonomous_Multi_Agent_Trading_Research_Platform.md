# PRD V1
# AI Autonomous Multi-Agent Trading & Research Platform

**Status:** Draft — Architecture & Implementation Specification  
**Version:** 1.0  
**Target:** Autonomous AI Trading & Research System  
**Primary Platform:** MetaTrader 5 (MT5)  
**Primary Instrument:** XAUUSD / XAUUSDC  
**Architecture:** Event-Driven Multi-Agent + Deterministic Trading Engine  
**Initial LLM Gateway:** 9Router  
**Initial Model Strategy:** Free / low-cost models first, model escalation when required  
**Execution:** MT5  
**UI:** React + Next.js  
**Backend:** Node.js / TypeScript  
**AI Runtime:** Python and/or dedicated AI service  
**Development Executor:** OpenCode

---

# 1. EXECUTIVE SUMMARY

## 1.1 Tujuan Produk

Membangun platform autonomous trading yang mampu:

1. menerima data pasar dari MT5;
2. memproses data melalui deterministic trading engines;
3. mendeteksi event pasar yang membutuhkan reasoning;
4. mengaktifkan AI specialist yang relevan;
5. memiliki Supervisor AI sebagai orchestrator;
6. meminta analisis dari specialist berdasarkan kebutuhan;
7. menggabungkan hasil analisis;
8. melakukan risk validation;
9. menghasilkan keputusan trading;
10. melakukan eksekusi melalui MT5 apabila memenuhi seluruh safety gate;
11. memonitor posisi setelah entry;
12. melakukan evaluasi terhadap keputusan trading;
13. menyimpan seluruh reasoning, keputusan, event, dan hasil;
14. melakukan research/backtesting;
15. terus meningkatkan strategy melalui data historis dan hasil trade.

Sistem harus dirancang agar **LLM bukan satu-satunya sumber kebenaran**.

LLM bertanggung jawab atas reasoning dan interpretation.

Deterministic engine bertanggung jawab atas:

- perhitungan;
- risk limit;
- position sizing;
- exposure;
- drawdown;
- spread;
- margin;
- order validation;
- execution;
- safety rules.

---

# 2. CORE DESIGN PRINCIPLE

Sistem harus mengikuti prinsip:

> **AI decides within boundaries. Code enforces boundaries.**

Artinya:

```text
AI
↓
Recommendation
↓
Deterministic Validation
↓
Risk Gate
↓
Execution
```

AI tidak boleh langsung:

```text
LLM → MT5 BUY
```

Tetapi:

```text
LLM
↓
Trade Proposal
↓
Risk Engine
↓
Safety Engine
↓
Execution Engine
↓
MT5
```

---

# 3. HIGH-LEVEL SYSTEM ARCHITECTURE

```text
                         ┌───────────────────────┐
                         │       WEB UI          │
                         │ React / Next.js       │
                         └───────────┬───────────┘
                                     │
                              API / WebSocket
                                     │
                         ┌───────────▼───────────┐
                         │     CONTROL PLANE      │
                         │ Node.js / TypeScript   │
                         └───────────┬───────────┘
                                     │
                    ┌────────────────┼─────────────────┐
                    │                │                 │
                    ▼                ▼                 ▼
             Event Manager     Agent Router      State Manager
                    │                │                 │
                    └────────────────┼─────────────────┘
                                     │
                              ┌──────▼──────┐
                              │  SUPERVISOR │
                              │     AGENT   │
                              └──────┬──────┘
                                     │
              ┌──────────────────────┼────────────────────────┐
              │                      │                        │
              ▼                      ▼                        ▼
       Market Department      Risk Department       Research Department
              │                      │                        │
       ┌──────┼──────┐        ┌──────┼──────┐          ┌──────┼──────┐
       ▼      ▼      ▼        ▼      ▼      ▼          ▼      ▼      ▼
   Technical Structure Momentum  Account Position Portfolio Strategy Backtest
   Analyst   Analyst   Analyst   Risk    Risk     Risk     Research Evaluation
              │                      │
              └──────────────────────┼────────────────────────
                                     ▼
                              ┌──────────────┐
                              │  RISK GATE   │
                              │ DETERMINISTIC│
                              └──────┬───────┘
                                     │
                              ┌──────▼───────┐
                              │  EXECUTION   │
                              │    ENGINE    │
                              └──────┬───────┘
                                     │
                                  MT5 API
                                     │
                              ┌──────▼───────┐
                              │    MT5       │
                              └──────────────┘
```

---

# 4. ARCHITECTURAL LAYERS

System dibagi menjadi 10 layer.

## Layer 1 — Market Data

Mengambil data:

- tick;
- OHLC;
- spread;
- bid;
- ask;
- volume;
- timeframe;
- symbol;
- market session;
- account state;
- positions;
- orders.

---

## Layer 2 — Deterministic Trading Engine

Menghasilkan:

- indicators;
- trend;
- volatility;
- market structure;
- spread status;
- liquidity conditions;
- risk metrics;
- exposure;
- position sizing.

Tidak menggunakan LLM.

---

## Layer 3 — Event Detection

Mendeteksi apakah sesuatu penting terjadi.

Contoh:

```text
NEW_CANDLE
TREND_CHANGE
BREAKOUT
BREAKDOWN
VOLATILITY_SPIKE
SPREAD_SPIKE
NEWS_EVENT
POSITION_OPENED
POSITION_CLOSED
DRAWDOWN_WARNING
RISK_LIMIT_REACHED
TRADE_SETUP_DETECTED
```

---

## Layer 4 — Agent Router

Menentukan agent mana yang perlu bekerja.

Contoh:

```text
TRADE_SETUP_DETECTED
        ↓
Supervisor
        ↓
Technical Analyst
        ↓
Risk Analyst
        ↓
Supervisor
```

Bukan:

```text
Supervisor
↓
10 agent sekaligus
```

---

# 5. SUPERVISOR AGENT

## 5.1 Fungsi

Supervisor adalah AI manager/orchestrator.

Supervisor tidak melakukan semua analisis sendiri.

Tugas:

- memahami objective;
- membaca state;
- menentukan agent yang dibutuhkan;
- meminta informasi;
- menggabungkan hasil;
- mendeteksi konflik;
- meminta second opinion;
- membuat trade proposal;
- menyerahkan proposal ke Risk Gate.

---

## 5.2 Supervisor tidak boleh

Supervisor tidak boleh:

- menghitung lot secara manual;
- bypass risk engine;
- mengubah hard risk limit;
- langsung mengirim order;
- mengabaikan blocked status;
- menganggap output agent selalu benar.

---

# 6. AGENT HIERARCHY

Sistem menggunakan struktur organisasi seperti perusahaan.

```text
CEO / SUPERVISOR
│
├── MARKET INTELLIGENCE
│   ├── Technical Analyst
│   ├── Market Structure Analyst
│   ├── Momentum Analyst
│   ├── Volatility Analyst
│   └── News/Sentiment Analyst
│
├── RISK DEPARTMENT
│   ├── Account Risk Agent
│   ├── Position Risk Agent
│   ├── Portfolio Risk Agent
│   └── Drawdown Agent
│
├── RESEARCH DEPARTMENT
│   ├── Strategy Researcher
│   ├── Backtest Analyst
│   ├── Performance Analyst
│   └── Experiment Agent
│
└── EXECUTION DEPARTMENT
    ├── Execution Monitor
    ├── Order Validation
    └── Position Monitor
```

Tidak semua department harus aktif pada setiap event.

---

# 7. MARKET INTELLIGENCE DEPARTMENT

## 7.1 Technical Analyst

Input:

- EMA;
- SMA;
- RSI;
- ADX;
- ATR;
- MACD;
- price;
- timeframe.

Output:

```json
{
  "signal": "BUY",
  "confidence": 0.72,
  "reason": "...",
  "conditions": []
}
```

---

## 7.2 Market Structure Analyst

Menganalisis:

- swing high;
- swing low;
- BOS;
- CHOCH;
- support;
- resistance;
- order block;
- liquidity;
- structure bias.

---

## 7.3 Momentum Analyst

Menganalisis:

- momentum;
- acceleration;
- weakening;
- divergence;
- impulse;
- retracement.

---

## 7.4 Volatility Analyst

Menganalisis:

- ATR;
- volatility regime;
- expansion;
- compression;
- abnormal movement.

---

## 7.5 News Agent

Opsional pada tahap awal.

Menganalisis:

- high impact news;
- economic events;
- sentiment;
- event risk.

News Agent hanya dipanggil ketika:

```text
NEWS_WINDOW
```

atau ketika market movement abnormal.

---

# 8. RISK DEPARTMENT

Risk Department merupakan salah satu komponen paling penting.

## 8.1 Account Risk Agent

Memeriksa:

- balance;
- equity;
- margin;
- free margin;
- drawdown;
- daily loss;
- weekly loss;
- exposure.

---

## 8.2 Position Risk Agent

Memeriksa:

- open positions;
- lot;
- SL;
- TP;
- distance;
- risk per position;
- correlation.

---

## 8.3 Portfolio Risk Agent

Memeriksa:

- total exposure;
- symbol concentration;
- correlated positions;
- aggregate risk.

---

## 8.4 Drawdown Agent

Memonitor:

```text
Current DD
Daily DD
Weekly DD
Peak DD
Recovery
```

---

# 9. DETERMINISTIC RISK ENGINE

Komponen ini **tidak menggunakan LLM**.

Hard rules harus dieksekusi oleh code.

Contoh:

```text
MAX_DRAWDOWN
MAX_DAILY_LOSS
MAX_WEEKLY_LOSS
MAX_POSITION_SIZE
MAX_TOTAL_EXPOSURE
MAX_OPEN_POSITIONS
MAX_SPREAD
MIN_MARGIN_LEVEL
MAX_RISK_PER_TRADE
MAX_CONSECUTIVE_LOSSES
```

Jika salah satu hard rule gagal:

```text
BLOCK TRADE
```

Tidak peduli apa yang dikatakan Supervisor.

---

# 10. MONEY MANAGEMENT ENGINE

Menghitung:

- risk percentage;
- stop loss distance;
- lot size;
- expected loss;
- expected reward;
- risk/reward;
- portfolio exposure.

Contoh:

```text
Account = $1,000
Risk = 1%
Maximum loss = $10
```

Engine menentukan lot berdasarkan:

```text
risk amount
/
SL distance
/
instrument specification
```

LLM tidak menghitung final lot.

---

# 11. TRADE PROPOSAL

Supervisor tidak menghasilkan order mentah.

Supervisor menghasilkan:

```json
{
  "symbol": "XAUUSD",
  "direction": "BUY",
  "entry_type": "MARKET",
  "entry": null,
  "stop_loss": 3340.50,
  "take_profit": 3352.50,
  "confidence": 0.76,
  "reason": "...",
  "strategy": "TREND_PULLBACK"
}
```

Kemudian deterministic engine memvalidasi.

---

# 12. RISK GATE

Risk Gate adalah firewall trading.

Flow:

```text
Trade Proposal
      ↓
Validate Symbol
      ↓
Validate Market
      ↓
Validate Spread
      ↓
Validate Account
      ↓
Validate Drawdown
      ↓
Validate Position Risk
      ↓
Validate Exposure
      ↓
Validate SL
      ↓
Validate TP
      ↓
Validate Lot
      ↓
APPROVE / REJECT
```

Jika REJECT:

```text
No order sent.
```

---

# 13. EXECUTION ENGINE

Execution Engine bertugas:

- connect MT5;
- validate connection;
- send order;
- verify order;
- detect rejection;
- retry sesuai policy;
- confirm position;
- store execution result.

Execution Engine tidak menggunakan LLM.

---

# 14. POSITION MONITOR

Setelah entry:

```text
OPEN POSITION
      ↓
MONITOR
      ↓
SL/TP
      ↓
Trailing
      ↓
Risk Change
      ↓
Exit Condition
```

AI dapat dipanggil jika terjadi event penting.

Contoh:

```text
POSITION_STALLED
VOLATILITY_SPIKE
TREND_REVERSAL
RISK_CHANGE
UNEXPECTED_MOVE
```

---

# 15. EVENT-DRIVEN ARCHITECTURE

LLM tidak boleh aktif terus menerus.

Event engine menentukan kapan reasoning diperlukan.

Contoh:

```text
Tick
 ↓
Deterministic processing
 ↓
No important event?
 ↓
YES → Stop
```

Jika:

```text
Trade setup detected
```

maka:

```text
Event
 ↓
Supervisor
 ↓
Relevant Agents
 ↓
Risk Gate
```

---

# 16. AGENT ROUTER

Agent Router menerima:

```json
{
  "event": "TRADE_SETUP_DETECTED",
  "symbol": "XAUUSD",
  "timeframe": "M1"
}
```

Router menentukan:

```text
Technical Analyst
Market Structure Analyst
Momentum Analyst
Risk Agent
```

Tidak mengaktifkan:

```text
Research Agent
Backtest Agent
News Agent
```

kecuali dibutuhkan.

---

# 17. STRUCTURED SHARED STATE

Agent tidak berkomunikasi menggunakan percakapan panjang.

Semua state disimpan dalam structured format.

Contoh:

```json
{
  "market": {},
  "technical": {},
  "structure": {},
  "momentum": {},
  "risk": {},
  "portfolio": {},
  "execution": {},
  "supervisor": {}
}
```

Setiap agent hanya boleh menulis namespace miliknya.

Contoh:

```text
technical.*
risk.*
market.*
```

---

# 18. AGENT OUTPUT STANDARD

Semua agent wajib menggunakan schema standar.

```json
{
  "agent": "technical_analyst",
  "timestamp": "...",
  "status": "completed",
  "signal": "BUY",
  "confidence": 0.74,
  "reasoning_summary": "...",
  "risks": [],
  "recommendation": "...",
  "data_quality": "GOOD"
}
```

Tidak boleh menghasilkan output tidak terstruktur untuk pipeline utama.

---

# 19. AGENT CONFIDENCE

Confidence bukan berarti probabilitas profit.

System harus membedakan:

```text
confidence
signal_strength
risk_score
data_quality
```

Contoh:

```text
confidence = 0.78
risk_score = 0.31
data_quality = GOOD
```

---

# 20. CONFLICT RESOLUTION

Jika:

```text
Technical = BUY
Structure = BUY
Momentum = SELL
Risk = SAFE
```

Supervisor mendeteksi conflict.

Supervisor dapat:

1. meminta additional analysis;
2. menunggu candle berikutnya;
3. meminta higher timeframe analysis;
4. menolak trade.

Tidak boleh otomatis mengambil mayoritas tanpa memahami conflict.

---

# 21. MODEL ROUTING

Model tidak harus sama untuk semua agent.

Contoh:

```text
Technical Analyst → Free model
Market Analyst → Free model
News → Free model
Research → Medium model
Supervisor → Strong model jika diperlukan
Conflict Resolver → Strong model
```

---

# 22. MODEL ESCALATION

Default:

```text
FREE MODEL
```

Jika:

```text
confidence rendah
```

atau:

```text
agent conflict
```

atau:

```text
market anomaly
```

maka:

```text
MEDIUM MODEL
```

Jika masih tidak yakin:

```text
STRONG MODEL
```

Jika tetap tidak yakin:

```text
NO TRADE
```

---

# 23. TOKEN BUDGET MANAGER

System harus memonitor:

- token input;
- token output;
- model;
- cost;
- latency;
- agent;
- event.

Setiap request memiliki budget.

Contoh:

```text
Market Analysis:
max 4,000 tokens

Supervisor:
max 6,000 tokens

Simple classification:
max 1,500 tokens
```

---

# 24. CONTEXT MANAGEMENT

Context harus dibatasi.

Agent tidak boleh menerima:

- seluruh database;
- seluruh history;
- seluruh chat;
- seluruh candle history.

Agent hanya menerima data relevan.

Contoh:

```text
Technical Agent:
technical snapshot

Risk Agent:
account + position state

News Agent:
news context

Supervisor:
summarized outputs
```

---

# 25. MEMORY SYSTEM

Memory dibagi:

## Short-Term Memory

Untuk event saat ini.

## Session Memory

Untuk satu trading session.

## Trade Memory

Untuk satu trade.

## Long-Term Memory

Untuk:

- strategy performance;
- agent performance;
- recurring patterns;
- lessons learned.

---

# 26. TRADE MEMORY

Setiap trade menyimpan:

```text
Market condition
Agent opinions
Supervisor decision
Risk state
Entry
SL
TP
Exit
P/L
MAE
MFE
Duration
Reason
```

Setelah trade selesai:

```text
Trade Review Agent
```

melakukan evaluasi.

---

# 27. TRADE REVIEW AGENT

Setelah trade:

```text
WIN / LOSS
 ↓
Review
 ↓
Was analysis correct?
Was execution correct?
Was risk correct?
Was timing correct?
```

Output:

```text
LESSON
```

Lesson tidak langsung mengubah strategy.

Perubahan strategy harus melalui Research/Experiment pipeline.

---

# 28. RESEARCH DEPARTMENT

Research Department tidak boleh mengubah live strategy secara langsung.

Tugas:

- hypothesis;
- experiment;
- backtest;
- optimization;
- comparison;
- statistical evaluation.

---

# 29. STRATEGY RESEARCH

Contoh:

```text
Hypothesis:
ADX > 25 + EMA trend + pullback
lebih efektif daripada
EMA trend saja.
```

Research engine:

```text
Generate hypothesis
 ↓
Backtest
 ↓
Evaluate
 ↓
Compare
 ↓
Store result
```

---

# 30. BACKTEST ENGINE

Harus mendukung:

- historical candles;
- spread;
- slippage;
- commission;
- swap;
- execution delay;
- strategy parameters;
- risk rules.

Output:

```text
Profit Factor
Win Rate
Expectancy
Max Drawdown
Sharpe
Sortino
Average R
Trade Count
```

---

# 31. FORWARD TEST

Sebelum live:

```text
Backtest
 ↓
Walk Forward
 ↓
Paper Trading
 ↓
Demo MT5
 ↓
Small Live
```

Tidak boleh langsung:

```text
AI → live account
```

---

# 32. PAPER TRADING ENGINE

Harus dapat mensimulasikan:

- order;
- fills;
- SL;
- TP;
- spread;
- slippage;
- position state.

Sehingga AI dapat diuji tanpa uang nyata.

---

# 33. SAFETY MODE

System harus memiliki:

```text
OFFLINE
BACKTEST
PAPER
DEMO
LIVE
EMERGENCY_STOP
```

Mode LIVE harus membutuhkan explicit enable.

---

# 34. KILL SWITCH

Harus tersedia:

```text
GLOBAL KILL SWITCH
```

Ketika aktif:

```text
NO NEW ORDERS
```

Existing positions dapat:

- tetap dikelola;
- ditutup;
- atau emergency close sesuai konfigurasi.

---

# 35. EMERGENCY CONDITIONS

Automatic kill switch jika:

```text
drawdown exceeded
MT5 connection unstable
unexpected order behavior
duplicate order detected
risk engine failure
state corruption
price feed invalid
spread abnormal
API failure
LLM service failure
```

---

# 36. LLM FAILURE POLICY

Trading tidak boleh bergantung pada LLM availability.

Jika LLM mati:

```text
LLM unavailable
 ↓
No new AI-dependent trade
```

Tetapi:

```text
Position Monitor
Risk Monitor
Kill Switch
SL/TP
```

tetap bekerja.

---

# 37. 9ROUTER INTEGRATION

Buat abstraction:

```text
LLMProvider
```

Sehingga application tidak bergantung langsung pada satu model.

Contoh:

```text
LLMProvider
├── 9Router
├── OpenAI
├── Anthropic
├── Local Model
└── Other Provider
```

Awal:

```text
9Router
```

---

# 38. MODEL REGISTRY

Database menyimpan:

```text
provider
model
capabilities
context_limit
cost
availability
priority
```

Agent dapat meminta:

```text
reasoning_level = LOW
```

atau:

```text
reasoning_level = HIGH
```

Router memilih model.

---

# 39. FALLBACK

Jika model utama gagal:

```text
Model A
 ↓ failure
Model B
 ↓ failure
Model C
 ↓ failure
NO AI DECISION
```

Jangan retry tanpa batas.

---

# 40. RATE LIMIT MANAGEMENT

System harus:

- detect rate limit;
- queue request;
- retry dengan backoff;
- fallback;
- record error.

---

# 41. DATABASE ARCHITECTURE

Minimal entities:

```text
users
accounts
brokers
symbols
market_snapshots
market_events
agent_runs
agent_outputs
agent_tasks
supervisor_decisions
trade_proposals
risk_checks
orders
positions
trades
trade_reviews
strategies
strategy_versions
backtests
experiments
model_registry
llm_requests
llm_usage
system_events
alerts
audit_logs
settings
```

---

# 42. AUDIT LOG

Semua keputusan penting harus dapat ditelusuri.

Contoh:

```text
Why did system buy XAUUSD?
```

Harus bisa menjawab:

```text
Event
 ↓
Supervisor
 ↓
Agents called
 ↓
Agent outputs
 ↓
Trade proposal
 ↓
Risk checks
 ↓
Approval
 ↓
Order
 ↓
Execution
```

---

# 43. OBSERVABILITY

Monitor:

- agent latency;
- LLM latency;
- token usage;
- model failures;
- MT5 connection;
- order failures;
- risk blocks;
- trade performance.

---

# 44. DASHBOARD

Dashboard React/Next.js harus memiliki:

## Overview

Menampilkan:

- account;
- equity;
- balance;
- drawdown;
- current exposure;
- current positions;
- AI status.

---

# 45. MARKET DASHBOARD

Menampilkan:

- XAUUSD;
- price;
- trend;
- volatility;
- spread;
- signal;
- market regime;
- active events.

---

# 46. AI ORGANIZATION VIEW

Menampilkan struktur:

```text
SUPERVISOR
│
├── Market
├── Risk
├── Research
└── Execution
```

User dapat melihat:

```text
ACTIVE
IDLE
WAITING
ERROR
```

untuk setiap agent.

---

# 47. LIVE AGENT ACTIVITY

Harus menampilkan event secara ringkas.

Contoh:

```text
16:02:13
Supervisor detected trade setup.

16:02:14
Technical Analyst requested.

16:02:15
Technical Analyst → BUY 74%.

16:02:15
Risk Agent → SAFE.

16:02:16
Supervisor → Trade proposal created.

16:02:16
Risk Gate → APPROVED.

16:02:17
Execution → BUY XAUUSD.
```

Tidak menampilkan seluruh chain-of-thought.

Yang disimpan hanya:

```text
decision summary
reason
inputs
outputs
```

---

# 48. TRADE PANEL

Setiap trade harus menampilkan:

```text
Entry
SL
TP
Lot
Risk
Strategy
Confidence
Reason
Agents consulted
Risk checks
Result
```

---

# 49. CONTROL PANEL

User dapat mengatur:

```text
Trading Mode
Risk %
Max Drawdown
Max Daily Loss
Max Exposure
Allowed Symbols
Allowed Sessions
Strategy
AI Enabled
Paper/Demo/Live
```

Hard safety limits tidak boleh dapat diubah oleh LLM.

---

# 50. SETTINGS HIERARCHY

Configuration dibagi:

```text
SYSTEM
ACCOUNT
RISK
STRATEGY
AGENT
MODEL
EXECUTION
NOTIFICATION
```

---

# 51. PERMISSION SYSTEM

Minimal:

```text
ADMIN
OPERATOR
VIEWER
```

ADMIN:

- settings;
- live trading;
- risk limits.

OPERATOR:

- monitoring;
- enable/disable strategy.

VIEWER:

- read-only.

---

# 52. SECURITY

Harus menggunakan:

- encrypted credentials;
- environment variables;
- secret manager;
- API authentication;
- role-based access;
- audit log;
- rate limiting;
- CSRF protection;
- secure WebSocket;
- no broker credentials exposed to frontend.

---

# 53. MT5 CONNECTOR

MT5 connector harus menyediakan interface:

```text
get_account()
get_symbol()
get_tick()
get_rates()
get_positions()
get_orders()
send_order()
modify_order()
close_position()
```

Connector harus dapat diganti tanpa mempengaruhi agent layer.

---

# 54. BROKER ABSTRACTION

Jangan hard-code broker.

Architecture:

```text
BrokerAdapter
├── MT5
├── Broker A
├── Broker B
└── Future
```

---

# 55. SYMBOL ABSTRACTION

Jangan hard-code XAUUSD.

System harus mendukung:

```text
XAUUSD
XAUUSDC
BTCUSD
EURUSD
...
```

Tetapi default configuration dapat:

```text
XAUUSD
```

---

# 56. TIMEFRAME ABSTRACTION

Mendukung:

```text
M1
M5
M15
M30
H1
H4
D1
```

Strategy menentukan timeframe yang digunakan.

---

# 57. MARKET REGIME ENGINE

Deterministic engine mengklasifikasikan:

```text
TREND
RANGE
HIGH_VOLATILITY
LOW_VOLATILITY
BREAKOUT
UNKNOWN
```

Agent kemudian menggunakan regime tersebut.

---

# 58. STRATEGY ENGINE

Strategy harus modular.

Contoh:

```text
Strategy
├── Trend Following
├── Pullback
├── Breakout
├── Mean Reversion
└── Custom
```

AI tidak boleh mengubah strategy production secara langsung.

---

# 59. STRATEGY VERSIONING

Setiap strategy:

```text
v1
v2
v3
```

memiliki:

- parameters;
- backtest;
- performance;
- status;
- created_at;
- approved_at.

---

# 60. EXPERIMENT PIPELINE

```text
Idea
 ↓
Hypothesis
 ↓
Experiment
 ↓
Backtest
 ↓
Validation
 ↓
Paper
 ↓
Approval
 ↓
Production
```

---

# 61. NO SELF-MODIFICATION WITHOUT GATE

AI boleh menyarankan:

> "Parameter ADX sebaiknya 25 → 27."

Tetapi tidak boleh langsung mengubah production.

Harus:

```text
Proposal
 ↓
Experiment
 ↓
Validation
 ↓
Human approval / policy approval
 ↓
Deploy
```

---

# 62. NOTIFICATION SYSTEM

Support:

- Telegram;
- Web notification;
- Email;
- future Discord.

Alert types:

```text
Trade Opened
Trade Closed
Risk Warning
Kill Switch
System Error
LLM Failure
Broker Error
Daily Summary
```

---

# 63. TELEGRAM CONTROL

Future integration:

```text
/status
/positions
/risk
/strategy
/pause
/resume
/kill
```

Critical action harus meminta confirmation.

---

# 64. SYSTEM HEALTH

Dashboard harus menunjukkan:

```text
MT5 = ONLINE
Database = ONLINE
AI Gateway = ONLINE
Agent Router = ONLINE
Risk Engine = ONLINE
Execution = ONLINE
```

---

# 65. ERROR HANDLING

Setiap subsystem harus memiliki:

```text
timeout
retry
fallback
circuit breaker
logging
alert
```

Tidak boleh ada infinite retry.

---

# 66. QUEUE SYSTEM

Agent tasks harus dapat masuk queue.

Contoh:

```text
Event
 ↓
Queue
 ↓
Agent Worker
 ↓
Result
```

Hal ini mencegah banyak event membuat LLM overload.

---

# 67. PRIORITY SYSTEM

Event priority:

```text
CRITICAL
HIGH
MEDIUM
LOW
```

Contoh:

```text
KILL_SWITCH = CRITICAL
TRADE_SETUP = HIGH
TRADE_REVIEW = MEDIUM
REPORT = LOW
```

---

# 68. CONCURRENCY CONTROL

System harus membatasi:

```text
max concurrent agents
max concurrent LLM calls
max concurrent trade operations
```

---

# 69. DUPLICATE PREVENTION

System harus memiliki idempotency key.

Contoh:

```text
TRADE_SETUP:XAUUSD:M1:timestamp
```

Mencegah duplicate order akibat:

- retry;
- network failure;
- duplicate event.

---

# 70. STATE MACHINE

Trade lifecycle:

```text
DETECTED
↓
ANALYZING
↓
PROPOSED
↓
RISK_CHECK
↓
APPROVED
↓
EXECUTING
↓
OPEN
↓
MONITORING
↓
CLOSED
↓
REVIEWED
```

Jika gagal:

```text
REJECTED
```

atau:

```text
ERROR
```

---

# 71. DEVELOPMENT PHASES

## PHASE 0 — Architecture Foundation

Tasks:

- repository setup;
- monorepo structure;
- environment management;
- TypeScript configuration;
- Python service setup;
- database;
- logging;
- configuration;
- Docker/dev environment.

Acceptance:

- semua service dapat dijalankan;
- health check tersedia.

---

# PHASE 1 — MT5 CONNECTOR

Tasks:

1. MT5 connection.
2. Account info.
3. Symbol info.
4. Tick data.
5. Historical candles.
6. Positions.
7. Orders.
8. Send order.
9. Modify order.
10. Close position.
11. Error handling.
12. Connection recovery.

Acceptance:

- dapat membaca account;
- dapat membaca market;
- paper/demo order dapat diuji.

---

# PHASE 2 — MARKET DATA ENGINE

Tasks:

1. Data normalization.
2. OHLC storage.
3. Tick processing.
4. Multi-timeframe.
5. Spread calculation.
6. Session detection.
7. Data validation.
8. Missing data detection.

---

# PHASE 3 — INDICATOR ENGINE

Implement:

- EMA;
- SMA;
- RSI;
- ADX;
- ATR;
- MACD;
- volatility;
- trend detection.

Semua deterministic.

---

# PHASE 4 — MARKET REGIME ENGINE

Implement:

- trend;
- range;
- breakout;
- high volatility;
- low volatility;
- unknown.

---

# PHASE 5 — EVENT ENGINE

Implement:

- event schema;
- event detection;
- priority;
- deduplication;
- queue;
- event history.

---

# PHASE 6 — AGENT FRAMEWORK

Implement:

- agent registry;
- agent interface;
- agent lifecycle;
- agent state;
- agent task;
- output schema;
- timeout;
- retry;
- agent logging.

---

# PHASE 7 — AGENT ROUTER

Implement:

- event → agent mapping;
- priority;
- context filtering;
- concurrency;
- token budget;
- routing policy.

---

# PHASE 8 — 9ROUTER LLM LAYER

Implement:

- provider abstraction;
- 9Router adapter;
- model registry;
- free model configuration;
- fallback;
- timeout;
- token tracking;
- usage tracking.

---

# PHASE 9 — MARKET AGENTS

Implement:

1. Technical Analyst.
2. Structure Analyst.
3. Momentum Analyst.
4. Volatility Analyst.
5. News Agent.

Each agent harus:

- memiliki prompt sendiri;
- input schema;
- output schema;
- confidence;
- reasoning summary;
- error handling.

---

# PHASE 10 — RISK ENGINE

Implement:

- account risk;
- position risk;
- portfolio risk;
- drawdown;
- daily loss;
- exposure;
- spread;
- margin;
- max positions.

---

# PHASE 11 — MONEY MANAGEMENT

Implement:

- risk percentage;
- lot calculation;
- SL;
- TP;
- R:R;
- exposure.

---

# PHASE 12 — SUPERVISOR

Implement:

- task planning;
- agent selection;
- result aggregation;
- conflict detection;
- trade proposal;
- confidence;
- escalation.

---

# PHASE 13 — RISK GATE

Implement deterministic final validation.

Tidak boleh dilewati oleh Supervisor.

---

# PHASE 14 — EXECUTION ENGINE

Implement:

- order validation;
- order sending;
- confirmation;
- retry;
- duplicate prevention;
- position synchronization.

---

# PHASE 15 — POSITION MONITOR

Implement:

- monitoring;
- SL;
- TP;
- trailing;
- abnormal movement;
- risk changes;
- exit events.

---

# PHASE 16 — TRADE MEMORY

Implement:

- trade history;
- decision history;
- agent outputs;
- risk checks;
- execution;
- result.

---

# PHASE 17 — TRADE REVIEW

Implement:

- automatic review;
- win/loss analysis;
- MAE;
- MFE;
- timing;
- decision quality;
- execution quality.

---

# PHASE 18 — RESEARCH ENGINE

Implement:

- hypothesis;
- experiment;
- strategy version;
- backtest;
- metrics;
- comparison.

---

# PHASE 19 — PAPER TRADING

Implement:

- simulated account;
- simulated execution;
- simulated spread;
- simulated slippage;
- full AI pipeline.

Acceptance:

> system mampu berjalan tanpa real money.

---

# PHASE 20 — DEMO TRADING

System diuji dengan MT5 demo.

Target:

- stability;
- latency;
- execution;
- risk;
- agent consistency.

---

# PHASE 21 — DASHBOARD FOUNDATION

Implement:

- authentication;
- layout;
- API;
- WebSocket;
- dashboard shell.

---

# PHASE 22 — TRADING DASHBOARD

Implement:

- account overview;
- positions;
- orders;
- P/L;
- drawdown;
- risk.

---

# PHASE 23 — AI CONTROL CENTER

Implement:

- supervisor status;
- agent hierarchy;
- agent activity;
- current reasoning summary;
- agent errors;
- model usage.

---

# PHASE 24 — STRATEGY CENTER

Implement:

- strategies;
- versions;
- parameters;
- performance;
- activate/deactivate.

---

# PHASE 25 — RESEARCH CENTER

Implement:

- experiments;
- backtests;
- comparisons;
- research results.

---

# PHASE 26 — SYSTEM SETTINGS

Implement:

- account;
- risk;
- AI;
- models;
- execution;
- notifications;
- safety.

---

# PHASE 27 — OBSERVABILITY

Implement:

- logs;
- metrics;
- alerts;
- LLM usage;
- latency;
- error dashboard.

---

# PHASE 28 — SECURITY HARDENING

Implement:

- authentication;
- authorization;
- secret management;
- API security;
- audit logs;
- rate limiting;
- WebSocket security.

---

# PHASE 29 — PAPER → DEMO VALIDATION

Checklist:

```text
[ ] Risk tested
[ ] Kill switch tested
[ ] MT5 disconnect tested
[ ] LLM failure tested
[ ] Duplicate order tested
[ ] Spread spike tested
[ ] Drawdown tested
[ ] API failure tested
[ ] Database failure tested
[ ] Recovery tested
```

---

# PHASE 30 — LIVE READINESS

Live trading hanya boleh aktif apabila:

```text
[ ] Backtest passed
[ ] Forward test passed
[ ] Paper trading passed
[ ] Demo passed
[ ] Risk validation passed
[ ] Kill switch tested
[ ] Monitoring active
[ ] Alerts active
[ ] Backup active
[ ] Recovery tested
[ ] Manual emergency control available
```

---

# 72. TESTING STRATEGY

Testing dibagi:

## Unit Test

Untuk:

- indicators;
- risk;
- lot;
- exposure;
- order validation.

## Integration Test

Untuk:

- MT5;
- database;
- LLM;
- queue.

## Agent Test

Test:

- input;
- output;
- hallucination;
- invalid response;
- timeout.

## Simulation Test

Market scenarios:

- trending;
- ranging;
- crash;
- spike;
- spread explosion;
- connection loss.

---

# 73. CHAOS TESTING

Simulasikan:

```text
MT5 offline
9Router offline
database offline
network timeout
duplicate event
duplicate order
invalid LLM response
corrupt market data
```

System harus fail-safe.

---

# 74. AI SAFETY RULES

AI tidak boleh:

- mengubah risk limit;
- bypass risk gate;
- menghapus audit log;
- mengirim order tanpa validation;
- membuat unlimited retry;
- mengakses secret;
- mengubah production strategy secara langsung;
- menghapus historical data.

---

# 75. COST CONTROL

Prioritas:

```text
1. Deterministic processing
2. Event filtering
3. Small/free model
4. Structured context
5. Agent routing
6. Caching
7. Model escalation
8. Strong model only when necessary
```

---

# 76. TOKEN OPTIMIZATION

Jangan mengirim:

```text
entire history
entire agent conversation
entire database
```

Gunakan:

```text
snapshot
summary
structured state
relevant context
```

---

# 77. CACHING

Cache:

- indicator values;
- market regime;
- agent result;
- news result;
- repeated analysis.

Cache harus memiliki TTL.

---

# 78. AI REQUEST BUDGET

System memiliki global budget:

```text
daily token budget
daily LLM request budget
per-agent budget
per-event budget
```

Jika budget habis:

```text
AI trading disabled
```

atau:

```text
paper-only mode
```

sesuai konfigurasi.

---

# 79. UX PRINCIPLE

Dashboard tidak boleh terasa seperti terminal AI mentah.

User harus melihat:

```text
WHAT HAPPENED
WHY
WHAT SYSTEM DECIDED
WHAT RISK CHECKED
WHAT HAPPENS NEXT
```

Bukan seluruh chain-of-thought.

---

# 80. SYSTEM TIMELINE

Dashboard menyediakan timeline:

```text
Market Event
    ↓
Agent Activation
    ↓
Analysis
    ↓
Supervisor Decision
    ↓
Risk Gate
    ↓
Execution
    ↓
Position
    ↓
Result
```

---

# 81. AGENT STATUS MODEL

Setiap agent:

```text
IDLE
QUEUED
WORKING
WAITING
COMPLETED
FAILED
BLOCKED
DISABLED
```

---

# 82. SUPERVISOR STATUS MODEL

```text
OBSERVING
ANALYZING
DELEGATING
WAITING_FOR_AGENT
RESOLVING_CONFLICT
PROPOSING_TRADE
WAITING_RISK
EXECUTING
MONITORING
PAUSED
```

---

# 83. IMPORTANT DESIGN DECISION

**Tidak semua agent harus berupa LLM.**

Contoh:

```text
Risk Engine        = Code
Money Management   = Code
Execution Engine   = Code
Indicator Engine   = Code
Market Data        = Code
```

Sedangkan:

```text
Technical Analyst  = LLM
Structure Analyst  = LLM
News Analyst       = LLM
Supervisor         = LLM
Researcher         = LLM
```

---

# 84. INITIAL MVP

MVP tidak perlu seluruh architecture.

MVP:

```text
MT5
 ↓
Market Data
 ↓
Indicators
 ↓
Event Engine
 ↓
Supervisor
 ↓
Technical Agent
 ↓
Risk Engine
 ↓
Risk Gate
 ↓
Paper Execution
```

Setelah stabil:

```text
+ Structure Agent
+ Momentum Agent
+ Portfolio Agent
+ Position Monitor
+ Research
+ Dashboard
```

---

# 85. MVP SUCCESS CRITERIA

MVP dianggap berhasil jika:

1. MT5 dapat terhubung.
2. Market data diterima.
3. Indicator engine berjalan.
4. Event terdeteksi.
5. Supervisor dapat membuat task.
6. Specialist dapat dipanggil.
7. Output terstruktur.
8. Risk engine memvalidasi.
9. Risk Gate dapat reject.
10. Paper trade dapat dieksekusi.
11. Semua event tersimpan.
12. Token usage tercatat.
13. LLM failure tidak menyebabkan unsafe trade.
14. Duplicate order dapat dicegah.

---

# 86. PRODUCTION ARCHITECTURE TARGET

Target akhir:

```text
                    WEB / MOBILE
                         │
                    CONTROL API
                         │
                  EVENT / QUEUE BUS
                         │
                    SUPERVISOR
                         │
       ┌─────────────────┼─────────────────┐
       │                 │                 │
   MARKET DEPT       RISK DEPT       RESEARCH DEPT
       │                 │                 │
    Agents            Agents            Agents
       │                 │                 │
       └─────────────────┼─────────────────┘
                         │
                    DECISION STATE
                         │
                     RISK GATE
                         │
                  EXECUTION ENGINE
                         │
                        MT5
                         │
                    TRADE MONITOR
                         │
                    TRADE REVIEW
                         │
                    RESEARCH LOOP
                         │
                   STRATEGY UPDATE
```

---

# 87. LONG-TERM AUTONOMOUS LOOP

Sistem akhirnya membentuk:

```text
OBSERVE
   ↓
UNDERSTAND
   ↓
ANALYZE
   ↓
DELIBERATE
   ↓
RISK CHECK
   ↓
ACT
   ↓
MONITOR
   ↓
REVIEW
   ↓
LEARN
   ↓
RESEARCH
   ↓
VALIDATE
   ↓
IMPROVE
   ↓
OBSERVE AGAIN
```

Namun:

> **LEARN tidak berarti AI bebas mengubah live trading strategy.**

Perubahan harus melalui validation pipeline.

---

# 88. DEFINITION OF DONE

Sebuah task dianggap selesai hanya jika:

```text
[ ] Implementation selesai
[ ] Unit test selesai
[ ] Integration test selesai jika relevan
[ ] Error handling tersedia
[ ] Logging tersedia
[ ] Configuration tersedia
[ ] Documentation tersedia
[ ] Security diperiksa
[ ] Tidak merusak module lain
[ ] Acceptance criteria terpenuhi
```

---

# 89. OPEN CODE DEVELOPMENT RULE

OpenCode harus:

1. membaca PRD sebelum coding;
2. memeriksa repository terlebih dahulu;
3. tidak mengulang module yang sudah ada;
4. menggunakan existing implementation apabila sesuai;
5. tidak menghapus logic yang masih digunakan;
6. membuat perubahan modular;
7. menjalankan test setelah perubahan;
8. memperbaiki error sebelum lanjut;
9. melakukan commit per logical task;
10. tidak mengklaim task selesai tanpa verification.

---

# 90. TASK EXECUTION RULE

Jangan mengerjakan:

```text
PHASE 1 → PHASE 30
```

dalam satu langkah.

Gunakan:

```text
Phase
 ↓
Task
 ↓
Subtask
 ↓
Implementation
 ↓
Test
 ↓
Verification
 ↓
Checkpoint
 ↓
Next task
```

---

# 91. DEPENDENCY RULE

Contoh:

```text
MT5 Connector
      ↓
Market Data
      ↓
Indicators
      ↓
Events
      ↓
Agents
      ↓
Supervisor
      ↓
Risk
      ↓
Execution
```

OpenCode tidak boleh mengerjakan layer yang bergantung pada layer yang belum stabil kecuali menggunakan mock/interface.

---

# 92. MOCK-FIRST DEVELOPMENT

Untuk development:

```text
Mock MT5
Mock LLM
Mock Market Data
Mock Broker
```

digunakan agar subsystem dapat dites secara independen.

---

# 93. FUTURE SCALABILITY

Architecture harus memungkinkan:

```text
1 symbol
→ multiple symbols

1 account
→ multiple accounts

1 broker
→ multiple brokers

1 strategy
→ multiple strategies

1 Supervisor
→ multiple Supervisors

1 user
→ multiple users
```

---

# 94. FUTURE SaaS ARCHITECTURE

Jika nantinya dijadikan SaaS:

```text
Tenant
 ├── Users
 ├── Accounts
 ├── Brokers
 ├── Strategies
 ├── Agents
 ├── Risk Policies
 ├── LLM Policies
 └── Trading Data
```

Setiap tenant harus terisolasi.

---

# 95. FINAL ARCHITECTURAL PRINCIPLE

Sistem ini bukan:

```text
"ChatGPT yang trading."
```

Tetapi:

```text
Trading Infrastructure
+
Deterministic Quant Engine
+
Multi-Agent AI
+
Risk Management
+
Execution Engine
+
Research System
+
Observability
+
Control Plane
```

LLM merupakan **reasoning component**, bukan keseluruhan sistem.

---

# 96. MASTER IMPLEMENTATION CHECKLIST

## FOUNDATION

- [ ] Repository
- [ ] Architecture
- [ ] Environment
- [ ] Configuration
- [ ] Logging
- [ ] Database
- [ ] Queue
- [ ] Health checks

## MT5

- [ ] Connection
- [ ] Account
- [ ] Symbol
- [ ] Tick
- [ ] OHLC
- [ ] Position
- [ ] Order
- [ ] Execution
- [ ] Recovery

## MARKET

- [ ] Indicators
- [ ] Structure
- [ ] Volatility
- [ ] Regime
- [ ] Events

## AI

- [ ] Agent framework
- [ ] Agent registry
- [ ] Router
- [ ] Supervisor
- [ ] Context manager
- [ ] Memory
- [ ] Token budget
- [ ] Model registry
- [ ] 9Router
- [ ] Fallback
- [ ] Escalation

## RISK

- [ ] Account risk
- [ ] Position risk
- [ ] Portfolio risk
- [ ] Drawdown
- [ ] Money management
- [ ] Risk Gate
- [ ] Kill switch

## EXECUTION

- [ ] Proposal
- [ ] Validation
- [ ] Order
- [ ] Confirmation
- [ ] Position monitor
- [ ] Duplicate prevention

## RESEARCH

- [ ] Trade review
- [ ] Hypothesis
- [ ] Experiment
- [ ] Backtest
- [ ] Forward test
- [ ] Strategy versioning

## UI

- [ ] Dashboard
- [ ] Market
- [ ] Positions
- [ ] AI organization
- [ ] Agent activity
- [ ] Risk
- [ ] Strategy
- [Research
- [ ] Settings
- [ ] Logs

## SECURITY

- [ ] Auth
- [ ] RBAC
- [ ] Secrets
- [ ] API security
- [ ] Audit log
- [ ] Rate limiting

## PRODUCTION

- [ ] Monitoring
- [ ] Backup
- [ ] Recovery
- [ ] Kill switch
- [ ] Paper trading
- [ ] Demo
- [ ] Live readiness