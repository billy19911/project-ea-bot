# PRD V2 — XynnBot Autonomous Multi-Agent Trading & Research Platform

**Status:** Target Architecture / Correction Baseline  
**Supersedes:** PRD V1 as implementation authority  
**Repository:** `billy19911/project-ea-bot`  
**Primary principle:** AI reasons and delegates within boundaries; deterministic software owns safety, validation, state integrity, and execution.

---

## 1. Purpose

This document defines the corrected target architecture for the existing XynnBot repository. It is **not** a greenfield rebuild specification.

Implementation must preserve working components and modify only what is needed to converge the existing repository toward this architecture.

### 1.1 Core goals

1. Autonomous event-driven trading and research.
2. Hierarchical AI organization: Supervisor → Department Lead → Specialist.
3. Dynamic delegation rather than fixed all-agent fan-out.
4. Explicit separation between AI reasoning and deterministic enforcement.
5. Safe path from observation → analysis → decision → risk gate → execution.
6. Continuous trade review and controlled research/strategy improvement.
7. Full observability of events, tasks, decisions, risk checks, and execution.
8. Efficient LLM usage through routing, context filtering, budgets, and escalation.
9. Compatibility with the existing Next.js / Node.js / Python / MT5 architecture unless audit proves a change is necessary.

---

## 2. Non-Goals

The system must not:

- give an LLM direct unrestricted MT5 order access;
- allow LLMs to change hard risk limits at runtime;
- treat LLM confidence as probability of profit;
- execute solely because a majority of agents voted BUY/SELL;
- mutate live strategy parameters directly after a losing trade;
- rebuild modules that already meet this specification;
- expose raw chain-of-thought as user-facing telemetry.

---

## 3. Canonical Architecture

```text
CONTROL PLANE
Dashboard / API / Settings / Audit / Kill Switch
                     |
                     v
               EVENT SYSTEM
      Market / Account / Position / Research
                     |
                     v
                SUPERVISOR
               AI MANAGER
                     |
        +------------+------------+
        |            |            |
        v            v            v
 MARKET LEAD     RISK LEAD    RESEARCH LEAD
        |            |            |
   specialists  specialists   specialists
        |            |            |
        +------------+------------+
                     |
                     v
              DECISION STATE
                     |
                     v
          DETERMINISTIC VALIDATION
                     |
                     v
              DETERMINISTIC
                RISK GATE
                     |
                 PASS/BLOCK
                 /       \
                v         v
           EXECUTION     STOP
                |
                v
               MT5
                |
                v
          POSITION MONITOR
                |
                v
            TRADE REVIEW
                |
                v
          RESEARCH / LEARNING
                |
                v
         VALIDATED STRATEGY
             VERSION
```

### 3.1 Authority rules

| Capability | AI | Deterministic code | Human/control plane |
|---|---:|---:|---:|
| Interpret market context | ✓ |  |  |
| Delegate specialist work | ✓ |  |  |
| Synthesize evidence | ✓ |  |  |
| Create trade proposal | ✓ |  |  |
| Calculate indicators |  | ✓ |  |
| Calculate hard risk |  | ✓ |  |
| Final lot enforcement |  | ✓ |  |
| Hard risk limits |  | ✓ | ✓ config with permissions |
| Send broker order |  | ✓ | controlled |
| Kill switch |  | ✓ | ✓ |
| Promote strategy to LIVE | recommendation only | enforcement | ✓ explicit approval |

---

## 4. Architectural Layers

### Layer A — Data

- MT5 market data adapter
- account state
- position/order state
- historical data
- news/external data adapters
- normalized market snapshot

### Layer B — Deterministic Trading Intelligence

- indicators
- trend
- volatility
- structure metrics
- spread
- liquidity conditions
- market regime
- risk metrics
- position sizing inputs

No LLM is required for calculations.

### Layer C — Event System

Event schema, detector, priority, deduplication, queue, scheduler, history, replay.

### Layer D — Orchestration

- Task Manager
- Agent Registry
- Department Registry
- Agent Router
- Context Builder
- Memory Router
- Retry / Timeout Manager
- Dependency Manager
- Model Router
- Token Budget Manager

### Layer E — AI Organization

Supervisor, department leads, specialist agents, research agents, review agents.

### Layer F — Decision

Evidence aggregation, conflict resolution, Decision State, Trade Proposal.

### Layer G — Safety / Execution

Deterministic validation, Risk Engine, Risk Gate, Execution Engine, Reconciliation.

### Layer H — Lifecycle

Position monitor, trade memory, trade review, research, experiment, strategy versioning.

### Layer I — Control / Observability

Dashboard, audit trail, metrics, traces, alerts, system controls, settings.

---

## 5. AI Organization

## 5.1 Supervisor

Supervisor is the AI manager/orchestrator.

Responsibilities:

- interpret objective and event;
- inspect current state/context;
- decide which department is relevant;
- create tasks;
- ask department leads for work;
- receive structured results;
- request follow-up work when evidence is insufficient;
- detect conflicts;
- request second opinions or deeper analysis;
- synthesize evidence;
- create Decision State;
- create Trade Proposal or non-trade decision;
- hand proposal to deterministic validation.

Supervisor may not:

- send MT5 orders;
- bypass Risk Gate;
- alter hard limits;
- invent missing market data;
- assume an agent is correct merely because confidence is high.

## 5.2 Department Leads

### Market Intelligence Lead

Children:

- Technical Analyst
- Structure Analyst
- Momentum Analyst
- Volatility Analyst
- News/Sentiment Analyst

Lead decides which specialists are required for the current task.

### Risk Intelligence Lead

Children:

- Account Risk Analyst
- Position Risk Analyst
- Portfolio Risk Analyst
- Drawdown Analyst

Lead provides risk interpretation. Hard enforcement remains deterministic.

### Research Lead

Children:

- Strategy Researcher
- Backtest Analyst
- Walk-Forward Analyst
- Performance Analyst
- Experiment Agent

Research is not allowed to silently modify live strategy.

### Review / Knowledge capability

May be implemented as a department or service depending on audit findings:

- Trade Review Analyst
- Pattern Analyst
- Learning Analyst

---

## 6. Dynamic Delegation Model

The system must support:

```text
Event
  -> Supervisor
  -> Department Lead
  -> Specialist(s)
  -> Lead synthesis
  -> Supervisor
  -> optional follow-up task(s)
  -> Decision State
```

Agents must **not** all run for every event.

Example:

```text
TRADE_SETUP_DETECTED
  -> Supervisor
  -> Market Lead
      -> Structure
      -> Momentum
  -> Supervisor
  -> Risk Lead
      -> Position Risk
      -> Account Risk
  -> Supervisor
  -> Decision
```

For a simple monitoring event, the Supervisor may need no market LLM at all.

---

## 7. Task Contract

Every delegated unit of work must have a stable Task Contract.

Required fields:

```json
{
  "task_id": "TASK-...",
  "parent_task_id": null,
  "root_event_id": "EVENT-...",
  "created_by": "supervisor",
  "assigned_role": "market_lead",
  "objective": "...",
  "priority": "HIGH",
  "required_context": [],
  "dependencies": [],
  "deadline_ms": 5000,
  "attempt": 1,
  "max_attempts": 3,
  "expected_output_schema": "market_assessment"
}
```

### Task states

```text
CREATED
ROUTED
QUEUED
ASSIGNED
WORKING
WAITING_DEPENDENCY
WAITING_RESULT
COMPLETED
REVIEWED

FAILED
RETRYING
ESCALATED
EXPIRED
CANCELLED
```

---

## 8. Evidence Model

Every material AI conclusion should distinguish:

1. **Fact** — directly observed/calculated.
2. **Interpretation** — agent assessment.
3. **Recommendation** — suggested action.

Evidence should include:

- source;
- timestamp;
- timeframe;
- freshness;
- data quality;
- supporting metric/value;
- originating agent/task.

Example:

```json
{
  "type": "fact",
  "source": "indicator_engine",
  "name": "ema_alignment",
  "value": "EMA20 > EMA50",
  "timeframe": "M1",
  "timestamp": "...",
  "freshness_ms": 240
}
```

---

## 9. Decision State

Before execution, the system must create a normalized Decision State.

```json
{
  "market_bias": "BULLISH",
  "setup_status": "VALID",
  "evidence": [],
  "conflicts": [],
  "market_risk": "CAUTION",
  "data_quality": "GOOD",
  "decision": "CONSIDER_BUY"
}
```

Allowed high-level decisions:

- BUY
- SELL
- WAIT
- NO_TRADE
- MONITOR
- CLOSE
- REDUCE
- ESCALATE

---

## 10. Conflict Resolution

Never use naive majority voting.

Required flow:

```text
Conflict detected
  -> compare evidence quality
  -> compare freshness
  -> compare specialist reliability
  -> request targeted second opinion if needed
  -> check higher timeframe / deterministic context
  -> Supervisor resolves
  -> if unresolved: WAIT / NO_TRADE / ESCALATE
```

### 10.1 Department Committee / Debate

Department Leads must not merely aggregate independent specialist outputs. When the task is decision-critical, the department operates as a structured committee. Specialists may inspect relevant peer findings, challenge contradictory evidence, provide counter-arguments, and revise their assessment when new evidence changes the conclusion.

The committee must produce one department-level conclusion containing:

- market state / risk state / research state;
- specialist positions;
- material agreements and disagreements;
- strongest supporting evidence;
- strongest counter-evidence;
- unresolved conflicts;
- consensus decision;
- confidence and evidence quality;
- conditions that would invalidate the decision.

Consensus is **not** a simple vote. The system must prefer evidence quality, freshness, domain relevance, deterministic measurements, and explicit conflict resolution. If material disagreement remains unresolved, the committee may only return `WAIT`, `NO_TRADE`, or `ESCALATE` for execution-critical decisions.

### 10.2 Decision dimensions

Trading decisions must separate: 

```text
MARKET_BIAS     = BULLISH / BEARISH / NEUTRAL
SETUP_DIRECTION = BUY / SELL / NONE
ACTION          = ENTER / WAIT / MONITOR / CLOSE / REDUCE / ESCALATE
```

A bullish market bias does not automatically authorize a BUY entry. For example: `BULLISH + BUY_BIAS + WAIT` is a valid autonomous decision.

---

## 10.3 Autonomous Operation

The autonomous workflow must never depend on user interaction or Telegram commands. Telegram and Dashboard are interfaces to the running system, not prerequisites for the Supervisor to operate.

The Supervisor is event-driven and may wake on:

- market/candle events;
- setup detection;
- price entering a monitored zone;
- volatility/spread/regime changes;
- news proximity;
- account/position/risk changes;
- execution/position lifecycle events;
- trade closure;
- research/experiment completion;
- system health anomalies.

The scheduler must avoid unnecessary LLM calls. Deterministic detectors should generate meaningful events first; the Supervisor decides whether analysis is needed. A normal `WAIT` state remains active until a relevant event requires reevaluation.

## 11. Confidence and Reliability

`confidence` is not a probability of profit.

Track separately:

- confidence
- signal strength
- risk score
- evidence quality
- data quality
- freshness
- agent reliability
- model reliability

---

## 12. Deterministic Risk Architecture

Two different concepts must exist.

### 12.1 Risk Intelligence

AI analysis and recommendations.

### 12.2 Deterministic Risk Engine / Risk Gate

Hard enforcement:

- maximum drawdown;
- daily loss limit;
- maximum exposure;
- max positions;
- margin conditions;
- spread conditions;
- symbol restrictions;
- lot bounds;
- account mode restrictions;
- kill switch;
- circuit breaker conditions.

Outputs:

```text
PASS
BLOCK
```

No LLM can bypass this.

---

## 13. Execution Architecture

Execution is a deterministic service, not an AI department.

```text
Trade Proposal
 -> deterministic validation
 -> Risk Gate
 -> idempotency check
 -> order build
 -> MT5 send
 -> broker confirmation
 -> position synchronization
 -> audit
```

Required identifiers:

- event_id
- task_id
- decision_id
- proposal_id
- execution_id
- client_order_id
- strategy_version

Repeated retries must not produce duplicate orders.

---

## 14. Reconciliation

A reconciliation engine must compare internal state against MT5 state.

Checks:

- positions
- orders
- lots
- SL/TP
- symbol
- magic number
- execution status
- orphan orders
- orphan positions

On critical mismatch:

```text
BLOCK NEW ORDERS
 -> reconcile
 -> recover
 -> resume only after consistency restored
```

---

## 15. Event Priority

```text
CRITICAL
HIGH
NORMAL
LOW
BACKGROUND
```

Examples:

- risk breach → CRITICAL
- execution/position anomaly → HIGH
- trade setup → HIGH
- new candle → NORMAL
- research → LOW
- analytics/housekeeping → BACKGROUND

Scheduling and LLM budgets must honor priority.

---

## 16. Context Builder

LLM calls must receive a filtered snapshot, not the full database.

Possible components:

- Market Snapshot
- Account Snapshot
- Position Snapshot
- Risk Snapshot
- Strategy Snapshot
- Recent Events
- Relevant Evidence
- Relevant Memory
- Relevant Agent Results

---

## 17. Memory Architecture

Separate memory types:

- Working Memory — current task.
- Episodic Memory — previous events/trades.
- Semantic Memory — stable knowledge/patterns.
- Strategy Memory — strategy versions/parameters.
- Research Memory — hypotheses/experiments/findings.

Memory retrieval must be relevance-based and source-aware.

---

## 18. Research and Learning Loop

```text
Trade
 -> Review
 -> Error / Pattern
 -> Hypothesis
 -> Experiment
 -> Backtest
 -> Walk Forward
 -> Paper
 -> Demo
 -> Evaluation
 -> Candidate Strategy
 -> Approval Gate
 -> Strategy Version
 -> Controlled Activation
```

A losing trade must never directly change LIVE parameters.

---

### 18.1 Learning-by-doing

After every completed trade, the platform should automatically review the decision and execution. The review must distinguish at least:

- strategy/market-analysis error;
- timing error;
- market-regime mismatch;
- news/event effect;
- execution/slippage/spread issue;
- risk-management issue;
- normal probabilistic loss despite valid setup.

The same review system must evaluate meaningful `WAIT` / `NO_TRADE` decisions using counterfactual outcomes where data permits. A correct avoided trade is a valid positive decision outcome.

The Research/Performance system should continuously discover patterns such as:

- best/worst trading hours and sessions;
- market-regime performance;
- volatility buckets;
- setup performance;
- timeframe performance;
- news proximity;
- symbol-specific behavior;
- repeated loss causes;
- repeated winning conditions;
- agent/committee decision quality.

Pattern discovery produces hypotheses, not live rule changes.

### 18.2 Hypothesis-driven improvement

Example: if losses cluster during a specific hour under extreme volatility, the system creates a hypothesis and tests it across historical and out-of-sample data. A candidate improvement must pass the research promotion pipeline before becoming a new Strategy Version.

No learning component may directly edit live parameters after a trade result.

### 18.3 Supervisor performance profile

Supervisor performance telemetry must include, where statistically meaningful:

- overall win rate;
- profit factor;
- expectancy/R;
- drawdown;
- recent rolling performance;
- performance by session/hour;
- performance by market regime;
- performance by setup;
- false-signal rate;
- no-trade decision quality;
- specialist/committee reliability.

These metrics are feedback/context only. They must never authorize a trade or override deterministic risk limits.

---

## 19. Strategy Registry

Each strategy version must track:

- strategy_id
- version
- parameters
- risk policy
- compatible market regimes
- status
- performance metrics
- validation evidence
- created_at
- approved_at
- activated_at
- retired_at

Statuses:

```text
DRAFT
RESEARCH
BACKTESTED
WALK_FORWARD
PAPER
DEMO
APPROVED
ACTIVE
RETIRED
REJECTED
```

---

## 20. AI Provider Manager / 9Router

For the current deployment, 9Router is the primary OpenAI-compatible LLM gateway. The application must not hard-code a static model list in the frontend.

Required behavior:

```text
Backend configuration
 -> connect to 9Router
 -> GET /v1/models
 -> discover available model IDs
 -> normalize Model Registry
 -> health/availability status
 -> Model Router selects model by policy
```

Provider configuration must be backend-only. The browser must never receive provider secrets. Model discovery must be cached and refreshable. The system must show `CONNECTED`, `DEGRADED`, or `DISCONNECTED` state and fail safely when the gateway is unavailable.

The architecture should use an OpenAI-compatible Provider Adapter so another gateway can be added later without rewriting agents.

Default policy is `AUTO`; optional per-role overrides may exist for Supervisor, Market, Risk, Research, and Review.

---

## 21. Telegram Control & Communication Gateway

Telegram is a communication/control interface, **not the trigger for autonomous operation**. The core autonomous workflow must continue when no user is connected to Telegram.

Telegram capabilities:

- ask Supervisor for current market condition;
- ask why no trade has occurred;
- ask current positions/risk/system status;
- request a detailed explanation of a prior decision;
- receive market signal/committee summaries;
- receive trade proposal/execution/position/closure alerts;
- receive risk/system alerts;
- inspect trade review and research summaries.

User questions must resolve against stored decision/task/evidence traces where possible. The system must explain structured reasoning summaries and evidence, **not expose private chain-of-thought**.

Telegram must not directly place broker orders or bypass Supervisor, deterministic validation, or Risk Gate.

Example autonomous flow:

```text
Market Event
 -> Supervisor
 -> Market Committee
 -> specialist discussion
 -> consensus
 -> Supervisor Decision
 -> Risk Intelligence
 -> deterministic Risk Gate
 -> Execution
 -> MT5
 -> Monitor
 -> Review
 -> Telegram notification (optional)
```

Example user inquiry:

```text
User: Why has there been no XAUUSD trade?
Telegram -> Supervisor -> Decision Trace
-> detailed structured explanation
```

---

## 22. Model Routing

Routing inputs:

- task complexity;
- event priority;
- risk level;
- conflict severity;
- current budget;
- model availability.

Example policy:

```text
simple classification -> low-cost/free model
normal specialist task -> medium model
high-conflict supervisor synthesis -> strong model
hard risk/execution -> deterministic code, no LLM
```

Fallbacks, timeout, token usage, latency, and cost must be logged.

## 23. Trading Modes

```text
OFFLINE
BACKTEST
PAPER
DEMO
LIVE
EMERGENCY_STOP
```

Mode transition must be explicit and auditable.

---

## 24. Circuit Breakers

Provide circuit breakers for:

- LLM gateway
- market data
- MT5 connection
- database
- queue
- execution

When an execution-critical circuit is open, new trading orders must be blocked.

---

## 25. Control Plane / Dashboard

Required areas:

- Overview
- Trading
- Positions
- Market
- AI Organization
- Supervisor
- Departments
- Tasks
- Risk
- Strategies
- Research
- Execution
- System Health
- Audit
- Settings

AI Organization view should show hierarchy and live state:

```text
Supervisor
  Market Lead
    Technical   DONE
    Structure   WORKING
    Momentum    QUEUED
  Risk Lead
    Account     DONE
    Position    WORKING
  Research Lead
    Research    IDLE
```

Do not expose raw private chain-of-thought. Show concise structured reasoning summaries, decisions, evidence, and status.

---

## 26. Traceability

Any trade or blocked trade should be traceable:

```text
EVENT
 -> SUPERVISOR
 -> TASK
 -> DEPARTMENT
 -> SPECIALIST
 -> EVIDENCE
 -> DECISION STATE
 -> RISK GATE
 -> EXECUTION
 -> MT5
 -> MONITOR
 -> REVIEW
```

---

## 27. Observability

Track:

- events
- tasks
- agent execution
- retries
- timeouts
- model calls
- tokens
- latency
- errors
- risk decisions
- execution results
- reconciliation
- strategy experiments

---

## 28. Security

- authentication
- RBAC
- secret isolation
- API authorization
- tool/agent permissions
- audit log
- rate limiting
- live-mode protection
- environment isolation

Agent permissions must follow least privilege.

---

## 29. Testing Requirements

Minimum test categories:

- unit
- integration
- orchestration
- agent failure
- LLM timeout/fallback
- duplicate order
- MT5 disconnect
- risk breach
- state recovery
- reconciliation mismatch
- circuit breaker
- end-to-end
- chaos/simulation

---

## 30. Implementation Doctrine

### Preserve

Existing modules that already conform to this PRD.

### Refactor

Modules whose interfaces or authority boundaries conflict with this PRD.

### Add

Missing contracts, orchestration, hierarchy, evidence, state, reconciliation, and controlled research features.

### Remove

Only dead, duplicated, contradictory, or unsafe logic proven by audit.

Never delete/rebuild large sections merely to match a preferred folder layout.

---

## 31. Definition of Done

A task is complete only when:

1. Code matches the task contract.
2. Existing valid behavior remains intact.
3. Tests are added or updated.
4. Relevant integration path is verified.
5. Logs/audit are available where needed.
6. Documentation is updated.
7. No hidden TODO remains for the acceptance criteria.
8. No unsafe bypass is introduced.

---

## 32. Final System Acceptance

The platform is considered architecturally ready only when it can demonstrate:

1. Supervisor dynamically delegates to the correct department.
2. Department Lead chooses only needed specialists.
3. Specialist results return as structured evidence.
4. Supervisor can request follow-up work.
5. Conflicts do not default to majority vote.
6. Decision State exists before execution.
7. Risk Intelligence and deterministic Risk Gate are separate.
8. AI cannot bypass hard limits.
9. Execution is deterministic and idempotent.
10. Internal state reconciles with MT5.
11. Every trade is fully traceable.
12. Research cannot silently mutate LIVE strategy.
13. Strategy versions are validated before promotion.
14. LLM usage is budgeted and observable.
15. Failure of AI infrastructure fails safely rather than opening uncontrolled trading.
16. Department committees can discuss contradictory specialist evidence and produce one structured decision or safe unresolved outcome.
17. Autonomous operation continues without Telegram/user interaction.
18. Telegram can query Supervisor using stored decision/task/evidence traces without becoming a dependency for trading.
19. 9Router model discovery is dynamic through the configured OpenAI-compatible gateway rather than a hard-coded frontend list.
20. Every completed trade receives an automated review and root-cause classification.
21. Performance analytics can identify patterns by hour/session/regime/setup and generate research hypotheses.
22. Learning can create candidate strategy versions but cannot directly mutate LIVE strategy parameters.
23. Supervisor performance metrics include win rate plus expectancy, profit factor, drawdown, timing, regime, setup, and no-trade quality where sample size is sufficient.

