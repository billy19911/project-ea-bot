# UI/UX PRD V2 — Xynn Autonomous Trading Command Center

**Project:** project-ea-bot  
**Document:** UI/UX Product Requirements Document  
**Version:** 2.0  
**Status:** Proposed / Implementation Specification  
**Primary UI Stack:** Next.js + React + TypeScript  
**Styling:** Tailwind CSS  
**Component Foundation:** shadcn/ui  
**Charting:** Recharts / TradingView-style chart component where appropriate  
**Typography Direction:** Geist-style system  
**Primary Usage:** Desktop / Laptop  
**Secondary Usage:** Tablet / Mobile  
**Design Target:** Premium, calm, information-dense, fast, understandable, non-sloppy

---

# 1. PURPOSE

Dokumen ini mendefinisikan ulang UI dan UX untuk Xynn Autonomous Trading System.

Targetnya bukan membuat dashboard admin biasa dan bukan membuat "AI dashboard" penuh gradient/neon.

Produk harus terasa seperti perpaduan:

```text
Professional Trading Terminal
+
Autonomous AI Operations Center
+
Risk Control Room
+
Research Laboratory
```

UI harus memungkinkan user menjawab pertanyaan berikut hanya dalam beberapa detik:

1. Apakah sistem sehat?
2. Apakah MT5 benar-benar tersambung?
3. Apakah market data masih fresh?
4. Apakah trading sedang aktif atau diblokir?
5. Apakah ada posisi terbuka?
6. Berapa risk yang sedang digunakan?
7. Kalau tidak trading, kenapa?
8. Kalau trading, keputusan dibuat berdasarkan apa?
9. Kalau ada mismatch, apakah broker dan internal system sama?
10. Apa yang sedang dipelajari sistem?
11. Strategy versi berapa yang sedang aktif?
12. Apakah perubahan strategy sudah tervalidasi?

---

# 2. UX PHILOSOPHY

## 2.1 Design Principle

Primary principle:

> **Clarity over decoration.**

Prioritaskan:

```text
INFORMATION HIERARCHY
→ STATUS
→ ACTION
→ CONTEXT
→ DETAIL
```

Bukan:

```text
DECORATION
→ GRADIENT
→ GLOW
→ CARD
→ INFORMATION
```

---

## 2.2 Product Personality

Produk harus terasa:

- profesional;
- tenang;
- presisi;
- cepat;
- terpercaya;
- teknikal tetapi tetap mudah dipahami;
- premium tanpa terlihat berlebihan.

Produk tidak boleh terasa:

- seperti crypto casino;
- seperti template AI dashboard;
- seperti admin CRUD;
- terlalu neon;
- terlalu rounded;
- terlalu banyak badge;
- terlalu banyak modal;
- penuh animasi;
- penuh angka tanpa konteks.

---

# 3. PRIMARY UX GOALS

## G1 — Situational Awareness

Dalam 3–5 detik user bisa memahami kondisi sistem.

## G2 — Fast Decision Inspection

User dapat membuka alasan trade/no-trade tanpa berpindah melalui banyak halaman.

## G3 — Safe Controls

Control yang dapat mempengaruhi trading harus jelas, berlapis, dan sulit salah klik.

## G4 — Operational Confidence

UI harus menunjukkan apakah data benar-benar tersedia, fresh, connected, atau sedang degraded.

## G5 — Explainability

User dapat memahami:

```text
event
→ analysis
→ decision
→ risk gate
→ execution
→ broker result
```

tanpa menampilkan private chain-of-thought.

## G6 — Research Clarity

User dapat membedakan:

```text
live trading
vs
historical research
vs
hypothesis
vs
validated strategy
```

---

# 4. CORE DESIGN RULES

## 4.1 No Fake Health

Tidak boleh menampilkan:

```text
HEALTHY
```

jika backend belum memberikan health result.

Gunakan:

```text
Healthy
Degraded
Stale
Disconnected
Unavailable
Not configured
Unknown
```

sesuai state.

---

## 4.2 No Fake Zero

Jika data belum tersedia:

```text
—
```

atau:

```text
No data
```

bukan:

```text
0
```

Contoh:

Jika performance belum dihitung:

```text
Win rate
—
Insufficient data
```

---

## 4.3 State > Color

Jangan mengandalkan warna saja.

Contoh:

```text
● HEALTHY
```

tetap harus memiliki text.

Bukan sekadar:

```text
●
```

---

## 4.4 Action Hierarchy

Tombol harus jelas berdasarkan severity.

```text
Primary
Secondary
Tertiary
Destructive
Emergency
```

Jangan semua button terlihat sama penting.

---

# 5. VISUAL DIRECTION

## 5.1 Color System

Base:

```text
Background  #09090B
Surface     #111318
Surface 2   #151820
Surface 3   #1A1E27
Border      rgba(255,255,255,0.08)
Border Subtle rgba(255,255,255,0.05)
Text        high contrast neutral
Text Muted  secondary neutral
```

Semantic colors:

```text
Success     green family
Warning     amber family
Danger      red family
Info        blue family
Neutral     gray family
```

Gunakan warna semantic hanya saat ada makna.

---

## 5.2 Typography

Direction:

```text
Geist Sans
Geist Mono
```

Typography hierarchy:

```text
Page Title      24–32px
Section Title   16–20px
Body            13–15px
Secondary       12–13px
Caption         11–12px
Numeric Data    Mono
```

Trading numbers:

```text
price
PnL
lot
risk
drawdown
spread
latency
```

menggunakan tabular/monospace numerals.

---

## 5.3 Radius

Gunakan restrained radius:

```text
Card       10–14px
Input      8–10px
Button     8–10px
Popover    10–12px
Modal      14–18px
```

Hindari seluruh UI menjadi pill/rounded-24.

---

## 5.4 Elevation

Gunakan border dan subtle elevation.

Tidak semua card membutuhkan shadow.

Priority:

```text
Border
→ Contrast
→ Small shadow
```

bukan:

```text
Huge shadow
→ glow
→ gradient
```

---

# 6. LAYOUT SYSTEM

## Desktop

Target viewport:

```text
1440×900
1600×1000
1920×1080
```

Layout:

```text
Sidebar
+
Topbar
+
Content Workspace
+
Optional Inspector
```

---

# 7. GLOBAL SHELL

```text
┌─────────────────────────────────────────────────────────────────────┐
│ Logo │ Environment │ MT5 │ Symbol │ Risk │ Time │ Alerts │ User   │
├───────────────┬─────────────────────────────────────────────────────┤
│               │                                                     │
│ NAVIGATION    │                 MAIN WORKSPACE                      │
│               │                                                     │
│               │                                                     │
│               │                                                     │
└───────────────┴─────────────────────────────────────────────────────┘
```

## Sidebar width

Expanded:

```text
240–260px
```

Collapsed:

```text
64–72px
```

Sidebar state harus persistent.

---

# 8. GLOBAL TOPBAR

Topbar harus compact.

Contents:

```text
Xynn
PROD
MT5 Connected
XAUUSD
Risk: NORMAL
Equity
Alerts
Command Search
Profile
```

Contoh:

```text
Xynn   PROD ●   MT5 ●   XAUUSD
Equity $10,482   Risk NORMAL
22:41 WIB        🔔   ⌘K
```

## UX

Environment harus selalu terlihat.

Untuk LIVE:

```text
PROD
```

harus visually distinct.

---

# 9. COMMAND PALETTE

Shortcut:

```text
⌘K / Ctrl+K
```

Search:

```text
Go to Overview
Open Risk Center
Open Position
Open Decision
Open Strategy
View Incident
Run Reconciliation
```

Juga support recent actions.

---

# 10. INFORMATION ARCHITECTURE

## COMMAND

```text
Overview
```

## MONITOR

```text
Market
Positions
Orders
Trade History
```

## INTELLIGENCE

```text
Agents
Decisions
Market Context
```

## RISK

```text
Risk Center
Reconciliation
Incidents
```

## RESEARCH

```text
Performance
Backtest
Walk Forward
Monte Carlo
Strategy Lab
Learning
```

## SYSTEM

```text
System Health
Execution
Models
Audit
Settings
```

---

# 11. NAVIGATION UX

Menu groups harus:

- jelas;
- ringkas;
- punya icon konsisten;
- tidak terlalu banyak nested levels.

Maximum recommended nesting:

```text
2 levels
```

Avoid:

```text
Research
  → Strategy
      → Experiment
          → Run
              → Result
```

Gunakan tabs di dalam halaman.

---

# 12. PAGE 01 — OVERVIEW

## Purpose

Cockpit utama.

User harus bisa menjawab:

```text
System sehat?
Trading aktif?
Ada posisi?
Risk aman?
Ada incident?
Bot sedang berpikir apa?
```

## Layout

```text
┌──────────────────────────────┬────────────────────────────┐
│ SYSTEM STATUS                │ ACTIVE DECISION            │
│                              │                            │
├──────────────────────────────┴────────────────────────────┤
│                                                           │
│                    MARKET CHART                            │
│                                                           │
├───────────────────────┬───────────────────────────────────┤
│ POSITION SUMMARY      │ RISK SUMMARY                      │
├───────────────────────┴───────────────────────────────────┤
│ EVENT / ACTIVITY TIMELINE                                 │
└───────────────────────────────────────────────────────────┘
```

---

# 13. OVERVIEW — SYSTEM STATUS

Display:

```text
MT5
Market Data
Risk Gate
Reconciliation
Supervisor
Execution
Database
```

Each:

```text
label
status
last updated
```

Example:

```text
MT5             ● Connected
Market Data     ● Healthy
Risk Gate       ● Ready
Reconciliation  ● Matched
Supervisor      ● Running
Execution       ● Ready
```

Clicking status opens context.

---

# 14. OVERVIEW — ACTIVE DECISION

This panel is the most important intelligence surface.

Example:

```text
ACTIVE DECISION

XAUUSD
BUY CANDIDATE

Technical       BUY
Structure       BUY
Momentum        NEUTRAL
Volatility      HIGH
Risk            PASS

Decision
WAIT

Reason
Momentum confirmation is insufficient.

[View Decision]
```

No chatbot UI required.

---

# 15. OVERVIEW — MARKET CHART

Chart should support:

```text
M1
M5
M15
M30
H1
```

Controls:

```text
timeframe
indicators
positions
entry
SL
TP
signals
events
```

Chart must avoid visual overload.

Use contextual overlays only.

---

# 16. OVERVIEW — POSITION SUMMARY

Show only active information:

```text
OPEN POSITIONS 1

XAUUSD BUY
0.02

+$11.60
+1.45R
```

Click opens position inspector.

---

# 17. OVERVIEW — RISK SUMMARY

Show:

```text
Daily P&L
Daily Loss Limit
Drawdown
Open Risk
Exposure
Circuit Breaker
```

Use progress only when appropriate.

Do not use giant gauges by default.

---

# 18. OVERVIEW — EVENT TIMELINE

Chronological feed:

```text
22:40:58
Market update

22:41:01
Agents evaluated

22:41:02
Supervisor decision

22:41:02
Risk Gate PASS

22:41:03
Entry not executed
```

Each event can expand.

---

# 19. PAGE 02 — MARKET

## Purpose

Professional market inspection.

Layout:

```text
┌────────────────────────────────────────────────────────┐
│ Symbol / Timeframe / Data Status                      │
├────────────────────────────────────────────────────────┤
│                                                        │
│                     CHART                              │
│                                                        │
├─────────────────────────┬──────────────────────────────┤
│ Market Context          │ Signals                      │
└─────────────────────────┴──────────────────────────────┘
```

---

# 20. MARKET — DATA HEALTH

Display:

```text
Tick age
Candle age
Spread age
Feed latency
Connection
```

Example:

```text
Market Data
● HEALTHY

Tick age        320ms
Candle age      1.2s
Spread age      320ms
Feed latency    84ms
```

If stale:

```text
● STALE

Last tick
38.4s ago

New entries blocked.
```

---

# 21. MARKET — MARKET CONTEXT

Structured:

```text
Trend
Structure
Momentum
Volatility
Session
Liquidity
Spread
```

Use neutral visual language.

---

# 22. PAGE 03 — POSITIONS

## Purpose

Fast monitoring and inspection.

Table columns:

```text
Symbol
Side
Size
Entry
Current
SL
TP
P&L
R
Duration
Strategy
Status
```

Table behavior:

- sortable;
- filterable;
- sticky header;
- row hover;
- keyboard navigation;
- click row → inspector.

---

# 23. POSITION INSPECTOR

Use right-side panel instead of navigation.

Sections:

```text
Position
Execution
Risk
Market
Decision
Timeline
```

Example:

```text
POSITION

XAUUSD BUY
0.02 LOT

Entry      3652.40
Current    3658.20
SL         3648.40
TP         3660.40

P&L        +$11.60
R          +1.45R
Duration   17m
```

---

# 24. PAGE 04 — ORDERS

States:

```text
Intent
Submitted
Acknowledged
Partial
Filled
Rejected
Cancelled
Unknown
```

Unknown harus visually prominent.

Click order → order inspector.

---

# 25. ORDER INSPECTOR

Show:

```text
Intent ID
Decision ID
Strategy Version
Risk Approval
Broker
Execution
Retry History
Reconciliation
```

Important UX:

```text
UNKNOWN
```

harus menjelaskan:

```text
"Broker state has not yet been confirmed."
```

---

# 26. PAGE 05 — TRADE HISTORY

Provide:

```text
Date range
Symbol
Strategy
Direction
Session
Regime
Result
```

Columns:

```text
Time
Symbol
Side
Entry
Exit
P&L
R
Duration
Strategy
Reason
```

Export capability may be added later.

---

# 27. PAGE 06 — AGENTS

## Purpose

Operational AI monitoring.

Grid/list:

```text
Technical Agent
Structure Agent
Momentum Agent
Volatility Agent
News/Fundamental
Risk Agents
Supervisor
Review Agent
```

Each card:

```text
Status
Last run
Latency
Latest conclusion
Failure count
Model
```

Example:

```text
Technical Agent
● RUNNING

Last run     22:41:02
Latency      183ms
Conclusion   BUY
Model        ...
```

---

# 28. AGENT DETAIL

Tabs:

```text
Overview
Runs
Errors
Model
Prompt Version
Performance
```

Do not expose private chain-of-thought.

Expose:

```text
structured output
decision factors
confidence
validation result
```

---

# 29. PAGE 07 — DECISIONS

This is the central explainability page.

List:

```text
Decision ID
Time
Symbol
Signal
Risk
Execution
Outcome
```

Example:

```text
#182
XAUUSD
BUY → WAIT
Risk PASS
Not Executed
```

---

# 30. DECISION DETAIL

Layout:

```text
HEADER
↓
MARKET SNAPSHOT
↓
AGENT CONSENSUS
↓
SUPERVISOR DECISION
↓
RISK GATE
↓
EXECUTION
↓
BROKER RESULT
```

Use expandable sections.

---

# 31. WHY NO TRADE UX

This must be a first-class component.

States:

```text
NO SIGNAL
WAITING
BLOCKED
RISK BLOCKED
DATA BLOCKED
EXECUTION BLOCKED
```

Example:

```text
NO TRADE

Signal
BUY

Blocked by
Spread threshold

Risk Gate
BLOCKED

Next evaluation
Next M5 close
```

Primary CTA:

```text
View blocking condition
```

---

# 32. PAGE 08 — MARKET CONTEXT

Structured context:

```text
Trend
Structure
Momentum
Volatility
Session
News
Spread
Liquidity
```

Show timestamps and freshness.

No stale context should appear as current.

---

# 33. PAGE 09 — RISK CENTER

## Layout

```text
┌────────────────────┬───────────────────────────┐
│ RISK STATUS        │ CIRCUIT BREAKER           │
├────────────────────┴───────────────────────────┤
│                                               │
│ Risk Metrics                                  │
│                                               │
├──────────────────────────┬────────────────────┤
│ Exposure                 │ Drawdown           │
└──────────────────────────┴────────────────────┘
```

---

# 34. RISK STATUS UX

Display:

```text
Current risk mode
Daily loss
Drawdown
Open risk
Exposure
Margin
```

Use simple hierarchy.

Example:

```text
RISK MODE

NORMAL

Open Risk
$18.20

Daily Loss
$31 / $200

Drawdown
2.8% / 10%
```

---

# 35. CIRCUIT BREAKER UX

Levels:

```text
NORMAL
CAUTION
RISK REDUCED
ENTRY BLOCKED
EMERGENCY
HALTED
```

UI:

```text
LEVEL 2
ENTRY BLOCKED

Trigger
Reconciliation mismatch

Detected
22:43:18
```

Actions:

```text
[View Incident]
[Reconcile]
```

---

# 36. SAFE ACTION DESIGN

Critical actions need:

```text
confirmation
reason
scope
current state
expected consequence
```

For emergency action:

```text
EMERGENCY CONTROL

Flatten positions

This will request closure of
ALL LIVE POSITIONS.

Environment
PRODUCTION

[Cancel]
[Confirm Emergency Action]
```

No ambiguous:

```text
[YES]
```

---

# 37. PAGE 10 — RECONCILIATION

Header:

```text
BROKER ↔ SYSTEM
● MATCHED
Last check 14s ago
```

Data:

```text
Broker positions
Internal positions
Orders
Deals
Account
```

Mismatch UI:

```text
⚠ MISMATCH

XAUUSD
Broker       0.02 BUY
Internal     0.00

Impact
New entries blocked
```

---

# 38. RECONCILIATION FILTERS

```text
All
Matched
Warning
Critical
Resolved
Unresolved
```

Each mismatch gets:

```text
severity
detected_at
component
action
resolution
```

---

# 39. PAGE 11 — INCIDENTS

Incident list:

```text
Severity
Status
Component
Time
Message
Recovery
```

States:

```text
OPEN
ACKNOWLEDGED
MITIGATING
RESOLVED
```

Incident detail timeline:

```text
Detected
Blocked
Action
Recovery
Resolved
```

---

# 40. PAGE 12 — PERFORMANCE

This page belongs to research.

Top filters:

```text
date
symbol
strategy
environment
```

Primary metrics:

```text
Net P&L
Profit Factor
Expectancy
Win Rate
Max Drawdown
Average R
Trades
```

Always show sample size.

Example:

```text
Win Rate
61.2%

N = 284 trades
```

---

# 41. PERFORMANCE BREAKDOWN

Tabs:

```text
Overview
By Hour
By Session
By Regime
By Setup
By Direction
By Strategy
By Symbol
```

Use charts only when they answer a question.

---

# 42. PAGE 13 — BACKTEST

Backtest should behave like an experiment workspace.

Flow:

```text
SELECT STRATEGY
↓
SET DATA
↓
SET EXECUTION MODEL
↓
RUN
↓
RESULT
```

Config:

```text
symbol
timeframe
period
spread model
slippage
commission
swap
execution delay
capital
risk policy
```

---

# 43. BACKTEST RESULT UX

Header:

```text
BACKTEST
Strategy v12
2024-01-01 → 2025-01-01
```

Results:

```text
Net Profit
Profit Factor
Expectancy
Max Drawdown
Win Rate
Trade Count
```

Then:

```text
Equity Curve
Drawdown
Trade Distribution
Session Breakdown
```

---

# 44. PAGE 14 — WALK-FORWARD

Visualize train/test windows.

```text
TRAIN ██████████
TEST            ███

TRAIN      ██████████
TEST                 ███
```

Table:

```text
Window
Train Period
Test Period
PF
DD
Expectancy
Status
```

---

# 45. PAGE 15 — MONTE CARLO

Show:

```text
Simulations
Median
5th percentile
95th percentile
Worst drawdown
Max loss streak
```

Visualization:

```text
distribution
+
highlight percentile boundaries
```

Never display a single simulated result as certainty.

---

# 46. PAGE 16 — STRATEGY LAB

Primary object:

```text
Strategy Version
```

Lifecycle visible:

```text
DRAFT
EXPERIMENT
BACKTESTED
WFA PASSED
PAPER
DEMO
CANDIDATE
APPROVED
PRODUCTION
```

Visual timeline.

---

# 47. STRATEGY DETAIL

Tabs:

```text
Overview
Parameters
Evidence
Backtest
Walk Forward
Monte Carlo
Paper
Demo
Production
Changes
Lessons
Audit
```

---

# 48. STRATEGY COMPARISON UX

Compare up to 3 versions.

Rows:

```text
Risk
Return
PF
Expectancy
DD
Trade Count
WFA
Monte Carlo
Paper
Demo
```

Never hide that results come from different periods.

---

# 49. PAGE 17 — LEARNING

Do not make vague "AI learned 93%" dashboards.

Use evidence.

Header:

```text
LEARNING ENGINE

248 reviewed trades
32 lessons
7 hypotheses
3 active experiments
```

---

# 50. LEARNING — OBSERVATIONS

Example:

```text
HIGH VOL + NY OPEN

N = 83

Observed outcome
Lower expectancy

Status
OBSERVATION
```

---

# 51. LEARNING — HYPOTHESES

Example:

```text
H-023

Hypothesis
Entry timing may degrade
during volatility transitions.

Evidence
83 trades

Status
UNDER TEST
```

---

# 52. LEARNING — EXPERIMENT

Display pipeline:

```text
Observation
↓
Hypothesis
↓
Backtest
↓
Walk Forward
↓
Paper
↓
Decision
```

Possible statuses:

```text
INSUFFICIENT DATA
FAILED
VALIDATED
REJECTED
```

---

# 53. PAGE 18 — EXECUTION QUALITY

Metrics:

```text
Average Slippage
P95 Slippage
Fill Latency
Reject Rate
Partial Fill Rate
```

Breakdowns:

```text
hour
session
symbol
spread bucket
volatility
strategy
```

---

# 54. PAGE 19 — SYSTEM HEALTH

Health map:

```text
Backend
Python
Node
Database
Redis
MT5
Market Feed
LLM Gateway
Telegram
Scheduler
```

Each:

```text
status
latency
last success
error rate
```

---

# 55. PAGE 20 — MODELS

Model registry:

```text
Provider
Model
Role
Status
Latency
Requests
Failure Rate
Token Usage
Fallback
```

States:

```text
ACTIVE
FALLBACK
DISABLED
DEPRECATED
```

---

# 56. PAGE 21 — AUDIT

Audit records:

```text
Time
Actor
Action
Object
Environment
Result
```

Actors:

```text
SYSTEM
SUPERVISOR
AGENT
USER
ADMIN
```

---

# 57. PAGE 22 — DECISION REPLAY

Premium feature.

Flow:

```text
Decision #182
↓
Replay
```

Timeline:

```text
Market Event
↓
Agent Runs
↓
Supervisor
↓
Risk Gate
↓
Execution
↓
Broker
↓
Position
```

Use stored snapshots.

Do not recompute the past decision against the current market.

---

# 58. PAGE 23 — SETTINGS

Sections:

```text
Environment
Broker / MT5
Symbols
Risk
Strategy
Agents
Models
Notifications
Security
Appearance
```

Settings that can affect safety must show scope.

Example:

```text
Max Daily Loss

Production

Protected setting
```

---

# 59. SAFE SETTING UX

For sensitive settings:

```text
Current
Proposed
Impact
Who changed
When
Reason
```

Require explicit confirmation.

---

# 60. LIVE ENVIRONMENT PROTECTION

When environment is LIVE:

Topbar:

```text
PRODUCTION
```

Use persistent visual distinction.

Dangerous controls require stronger confirmation.

Do not hide environment.

---

# 61. GLOBAL EMPTY STATES

Types:

## No Data

```text
No performance data
No trades found for this period.
```

## Not Configured

```text
Not configured
MT5 terminal is not armed.
```

## Insufficient Sample

```text
Insufficient sample
Need at least N trades.
```

## Unavailable

```text
Unavailable
Market feed cannot be reached.
```

## Loading

Use skeleton.

Do not show fake zeros.

---

# 62. LOADING UX

Initial load:

Use skeleton matching actual layout.

Avoid full-page spinner unless unavoidable.

For actions:

```text
Run backtest
→ button becomes
Running…
```

Show progress only if meaningful.

---

# 63. ERROR UX

Error should answer:

```text
What happened?
Why?
What is affected?
What can user do?
```

Example:

```text
Reconciliation failed

Broker data could not be fetched.

New entries remain blocked.

[Retry]
[View Health]
```

---

# 64. TOAST UX

Use toast only for:

```text
success
warning
background completion
```

Do not use toast for critical incidents only.

Critical incidents remain in persistent incident center.

---

# 65. MODAL POLICY

Avoid modal overuse.

Use:

```text
Drawer / Inspector
```

for details.

Use:

```text
Modal
```

only for:

- destructive action;
- confirmation;
- critical setting;
- focused workflow.

---

# 66. TABLE UX

Requirements:

- sticky header;
- density switch;
- pagination or virtualized list;
- sorting;
- filtering;
- column visibility;
- responsive fallback;
- keyboard navigation.

Density options:

```text
Comfortable
Compact
```

Default:

```text
Compact
```

for trading tables.

---

# 67. FILTER UX

Use persistent filter bar.

Example:

```text
Date
Symbol
Strategy
Session
Status
```

Filters should display active count.

```text
Filters (3)
```

---

# 68. SEARCH UX

Global search should locate:

```text
decision
trade
position
order
strategy
incident
agent
```

Search result should include type badge.

Example:

```text
#182  Decision
XAUUSD BUY
```

---

# 69. KEYBOARD UX

Desktop shortcuts:

```text
Ctrl/Cmd + K
G then O → Overview
G then M → Market
G then P → Positions
G then R → Risk
G then S → Strategy Lab
```

Do not conflict with browser shortcuts.

---

# 70. RESPONSIVE DESIGN

## 1440px+

Full layout:

```text
sidebar
main
optional inspector
```

## 1024–1439px

Sidebar collapse.

Inspector becomes overlay/drawer.

## 768–1023px

Two-column layouts become one/two flexible columns.

## <768px

Mobile priority:

```text
System Status
Risk
Positions
Alerts
Decision
```

Research pages should simplify.

---

# 71. MOBILE BOTTOM NAV

For mobile:

```text
Home
Positions
Risk
Alerts
More
```

Do not mirror desktop sidebar.

---

# 72. ACCESSIBILITY

Minimum target:

```text
WCAG 2.2 AA direction
```

Requirements:

- keyboard navigation;
- visible focus;
- semantic buttons;
- screen reader labels;
- sufficient contrast;
- no color-only status;
- reduced motion support;
- accessible tables;
- accessible charts with summary text.

---

# 73. MOTION DESIGN

Animation should communicate state change.

Allowed:

```text
fade
slide
number transition
pulse for live status
progress
```

Avoid:

```text
constant glow
background particles
large page transitions
excessive bouncing
```

Respect:

```text
prefers-reduced-motion
```

---

# 74. REALTIME UX

Use realtime only where useful:

```text
P&L
price
position state
health
alerts
execution
```

Avoid re-rendering entire page.

Update local data blocks independently.

---

# 75. REALTIME CONNECTION INDICATOR

Topbar should expose:

```text
LIVE
RECONNECTING
DEGRADED
OFFLINE
```

When websocket reconnects:

```text
Reconnected
Market data synchronized
```

Do not hide temporary disconnections.

---

# 76. NOTIFICATION CENTER

Notification categories:

```text
Trade
Risk
Reconciliation
System
Research
Incident
```

Priority:

```text
INFO
WARNING
CRITICAL
```

Critical alerts are sticky until acknowledged/resolved.

---

# 77. USER PREFERENCES

Persist:

```text
sidebar state
theme
table density
chart timeframe
visible columns
filters
favorite pages
timezone display
```

Never persist security credentials in client local state unless explicitly designed securely.

---

# 78. THEME

Primary theme:

```text
Dark
```

Optional future:

```text
Light
```

Dark theme must be designed as first-class, not simply inverted.

---

# 79. PREMIUM VISUAL DETAILS

Use subtle quality signals:

```text
1px borders
precise spacing
numeric alignment
consistent line-height
small status indicators
smooth hover states
clean icons
excellent empty states
stable layout
```

Premium feel should come from precision.

---

# 80. ICONOGRAPHY

Use one icon system consistently.

Recommended:

```text
Lucide
```

Do not mix several icon packs.

Icons should generally be:

```text
16px / 18px / 20px
```

---

# 81. SPACING SYSTEM

Use 4px base scale.

Common:

```text
4
8
12
16
20
24
32
40
48
64
```

Avoid arbitrary spacing.

---

# 82. COMPONENT ARCHITECTURE

Create internal UI primitives:

```text
XynnUI
├── AppShell
├── Sidebar
├── Topbar
├── StatusIndicator
├── EnvironmentBadge
├── DataFreshness
├── RiskBadge
├── DecisionBadge
├── Metric
├── MetricGroup
├── PnLValue
├── PositionRow
├── OrderRow
├── AgentCard
├── DecisionPanel
├── DecisionTimeline
├── EventTimeline
├── Inspector
├── DataTable
├── FilterBar
├── ChartPanel
├── EvidencePanel
├── StrategyLifecycle
├── ReconciliationState
├── CircuitBreaker
├── IncidentCard
├── EmptyState
├── ErrorState
├── LoadingState
└── CommandPalette
```

---

# 83. COMPONENT RULE

No page should invent a one-off component for a recurring pattern.

Example:

Do not build:

```text
RiskCardA
RiskCardB
RiskCardC
```

if they represent the same information pattern.

Create:

```text
RiskMetric
```

and use variants.

---

# 84. DESIGN TOKENS

Create central token layer for:

```text
colors
spacing
radius
font
font-size
shadow
z-index
motion
breakpoints
```

No hardcoded values scattered across components.

---

# 85. DATA CONTRACT FOR UI

UI must not guess data.

For each API:

```text
value
status
updated_at
source
```

Example:

```json
{
  "value": 3658.2,
  "status": "HEALTHY",
  "updated_at": "...",
  "source": "MT5"
}
```

---

# 86. STATUS MODEL

Standardize:

```text
HEALTHY
RUNNING
READY
PAUSED
WAITING
DEGRADED
STALE
DISCONNECTED
BLOCKED
FAILED
UNKNOWN
NOT_CONFIGURED
INSUFFICIENT_DATA
```

Frontend should map API state → consistent visual treatment.

---

# 87. ACTION MODEL

Every action should have:

```text
action_id
label
severity
scope
loading
success
error
```

Critical actions need confirmation.

---

# 88. ERROR BOUNDARY STRATEGY

Each major page can fail independently.

Example:

If Market chart fails:

```text
Market chart unavailable
```

Risk panel can still function.

Avoid whole-app blank screen for isolated data failure.

---

# 89. PERFORMANCE REQUIREMENTS

Target:

```text
Initial shell renders quickly.
Navigation is client-side.
No unnecessary full-page refresh.
Charts are lazy-loaded where possible.
Heavy research pages can load asynchronously.
```

Avoid loading all research datasets on Overview.

---

# 90. PAGE TRANSITION UX

Navigation should preserve:

```text
scroll where reasonable
filters
selected symbol
```

Inspector opening should not reload page.

---

# 91. DESIGN FOR "ONE SCREEN ANSWER"

Overview should answer:

```text
System?
Market?
Position?
Risk?
Decision?
Incident?
```

without requiring navigation.

---

# 92. DESIGN FOR "ONE CLICK DETAIL"

From Overview:

```text
Position → inspect
Decision → inspect
Risk → inspect
Incident → inspect
```

all should be one click away.

---

# 93. NO-TRADE EXPERIENCE

This is a signature feature.

Possible states:

```text
No signal
Waiting for confirmation
Blocked by risk
Blocked by data
Blocked by execution
Outside trading window
No valid setup
```

Each must show:

```text
reason
timestamp
next evaluation
```

---

# 94. DECISION CONFIDENCE UX

Do not show confidence as a giant AI score.

Prefer:

```text
Technical    BUY
Structure    BUY
Momentum     NEUTRAL
Risk         PASS
```

If confidence exists:

```text
Confidence
78%

Based on configured decision model.
```

Always avoid implying certainty.

---

# 95. RISK VISUALIZATION UX

Risk should not use decorative gauges by default.

Prefer:

```text
current / limit
```

Example:

```text
Daily Loss
$31 / $200
15.5%
```

Same visual scale across risk metrics.

---

# 96. STRATEGY LIFECYCLE VISUAL

Use a horizontal lifecycle when space allows:

```text
Draft
  ↓
Backtest
  ↓
WFA
  ↓
Paper
  ↓
Demo
  ↓
Candidate
  ↓
Production
```

Current state highlighted.

Failed stages show evidence.

---

# 97. RESEARCH UX PRINCIPLE

Research pages must separate:

```text
Observation
Analysis
Evidence
Conclusion
```

Do not mix them.

---

# 98. LEARNING UX PRINCIPLE

Learning UI should never make one weak observation look like a proven fact.

Always show:

```text
sample size
period
confidence/evidence state
```

---

# 99. AUDIT UX PRINCIPLE

Audit page should explain:

```text
what
when
who/which subsystem
affected object
result
```

Do not expose secrets.

---

# 100. SECURITY UX

Never display:

```text
API keys
MT5 passwords
Telegram bot token
database credentials
```

Mask sensitive identifiers.

---

# 101. DANGER ZONE

Settings page should have a clearly separated:

```text
Danger Zone
```

for:

```text
disarm terminal
disable strategy
halt system
emergency actions
```

Never place next to harmless settings without separation.

---

# 102. UX FOR RECONNECT

When connection fails:

```text
┌───────────────────────────────┐
│ MT5 disconnected              │
│ New entries are blocked.      │
│ Existing positions monitored. │
│                               │
│ Last connected: 22:41:02      │
│ [View Health]                 │
└───────────────────────────────┘
```

---

# 103. UX FOR RECONCILIATION MISMATCH

Persistent banner:

```text
⚠ BROKER / SYSTEM MISMATCH

New entries blocked.

[View Reconciliation]
```

Banner remains until resolved.

---

# 104. UX FOR EMERGENCY HALT

Full-width critical state:

```text
SYSTEM HALTED

Reason
Critical broker state mismatch

New trades
BLOCKED

Existing positions
MONITORING / ACTION REQUIRED

[Open Incident]
[View Reconciliation]
```

---

# 105. UX FOR PAPER / DEMO / LIVE

Environment badge always visible.

Example:

```text
PAPER
DEMO
PRODUCTION
```

Use explicit labels, never abbreviations only.

---

# 106. UI COPY STYLE

Language should be concise.

Prefer:

```text
Entry blocked
```

instead of:

```text
The autonomous intelligent trading system has decided
that it is currently unable to proceed with execution.
```

Prefer:

```text
Market data stale
```

instead of:

```text
Something appears to be wrong with market data.
```

---

# 107. INDONESIAN / ENGLISH SUPPORT

Primary UI language can be English for technical consistency.

User-facing incident explanations may support Indonesian later.

Do not mix random languages within one screen.

---

# 108. UX FOR TECHNICAL USERS

Advanced details should be discoverable but not mandatory.

Pattern:

```text
Simple summary
+
"View details"
```

Example:

```text
Risk
PASS

[View checks]
```

Then detailed checks.

---

# 109. RESPONSIVE CHART RULE

On small screens:

- simplify overlays;
- preserve price and position;
- hide secondary indicators behind controls;
- avoid unreadable legends.

---

# 110. RESPONSIVE TABLE RULE

On mobile, convert dense tables to cards only when necessary.

Priority fields:

```text
symbol
side
PnL
status
time
```

Secondary information opens in inspector.

---

# 111. MOBILE ALERT PRIORITY

Priority:

```text
Critical incident
Risk block
Position update
Trade execution
System health
Research result
```

Do not notify everything.

---

# 112. NOTIFICATION UX

Notifications should be actionable.

Bad:

```text
Something happened.
```

Good:

```text
Entry blocked
XAUUSD
Reason: stale market data
```

---

# 113. FRONTEND STATE MANAGEMENT

Separate:

```text
server state
UI state
temporary interaction state
```

Do not store broker truth only in frontend state.

Recommended direction:

```text
Server state
→ query/cache layer

UI state
→ local state/store

Realtime
→ event updates
```

---

# 114. DATA FRESHNESS COMPONENT

Every realtime-critical panel may expose freshness:

```text
Updated 0.8s ago
```

For compact state:

```text
● LIVE
```

Hover/detail should show timestamp.

---

# 115. CHART EVENT OVERLAY

Events can be markers:

```text
● agent decision
▲ entry
■ exit
⚠ incident
```

Tooltip:

```text
Decision #182
22:41
BUY candidate
```

---

# 116. POSITION + DECISION LINK

Every position row should link to:

```text
decision_id
execution_id
strategy_version
```

This creates traceability.

---

# 117. TRADE → LEARNING LINK

Trade detail should show:

```text
Review
Lessons
Hypotheses
```

if available.

---

# 118. STRATEGY → TRADE LINK

Strategy detail should provide:

```text
Trades using this version
Performance
Research Evidence
```

---

# 119. INCIDENT → SYSTEM LINK

Incident should link to:

```text
component health
event timeline
affected orders
affected positions
reconciliation
```

---

# 120. AUDIT GRAPH

The app should make relationships easy to navigate:

```text
Decision
  ↕
Trade
  ↕
Order
  ↕
Position
  ↕
Strategy
  ↕
Review
  ↕
Lesson
```

Use links rather than duplicated datasets.

---

# 121. GLOBAL CONTEXT

User-selected:

```text
symbol
environment
date range
```

can remain sticky where useful.

But page-specific context must not unexpectedly change.

---

# 122. MULTI-SYMBOL PREPARATION

Design should support future:

```text
XAUUSD
XAUUSDC
BTCUSD
...
```

without rewriting page layout.

---

# 123. MULTI-ACCOUNT PREPARATION

Topbar may later support:

```text
Account
Broker
Environment
```

But do not overload the initial layout.

---

# 124. MULTI-STRATEGY PREPARATION

Strategy filters should support:

```text
All
Strategy A
Strategy B
Strategy C
```

once available.

---

# 125. UX ANTI-PATTERNS

Do NOT:

```text
1. Giant gradient hero on dashboard
2. 10 KPI cards above the fold
3. Huge "AI Confidence" gauge
4. Excessive glassmorphism
5. Neon purple everywhere
6. Full-screen chat as primary interface
7. Modal for every detail
8. Page refresh after every action
9. Blank page while loading
10. Fake 0 values
11. Color-only status
12. Hidden environment
13. Tiny unreadable tables
14. Overly animated charts
15. Nested navigation deeper than 2 levels
```

---

# 126. DESIGN QUALITY BAR

Before merging a page, ask:

```text
Can user understand it in 5 seconds?
Can user find primary action?
Can user identify system state?
Can user distinguish current vs stale data?
Can user inspect detail in one click?
Can user recover from errors?
Can user use keyboard?
Does it look professional without effects?
```

---

# 127. ACCEPTANCE CRITERIA — OVERVIEW

Overview passes only if:

```text
[ ] system status visible
[ ] MT5 status visible
[ ] market freshness visible
[ ] risk status visible
[ ] reconciliation status visible
[ ] active decision visible
[ ] positions visible
[ ] incident visibility
[ ] no fake data
[ ] realtime updates scoped correctly
[ ] mobile fallback
```

---

# 128. ACCEPTANCE CRITERIA — RISK

```text
[ ] current risk mode visible
[ ] daily loss visible
[ ] drawdown visible
[ ] open risk visible
[ ] circuit breaker visible
[ ] critical states persistent
[ ] destructive controls protected
```

---

# 129. ACCEPTANCE CRITERIA — DECISION

```text
[ ] decision ID
[ ] timestamp
[ ] market snapshot
[ ] structured agent outputs
[ ] supervisor result
[ ] risk result
[ ] execution result
[ ] reason for no trade
[ ] replay available
```

---

# 130. ACCEPTANCE CRITERIA — RESEARCH

```text
[ ] experiment configuration visible
[ ] result metrics
[ ] sample size
[ ] date range
[ ] backtest
[ ] WFA
[ ] Monte Carlo
[ ] evidence state
[ ] strategy lifecycle
```

---

# 131. ACCEPTANCE CRITERIA — RESPONSIVE

```text
[ ] 1920 desktop
[ ] 1440 desktop
[ ] 1280 laptop
[ ] 1024 tablet landscape
[ ] 768 tablet
[ ] 390 mobile
```

No horizontal overflow.

---

# 132. ACCEPTANCE CRITERIA — ACCESSIBILITY

```text
[ ] keyboard usable
[ ] visible focus
[ ] semantic labels
[ ] color contrast
[ ] color-independent status
[ ] reduced motion
[ ] accessible errors
```

---

# 133. IMPLEMENTATION PHASES

## UI-01 — Design Foundation

```text
tokens
fonts
colors
spacing
radius
icons
motion
```

## UI-02 — App Shell

```text
sidebar
topbar
routing
command palette
notifications
```

## UI-03 — Shared States

```text
loading
empty
error
degraded
stale
offline
```

## UI-04 — Overview

## UI-05 — Market

## UI-06 — Positions / Orders

## UI-07 — Intelligence

## UI-08 — Risk

## UI-09 — Reconciliation / Incidents

## UI-10 — Research

## UI-11 — Learning / Strategy Lab

## UI-12 — System / Audit

## UI-13 — Responsive / Accessibility

## UI-14 — Final Polish / Performance

---

# 134. IMPLEMENTATION ORDER

Strict order:

```text
UI-01
  ↓
UI-02
  ↓
UI-03
  ↓
UI-04
  ↓
UI-05
  ↓
UI-06
  ↓
UI-07
  ↓
UI-08
  ↓
UI-09
  ↓
UI-10
  ↓
UI-11
  ↓
UI-12
  ↓
UI-13
  ↓
UI-14
```

---

# 135. OPEN CODE UI DEVELOPMENT PROTOCOL

For each UI phase:

```text
READ UI PRD
↓
INSPECT EXISTING COMPONENTS
↓
REUSE EXISTING DESIGN SYSTEM
↓
IMPLEMENT
↓
RUN TYPE CHECK
↓
RUN LINT
↓
RUN BUILD
↓
RUN UI TEST
↓
VERIFY RESPONSIVE
↓
VERIFY ERROR STATES
↓
VERIFY REAL DATA STATES
↓
SCREENSHOT REVIEW
↓
FIX
↓
UPDATE DOCUMENTATION
↓
COMMIT
```

---

# 136. DO NOT MODIFY TRADING LOGIC BY ACCIDENT

Frontend work must not silently alter:

```text
Risk Engine
Risk Gate
Execution Engine
Position Monitor
Broker connector
Strategy logic
```

unless explicitly required by an API contract change.

UI PRD is presentation + interaction specification.

---

# 137. API-FIRST UX

Before implementing complex screens:

```text
identify endpoint
identify schema
identify states
identify loading behavior
identify failure state
```

Do not build screen against hardcoded mock data unless:

```text
mock is explicitly marked
```

---

# 138. REAL-DATA DEVELOPMENT

Development should use:

```text
realistic fixtures
+
mock failure states
+
real backend where available
```

Need fixtures for:

```text
healthy
no position
active position
no trade
risk blocked
stale
reconciliation mismatch
incident
empty research
insufficient sample
```

---

# 139. VISUAL QA

Every major page must be checked at:

```text
1440×900
1920×1080
1280×800
1024×768
768×1024
390×844
```

Review:

```text
alignment
overflow
density
contrast
empty state
error state
long text
large numbers
small numbers
```

---

# 140. PERFORMANCE QA

Verify:

```text
navigation speed
chart rendering
large trade table
large event timeline
realtime updates
filter changes
inspector opening
```

Avoid memory leaks from realtime subscriptions.

---

# 141. FINAL USER JOURNEYS

## Journey A — Morning Check

```text
Open app
→ Overview
→ System status
→ Risk
→ Position
→ Done
```

Target:

```text
< 10 seconds
```

for situational awareness.

---

## Journey B — Why No Trade?

```text
Overview
→ Active Decision
→ View Decision
→ Blocking reason
→ Done
```

Target:

```text
≤ 2 clicks
```

---

## Journey C — Unexpected Position

```text
Overview
→ Position
→ Decision
→ Execution
→ Broker
→ Audit
```

---

## Journey D — Reconciliation Problem

```text
Banner
→ Reconciliation
→ Mismatch
→ Incident
→ Recovery
→ Verify
```

---

## Journey E — Research Strategy

```text
Strategy Lab
→ Version
→ Evidence
→ Backtest
→ WFA
→ Monte Carlo
→ Lifecycle
```

---

## Journey F — Investigate Loss

```text
Trade History
→ Trade
→ Decision
→ Review
→ Lesson
→ Related Hypothesis
```

---

# 142. UX METRICS

Track eventually:

```text
time to system understanding
time to locate open position
clicks to explain no-trade
clicks to inspect decision
time to identify incident
time to identify reconciliation mismatch
```

Target UX characteristics:

```text
low interaction cost
low cognitive load
high discoverability
high traceability
```

---

# 143. FINAL DESIGN MODEL

The application should feel like:

```text
┌────────────────────────────────────────────────────────────┐
│ Xynn  PROD ●  MT5 ●  XAUUSD  Risk NORMAL  Alerts          │
├─────────────┬──────────────────────────────────────────────┤
│             │                                              │
│ Navigation  │              OVERVIEW                        │
│             │                                              │
│ Monitor     │ System Health       Active Decision          │
│ Intelligence│                                              │
│ Risk        │        MARKET / PRICE                        │
│ Research    │                                              │
│ System      │ Position           Risk                      │
│             │                                              │
│             │ Event Timeline                               │
└─────────────┴──────────────────────────────────────────────┘
```

The visual language:

```text
dark
clean
precise
dense
quiet
responsive
```

The UX language:

```text
state-aware
evidence-driven
action-oriented
recoverable
traceable
```

---

# 144. FINAL PRODUCT STANDARD

The UI is considered successful when:

```text
USER OPENS APP
        ↓
KNOWS SYSTEM STATE
        ↓
KNOWS MARKET STATE
        ↓
KNOWS RISK STATE
        ↓
KNOWS POSITION STATE
        ↓
CAN UNDERSTAND DECISION
        ↓
CAN FIND WHY NO TRADE
        ↓
CAN TRACE A TRADE
        ↓
CAN INVESTIGATE FAILURE
        ↓
CAN REVIEW RESEARCH
        ↓
CAN UNDERSTAND WHAT SYSTEM LEARNED
```

without feeling overwhelmed.

---

# 145. FINAL DESIGN PRINCIPLE

Do not optimize for:

```text
"Looks impressive in a screenshot"
```

Optimize for:

```text
"Remains understandable at 22:43
when an unexpected broker mismatch occurs."
```

This is the quality bar for Xynn.

---

# 146. IMPLEMENTATION CHECKLIST

## FOUNDATION

- [ ] Design tokens
- [ ] Typography
- [ ] Color system
- [ ] Icon system
- [ ] Motion
- [ ] Layout grid

## SHELL

- [ ] Sidebar
- [ ] Topbar
- [ ] Command palette
- [ ] Notification center
- [ ] Environment indicator

## CORE

- [ ] Overview
- [ ] Market
- [ ] Positions
- [ ] Orders
- [ ] Trade History

## INTELLIGENCE

- [ ] Agents
- [ ] Decisions
- [ ] Market Context
- [ ] Why No Trade

## RISK

- [ ] Risk Center
- [ ] Circuit Breaker
- [ ] Reconciliation
- [ ] Incidents

## RESEARCH

- [ ] Performance
- [ ] Backtest
- [ ] Walk Forward
- [ ] Monte Carlo
- [ ] Strategy Lab
- [ ] Learning
- [ ] Execution Quality

## SYSTEM

- [ ] System Health
- [ ] Models
- [ ] Audit
- [ ] Decision Replay
- [ ] Settings

## UX QUALITY

- [ ] Loading states
- [ ] Empty states
- [ ] Error states
- [ ] Stale states
- [ ] Offline states
- [ ] Realtime state
- [ ] Responsive
- [ ] Accessibility
- [ ] Visual QA
- [ ] Performance QA

---

# 147. RELATION TO TRADING PRD V2

UI PRD ini merupakan presentation/UX layer dari:

```text
PRD_V2_Production_Autonomous_Trading_Upgrade.md
```

Mapping utama:

```text
Market Data Health
→ Market / Overview

Broker Reality
→ Market / System Health

Durable Execution
→ Orders / Execution

Reconciliation 2.0
→ Reconciliation

Circuit Breaker
→ Risk Center

Recovery
→ System Health / Incidents

Backtest
→ Research

Walk Forward
→ Research

Monte Carlo
→ Research

Performance Intelligence
→ Performance

Learning
→ Learning

Strategy Lifecycle
→ Strategy Lab

Decision Replay
→ Decisions / Audit

LLM Observability
→ Models / Agents

Execution Quality
→ Execution

Telegram Control
→ Notifications / Control surfaces
```

---

# 148. FINAL IMPLEMENTATION RULE

OpenCode should not start by building every page.

First build:

```text
DESIGN SYSTEM
+
APP SHELL
+
STATE COMPONENTS
```

Then build:

```text
OVERVIEW
```

and use it as visual benchmark for the rest of the application.

Every next page must visually belong to the same product.

