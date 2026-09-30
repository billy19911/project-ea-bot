# Phase 6 — Model Router Architecture

## Authoritative gateway

`src/llm/router.py::CanonicalModelRouter` is the single AI-orchestration
gateway. All non-trivial LLM work flows: ModelRequest → classify → risk tier →
route → budget reserve → versioned sanitized prompt → bounded execution →
schema + forbidden-authority validation → bounded fallback/escalation →
ModelDecisionRecord + budget commit + snapshot-safe cache.

Existing classes are WRAPPED, not forked: `llm.model_router.ModelRouter`
(deterministic selection), `ModelRegistry` (models/pricing/health/discovery),
`NineRouterClient` (9Router OpenAI-compatible execution). The advisor
(`LLMAdvisor.advise`) now routes through it with its injected client as the
backing transport.

## Registry & provider (§2–§4)

`ModelInfo` extended contract (name/provider/is_free/context_window/costs/
capabilities) is consumed as-is; `CanonicalModelRouter._capability_filter`
rejects models lacking required capabilities (unknown models allowed —
registry may lag). 9Router stays the configured provider (base_url/api_key
from env); no other provider is hardcoded, and no code assumes tools/JSON/
effort/streaming support — `_model_supports_effort` checks capabilities and
omits the parameter when unsupported (§10).

## Task, risk, complexity (§5–§8)

`TASK_DEFAULTS` maps each of the 15 task types to a (risk_tier, complexity)
base; explicit request fields override. T0–T4 are orchestration tiers (not
RiskGate risk). LOW→free, MEDIUM→cheap, HIGH/CRITICAL→strong via the legacy
router; HIGH orchestration risk forbids free models; conflict/critical
upgrades. Event-driven dispatch (Phase 3) is preserved — the router never
invokes the full committee per M1 candle (§9).

## Budget (§11–§13, §32–§33)

`BudgetLedger` per cycle_id: reserve-before-call, commit-after (with refund of
unused estimate, mirroring the advisor pattern). UNKNOWN cost is preserved as
no-cost-limit, never faked to zero. Exhaustion → STOP/DEGRADE (optional AI
stopped; deterministic safety untouched). RouterConfig centralizes all limits
(specialists, parallel, debate, challenges, escalations, calls/cycle, depth,
cost ceilings, output tokens).

## Escalation & fallback (§14–§16)

Bounded chain: primary + `max_escalations` fallbacks, then FAILED/UNKNOWN —
never unbounded retries. Timeout per request; no duplicate side effects (LLM
calls treated side-effect-free). Last error surfaced honestly for telemetry.

## Validation (§17–§18, §51)

`OutputValidator.validate`: JSON/object shape, required fields, enum allowlist,
forbidden-authority stripping (`final_volume`, `risk_override`, `bypass_risk`,
`execute_mt5`, `activate_strategy`, `promote_live`, …). Invalid → rejected or
bounded single repair; never trusted into canonical components.

## Context & cache (§22–§26)

`ContextBuilder`: priority-ordered (state → blocking → evidence → setup →
history → narrative), deterministic truncation that NEVER drops blocking
conditions; summaries preserve IDs/timestamps/direction/state/reason codes.
`SnapshotCache`: key = model|prompt|input-hash|SNAPSHOT|strategy — a new market
snapshot can never hit a stale answer.

## Provenance (§19–§21, §29–§30, §55–§56)

Every call yields `ModelDecisionRecord` (request/cycle/task/role, provider,
model, routing + prompt versions, effort, tokens, cost-or-UNKNOWN, latency,
retries, fallback, escalation, status, evidence refs). Prompts are immutable
versions (`PromptRegistry`); routing policy is versioned (`RoutingPolicyVersion`
`routing-v1`). Cost aggregates by model/agent/task with unknown-cost counters
(`cost_summary`); provider health observable (`provider_health`).

## Security (§41–§44, §49–§52)

External text is untrusted DATA in a labeled section, never authorization
(prompt-injection test asserts SYSTEM POLICY + untrusted labeling). Tool roles
are separated by construction: the router exposes no tool surface; analysis
roles receive no execution tools; research roles cannot activate strategies.
UNKNOWN is preserved (news/metadata), never best-guessed.
