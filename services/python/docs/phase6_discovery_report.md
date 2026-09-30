# PHASE 6 DISCOVERY REPORT — Model Router, Agent Intelligence & Budget

## 1. Current provider abstraction

`src/llm/base.py`: `BaseLLMProvider` (ABC: `generate`/`stream`), `TokenUsage`
(prompt/completion/total/cost_usd), `ModelInfo` (name/provider/is_free/
context_window/costs/capabilities), `LLMResponse` (content/model/usage/raw/
latency/is_fallback), usage aggregates + reset. Clean interface; all traffic
flows through it.

## 2. Current model selection logic

`src/llm/model_router.py::ModelRouter.route(complexity, priority, risk_level,
conflict_severity, budget_remaining_usd, expected_tokens, role)`:
deterministic pure function → `RoutingDecision(model, fallback_chain, reason,
complexity, priority, risk_level, health_state, cost_estimate,
latency_ms_budget)`. Tiers: LOW→free, MEDIUM→cheap, HIGH→strong; HIGH risk
forbids free models; conflict≥0.7 / CRITICAL upgrades free→cheap; budget
ceiling with fail-safe degradation. Deterministic, logged.

## 3. Current 9router integration

`src/llm/nine_router.py::NineRouterClient(BaseLLMProvider)`: OpenAI-compatible
client (base_url/api_key from env, `NINE_ROUTER_*` first), default
`google/gemini-2.0-flash-lite:free` + fallback `deepseek/deepseek-r1:free`,
timeout 30s, max_retries 2 w/ exponential backoff, per-model fallback chain,
real token/cost tracking via registry, rule-based mock fallback (flagged
`is_fallback=True`, heuristic signal from prompt keywords — advisory only).

## 4. Current fallback/retry behavior

Per-model: max_retries+1 attempts w/ backoff, then next model in chain; all
fail → rule-based mock (never raises). Streaming mirrors with fallback.
Advisor: max_retries=1, refusal paths (role/budget/data/call-failure).

## 5. Current agent invocation paths

ZERO production decision-path LLM calls. Verified by grep: no llm/NineRouter
imports in agents/, analysts/, market/intelligence.py. Decision path is fully
deterministic (price math + feeds). Consumers of LLM: `LLMAdvisor.advise`
(human-facing text only, opt-in OFF, supervisor budget) and research-side
callers (none in hot path).

## 6. Current token/context handling

Advisor: MAX_TOKENS=512, REQUEST_TIMEOUT_S=30, estimate commit 1200 tokens
through the REAL supervisor budget (`check_token_budget`), refund of unused
remainder after the call. No generic context assembler; prompt built inline
from whitelisted market fields.

## 7. Current prompt construction

Inline per-caller (`advisor._build_prompt`: system=user strings, whitelisted
market keys). No prompt registry, no versioning, no hash tracking.

## 8. Current caching

NONE (no response cache anywhere). `registry.discover_from_gateway` has a
negative-cache + single-flight for model LIST discovery only (60s TTL).

## 9. Current model provenance

Per-call: model name + fallback flag + usage recorded in client aggregates
(`get_usage_stats`) and advisor `_model_usage` buckets; shared telemetry store
(`LLMRequestTelemetry`: request_id/agent/provider/model/prompt_version/
tokens/latency/fallback/error/structured_output_valid) behind
`/v2/llm/telemetry`. No routing-policy version, no effort, no cost-by-agent
aggregation.

## 10. Current budget controls

Supervisor `token_budget`/`token_used` per cycle + `check_token_budget` (used
by both committee dispatch skip AND advisor commit). No hierarchical
system→cycle→task→agent→request ledgers, no cost ceilings, no reservation.

## 11. Current effort/reasoning controls

NONE. No LOW/MEDIUM/HIGH/MAX effort abstraction; provider kwargs pass through
(`**kwargs` to `chat.completions.create`).

## 12. Duplicate/overlapping logic

- `registry.discover_from_gateway` vs `advisor._fetch_live_model_names`: two
  model-list fetchers (registry: httpx+cache; advisor: urllib, no cache).
  Overlap is benign (advisor needs live-preferred free model) but should share
  one path long-term.
- Two `TechnicalAnalyst` classes (documented intentional, PRD_V2 §25).
- `ModelInfo.capabilities` (chat/streaming/fast/reasoning/vision) vs
  structured-output/tools/streaming flags needed by Phase 6 — extend, don't fork.

## 13. Unsafe bypasses

NONE found: advisor output is human text only (nothing consumes it
automatically); rule-based mock is flagged; no LLM output reaches
proposal/gate/volume/execution/strategy paths.

## 14. Missing capabilities (Phase 6 build list)

Task taxonomy, T0–T4 risk tiers, LOW–CRITICAL complexity, effort control,
hierarchical budget + reservation, bounded escalation/fallback/timeout,
structured-output + forbidden-authority validation, task-specific context
builder + budget, snapshot-safe cache, prompt + routing-policy versioning,
ModelDecisionRecord, cost observability aggregation, provider health/circuit
breaker, tool permission separation, prompt-injection sanitization.

## 15. Recommended integration path

New module `src/llm/canonical.py` (frozen dataclasses: ModelRequest, RoutingPolicy,
ModelDecisionRecord, BudgetLedger, PromptVersion, CacheKey) + `src/llm/router.py`
(`CanonicalModelRouter` wrapping existing `ModelRouter` + `ModelRegistry` +
`NineRouterClient`: task classify → risk tier → complexity → route → budget
reserve → execute w/ timeout → validate output → bounded fallback/escalation →
record). Existing classes stay untouched (wrap, don't fork); advisor migrates
to route through it.
