# XYNNBOT — MASTER CRITICAL FIX & INTEGRATION PLAN
## Repository: `billy19911/project-ea-bot`

> **Purpose:** one master execution plan for OpenCode/AI coding agents.
>
> **Execution rule:** Tasks MUST be completed in order. A task is not complete merely because code was changed or unit tests pass. Each task has a STOP GATE. The agent MUST NOT start the next task until every acceptance criterion and verification command for the current task passes.
>
> **Safety:** keep all MT5 execution paths DISARMED by default. Demo execution may be explicitly armed by the operator. LIVE terminals must remain disarmed unless explicitly armed.

---

# 0. NON-NEGOTIABLE OPERATING CONTRACT

The final architecture must satisfy all of these invariants:

1. **One Supervisor, one canonical signal per market opportunity.**
2. A single canonical signal may fan out to multiple eligible MT5 terminals/accounts.
3. Fan-out MUST NOT cause a second AI analysis or a different entry for another account.
4. Each account/terminal gets deterministic broker normalization and its own deterministic risk validation.
5. LIVE accounts are supported but default to DISARMED.
6. DEMO accounts are also DISARMED by default and become executable only after explicit ARM.
7. ARM is an execution permission, not an analysis trigger.
8. No order may reach native MT5 execution without deterministic approval.
9. The exact final order sent to broker MUST be the same order that passed the final risk validation.
10. R is calculated from ORIGINAL entry risk:
    - BUY: `(exit - entry) / abs(entry - initial_SL)`
    - SELL: `(entry - exit) / abs(entry - initial_SL)`
11. Trailing SL/BEP/progressive SL MUST NOT redefine initial R.
12. Every closed broker trade must be traceable to its entry context and review record.
13. Performance must use persisted closed-trade records, not only process memory.
14. Supervisor is event-driven: no periodic "analyze every N minutes" decision loop.
15. Market polling may happen periodically, but supervisor analysis only happens after a qualifying event.
16. Duplicate market events must be suppressed deterministically.
17. Committee messages must describe actual evidence and disagreement, not repeat canned templates.
18. AI Control must distinguish:
    - Python unavailable
    - endpoint 4xx
    - endpoint 5xx
    - agent error
    - LLM provider 5xx/503
    - timeout
19. A 503 must never be displayed as a generic "agent error" without the real failure layer.
20. No orphaned production component may silently run independently.
21. Every production component must have one of:
    - runtime entry point,
    - explicit background worker,
    - API endpoint,
    - scheduled lifecycle,
    - test-only classification.
22. Every claimed feature in UI must map to a real backend source.
23. No mock data may remain on operational pages.
24. UI headers must remain aligned at desktop, tablet, and mobile widths.

---

# 1. CURRENT AUDIT SUMMARY

## Confirmed working concepts

- Event-driven scheduler exists.
- Scheduler supports `wake()` and does not need to wait for the poll interval after a new event.
- Market feed has fingerprint deduplication and an event cooldown.
- Supervisor routes events to specialists.
- Supervisor can dispatch concurrently.
- Committee synthesis exists.
- Deterministic Risk Gate exists in the main pipeline.
- Execution approval token is enforced by the production executor.
- MT5 terminal arm state is explicit and starts OFF.
- Terminal switching disarms before/after switching.
- Entry context has persistent JSONL support for ORIGINAL stop loss and entry data.
- Auto-review is wired to position-close detection.
- Performance page has R-multiple UI and an `/v2/r-performance` endpoint.
- Node API proxies Python service and intentionally returns 503 when Python is unreachable.

## Confirmed incomplete / dangerous areas

### P0/P1

- R/performance depends on the close/review path and is not a durable performance ledger.
- Review history is process-memory based; persisted entry context alone is insufficient for historical performance.
- Risk projection does not consistently validate `current exposure + proposed exposure`.
- Broker normalization can occur after risk validation; final order must be validated after normalization.
- Reconciliation internal ledger is not a durable broker-correlated order ledger.
- Order state machine is not a strong transition-enforcement boundary.
- Restart recovery is incomplete.
- Market feed has fingerprint/cooldown protection but stale-age protection is incomplete.
- LLM output validation is incomplete.
- Several governance/learning components are orphaned or test-only.
- Multi-terminal runtime is not yet the requested "one signal -> N MT5 accounts" architecture.
- AI Control 503 can be a generic proxy-level error and needs proper failure attribution.
- Dashboard contains pages/components whose "real" status varies; audit all UI-to-API mappings.
- Header/topbar layout can overflow or become visually imprecise at intermediate widths.

---

# 2. TARGET ARCHITECTURE

```text
MT5 READ-ONLY FEEDS
        |
        v
Market Feed Loop
        |
        v
Event Detector
        |
        +---- dedup / cooldown / stale-data gate
        |
        v
Event Queue
        |
        v
EVENT-DRIVEN SCHEDULER
        |
        v
SUPERVISOR
        |
        +------------------------------+
        |                              |
        v                              v
Market Department                Risk/Context checks
        |
        +------------------------------+
        |
        v
COMMITTEE / SYNTHESIS
        |
        v
CANONICAL TRADE INTENT
(signal_id / opportunity_id)
        |
        v
DETERMINISTIC COMPLETION
(entry / initial SL / TP / risk / RR / volume)
        |
        v
FINAL BROKER NORMALIZATION
        |
        v
PER-ACCOUNT RISK VALIDATION
        |
        v
FAN-OUT PLAN
        |
        +--------> MT5 DEMO A
        |
        +--------> MT5 DEMO B
        |
        +--------> MT5 LIVE A
        |
        +--------> MT5 LIVE B
        |
        v
PER-ACCOUNT EXECUTION
        |
        v
BROKER RECONCILIATION
        |
        v
PERSISTED TRADE LEDGER
        |
        v
POSITION CLOSE / DEAL HISTORY
        |
        v
PERSISTED REVIEW
        |
        +----> R / performance
        +----> learning
        +----> pattern statistics
        +----> supervisor feedback
```

Important:

**Supervisor must produce one canonical market decision.**

Accounts must NOT independently call the committee for the same event.

---

# 3. TASK 01 — R/R + PERFORMANCE PIPELINE

## Goal

Make R/R and performance a reliable end-to-end data pipeline.

## Required investigation

Trace:

```text
entry
→ final order
→ original SL
→ ticket/position identity
→ close detection
→ closing deal lookup
→ review
→ R calculation
→ persistence
→ /v2/r-performance
→ Performance page
```

Do not assume the existing `entry_context` persistence is enough.

## Required implementation

### 3.1 Persist a canonical trade ledger

Create or reuse a durable store containing at minimum:

```text
trade_id
signal_id
opportunity_id
account_id
terminal_id
symbol
direction
volume
entry_price
initial_stop_loss
initial_take_profit
initial_risk_price_distance
initial_risk_money
target_rr
opened_at
closed_at
exit_price
pnl
r_multiple
close_reason
broker_order_ticket
broker_deal_ticket
broker_position_ticket
status
review_status
created_at
updated_at
```

### 3.2 RR must be explicit

Store:

```text
risk_distance = abs(entry - initial_SL)
reward_distance = abs(initial_TP - entry)
planned_rr = reward_distance / risk_distance
```

Do not infer RR from current/trailing SL.

### 3.3 R calculation

Use the ORIGINAL SL.

BUY:

```text
R = (exit - entry) / abs(entry - initial_SL)
```

SELL:

```text
R = (entry - exit) / abs(entry - initial_SL)
```

Reject/mark unavailable if:

```text
entry <= 0
exit <= 0
initial_SL <= 0
direction unknown
risk_distance <= 0
```

Never fabricate R.

### 3.4 Close detection must use MT5 deal history

Do not depend only on:

```text
positions_get()
```

When a position disappears:

1. identify position ticket;
2. query deal/order history;
3. identify the closing deal;
4. retrieve actual close price/time/PnL;
5. join it with the durable trade ledger;
6. create/update review exactly once.

### 3.5 Persist the review

The Performance page must not depend only on `ReviewAutoTrigger._history`.

Review records must survive process restart.

### 3.6 Performance API

`/v2/r-performance` must read from durable review/trade records.

Return:

```text
trade_count
reviews_total
r_available
r_unavailable
overall
period buckets
```

Performance should show both:

- all closed trades;
- trades with valid R.

### 3.7 Performance UI

Change the empty state to distinguish:

```text
No closed trades
```

from:

```text
Closed trades exist, but R unavailable
```

and:

```text
API unavailable
```

and:

```text
Review pipeline has not processed closes
```

## Required tests

- BUY + profitable close
- BUY + losing close
- SELL + profitable close
- SELL + losing close
- exact 1R
- exact 2R
- exact 3R
- trailing SL changed after entry
- BEP after entry
- missing original SL
- restart before close
- restart after close
- manual broker close
- fast SL/TP close
- partial close
- duplicate close event
- same symbol on multiple accounts

## STOP GATE 01

Do not continue until:

```text
[ ] R is visible for a newly closed DEMO trade
[ ] RR is stored on the entry record
[ ] R survives Python service restart
[ ] Performance survives restart
[ ] trailing SL does not alter initial R
[ ] duplicate close does not duplicate review
[ ] API distinguishes unavailable vs zero
[ ] all R tests pass
```

---

# 4. TASK 02 — EVENT-DRIVEN SUPERVISOR / WAKE MODEL

## Goal

Ensure the supervisor does NOT wake every 1–2 minutes just to ask for another analysis.

The desired behavior is:

```text
NO EVENT
   ↓
SUPERVISOR IDLE

QUALIFYING EVENT
   ↓
wake scheduler immediately
   ↓
supervisor
   ↓
committee
   ↓
decision
```

## Important distinction

The market feed may poll MT5 every N seconds.

That is NOT the same as supervisor analysis.

Polling:

```text
MT5 → read latest bars
```

is allowed.

Analysis:

```text
Supervisor → agents → committee
```

must only occur after a qualifying event.

## Investigate why user currently sees 1–2 minute analysis

Trace:

```text
feed_loop.py
EventDetector
event cooldown
event fingerprint
EventQueue
scheduler.wake()
pipeline
Supervisor
```

Record for every analysis:

```text
event_id
event_type
event_created_at
bar_time
feed_poll_time
queue_time
scheduler_wake_time
supervisor_start
supervisor_end
```

Then determine whether the 1–2 minute cadence is caused by:

1. actual event generation,
2. candle close cadence,
3. cooldown,
4. repeated event types,
5. manual polling endpoint,
6. UI auto-refresh being mistaken for supervisor activity,
7. a background worker invoking pipeline directly,
8. duplicate scheduler/runtime instances.

## Event classes

Separate:

### TRADE_TRIGGER events

Examples:

```text
BREAKOUT
BREAKDOWN
REVERSAL
STRUCTURE_SHIFT
MOMENTUM_CONFIRMATION
ZONE_ENTRY
VOLATILITY_EXPANSION
```

These may trigger committee analysis.

### CONTEXT_UPDATE events

Examples:

```text
NEWS_UPDATE
ECONOMIC_EVENT
REGIME_CHANGE
VOLATILITY_CHANGE
```

These may update context but should not necessarily create a new trade proposal.

### HOUSEKEEPING events

Examples:

```text
RECONCILIATION
HEALTH_CHECK
METRICS
```

These must never create a trade signal.

### TRADE_CLOSE

This triggers review/learning and may optionally request a new market opportunity evaluation, but it must not blindly repeat the previous signal.

## Required behavior

For one opportunity:

```text
event A
→ committee
→ signal_id = S1
```

Additional identical events:

```text
event A duplicate
event A duplicate
```

must not create:

```text
S2
S3
S4
```

unless the opportunity materially changed.

## STOP GATE 02

Do not continue until:

```text
[ ] Supervisor does not run on a fixed 1–2 minute decision timer
[ ] A qualifying event wakes the scheduler immediately
[ ] Duplicate events do not create duplicate committee cycles
[ ] UI polling cannot trigger analysis
[ ] Health/reconciliation cannot trigger a trade proposal
[ ] Event trace shows exact wake cause
[ ] Tests cover event/no-event/duplicate-event behavior
```

---

# 5. TASK 03 — SUPERVISOR + COMMITTEE BEHAVIOR

## Goal

Make the hierarchy logically correct and committee conversation natural.

## Current concern

The current synthesis produces highly structured strings such as:

```text
Konsensus: BUY (...)
Kesepakatan: ...
Keyakinan rata-rata: ...
Konflik: ...
```

This is useful for machines but reads like a template rather than an actual committee discussion.

## Required architecture

Supervisor:

```text
1. receives event
2. decides which departments are relevant
3. requests evidence
4. collects specialist outputs
5. challenges conflicts
6. asks for confirmation only when needed
7. synthesizes one canonical intent
```

Department leads:

```text
Market Lead
Risk Lead
Review Lead
```

Specialists:

```text
Structure
Momentum
Volatility
News
Macro
```

## Do NOT

Do not make every agent speak on every event.

Example:

```text
BREAKOUT
```

should not automatically require:

```text
News
Macro
Review
Volatility
Momentum
Structure
```

if their evidence is irrelevant.

## Natural committee format

Internal machine output remains structured.

Human-facing message should look like:

```text
OVERWATCH

Structure sees a bullish break above the recent range, but the breakout is still
close to the previous resistance zone.

Momentum agrees with the direction, although strength is not extreme yet.

Volatility is acceptable for the setup.

News has no immediate high-impact contradiction.

Committee view:
BUY remains valid, but only if price holds above the breakout level.
```

For disagreement:

```text
Structure: BUY
Momentum: NEUTRAL
Volatility: elevated

OVERWATCH:
The structure supports continuation, but momentum has not confirmed it.
I am not treating this as a clean entry yet.

Decision: WAIT
Reason: confirmation missing.
```

No fake conversational fluff.

## Required structured data

Every committee cycle must persist:

```text
event
agents_called
agents_skipped
agent_outputs
conflicts
evidence
supervisor_reasoning
decision
confidence
signal_id
```

## STOP GATE 03

```text
[ ] Relevant specialists only
[ ] Conflicts are visible
[ ] Supervisor explains why a specialist was called
[ ] Supervisor explains why a trade was rejected
[ ] Human-facing committee text is natural
[ ] Machine structured output remains deterministic
[ ] No agent independently creates an order
```

---

# 6. TASK 04 — AI CONTROL / 503 DIAGNOSTICS

## Goal

Fix the AI Control page so 503 errors identify the actual failing layer.

Current Node proxy intentionally returns:

```text
503 python_service_unavailable
```

when the Python service is unreachable.

That is correct behavior at the proxy boundary, but the UI must not call every 503 an "agent error".

## Required error taxonomy

```text
NODE_API_UNAVAILABLE
PYTHON_SERVICE_UNAVAILABLE
PYTHON_ENDPOINT_4XX
PYTHON_ENDPOINT_5XX
AGENT_TIMEOUT
AGENT_EXCEPTION
LLM_PROVIDER_4XX
LLM_PROVIDER_5XX
LLM_PROVIDER_503
LLM_TIMEOUT
MODEL_UNAVAILABLE
AUTH_FAILURE
DATA_GUARD_FAILURE
```

Every error should carry:

```text
trace_id
service
endpoint
status_code
agent
event_id
model
provider
timestamp
message
retryable
```

## AI Control UI

Show:

```text
Supervisor: ACTIVE
Python: HEALTHY
LLM Gateway: HEALTHY
9Router: HEALTHY
Agents: 7 active / 1 error
```

If an agent errors:

```text
TREND-SCAN
Status: ERROR
Cause: LLM_PROVIDER_503
Provider: ...
Model: ...
Retryable: YES
Last event: ...
Trace: ...
```

Not simply:

```text
agent error
```

## Retry policy

Only retry errors marked retryable.

Do not retry:

```text
invalid schema
risk rejection
auth failure
missing data
```

## STOP GATE 04

```text
[ ] Simulate Python unavailable → UI says Python unavailable
[ ] Simulate LLM 503 → UI says LLM provider 503
[ ] Simulate agent exception → UI says agent exception
[ ] Trace ID visible
[ ] Retryability visible
[ ] No generic misleading 503 label
[ ] AI Control remains usable with partial subsystem failure
```

---

# 7. TASK 05 — COMPLETE SOURCE WIRING / ORPHAN AUDIT

## Goal

Determine exactly what runs in production.

Create:

```text
docs/audit/PRODUCTION_WIRING_MAP.md
```

For every module, classify:

```text
LIVE_RUNTIME
BACKGROUND_WORKER
API_ENDPOINT
UI_ONLY
TEST_ONLY
LEGACY
ORPHANED
DEAD_CODE
```

## Known candidates requiring explicit classification

From current audit:

```text
llm/model_router.py
learning/engine_v2.py
learning/*
execution/order_builder.py / ExecutionRecoveryEngine
paper/simulated_execution.py
memory/*
agents/task.py
orchestration/context_builder.py
agents/evidence.py
agents/decision_state.py
agents/permissions.py
risk/MultiLevelBreaker
risk/CapitalAllocator
trading/EventDeduplicator
research/*
strategy/LifecycleGovernor
market/intelligence legacy committee
```

Do NOT delete code automatically.

First classify and document.

## Runtime singleton rule

There must be exactly one production instance of:

```text
runtime
scheduler
event queue
supervisor
pipeline
market feed loop
position monitor
reconciliation runner
```

unless a component is explicitly scoped per account/terminal.

## Detect duplicate workers

Add runtime identity:

```text
process_id
runtime_instance_id
scheduler_instance_id
feed_instance_id
```

Every analysis log must include them.

## STOP GATE 05

```text
[ ] Every production module has a known entry path
[ ] Every background worker has one owner
[ ] No duplicate scheduler/feed loops
[ ] Orphans are documented
[ ] Legacy code is not accidentally imported
[ ] No hidden test-only component is assumed to be production
```

---

# 8. TASK 06 — MULTI-MT5 / ONE SIGNAL → MANY ACCOUNTS

## Goal

Implement the exact desired trading model:

```text
1 Supervisor
    ↓
1 Committee
    ↓
1 Canonical Signal
    ↓
N MT5 Accounts
```

## Canonical signal

Create immutable:

```text
signal_id
opportunity_id
symbol
direction
entry_reference
initial_SL
initial_TP
planned_RR
risk_policy
strategy_version
created_at
evidence_hash
```

The same `signal_id` is used for every account.

## Fan-out

For each eligible terminal:

```text
canonical signal
    ↓
account-specific context
    ↓
broker normalization
    ↓
account-specific Risk Gate
    ↓
execution
```

The signal itself MUST NOT be changed.

Only account-specific values may differ when required by broker constraints:

```text
volume
digits
point
min/max/step
price normalization
margin availability
account risk budget
```

## Critical rule

If:

```text
Account A → approved
Account B → rejected
Account C → approved
```

the system must NOT ask Supervisor to generate another signal for B.

B is simply:

```text
signal_id S1
account B
status REJECTED
reason ...
```

## Fan-out status

Use:

```text
signal_status:
  CREATED
  VALIDATED
  PARTIALLY_EXECUTED
  EXECUTED_ALL
  REJECTED_ALL
  EXPIRED
```

and per account:

```text
PENDING
APPROVED
REJECTED
SUBMITTING
SUBMITTED
FILLED
FAILED
RECONCILED
CLOSED
```

## Demo/Live arming

Every terminal:

```text
execution_allowed = true/false
armed = false
environment = DEMO/LIVE
```

Default:

```text
armed = false
```

Always.

LIVE may be configured as an eligible terminal but remains DISARMED.

Demo can be explicitly armed.

Terminal selection must not be the only way to control execution if multi-terminal fan-out is enabled.

## STOP GATE 06

```text
[ ] One event creates one signal_id
[ ] One supervisor analysis only
[ ] 2+ demo terminals receive the same signal_id
[ ] Live terminal can be configured but starts disarmed
[ ] Arm is explicit
[ ] One account rejection does not create a second signal
[ ] Per-account risk is enforced
[ ] No account can bypass the canonical signal
[ ] Duplicate fan-out cannot duplicate orders
```

---

# 9. TASK 07 — RISK / FINAL ORDER INVARIANT

## Goal

Make risk validation apply to the exact final order.

Correct order:

```text
AI proposal
→ deterministic completion
→ broker normalization
→ final order
→ projected exposure calculation
→ final Risk Gate
→ execution
```

NOT:

```text
Risk Gate
→ normalize
→ execute
```

## Projected exposure

Must validate:

```text
existing exposure
+
proposed trade exposure
<= exposure limit
```

not only current exposure.

## Monetary risk

For XAU/CFD:

```text
risk_money =
abs(entry - initial_SL)
× contract_size
× volume
```

Use actual broker symbol specification.

No invented fallback contract size.

## STOP GATE 07

```text
[ ] final normalized volume is risk-checked
[ ] proposed exposure is included
[ ] monetary SL risk is correct
[ ] broker contract specification is used
[ ] final order sent == final order approved
[ ] tests cover lot rounding upward/downward
```

---

# 10. TASK 08 — RECONCILIATION + RESTART RECOVERY

## Goal

Make broker state and internal state converge safely.

## Durable order identity

Persist:

```text
intent_id
signal_id
account_id
terminal_id
broker_order_ticket
broker_deal_ticket
broker_position_ticket
```

## Restart sequence

After service restart:

```text
load durable intents
connect MT5
read open positions
read recent orders/deals
reconcile
rebuild internal state
ONLY THEN permit new execution
```

If state is uncertain:

```text
BLOCK NEW ORDERS
```

Do not interpret:

```text
internal = empty
```

as:

```text
broker = empty
```

## STOP GATE 08

```text
[ ] Restart with open trade → state restored
[ ] Restart with closed trade → review still possible
[ ] Orphan broker position blocks new entries
[ ] Unknown reconciliation state blocks new entries
[ ] Duplicate recovery does not create duplicate order
```

---

# 11. TASK 09 — MARKET FRESHNESS

## Goal

Prevent stale market data from producing a trade.

Every market snapshot requires:

```text
bar_timestamp
received_at
age_seconds
timeframe
symbol
```

Reject when:

```text
age_seconds > max_allowed_age
```

Use a timeframe-aware threshold.

Example:

```text
M1: strict
M5: wider
H1: wider
```

Do not hard-code one universal value without documenting it.

## STOP GATE 09

```text
[ ] stale snapshot rejected
[ ] fresh snapshot accepted
[ ] clock anomaly rejected
[ ] stale state visible in UI
[ ] stale data cannot reach committee as trade-ready context
```

---

# 12. TASK 10 — UI / HEADER / RESPONSIVE PROFESSIONAL PASS

## Goal

Fix header widths/alignment without redesigning the entire application.

Current AppShell has:

```text
topbar
topbarText
actions
```

with fixed non-shrinking actions. This can create pressure at intermediate widths.

## Required changes

Use a robust layout:

```css
grid-template-columns: minmax(0, 1fr) auto;
```

or equivalent.

Ensure:

```text
topbarText: min-width: 0
actions: flex-wrap: wrap where appropriate
buttons: never overflow viewport
environment badge: never clip
theme toggle: never clip
page actions: move/wrap at defined breakpoint
```

Do not solve by hiding critical status.

## Responsive breakpoints

Verify at:

```text
1920
1600
1440
1280
1100
1024
920
768
480
390
```

## Check

- topbar border extends exactly to content width
- title aligns with page body
- right controls align consistently
- no horizontal scrollbar
- sticky header does not overlap content
- action controls do not push title outside viewport
- collapsed sidebar keeps exact content alignment

## STOP GATE 10

```text
[ ] no horizontal overflow
[ ] header aligned at all listed widths
[ ] title/action spacing consistent
[ ] sticky behavior correct
[ ] desktop/tablet/mobile screenshots visually inspected
[ ] tsc passes
[ ] lint passes
```

---

# 13. TASK 11 — OPERATIONAL UI DATA INTEGRITY

Audit all pages:

```text
Overview
Market
Orders
Positions
Trade History
Decisions
Decision Replay
Risk Center
Execution
AI Control
Agents
Performance
Learning
Accounts
Certification
Observability
Reconciliation
```

For each page:

```text
UI field
→ API endpoint
→ backend handler
→ Python source
→ actual data source
```

Mark:

```text
REAL
DERIVED
SIMULATED
MOCK
UNAVAILABLE
```

No operational page should silently show mock data.

---

# 14. TASK 12 — ADVERSARIAL E2E CERTIFICATION

Create tests proving invariants across the whole stack.

Required scenarios:

### A. No event

```text
market feed polls
→ no qualifying event
→ supervisor remains idle
→ no proposal
```

### B. Event

```text
qualifying event
→ wake
→ supervisor
→ committee
→ one signal
```

### C. Duplicate event

```text
same event
→ no duplicate signal
```

### D. Multi-account

```text
one signal
→ 3 accounts
→ 3 execution attempts
→ same signal_id
```

### E. One account fails

```text
A success
B failure
C success

NO second AI analysis.
```

### F. Risk

```text
existing exposure 25%
proposal adds 10%
limit 30%

→ BLOCK
```

### G. Restart

```text
open broker position
→ restart
→ reconcile
→ state restored
```

### H. R

```text
entry 2500
initial SL 2495
exit 2510

BUY:
risk = 5
reward = 10
R = +2
RR = planned reward / risk
```

### I. Trailing

```text
initial SL = 2495
trailing SL = 2506
exit = 2510

R remains calculated from 2495.
```

### J. AI provider 503

```text
LLM → 503
→ agent error classified
→ no order
→ UI shows provider 503
```

### K. Python service down

```text
Python down
→ Node returns 503
→ UI says Python unavailable
```

### L. LIVE disarmed

```text
LIVE terminal configured
→ startup
→ DISARMED
→ signal may be analysed
→ no native order
```

### M. DEMO armed

```text
DEMO terminal
→ explicit ARM
→ signal passes all gates
→ execution allowed
```

---

# 15. TASK EXECUTION PROTOCOL FOR OPENCODE

The agent MUST execute only one task at a time.

For each task:

```text
1. READ
2. TRACE
3. PLAN
4. IMPLEMENT
5. TEST
6. VERIFY RUNTIME WIRING
7. UPDATE DOCUMENTATION
8. WRITE COMPLETION REPORT
9. STOP
```

The completion report must include:

```text
TASK:
STATUS: PASS / BLOCKED

FILES CHANGED:
- ...

ROOT CAUSE:
- ...

FIX:
- ...

TESTS:
- command
- result

RUNTIME VERIFICATION:
- ...

REMAINING ISSUES:
- ...

NEXT TASK:
NOT STARTED
```

If any acceptance criterion fails:

```text
STATUS: BLOCKED
```

and STOP.

Do not start the next task.

---

# 16. MASTER STOP RULE

The following is forbidden:

```text
"Tests pass, continuing to next task."
```

unless the task's STOP GATE is explicitly checked.

The agent must not:

- skip a task,
- combine unrelated tasks,
- mark TODO as fixed without runtime evidence,
- delete orphan code without classification,
- change trading behavior without tests,
- enable LIVE execution,
- change default arm state to ON,
- create multiple supervisor signals for multiple MT5 accounts,
- hide UI errors to make the dashboard look healthy.

---

# 17. FINAL CERTIFICATION

The project is NOT considered ready until:

```text
[ ] TASK 01 PASS
[ ] TASK 02 PASS
[ ] TASK 03 PASS
[ ] TASK 04 PASS
[ ] TASK 05 PASS
[ ] TASK 06 PASS
[ ] TASK 07 PASS
[ ] TASK 08 PASS
[ ] TASK 09 PASS
[ ] TASK 10 PASS
[ ] TASK 11 PASS
[ ] TASK 12 PASS
```

Final required statement:

```text
SYSTEM INTEGRATION STATUS: PASS

Supervisor:
  EVENT-DRIVEN

Signal model:
  ONE CANONICAL SIGNAL → MULTI ACCOUNT FAN-OUT

Execution:
  DISARMED BY DEFAULT

LIVE:
  SUPPORTED / DISARMED BY DEFAULT

DEMO:
  SUPPORTED / DISARMED BY DEFAULT

Risk:
  FINAL-ORDER VALIDATED

Reconciliation:
  DURABLE

Performance:
  R/R + R PERSISTED

AI Control:
  ERROR SOURCE IDENTIFIABLE

UI:
  RESPONSIVE / NO OVERFLOW

Orphan audit:
  COMPLETE

Adversarial E2E:
  PASS
```

If any line cannot be proven:

```text
SYSTEM INTEGRATION STATUS: BLOCKED
```

Do not claim production readiness.
