# MASTER BUILD PROMPT — XynnBot Existing Repository Correction

You are working on an **existing repository**: `billy19911/project-ea-bot`.

Your job is to bring the existing implementation into compliance with `PRD_V2.md` and `MASTER_TASKS.md`.

## NON-NEGOTIABLE RULE

**Do not rebuild the project from scratch. Do not delete working modules merely because the folder structure or implementation style is different from the target blueprint.**

The repository already contains working foundations. Preserve anything that satisfies the target contracts.

---

# 1. SOURCE OF TRUTH

Read these files first:

1. `PRD_V2.md`
2. `MASTER_TASKS.md`
3. `CONSTRAINTS.md`
4. existing architecture/audit documents if present
5. relevant source code and tests

`PRD_V2.md` defines target architecture.  
`MASTER_TASKS.md` defines implementation order.  
Current code is evidence of what already exists, not proof that a requirement is complete.

---

# 2. MANDATORY WORKFLOW

For every task:

```text
READ
↓
INSPECT
↓
MAP CURRENT IMPLEMENTATION
↓
COMPARE WITH TARGET
↓
IDENTIFY GAP
↓
PLAN MINIMAL CHANGE
↓
IMPLEMENT
↓
TEST
↓
REVIEW DIFF
↓
UPDATE DOCS
↓
REPORT
```

Never skip the audit step for a subsystem that is already implemented.

---

# 3. FIRST ACTION: AUDIT ONLY

Before changing architecture, perform EPIC 00.

Produce:

- current architecture map;
- module inventory;
- agent inventory;
- event flow;
- task flow;
- risk/execution flow;
- data flow;
- dependency map;
- duplicate/dead-code findings;
- safety findings;
- PRD V1 vs PRD V2 deviation matrix;
- baseline test results.

**Do not refactor during the audit.**

---

# 4. CLASSIFY EVERY COMPONENT

For every relevant component, assign exactly one primary class:

```text
AI_MANAGER
AI_DEPARTMENT
AI_SPECIALIST
DETERMINISTIC_ENGINE
ORCHESTRATION
INFRASTRUCTURE
CONTROL_PLANE
```

Pay special attention to:

- Supervisor
- Risk
- Execution
- Event Manager
- Agent Router
- Research
- Position Monitor

Do not allow naming alone to determine authority. Inspect actual behavior.

---

# 5. AUTHORITY BOUNDARIES

The following rules are absolute:

AI may:

- analyze;
- interpret;
- delegate;
- synthesize;
- recommend;
- produce Trade Proposal.

Deterministic code owns:

- calculations;
- hard risk limits;
- final lot enforcement;
- safety checks;
- idempotency;
- execution;
- reconciliation;
- state integrity.

Supervisor must never:

- send an MT5 order;
- bypass the Risk Gate;
- change hard limits;
- fabricate missing data;
- assume specialist output is automatically correct.

---

# 6. HIERARCHY RULE

Implement this organizational model:

```text
SUPERVISOR
│
├── MARKET INTELLIGENCE LEAD
│   ├── Technical
│   ├── Structure
│   ├── Momentum
│   ├── Volatility
│   └── News/Sentiment
│
├── RISK INTELLIGENCE LEAD
│   ├── Account Risk
│   ├── Position Risk
│   ├── Portfolio Risk
│   └── Drawdown
│
└── RESEARCH LEAD
    ├── Strategy Research
    ├── Backtest
    ├── Walk Forward
    └── Performance
```

Department Leads decide which specialists are actually required for their assigned task.

## 7A. COMMITTEE / DEBATE RULE

The target is not independent agents returning opinions to the Supervisor. For decision-critical tasks, selected specialists must be able to inspect relevant peer findings and conduct a structured discussion.

Required behavior:

```text
Specialist analysis
→ peer evidence visibility
→ challenge / counter-argument
→ revision if warranted
→ Department consensus
→ Supervisor
```

The committee must output one structured conclusion, not merely a vote. It must preserve material disagreement and the reason the final conclusion won. Never implement naive majority voting as the decision authority. If disagreement remains material and unresolved, prefer WAIT/NO_TRADE/ESCALATE.

Separate:

```text
MARKET BIAS     = BULLISH / BEARISH / NEUTRAL
SETUP DIRECTION = BUY / SELL / NONE
ACTION          = ENTER / WAIT / MONITOR / CLOSE / REDUCE / ESCALATE
```

Example: `BULLISH + BUY BIAS + WAIT` is valid and must not be converted into an entry merely because some specialists say BUY.

Do not create fixed fan-out where all specialists run on every event.

---

# 7. SUPERVISOR BEHAVIOR

Supervisor must support:

```text
EVENT
→ inspect state
→ choose department
→ create task
→ wait for result
→ evaluate evidence
→ ask follow-up if needed
→ resolve conflict
→ create Decision State
→ create Trade Proposal / NO_TRADE
→ deterministic validation
```

A single event may require zero, one, or multiple specialist tasks.

A Supervisor may ask another specialist for second opinion only when justified by the evidence/state.

---

# 8. TASK CONTRACT

Every task must carry:

- task_id
- parent_task_id
- root_event_id
- creator
- assignment
- objective
- priority
- context requirements
- dependencies
- timeout
- attempt count
- max attempts
- expected output schema

Do not use ad-hoc dictionaries when a stable typed contract is appropriate.

---

# 9. EVIDENCE AND DECISION

Every material recommendation must be traceable to evidence.

Separate:

```text
FACT
INTERPRETATION
RECOMMENDATION
```

Before execution, produce a Decision State.

Never directly map raw agent text to a broker order.

---

# 10. CONFLICT RESOLUTION

Never resolve conflict by simple vote count.

Use:

1. evidence quality;
2. data freshness;
3. source reliability;
4. relevant timeframe;
5. targeted second opinion;
6. deterministic market/risk context.

When unresolved, prefer:

```text
WAIT
NO_TRADE
ESCALATE
```

over forced execution.

---

# 11. RISK / EXECUTION

Keep these concepts separate:

```text
Risk Intelligence = AI interpretation
Risk Engine        = deterministic calculation/enforcement
Risk Gate          = final PASS/BLOCK authority
Execution Engine   = deterministic broker operation
```

Execution is not an AI department.

Required path:

```text
Decision State
→ Trade Proposal
→ deterministic validation
→ Risk Gate
→ idempotency
→ execution
→ confirmation
→ reconciliation
→ audit
```

---

# 12. RECONCILIATION

Never assume internal state equals MT5 state.

Implement/reuse reconciliation for:

- positions;
- orders;
- lot;
- SL/TP;
- symbols;
- magic number;
- order status.

Critical mismatch must block new orders until resolved.

---

# 13. RESEARCH SAFETY

Trade review may generate hypotheses.

Research may create candidate strategy versions.

Research must never silently mutate LIVE strategy parameters.

Required promotion path:

```text
TRADE REVIEW
→ HYPOTHESIS
→ EXPERIMENT
→ BACKTEST
→ WALK FORWARD
→ PAPER
→ DEMO
→ VALIDATION
→ APPROVAL
→ STRATEGY VERSION
→ CONTROLLED ACTIVATION
```

---

# 13A. TRADE REVIEW AND LEARNING-BY-DOING

Every completed trade must be reviewed automatically. Classify root cause into strategy/analysis error, timing error, market-regime mismatch, news/event effect, execution/slippage/spread issue, risk issue, or normal probabilistic loss.

Evaluate meaningful WAIT/NO_TRADE decisions with counterfactual outcomes where possible. A correctly avoided trade is a valid positive decision outcome.

The system must discover patterns such as best/worst hours, sessions, setups, volatility regimes, news proximity, timeframes, symbols, and repeated win/loss conditions. Convert patterns into explicit hypotheses and experiments.

Supervisor performance telemetry should include win rate, profit factor, expectancy/R, drawdown, rolling performance, performance by hour/session/regime/setup, false-signal rate, and no-trade quality when sample size is sufficient. These are feedback metrics, never trade authorization.

Required learning loop:

```text
DO → REVIEW → PATTERN → HYPOTHESIS → EXPERIMENT
→ BACKTEST → WALK-FORWARD → PAPER → DEMO
→ VALIDATE → APPROVE → NEW STRATEGY VERSION
```

Never mutate LIVE strategy parameters directly from a trade result or LLM suggestion.

## 13B. AI PROVIDER / TELEGRAM REQUIREMENTS

9Router is the configured OpenAI-compatible gateway. Backend startup/health flow must discover models via `/v1/models`, normalize them into a registry, and route by policy. Do not hard-code a model list in the frontend. Provider secrets remain backend-only.

Telegram is an optional Control/Communication interface. It may query Supervisor for market status, why-no-trade, risk, positions, decisions, and reviews, and receive signal/execution/risk/system notifications. Telegram must never be required for autonomous operation and must never bypass deterministic Risk Gate or directly execute broker orders.

User questions must be answered from stored structured event/task/evidence/decision traces where possible; expose concise reasoning summaries, not raw hidden chain-of-thought.

# 14. MODEL ROUTING

Do not spend an expensive model on deterministic work.

Example policy:

- simple specialist analysis → low-cost model;
- normal synthesis → medium model;
- unresolved/high-risk/high-conflict Supervisor decision → stronger model;
- risk calculation / execution → no LLM.

Track model, tokens, latency, and fallback.

---

# 15. TOKEN AND CONTEXT EFFICIENCY

Never dump the entire database or entire conversation into an agent prompt.

Use Context Builder to create a minimal relevant snapshot.

Budget at:

- global;
- department;
- task;
- agent;
- model.

If budget is exhausted:

- defer;
- downgrade model;
- use deterministic path;
- or safely NO_TRADE for execution-critical cases.

---

# 16. UI RULES

Dashboard is a control plane, not just a chart page.

It must expose:

- AI hierarchy;
- current agent/task states;
- event trace;
- decision trace;
- risk result;
- execution result;
- research status;
- strategy version;
- system health.

Never expose raw hidden chain-of-thought. Show concise structured summaries and evidence.

---

# 17. PRESERVATION RULE

Before modifying an existing component, answer in the implementation notes:

1. What already works?
2. Which PRD V2 requirement does it satisfy?
3. What exact gap remains?
4. What is the smallest safe change?
5. Which tests prove no regression?

If no gap exists, **do not modify it**.

---

# 18. NO DUPLICATE SYSTEMS

Before adding any new:

- Event Manager
- Agent Router
- Risk Engine
- Risk Gate
- Execution Engine
- Memory system
- Research engine
- model router

search the repository for existing equivalents.

Prefer adapting an existing implementation over creating a competing subsystem.

---

# 19. ERROR HANDLING

Failures must be explicit and recoverable.

Required handling for:

- LLM timeout;
- invalid JSON/schema;
- unavailable model;
- MT5 disconnect;
- stale market data;
- queue failure;
- database failure;
- duplicate execution;
- reconciliation mismatch.

Fail safely.

---

# 20A. REQUIRED ACCEPTANCE TESTS FOR NEW CAPABILITIES

Before marking the correction complete, prove:

1. Supervisor operates without Telegram/user input.
2. Specialists can debate and produce one department consensus.
3. Material disagreement results in follow-up or safe WAIT/NO_TRADE/ESCALATE.
4. Telegram can explain prior decisions from stored structured traces.
5. Telegram cannot bypass Risk Gate or directly execute MT5.
6. 9Router models are discovered dynamically through `/v1/models`.
7. Provider failure fails safely and does not trigger uncontrolled trading.
8. Trade reviews classify root causes and persist lessons.
9. Performance analytics can identify time/session/setup/regime patterns.
10. Research hypotheses cannot mutate LIVE strategy directly.

# 20. TEST DISCIPLINE

After each task:

1. run focused unit tests;
2. run relevant integration tests;
3. run lint/type checks where applicable;
4. inspect git diff;
5. verify no unrelated changes;
6. update task status.

Never mark a task complete because code “looks correct”.

---

# 21. CHECKPOINT REPORT FORMAT

After each task, report:

```text
TASK: 06.04
STATUS: DONE

IMPLEMENTED:
- ...

PRESERVED:
- ...

NOT CHANGED:
- ...

TESTS:
- ...

FAILURES:
- none / ...

DEVIATIONS REMAINING:
- ...

NEXT TASK:
- ...
```

---

# 22. STOP CONDITIONS

Stop and report instead of guessing when:

- two existing modules have conflicting authority;
- a migration could destroy existing trading data;
- an existing behavior is undocumented and safety-critical;
- a dependency is unavailable;
- a required environment secret is missing;
- a refactor would affect unrelated production paths.

When stopped, produce a concrete blocker report and continue only with independent safe tasks.

---

# 23. FIRST EXECUTION COMMAND

Your first implementation action is **EPIC 00 audit only**.

Do not begin architectural refactoring until the audit artifacts exist.

The target is not “maximum code changed”.

The target is:

> **minimum safe changes required to make the existing repository conform to PRD V2.**

