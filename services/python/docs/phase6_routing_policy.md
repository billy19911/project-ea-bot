# Phase 6 — Routing / Budget / Failure-Escalation Policies

## Routing policy (§8, §29, §34, §37)

Version `routing-v1`. Selection inputs: task_type, risk_tier, complexity,
required_capabilities, conflict level, budget, provider health.

| Complexity | Tier | Effort |
|-----------|------|--------|
| LOW | free/cheap | LOW |
| MEDIUM | cheap/standard | MEDIUM |
| HIGH | strong | HIGH |
| CRITICAL | strong + challenge/escalation | MAX |

High/critical conflict → stronger model OR independent second opinion OR
targeted challenger (bounded, never "call every model"). Unresolved conflict →
WAIT/NO_TRADE per canonical policy. Role mapping is config-driven
(`TASK_DEFAULTS` + request overrides), not forced-uniform.

## Effort (§10)

`LOW/MEDIUM/HIGH/MAX` normalized. Passed ONLY when the registry declares the
model supports reasoning/effort; otherwise the parameter is omitted — never
fabricated.

## Budget policy (§11–§13, §32)

Hierarchical: system → cycle → task → agent → request (cycle ledger
implemented; config-derived ceilings). Reservation before expensive calls;
STOP/DEGRADE on exhaustion; deterministic safety layers (TriggerEngine,
DecisionState, RiskGate, MoneyManager, ExecutionEngine) never depend on AI
budget.

Config ceilings (RouterConfig): max_cost_per_request / per_cycle / per_day,
max_calls_per_cycle, max_output_tokens, max_specialists, max_parallel_calls,
max_debate_rounds, max_challenges, max_escalations, max_depth, max_repair_attempts.

## Failure & escalation (§14–§16, §54, §57–§58)

| Failure | Policy |
|---------|--------|
| provider unavailable | bounded fallback chain |
| timeout | mark UNKNOWN/FAILED, bounded fallback |
| rate limit | backoff (NineRouterClient) then fallback |
| invalid output | bounded repair (max 1), else reject |
| context overflow | context builder truncation (blocking preserved) |
| all providers down | AI task FAILED → caller WAIT/NO_TRADE |

Escalation is bounded (max_escalations + max_depth loop guard); it never means
"keep trying until an answer appears". Failure never bypasses
TriggerEngine/RiskGate and never fabricates an answer.

## Circuit / health (§57–§58)

`provider_health()` tracks calls/errors/state (HEALTHY/DEGRADED). No unbounded
retry storm. Health is a routing signal only within explicit config policy.
