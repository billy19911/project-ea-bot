# MASTER TASKS — XynnBot Architecture Correction & Completion

**Execution model:** Audit first, then patch existing repository.  
**Rule:** One task at a time, verify, checkpoint, then continue.

## Global task rules

Every task must include:

- Scope
- Existing files inspected
- Changes made
- Changes explicitly NOT made
- Acceptance criteria
- Tests
- Verification result
- Follow-up / blocked items

Do not start a later epic while a dependency contract is unstable.

---

# EPIC 00 — REPOSITORY AUDIT

## 00.01 Full repository inventory

Inspect all applications, services, packages, infrastructure, Telegram integration, tests, configs, and docs.

**Output:** `docs/audit/CURRENT_STATE.md`

## 00.02 Architecture mapping

Map actual code to PRD layers and canonical architecture.

**Output:** `docs/audit/ARCHITECTURE_MAP.md`

## 00.03 Duplicate/dead-code audit

Find duplicate engines, unused agent paths, conflicting schemas, stale modules, and misleading abstractions.

## 00.04 PRD deviation matrix

Create:

| Requirement | Existing implementation | Status | Action |
|---|---|---|---|

Statuses: `MATCH`, `PARTIAL`, `MISSING`, `CONFLICT`, `UNKNOWN`.

**Output:** `docs/audit/DEVIATION_MATRIX.md`

## 00.05 Safety boundary audit

Prove that AI cannot directly execute MT5 or bypass Risk Gate.

## 00.06 Baseline tests

Run current tests and record failures before any architectural change.

## 00.07 Audit checkpoint

No code refactor yet. Deliver report only.

---

# EPIC 01 — ARCHITECTURE NORMALIZATION

## 01.01 Authority model

Implement explicit boundaries between AI, deterministic engines, infrastructure, and control plane.

## 01.02 Component registry

Normalize registry metadata for:

- type
- role
- permissions
- dependencies
- model policy
- timeout

## 01.03 Department model

Add formal Department and Department Lead concepts without duplicating existing agent logic.

## 01.04 Permission model

Agents must declare allowed tools/capabilities.

## 01.05 Architecture documentation sync

Update diagrams and module ownership.

---

# EPIC 02 — CONTRACTS & STATE

## 02.01 Event contract

Normalize event schema and IDs.

## 02.02 Task contract

Implement parent/child/root task relationships.

## 02.03 Task state machine

Implement the states in PRD V2.

## 02.04 Agent result contract

Standardize result envelope with status, evidence, confidence, reliability, errors.

## 02.05 Evidence contract

Separate fact, interpretation, and recommendation.

## 02.06 Decision state contract

Add normalized pre-execution Decision State.

## 02.07 Trace IDs

Propagate event/task/decision/proposal/execution IDs through all services.

---

# EPIC 03 — EVENT & ORCHESTRATION

## 03.01 Event priority

Implement CRITICAL/HIGH/NORMAL/LOW/BACKGROUND scheduling.

## 03.02 Task manager

Create/queue/assign/cancel/timeout/retry tasks.

## 03.03 Dependency manager

Support task dependencies and WAITING_DEPENDENCY.

## 03.04 Agent router

Route events through Supervisor policy rather than fixed fan-out.

## 03.05 Context builder

Generate filtered task context.

## 03.06 Retry/timeout manager

Maximum attempts configurable; default 3 unless policy overrides.

## 03.07 Model router

Select models using task complexity, risk, conflicts, and budget.

## 03.08 Budget manager

Track global, department, task, agent, and model budgets.

## 03.09 Autonomous wake-up/event policy

Implement event-driven Supervisor wake-up without requiring Telegram/user input. Avoid polling LLMs unnecessarily.

## 03.10 AI Provider Manager

Implement provider adapter, backend-only configuration, connection health, and dynamic `/v1/models` discovery for 9Router/OpenAI-compatible gateways.

## 03.11 Model registry

Persist/cache discovered model metadata and availability. Remove hard-coded frontend model lists where they conflict with dynamic discovery.

## 03.12 Provider/model fallback

Handle unavailable models, gateway timeout, degraded state, and safe execution behavior.

## 03.13 Telegram gateway

Connect Telegram to the Control Plane/Supervisor without putting Telegram in the autonomous trading dependency chain.

## 03.14 Telegram command/query routing

Support structured inquiries such as market condition, why-no-trade, risk, positions, supervisor status, and trade review.

## 03.15 Telegram event notifications

Publish signal, committee decision, execution, position, closure, risk, and system-health events.

## 03.16 Telegram authorization

Protect control/query capabilities with allowlists/RBAC and never expose provider secrets or direct MT5 order tools.


---

# EPIC 04 — MARKET INTELLIGENCE

## 04.01 Market Lead

Implement formal lead role.

## 04.02 Technical Analyst

Ensure structured output and evidence.

## 04.03 Structure Analyst

Ensure structured output and evidence.

## 04.04 Momentum Analyst

Ensure structured output and evidence.

## 04.05 Volatility Analyst

Ensure structured output and evidence.

## 04.06 News/Sentiment Analyst

Ensure structured output and evidence.

## 04.07 Lead synthesis

Market Lead decides which specialists are required and returns a department-level assessment.

## 04.08 Specialist reliability

Persist measurable reliability metadata without treating it as a direct profitability probability.

## 04.09 Committee discussion

Allow selected specialists to inspect relevant peer findings, challenge contradictions, and revise assessments.

## 04.10 Consensus synthesis

Produce one department decision with agreements, conflicts, evidence, counter-evidence, confidence, and invalidation conditions.

## 04.11 Committee conflict escalation

Require targeted second opinion/deeper analysis when material disagreement remains. Safe unresolved outcome must be WAIT/NO_TRADE/ESCALATE.

## 04.12 Decision dimension separation

Separate market bias, setup direction, and action so bullish bias does not imply immediate entry.

---

# EPIC 05 — RISK INTELLIGENCE

## 05.01 Risk Lead

Formalize AI risk department.

## 05.02 Account Risk Analyst

## 05.03 Position Risk Analyst

## 05.04 Portfolio Risk Analyst

## 05.05 Drawdown Analyst

## 05.06 Risk synthesis

Return recommendations and warnings to Supervisor.

## 05.07 Separation test

Prove AI risk advice cannot alter deterministic hard limits.

---

# EPIC 06 — SUPERVISOR

## 06.01 Supervisor runtime

Normalize supervisor lifecycle.

## 06.02 Event intake

Supervisor receives event + filtered context.

## 06.03 Task planning

Supervisor creates structured tasks.

## 06.04 Department delegation

Supervisor chooses department, not individual specialist by default.

## 06.05 Follow-up delegation

Supervisor can create child tasks after receiving results.

## 06.06 Conflict resolution

Implement evidence/freshness/reliability-based conflict handling.

## 06.07 Decision synthesis

Create Decision State.

## 06.08 Trade proposal

Create Trade Proposal only after sufficient evidence.

## 06.09 No-trade behavior

Support WAIT/NO_TRADE/MONITOR/ESCALATE.

## 06.10 Supervisor safety tests

Ensure Supervisor cannot call MT5 or bypass risk.

## 06.11 Autonomous Supervisor loop

Supervisor continues operating from events even when Telegram/user interaction is absent.

## 06.12 Committee-aware synthesis

Supervisor consumes department consensus plus disagreement metadata rather than naive agent voting.

## 06.13 Decision trace explanation

Persist structured reasoning summaries so Supervisor can later explain why a trade was or was not taken.

## 06.14 Supervisor performance profile

Expose statistically meaningful win rate, profit factor, expectancy, drawdown, rolling results, and decision-quality metrics.

## 06.15 No-trade quality

Evaluate WAIT/NO_TRADE decisions using counterfactual outcomes where data permits.

## 06.16 Supervisor status API

Provide current autonomous state, market bias/action, confidence, next conditions, and performance snapshot to Dashboard/Telegram.

---

# EPIC 07 — DETERMINISTIC RISK & SAFETY

## 07.01 Hard risk configuration

## 07.02 Position sizing

## 07.03 Spread validation

## 07.04 Margin validation

## 07.05 Exposure validation

## 07.06 Drawdown/daily-loss validation

## 07.07 Kill switch

## 07.08 Circuit breakers

## 07.09 Risk Gate PASS/BLOCK contract

## 07.10 Safety regression tests

---

# EPIC 08 — EXECUTION

## 08.01 Proposal validator

Validate schema and stale context.

## 08.02 Idempotency

Prevent duplicate execution across retries/restarts.

## 08.03 Order builder

Build broker order from validated proposal.

## 08.04 MT5 execution

Keep broker-specific operation deterministic.

## 08.05 Confirmation

Handle accepted/rejected/partial/error states.

## 08.06 Reconciliation engine

Compare DB/internal state and MT5 state.

## 08.07 Recovery

Block new orders on critical mismatches.

---

# EPIC 09 — POSITION MONITORING

## 09.01 Position lifecycle

## 09.02 SL/TP monitoring

## 09.03 Trailing

## 09.04 Abnormal movement events

## 09.05 Risk-change events

## 09.06 Exit events

## 09.07 Position reconciliation

---

# EPIC 10 — MEMORY & TRACEABILITY

## 10.01 Working memory

## 10.02 Episodic memory

## 10.03 Semantic memory

## 10.04 Strategy memory

## 10.05 Research memory

## 10.06 Retrieval policy

## 10.07 Task/event/decision trace

---

# EPIC 11 — TRADE REVIEW

## 11.01 Automatic trade review

## 11.02 Win/loss analysis

## 11.03 MAE/MFE

## 11.04 Timing quality

## 11.05 Decision quality

## 11.06 Execution quality

## 11.07 Root-cause classification

## 11.08 Strategy-vs-execution attribution

Distinguish analytical error, timing, regime mismatch, news, execution/slippage, risk issue, and normal probabilistic loss.

## 11.09 Winning-trade pattern extraction

Identify recurring conditions associated with successful trades.

## 11.10 Losing-trade pattern extraction

Identify recurring conditions associated with losing trades.

## 11.11 Time/session analysis

Measure performance by hour, session, day, and market regime.

## 11.12 No-trade/counterfactual review

Evaluate whether WAIT/NO_TRADE decisions avoided adverse outcomes.

## 11.13 Committee decision quality

Measure whether consensus decisions were directionally/tactically correct independent of raw P/L.

## 11.14 Learning journal

Persist structured trade reviews, lessons, evidence, and linked hypotheses.

---

# EPIC 12 — RESEARCH

## 12.01 Research Lead

## 12.02 Hypothesis model

## 12.03 Experiment model

## 12.04 Backtest runner

## 12.05 Walk-forward validation

## 12.06 Paper validation

## 12.07 Demo validation

## 12.08 Metrics comparison

## 12.09 Strategy candidate generation

## 12.10 Pattern discovery

Discover performance patterns by hour/session, setup, regime, volatility, news proximity, timeframe, and symbol.

## 12.11 Hypothesis generation from patterns

Turn repeatable patterns into explicit testable hypotheses rather than live changes.

## 12.12 Out-of-sample validation

Ensure discovered improvements are tested on data not used for hypothesis formation.

## 12.13 Degradation detection

Detect when an active strategy/setup materially degrades by regime/time/setup.

## 12.14 Research explanation

Generate concise explanation of why a candidate improvement may work and what evidence supports it.

## 12.15 Research safety

Block research from directly modifying live strategy parameters.

---

# EPIC 13 — STRATEGY VERSIONING & PROMOTION

## 13.01 Strategy registry

## 13.02 Version schema

## 13.03 Promotion gates

## 13.04 Activation/deactivation

## 13.05 Retirement

## 13.06 Live-parameter protection

---

# EPIC 14 — LEARNING LOOP

## 14.01 Review → pattern pipeline

## 14.02 Pattern → hypothesis pipeline

## 14.03 Hypothesis → experiment pipeline

## 14.04 Experiment → candidate pipeline

## 14.05 Candidate → validation pipeline

## 14.06 Validation → approval pipeline

## 14.07 Learning-by-doing loop

Connect trade review → pattern → hypothesis → experiment → validation.

## 14.08 Performance-by-time learning

Track best/worst hours and sessions with minimum sample-size safeguards.

## 14.09 Performance-by-regime learning

Track strategy quality across volatility/trend/range/news regimes.

## 14.10 Setup-level learning

Track recurring winning and losing conditions for each setup.

## 14.11 Supervisor KPI learning

Track win rate, profit factor, expectancy, drawdown, false signals, and no-trade quality.

## 14.12 Candidate strategy comparison

Compare current vs candidate versions using consistent metrics and out-of-sample evidence.

## 14.13 Learning memory

Store validated lessons separately from raw trade history.

## 14.14 No direct live mutation

No automatic live mutation.

---

# EPIC 15 — DASHBOARD / CONTROL PLANE

## 15.01 System overview

## 15.02 Trading

## 15.03 Positions

## 15.04 Market

## 15.05 AI Organization

## 15.06 Supervisor activity

## 15.07 Department/specialist activity

## 15.08 Task explorer

## 15.09 Decision explorer

## 15.10 Risk center

## 15.11 Strategy center

## 15.12 Research center

## 15.13 Execution center

## 15.14 Audit viewer

## 15.15 System health

## 15.16 Settings / mode controls
## 15.17 Supervisor performance center
## 15.18 Committee/debate trace
## 15.19 Telegram integration status
## 15.20 AI provider / 9Router status
## 15.21 Model discovery and registry
## 15.22 Learning / performance analytics

---

# EPIC 16 — OBSERVABILITY

## 16.01 Structured logs
## 16.02 Metrics
## 16.03 Event traces
## 16.04 Task traces
## 16.05 Model/token usage
## 16.06 Latency
## 16.07 Error rates
## 16.08 Risk decisions
## 16.09 Execution metrics
## 16.10 Alerts
## 16.11 Supervisor KPIs
## 16.12 Committee consensus metrics
## 16.13 Decision quality metrics
## 16.14 No-trade outcome metrics
## 16.15 Learning pattern metrics
## 16.16 Telegram delivery metrics
## 16.17 Provider/model health metrics

---

# EPIC 17 — SECURITY

## 17.01 Authentication
## 17.02 RBAC
## 17.03 Secret isolation
## 17.04 API authorization
## 17.05 Agent permissions
## 17.06 Tool permissions
## 17.07 Audit protection
## 17.08 Rate limiting
## 17.09 LIVE mode protection

---

# EPIC 18 — TESTING & FAILURE SIMULATION

## 18.01 Unit coverage
## 18.02 Integration coverage
## 18.03 Supervisor simulations
## 18.04 Agent timeout/failure
## 18.05 Model fallback
## 18.06 MT5 disconnect
## 18.07 Duplicate order
## 18.08 Risk breach
## 18.09 Reconciliation mismatch
## 18.10 Circuit breaker
## 18.11 Restart/recovery
## 18.12 End-to-end paper trading
## 18.13 End-to-end demo trading
## 18.14 Chaos scenarios

---

# EPIC 19 — LIVE READINESS

## 19.01 Backtest gate
## 19.02 Walk-forward gate
## 19.03 Paper gate
## 19.04 Demo gate
## 19.05 Risk gate
## 19.06 Stability gate
## 19.07 Recovery gate
## 19.08 Observability gate
## 19.09 Security gate
## 19.10 Explicit LIVE activation
## 19.11 Autonomous workflow gate
## 19.12 Committee/consensus gate
## 19.13 Learning safety gate
## 19.14 Telegram/control-plane gate
## 19.15 9Router/provider discovery gate

---

# Dependency Order

```text
00 Audit
 ↓
01 Architecture
 ↓
02 Contracts/State
 ↓
03 Orchestration
 ↓
04 Market Department
 ↓
05 Risk Intelligence
 ↓
06 Supervisor
 ↓
07 Deterministic Risk
 ↓
08 Execution
 ↓
09 Monitoring
 ↓
10 Memory/Trace
 ↓
11 Review
 ↓
12 Research
 ↓
13 Strategy Versioning
 ↓
14 Learning
 ↓
15 Dashboard
 ↓
16 Observability
 ↓
17 Security
 ↓
18 Testing
 ↓
19 Live Readiness
```

Dashboard/observability/security may be developed in parallel only after the underlying API/contracts are stable.

---

# Checkpoint Protocol

After each task:

1. Run focused tests.
2. Run relevant integration tests.
3. Inspect diff for unintended changes.
4. Update docs.
5. Mark task `DONE`, `BLOCKED`, or `NEEDS_REVIEW`.
6. Do not silently skip failures.

