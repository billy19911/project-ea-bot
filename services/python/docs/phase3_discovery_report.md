# PHASE 3 DISCOVERY REPORT — Committee & Debate Engine

## 1. Current Agent Hierarchy

```
SupervisorAgent (agents/supervisor.py)
├── routing: first_match / all_match / priority_based
├── dispatch: sequential (max_concurrency<=1) or ThreadPoolExecutor
├── budget: token_used vs token_budget per cycle
└── synthesis: AgentSynthesizer.generate_proposal() → proposal dict → pipeline

    DepartmentLead (agents/departments.py) — unanimity-only consensus
    ├── MarketLead (market/intelligence.py) — regime-weighted evidence synthesis
    │   └── _specialists dict: Technical Analyst, Momentum, Structure, Volatility, News...
    ├── RiskLead (risk/intelligence.py) — advisory only, never authoritative
    └── ReviewLead (agents/analysts/review_agent.py) — post-trade review only
```

Registered in `main.register_default_agents()`:
TechnicalAnalystAgent, MomentumAnalystAgent, StructureAnalystAgent,
VolatilityAnalystAgent, NewsSentimentAgent, FundamentalAnalystAgent,
MarketLead, RiskLead, ReviewLead.

## 2. Current Specialist Implementations

All in `src/agents/analysts/`, ALL DETERMINISTIC (no LLM calls):

| File | Class | Output contract | Domain |
|------|-------|-----------------|--------|
| structure_analyst.py | StructureAnalystAgent | {signal, confidence, reasoning, key_levels, bos/choch, zone} | structure |
| momentum_analyst.py | MomentumAnalystAgent | {signal, confidence, reasoning, multi-TF} | momentum |
| volatility_analyst.py | VolatilityAnalystAgent | {signal, confidence, atr, spread_context} | volatility |
| news_agent.py | NewsSentimentAgent | {signal UNKNOWN when no source, confidence, impact} | news |
| fundamental_analyst.py | FundamentalAnalystAgent | {signal, confidence, reasoning} deterministic | regime/macro |
| review_agent.py | PostTradeReviewAgent | {signal: NEUTRAL always, lessons} | review (never directional) |

Common contract (normalized by `supervisor.normalize_agent_output`):
{agent, signal (upper), confidence [0,1], reasoning (str), reasons (list), evidence (list, often EMPTY)}.

GAP: `evidence` list is usually EMPTY from real specialists. `AgentOutputAdapter`
(agents/committee.py) already synthesizes EvidenceItems from signal/confidence,
marking directional claims without facts as [INCOMPLETE]. Real specialists do
NOT yet emit canonical EvidenceItems natively.

MISSING ROLES (no dedicated agent): Regime specialist (MarketLead.detect_regime
does it inline, not a separate agent), Liquidity specialist (structure analyst
partially covers sweeps), Entry/Timing specialist (pipeline zone_entry_gate
exists but no agent), Challenger (CommitteeCoordinator.run_challenge exists but
no dedicated agent wired in production path).

## 3. Real vs Wrappers/Adapters

REAL (compute from market data):
- StructureAnalystAgent (swings, BOS/CHOCH, S/R, FVG, OB, ADX)
- MomentumAnalystAgent (multi-TF momentum, divergence)
- VolatilityAnalystAgent (ATR, regime, spread)
- NewsSentimentAgent (feed-backed; UNKNOWN when no source)
- FundamentalAnalystAgent (calendar-driven, deterministic)
- TechnicalAnalystAgent (agents/base.py — legacy EMA/RSI signal)

WRAPPERS/ADAPTERS:
- MarketLead (market/intelligence.py) — aggregates _specialists dict results
- DepartmentLead (agents/departments.py) — selects + runs specialists per routing_fn
- AgentOutputAdapter (agents/committee.py) — legacy dict → EvidenceBundle
- RiskLead — advisory wrapper around deterministic risk reads

DUPLICATION NOTE: `TechnicalAnalyst` (market/intelligence.py, AnalystReport
contract) vs `TechnicalAnalystAgent` (agents/base.py, plain dict contract) —
intentionally kept separate (PRD_V2 §25 comment). Do NOT merge.

## 4. Existing Evidence Production

- `agents/evidence.py`: EvidenceItem/EvidenceBundle (FACT/INTERPRETATION/
  RECOMMENDATION, quality [0,1], freshness from age_seconds).
- `agents/canonical.py` (Phase 2): extends with domain, metric_name/value,
  Conflict, MarketAssessment, SetupCandidate, EntryAssessment, Challenge,
  DecisionState.
- `agents/committee.py: AgentOutputAdapter.to_evidence()`: converts any legacy
  output → bundle (directional claim + facts + [INCOMPLETE] marker).
- Real specialists: evidence list EMPTY in practice; adapter synthesizes from
  signal/confidence. Provenance = agent name + timestamp, timeframe often "".

## 5. Existing Conflict Detection

- `synthesis.detect_conflicts()`: pairwise bullish-vs-bearish opposition strings.
- `synthesis._has_severe_conflict()`: high-confidence (≥0.7) opposing pair, or
  flagged unresolved_conflict with conf ≥0.75.
- `committee.CommitteeCoordinator.detect_conflicts()`: structural HIGH conflict
  for opposing directional domains + MEDIUM for news UNKNOWN.
- `supervisor._has_unresolved_conflict()`: any result with unresolved_conflict=true.
- Phase 2 hardening: ANY unresolved_conflict suppresses directional proposal
  (WAIT/NO_TRADE), irrespective of confidence magnitude.

## 6. Existing Challenge Mechanism

- `canonical.Challenge` dataclass (challenge_id, setup_id, issue,
  evidence_requested, assigned_to, outcome PENDING/PASSED/FAILED).
- `committee.CommitteeCoordinator.run_challenge(setup, conflict)`:
  creates targeted challenge (asks OPPOSING domain, not all agents),
  optional `challenge_runner(agent, issue, ctx)` callable for second opinion,
  records on setup.challenges.
- NOT WIRED in production path: supervisor/pipeline never call run_challenge;
  only unit tests exercise it. No dedicated Challenger agent registered.

## 7. Current Supervisor Orchestration

`SupervisorAgent.analyze(context)`:
1. reset token budget; resolve registry; build target_names (leads first).
2. sort by priority → filter by can_handle → apply routing policy.
3. dispatch (sequential or threadpool) with per-agent timeout.
4. track overall_signal = HIGHEST single-agent confidence (not vote).
5. `_synthesise()`: generate_proposal → suppress if unresolved conflict →
   emit proposal dict {symbol, direction, confidence, reasoning, stop_loss,
   take_profit, entry_price, requires_escalation, reason_codes, evidence_refs}.
6. HOLD/NEUTRAL → proposal None → pipeline NO_TRADE.

## 8. Current Market Lead Behavior

`MarketLead.analyze(context)` (market/intelligence.py:687):
1. detect_regime(context) → regime string + adaptive weights.
2. run each _specialist defensively (ERROR → NEUTRAL placeholder).
3. evidence weight = regime_weight × confidence × evidence_quality.
4. dominance_ratio = winner_weight / total; if unresolved AND ratio < 0.6
   → NEUTRAL (no winner by narrow margin).
5. returns {signal, confidence (=weight share, NOT P(profit)), reasons,
   regime, regime_weights, specialist_results, dissent, unresolved_conflict}.

Phase 2 reframed: comments explicitly say "NOT a unit vote", output carries
full evidence map. `synthesize()` classmethod (line ~527) has similar
winner=sorted(weights) pattern — used by older department-committee API path.

## 9. Current Entry/Tactical Analysis

- NO dedicated Entry/Timing agent. Pipeline has `zone_entry_gate` (F2
  watch-and-fire at OB/FVG) — deterministic gate, not an agent.
- `EntryAssessment` dataclass exists (canonical.py) but nothing constructs it
  in production. `is_ready_for_entry()` tested only in unit tests.
- Pipeline `_htf_bias_veto`, entry cooldown/distance guards are deterministic
  pre-gate filters, not committee debate.

## 10. Existing Model Calls

NONE in the agent decision path. Verified by grep: no llm/NineRouter/9router/
complete/chat imports in agents/, analysts/, market/intelligence.py.
- `agents/base.py` has `model_policy` metadata field only (routing hint, unused).
- `src/llm/` (advisor, model_router, nine_router, registry) exists but is
  consumed by research/optimization paths, NOT by the per-cycle committee.
- All 6 production specialists are fully deterministic (price math + feeds).

IMPLICATION: Phase 3 debate loop runs on deterministic specialists; the
"LLM call" budget in the spec maps to "specialist invocation" budget here.
`max_concurrency`, `token_budget`, per-agent `timeout_seconds` already exist.

## 11. Existing Fallback Behavior

- Specialist exception → {signal NEUTRAL, confidence 0, reasons [error]}.
- Specialist timeout → same NEUTRAL placeholder via _call_with_timeout.
- Empty agent_outputs → synthesis returns proposal None + escalate True.
- MarketLead no votes → NEUTRAL, confidence 0, unresolved False.
- News no source → signal UNKNOWN, confidence 0 (never fabricated CLEAR).
- Structure insufficient data → INSUFFICIENT_DATA pattern + fallback NEUTRAL.

All fail-safe; no fabricated directional output on failure.

## 12. Existing Event Triggers

- Pipeline events: BREAKOUT, TREND_*, STRUCTURE_*, VOLATILITY_*, NEWS_*, etc.
- `match_routes()`: prefix match on routing_table; fallback technical_analyst.
- `can_handle(event_type, context)` per agent filters relevance.
- `signal_registry.should_convene(symbol)`: PENDING/EXECUTING/OPEN or cooldown
  → skip committee (prevents M1 spam). Post-failure cooldown exists.
- NO granular trigger taxonomy (BOS/CHOCH/sweep/OB-touch/FVG/HTF-change as
  first-class dispatch keys) — events are coarse strings.

## 13. Existing Test Coverage

- test_synthesis.py (14): plan, aggregate, conflicts, proposal, escalation.
- test_supervisor.py (24): routing, filtering, budget, normalize, display.
- test_committee_conflict.py (4): unresolved suppression (Phase 2 hardened).
- test_phase2_decision_architecture.py (22): canonical objects, coordinator,
  state machine, adversarial.
- test_market_intelligence*.py: regime, weights, synthesis dominance.
- test_phase1_safety.py (14) + test_phase1_hardening.py (24): risk/exec guards.
- Total suite: 2644 passed + 61 Node API passed.

## 14. Remaining Majority-Voting / Pseudo-Voting Logic

| Location | Pattern | Status |
|----------|---------|--------|
| synthesis.py `bullish_count/bearish_count` | headcount tallies | OBSERVABILITY ONLY (decision uses evidence weights) |
| synthesis.py `agreement_score = majority/total` | headcount fraction | OBSERVABILITY ONLY (escalation uses evidence_strength) |
| intelligence.py:527 `winner = sorted(weights...)` | max-weight winner | LEGACY `synthesize()` classmethod; production `analyze()` uses dominance gate. Caller check needed |
| intelligence.py:770 `winner = sorted(votes...)` | max-weight winner | GUARDED by dominance_ratio>=0.6 else NEUTRAL. Not headcount, but still single-winner collapse |
| supervisor.py `overall_signal` = max confidence | highest-single wins | DISPLAY ONLY (proposal comes from synthesis, not this) |
| departments.py `_resolve_consensus` | unanimity-only | SAFE (never majority) |

RECOMMENDATION: keep counts/scores as observability; ensure no future code
branches trading action on them. Audit `intelligence.synthesize()` callers;
if dead, deprecate.

## 15. Recommended Integration Points

1. `supervisor.analyze()` post-dispatch: insert CommitteeCoordinator as the
   synthesis backend (replace/augment AgentSynthesizer) — single seam.
2. `main.register_default_agents()`: register 8 canonical role agents
   (regime/structure/liquidity/momentum/volatility/news/entry/challenger) as
   thin deterministic wrappers over existing analysts where they exist;
   new deterministic logic only where a gap exists (regime, liquidity,
   entry, challenger).
3. `committee.py`: add DebateRecord + bounded debate loop + event classifier
   + budget config (max_specialists/rounds/challenges/cycle_duration).
4. `pipeline.py`: consume DecisionState (action + reason_codes) for
   NO_TRADE/WAIT vs proposal; keep RiskGate boundary untouched.
5. `signal_state_machine.py` (trading/): already exists for lifecycle; wire
   setup_id stability (don't regenerate per cycle).
6. `market/intelligence.py`: keep MarketLead.analyze() as Market Lead
   hypothesis builder; add supporting/contradicting/assumptions/invalidators
   fields to its output (currently reasons+dissent only).
